#!/usr/bin/env python3
"""Secret-safe Conductor API tools for Hermes."""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from mcp.server.fastmcp import FastMCP

CONDUCTOR_API = "https://api.conductor.build/v0"
USER_AGENT = "Hermes-Conductor-Launcher/2.0"
GITHUB_ORG = "TS-Value-Software"
STATE_DIR = Path(os.environ.get("STATE_DIRECTORY", "/var/lib/hermes-conductor"))
DB_PATH = STATE_DIR / "workspaces.sqlite3"
TOKEN_PATH = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "conductor-api.token"
REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
BRANCH_RE = re.compile(r"^[A-Za-z0-9._/-]{1,128}$")
ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,160}$")
ALLOWED_AGENTS = {"codex", "claude", "cursor", "acp"}
ALLOWED_MODELS = {
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "opus",
    "sonnet",
    "haiku",
    "auto",
}
ALLOWED_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max", "ultra"}
DEFAULT_BRANCHES = {"ts-prefect": "staging"}
LOCK = threading.Lock()

mcp = FastMCP(
    "hermes-conductor",
    instructions=(
        "Launch Conductor workspaces for arbitrary tasks in repositories owned by "
        "the TS-Value-Software GitHub organization. You can list Hermes launches, "
        "check a Conductor session's status, and read its messages. The service "
        "never exposes the Conductor credential and never accepts environment variables."
    ),
    host="127.0.0.1",
    port=8794,
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    log_level="INFO",
)


class SafeError(RuntimeError):
    pass


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS workspaces (
              launch_id TEXT PRIMARY KEY,
              repo TEXT NOT NULL,
              branch TEXT,
              workspace_name TEXT NOT NULL,
              task_summary TEXT NOT NULL,
              state TEXT NOT NULL,
              created_at TEXT NOT NULL,
              updated_at TEXT NOT NULL,
              workspace_id TEXT,
              session_id TEXT,
              deep_link TEXT,
              error TEXT
            )
            """
        )


def read_token() -> str:
    token = TOKEN_PATH.read_text().strip()
    if not token:
        raise SafeError("Conductor credential is empty.")
    return token


def conductor_client() -> httpx.Client:
    return httpx.Client(
        base_url=CONDUCTOR_API,
        headers={
            "Authorization": f"Bearer {read_token()}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        timeout=45.0,
    )


def conductor_request(
    client: httpx.Client, method: str, path: str, **kwargs: Any
) -> dict[str, Any]:
    response = client.request(method, path, **kwargs)
    if response.status_code >= 400:
        # Do not relay upstream response bodies: they may contain sensitive text.
        raise SafeError(
            f"Conductor API {method} {path} failed with HTTP {response.status_code}."
        )
    result = response.json()
    if not isinstance(result, dict):
        raise SafeError("Conductor returned an unexpected response.")
    return result


def validate_repo(repo: str) -> str:
    repo = repo.strip()
    if not REPO_RE.fullmatch(repo):
        raise SafeError("Invalid TS repository name.")
    return repo


def validate_branch(branch: str | None, repo: str) -> str | None:
    branch = branch.strip() if branch else DEFAULT_BRANCHES.get(repo)
    if branch is None:
        return None
    forbidden = ("..", "@{", "//")
    if (
        not BRANCH_RE.fullmatch(branch)
        or any(piece in branch for piece in forbidden)
        or branch.startswith(("/", "."))
        or branch.endswith(("/", "."))
    ):
        raise SafeError("Invalid git branch.")
    return branch


def validate_id(value: str, label: str) -> str:
    if not ID_RE.fullmatch(value):
        raise SafeError(f"Invalid {label}.")
    return value


def safe_error(exc: Exception) -> str:
    return str(exc)[:500] if isinstance(exc, SafeError) else type(exc).__name__


def row_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "launch_id": row["launch_id"],
        "repo": row["repo"],
        "branch": row["branch"],
        "workspace_name": row["workspace_name"],
        "task_summary": row["task_summary"],
        "state": row["state"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "workspace_id": row["workspace_id"],
        "session_id": row["session_id"],
        "deep_link": row["deep_link"],
        "error": row["error"],
    }


def bounded_messages(payload: dict[str, Any]) -> dict[str, Any]:
    """Bound pathological transcripts while retaining complete normal messages."""
    output: list[dict[str, Any]] = []
    budget = 80_000
    used = 0
    for message in payload.get("data", []):
        item = {
            key: message.get(key)
            for key in ("id", "sessionId", "sessionIndex", "type", "content", "receivedAt")
        }
        encoded = json.dumps(item, ensure_ascii=False, default=str)
        if used + len(encoded) > budget:
            remaining = max(0, budget - used)
            item["content"] = encoded[:remaining] + "…[truncated]"
            output.append(item)
            break
        output.append(item)
        used += len(encoded)
    return {
        "messages": output,
        "offset": payload.get("offset"),
        "has_more": payload.get("hasMore", False),
        "response_truncated": len(output) < len(payload.get("data", [])),
    }


@mcp.tool()
def get_launch_policy() -> dict[str, Any]:
    """Describe the server-enforced launch scope and defaults."""
    return {
        "github_organization": GITHUB_ORG,
        "repository_scope": f"any {GITHUB_ORG} repository name",
        "default_agent": "codex",
        "default_model": "gpt-5.5",
        "default_effort": "high",
        "repo_branch_defaults": DEFAULT_BRANCHES,
        "arbitrary_tasks_allowed": True,
        "environment_variables_allowed": False,
    }


@mcp.tool()
def launch_workspace(
    repo: str,
    task: str,
    branch: str | None = None,
    workspace_name: str | None = None,
    agent: str = "codex",
    model: str = "gpt-5.5",
    effort: str = "high",
) -> dict[str, Any]:
    """Launch an arbitrary task in any TS-Value-Software repository.

    `repo` is a repository name, not a URL. The service fixes the GitHub
    organization and does not permit caller-supplied environment variables.
    Branch is optional; ts-prefect defaults to staging and other repositories
    use their configured default branch when omitted.
    """
    repo = validate_repo(repo)
    branch = validate_branch(branch, repo)
    task = task.strip()
    if not task or len(task) > 40_000:
        raise SafeError("Task must contain 1 to 40,000 characters.")
    if agent not in ALLOWED_AGENTS:
        raise SafeError("Unsupported Conductor agent.")
    if model not in ALLOWED_MODELS:
        raise SafeError("Unsupported Conductor model.")
    if effort not in ALLOWED_EFFORTS:
        raise SafeError("Unsupported reasoning effort.")
    if workspace_name:
        workspace_name = workspace_name.strip()
        if not workspace_name or len(workspace_name) > 100:
            raise SafeError("Workspace name must contain 1 to 100 characters.")
    else:
        workspace_name = f"{repo}-hermes-{uuid.uuid4().hex[:6]}"

    launch_id = uuid.uuid4().hex
    timestamp = now_iso()
    summary = " ".join(task.split())[:240]
    with LOCK, sqlite3.connect(DB_PATH) as db:
        db.execute(
            """
            INSERT INTO workspaces
              (launch_id, repo, branch, workspace_name, task_summary, state,
               created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 'reserved', ?, ?)
            """,
            (launch_id, repo, branch, workspace_name, summary, timestamp, timestamp),
        )

    try:
        workspace_request: dict[str, Any] = {
            "repositoryUrl": f"https://github.com/{GITHUB_ORG}/{repo}.git",
            "name": workspace_name,
            "sessionName": summary[:100] or f"Hermes task in {repo}",
            "agent": agent,
            "model": model,
            "effort": effort,
        }
        if branch:
            workspace_request["branch"] = branch
        with conductor_client() as client:
            created = conductor_request(
                client, "POST", "/workspaces", json=workspace_request
            )
            workspace_id = created["workspaceId"]
            session_id = created["sessionId"]
            deep_link = created["deepLink"]
            conductor_request(
                client,
                "POST",
                f"/sessions/{session_id}/messages",
                json={"message": task},
            )
        state, error = "launched", None
    except Exception as exc:
        # Keep ambiguous failures in history so they can be reconciled rather
        # than silently issuing a duplicate paid launch.
        workspace_id = locals().get("workspace_id")
        session_id = locals().get("session_id")
        deep_link = locals().get("deep_link")
        state = "launch_unknown" if not workspace_id else "message_failed"
        error = safe_error(exc)

    with LOCK, sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        db.execute(
            """
            UPDATE workspaces SET state=?, updated_at=?, workspace_id=?,
              session_id=?, deep_link=?, error=? WHERE launch_id=?
            """,
            (
                state,
                now_iso(),
                workspace_id,
                session_id,
                deep_link,
                error,
                launch_id,
            ),
        )
        row = db.execute(
            "SELECT * FROM workspaces WHERE launch_id=?", (launch_id,)
        ).fetchone()
    return row_dict(row)


@mcp.tool()
def list_launches(limit: int = 20) -> dict[str, Any]:
    """List recent workspaces launched through Hermes, newest first."""
    limit = max(1, min(limit, 100))
    with sqlite3.connect(DB_PATH) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM workspaces ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return {"launches": [row_dict(row) for row in rows]}


@mcp.tool()
def get_session_status(session_id: str) -> dict[str, Any]:
    """Read live status for any Conductor session visible to this API account."""
    session_id = validate_id(session_id, "session ID")
    with conductor_client() as client:
        status = conductor_request(client, "GET", f"/sessions/{session_id}/status")
    return {
        key: status.get(key)
        for key in (
            "workspaceId",
            "sessionId",
            "status",
            "updatedAt",
            "errorMessage",
            "lastError",
            "lastErrorAt",
        )
        if key in status
    }


@mcp.tool()
def read_session_messages(
    session_id: str, limit: int = 20, after_message_id: str | None = None
) -> dict[str, Any]:
    """Read transcript messages from any Conductor session visible to the account."""
    session_id = validate_id(session_id, "session ID")
    limit = max(1, min(limit, 100))
    params: dict[str, Any] = {"limit": limit}
    if after_message_id:
        params["after"] = validate_id(after_message_id, "message ID")
    with conductor_client() as client:
        payload = conductor_request(
            client, "GET", f"/sessions/{session_id}/messages", params=params
        )
    return bounded_messages(payload)


if __name__ == "__main__":
    init_db()
    mcp.run(transport="streamable-http")

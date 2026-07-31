#!/usr/bin/env python3
"""Full, secret-safe MCP facade over the official Conductor API."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal, cast
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

API_ROOT = "https://api.conductor.build"
USER_AGENT = "Hermes-Conductor-MCP/3.0"
TOKEN_PATH = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "conductor-api.token"
MAX_ERROR_CHARS = 500

Channel = Literal["prod", "alpha", "alpha-chromium", "beta", "patch", "dev"]
Agent = Literal["claude", "codex", "cursor", "acp"]
Effort = Literal["none", "low", "medium", "high", "xhigh", "max", "ultra"]
Model = Literal[
    "fable-5",
    "opus-5-1m",
    "opus-4-8-1m",
    "opus-4-8",
    "opus-4-7-1m",
    "opus-4-7",
    "opus-1m",
    "opus",
    "opus-4-6-1m",
    "sonnet-5-1m",
    "sonnet-4-6-1m",
    "sonnet",
    "haiku",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.3-codex-spark",
    "gpt-5.3-codex",
    "gpt-5.2-codex",
    "auto",
    "composer-2.5",
    "grok-4.5",
]
JsonObject = dict[str, object]

# One typed MCP tool covers every operation in the 2026-07-31 OpenAPI contract.
# Tests lock this inventory so a partial facade cannot be described as complete.
OFFICIAL_OPERATION_TOOLS = {
    "get_current_user": ("GET", "/me"),
    "list_projects": ("GET", "/v0/projects"),
    "get_project": ("GET", "/v0/projects/{projectId}"),
    "list_project_workspaces": ("GET", "/v0/projects/{projectId}/workspaces"),
    "create_workspace": ("POST", "/v0/workspaces"),
    "get_workspace": ("GET", "/v0/workspaces/{workspaceId}"),
    "rename_workspace": ("POST", "/v0/workspaces/{workspaceId}/rename"),
    "archive_workspace": ("POST", "/v0/workspaces/{workspaceId}/archive"),
    "list_workspace_sessions": ("GET", "/v0/workspaces/{workspaceId}/sessions"),
    "create_session": ("POST", "/v0/sessions"),
    "get_session": ("GET", "/v0/sessions/{sessionId}"),
    "rename_session": ("POST", "/v0/sessions/{sessionId}/rename"),
    "archive_session": ("POST", "/v0/sessions/{sessionId}/archive"),
    "list_session_messages": ("GET", "/v0/sessions/{sessionId}/messages"),
    "send_session_message": ("POST", "/v0/sessions/{sessionId}/messages"),
    "get_message": ("GET", "/v0/messages/{messageId}"),
    "get_workspace_status": ("GET", "/v0/workspaces/{workspaceId}/status"),
    "get_session_status": ("GET", "/v0/sessions/{sessionId}/status"),
    "cancel_session": ("POST", "/v0/sessions/{sessionId}/cancel"),
    "query_conductor_sql": ("POST", "/v0/sql"),
}

mcp = FastMCP(
    "hermes-conductor",
    instructions=(
        "This server exposes the complete current Conductor API. Use list_projects "
        "then list_project_workspaces to enumerate cloud workspaces. Use "
        "query_conductor_sql over session_transcripts_view for organization-wide "
        "activity and transcript searches. To launch work, create_workspace then "
        "send_session_message. Supervise with get_session_status and incremental "
        "list_session_messages(after_message_id=...). A queued prompt reports idle "
        "until it starts; observe working or a transcript reply before treating idle "
        "as complete. The API key remains inside this loopback service."
    ),
    host="127.0.0.1",
    port=8794,
    streamable_http_path="/",
    json_response=True,
    stateless_http=True,
    log_level="INFO",
)


class SafeError(RuntimeError):
    """An error whose message may cross the MCP boundary."""


def read_token() -> str:
    token = TOKEN_PATH.read_text().strip()
    if not token:
        raise SafeError("Conductor credential is empty.")
    return token


def conductor_client() -> httpx.Client:
    return httpx.Client(
        base_url=API_ROOT,
        headers={
            "Authorization": f"Bearer {read_token()}",
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
        },
        timeout=45.0,
    )


def safe_upstream_message(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    message = payload.get("userMessage")
    if not isinstance(message, str) or not message.strip():
        return None
    return re.sub(r"[\x00-\x1f\x7f]+", " ", message).strip()[:MAX_ERROR_CHARS]


def conductor_request(
    method: Literal["GET", "POST"],
    path: str,
    operation: str,
    *,
    params: JsonObject | None = None,
    json_body: JsonObject | None = None,
) -> JsonObject:
    with conductor_client() as client:
        response = client.request(method, path, params=params, json=json_body)
    if response.status_code >= 400:
        detail = safe_upstream_message(response)
        suffix = f": {detail}" if detail else ""
        raise SafeError(
            f"Conductor {operation} failed with HTTP {response.status_code}{suffix}"
        )
    result = response.json()
    if not isinstance(result, dict):
        raise SafeError(f"Conductor {operation} returned an unexpected response.")
    return cast(JsonObject, result)


def clean_text(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise SafeError(f"{label} must not be empty.")
    return value


def path_id(value: str, label: str) -> str:
    return quote(clean_text(value, label), safe="")


def optional_body(**values: object) -> JsonObject:
    return {key: value for key, value in values.items() if value is not None}


def page_params(
    limit: int,
    offset: int,
    channel: Channel | None = None,
) -> JsonObject:
    if limit < 1:
        raise SafeError("limit must be at least 1.")
    if offset < 0:
        raise SafeError("offset must be non-negative.")
    return optional_body(limit=limit, offset=offset, channel=channel)


@mcp.tool()
def get_current_user() -> JsonObject:
    """Get the authenticated Conductor user, organization, and API-key metadata."""
    return conductor_request("GET", "/me", "me.get")


@mcp.tool()
def list_projects(limit: int = 100, offset: int = 0) -> JsonObject:
    """List repositories available for Conductor cloud workspace creation."""
    return conductor_request(
        "GET",
        "/v0/projects",
        "projects.list",
        params=page_params(limit, offset),
    )


@mcp.tool()
def get_project(project_id: str) -> JsonObject:
    """Get one Conductor project by ID."""
    identifier = path_id(project_id, "project_id")
    return conductor_request("GET", f"/v0/projects/{identifier}", "project.get")


@mcp.tool()
def list_project_workspaces(
    project_id: str,
    limit: int = 100,
    offset: int = 0,
    channel: Channel | None = None,
) -> JsonObject:
    """List a project's cloud workspaces, including deep links and activity times."""
    identifier = path_id(project_id, "project_id")
    return conductor_request(
        "GET",
        f"/v0/projects/{identifier}/workspaces",
        "project.workspaces.list",
        params=page_params(limit, offset, channel),
    )


@mcp.tool()
def create_workspace(
    project_id: str | None = None,
    repository_url: str | None = None,
    branch: str | None = None,
    name: str | None = None,
    session_name: str | None = None,
    agent: Agent | None = None,
    model: Model | None = None,
    effort: Effort | None = None,
    env: dict[str, str] | None = None,
    channel: Channel | None = None,
) -> JsonObject:
    """Create a cloud workspace and its first session.

    Supply exactly one of project_id or repository_url. This is the full official
    operation, including branch, agent, model, effort, and environment variables.
    Send the initial task separately with send_session_message.
    """
    has_project = bool(project_id and project_id.strip())
    has_repository = bool(repository_url and repository_url.strip())
    if has_project == has_repository:
        raise SafeError("Supply exactly one of project_id or repository_url.")
    source: JsonObject
    if has_project:
        source = {"projectId": clean_text(cast(str, project_id), "project_id")}
    else:
        source = {
            "repositoryUrl": clean_text(
                cast(str, repository_url),
                "repository_url",
            )
        }
    body = {
        **source,
        **optional_body(
            branch=branch,
            name=name,
            sessionName=session_name,
            agent=agent,
            model=model,
            effort=effort,
            env=env,
        ),
    }
    return conductor_request(
        "POST",
        "/v0/workspaces",
        "workspace.create",
        params=optional_body(channel=channel),
        json_body=body,
    )


@mcp.tool()
def get_workspace(
    workspace_id: str,
    channel: Channel | None = None,
) -> JsonObject:
    """Get a workspace, including its name, timestamps, and deep link."""
    identifier = path_id(workspace_id, "workspace_id")
    return conductor_request(
        "GET",
        f"/v0/workspaces/{identifier}",
        "workspace.get",
        params=optional_body(channel=channel),
    )


@mcp.tool()
def rename_workspace(
    workspace_id: str,
    name: str,
    channel: Channel | None = None,
) -> JsonObject:
    """Rename a workspace."""
    identifier = path_id(workspace_id, "workspace_id")
    return conductor_request(
        "POST",
        f"/v0/workspaces/{identifier}/rename",
        "workspace.rename",
        params=optional_body(channel=channel),
        json_body={"name": clean_text(name, "name")},
    )


@mcp.tool()
def archive_workspace(workspace_id: str) -> JsonObject:
    """Archive a workspace, stopping its machine and hiding it in the app."""
    identifier = path_id(workspace_id, "workspace_id")
    return conductor_request(
        "POST",
        f"/v0/workspaces/{identifier}/archive",
        "workspace.archive",
    )


@mcp.tool()
def list_workspace_sessions(
    workspace_id: str,
    limit: int = 100,
    offset: int = 0,
    channel: Channel | None = None,
) -> JsonObject:
    """List all agent sessions in one workspace."""
    identifier = path_id(workspace_id, "workspace_id")
    return conductor_request(
        "GET",
        f"/v0/workspaces/{identifier}/sessions",
        "workspace.sessions.list",
        params=page_params(limit, offset, channel),
    )


@mcp.tool()
def create_session(
    workspace_id: str,
    agent: Agent,
    name: str | None = None,
    session_id: str | None = None,
    model: Model | None = None,
    effort: Effort | None = None,
    fast_mode: bool | None = None,
    channel: Channel | None = None,
) -> JsonObject:
    """Create another agent session inside an existing workspace."""
    body = optional_body(
        workspaceId=clean_text(workspace_id, "workspace_id"),
        agent=agent,
        name=name,
        sessionId=session_id,
        model=model,
        effort=effort,
        fastMode=fast_mode,
    )
    return conductor_request(
        "POST",
        "/v0/sessions",
        "session.create",
        params=optional_body(channel=channel),
        json_body=body,
    )


@mcp.tool()
def get_session(
    session_id: str,
    channel: Channel | None = None,
) -> JsonObject:
    """Get one agent session, including model, effort, name, and deep link."""
    identifier = path_id(session_id, "session_id")
    return conductor_request(
        "GET",
        f"/v0/sessions/{identifier}",
        "session.get",
        params=optional_body(channel=channel),
    )


@mcp.tool()
def rename_session(
    session_id: str,
    name: str,
    channel: Channel | None = None,
) -> JsonObject:
    """Rename an agent session."""
    identifier = path_id(session_id, "session_id")
    return conductor_request(
        "POST",
        f"/v0/sessions/{identifier}/rename",
        "session.rename",
        params=optional_body(channel=channel),
        json_body={"name": clean_text(name, "name")},
    )


@mcp.tool()
def archive_session(session_id: str) -> JsonObject:
    """Archive a session and cancel its queued messages."""
    identifier = path_id(session_id, "session_id")
    return conductor_request(
        "POST",
        f"/v0/sessions/{identifier}/archive",
        "session.archive",
    )


@mcp.tool()
def list_session_messages(
    session_id: str,
    limit: int = 100,
    offset: int = 0,
    after_message_id: str | None = None,
) -> JsonObject:
    """Read a session transcript, optionally after one message ID."""
    if limit < 1:
        raise SafeError("limit must be at least 1.")
    if offset < 0:
        raise SafeError("offset must be non-negative.")
    if after_message_id is not None and offset != 0:
        raise SafeError("after_message_id cannot be combined with a non-zero offset.")
    identifier = path_id(session_id, "session_id")
    params = optional_body(limit=limit)
    if after_message_id is None:
        params["offset"] = offset
    else:
        params["after"] = clean_text(after_message_id, "after_message_id")
    return conductor_request(
        "GET",
        f"/v0/sessions/{identifier}/messages",
        "session.messages.list",
        params=params,
    )


@mcp.tool()
def send_session_message(
    session_id: str,
    message: str,
    message_id: str | None = None,
) -> JsonObject:
    """Send a prompt or follow-up to an agent session."""
    identifier = path_id(session_id, "session_id")
    return conductor_request(
        "POST",
        f"/v0/sessions/{identifier}/messages",
        "message.create",
        json_body=optional_body(
            message=clean_text(message, "message"),
            messageId=message_id,
        ),
    )


@mcp.tool()
def get_message(message_id: str) -> JsonObject:
    """Get one transcript message by ID."""
    identifier = path_id(message_id, "message_id")
    return conductor_request("GET", f"/v0/messages/{identifier}", "message.get")


@mcp.tool()
def get_workspace_status(workspace_id: str) -> JsonObject:
    """Get workspace lifecycle status and setup/update errors."""
    identifier = path_id(workspace_id, "workspace_id")
    return conductor_request(
        "GET",
        f"/v0/workspaces/{identifier}/status",
        "workspace.status.get",
    )


@mcp.tool()
def get_session_status(session_id: str) -> JsonObject:
    """Get whether an agent session is idle, working, or errored."""
    identifier = path_id(session_id, "session_id")
    return conductor_request(
        "GET",
        f"/v0/sessions/{identifier}/status",
        "session.status.get",
    )


@mcp.tool()
def cancel_session(session_id: str) -> JsonObject:
    """Stop the current agent turn and drop queued messages."""
    identifier = path_id(session_id, "session_id")
    return conductor_request(
        "POST",
        f"/v0/sessions/{identifier}/cancel",
        "session.cancel",
    )


@mcp.tool()
def query_conductor_sql(query: str) -> JsonObject:
    """Run Conductor's read-only SQL over session_transcripts_view.

    Useful columns include workspace_id, workspace_name, session_title,
    transcript, and transcript_updated_at. Conductor enforces the read-only view.
    """
    return conductor_request(
        "POST",
        "/v0/sql",
        "sql.query",
        json_body={"query": clean_text(query, "query")},
    )


if __name__ == "__main__":
    mcp.run(transport="streamable-http")

"""Resolve an exact project's non-sensitive MCP bearer without persisting it."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT_CONTEXT = ROOT / "bin/project-context"
DEFAULT_CONFIG = ROOT / "config/project-tools.json"
TOKEN_ENV = re.compile(r"^[A-Z][A-Z0-9_]*_OP_SERVICE_ACCOUNT_TOKEN$")


class McpAuthError(RuntimeError):
    """Credential resolution failed without exposing credential material."""


def _run(command: list[str], *, env: dict[str, str] | None = None) -> str:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, check=False, env=env, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise McpAuthError(f"could not run {Path(command[0]).name}") from error
    if result.returncode:
        raise McpAuthError(f"{Path(command[0]).name} failed")
    if len(result.stdout) > 65_536:
        raise McpAuthError(f"{Path(command[0]).name} returned oversized output")
    return result.stdout


def resolve_autodev_memory(project: str, cwd: Path) -> tuple[str, str]:
    """Return the HTTPS REST base and restricted bearer for one registered repository."""
    profile_project = "workflow-pro" if project == "workflow_pro" else project
    config = Path(os.environ.get("PROJECT_TOOLS_CONFIG", DEFAULT_CONFIG))
    context_env = {**os.environ, "PROJECT_TOOLS_CONFIG": str(config)}
    raw = _run([
        str(PROJECT_CONTEXT), "--cwd", str(cwd), "--project", profile_project,
        "--tool", "autodev_memory",
    ], env=context_env)
    try:
        profile = json.loads(raw)
        service = profile["service_account"]
        memory = profile["tools"]["autodev_memory"]
        token_env = service["token_env"]
        keychain_item = service.get("keychain_item", "")
        token_ref = memory["token_ref"]
        url = memory["url"]
        registry = json.loads(config.read_text(encoding="utf-8"))
        registered_envs = [
            value["service_account"]["token_env"]
            for value in registry["projects"].values()
        ]
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise McpAuthError("invalid project credential profile") from error
    if not isinstance(token_env, str) or not TOKEN_ENV.fullmatch(token_env):
        raise McpAuthError("invalid service-account environment name")
    if not isinstance(url, str) or not (
        url.startswith("https://")
        or url.startswith("http://127.0.0.1:")
        or url.startswith("http://localhost:")
    ):
        raise McpAuthError("invalid autodev-memory URL")
    if not isinstance(token_ref, str) or not token_ref.startswith("op://"):
        raise McpAuthError("invalid autodev-memory credential reference")

    service_token = os.environ.get(token_env, "")
    if not service_token and sys.platform == "darwin" and keychain_item:
        command = ["security", "find-generic-password", "-s", keychain_item]
        if os.environ.get("USER"):
            command.extend(["-a", os.environ["USER"]])
        command.append("-w")
        service_token = _run(command).rstrip("\n")
    if not service_token:
        raise McpAuthError(f"no service-account token for {profile_project}")

    child_env = dict(os.environ)
    for name in list(child_env):
        if name in {"OP_SERVICE_ACCOUNT_TOKEN", "OP_CONNECT_HOST", "OP_CONNECT_TOKEN"}:
            child_env.pop(name, None)
        elif name.startswith("OP_SESSION_") or TOKEN_ENV.fullmatch(name):
            child_env.pop(name, None)
    child_env["OP_SERVICE_ACCOUNT_TOKEN"] = service_token
    service_token = ""
    try:
        bearer = _run(
            [str(ROOT / "bin/op"), "read", "--no-newline", token_ref], env=child_env,
        )
    finally:
        child_env.pop("OP_SERVICE_ACCOUNT_TOKEN", None)
        for name in registered_envs:
            if isinstance(name, str):
                os.environ.pop(name, None)
        for name in ("OP_SERVICE_ACCOUNT_TOKEN", "OP_CONNECT_HOST", "OP_CONNECT_TOKEN"):
            os.environ.pop(name, None)
    if not bearer:
        raise McpAuthError("1Password returned an empty autodev-memory credential")
    return url.rstrip("/"), bearer

#!/usr/bin/env python3
"""Merge the reviewed Hermes MCP configuration into config.yaml."""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

import yaml


MCP_SERVERS = {
    "autodev-memory": {
        "url": "http://127.0.0.1:8792/",
        "enabled": True,
        "connect_timeout": 30,
        "timeout": 60,
        "supports_parallel_tool_calls": False,
        "tools": {
            "include": [
                "create_ticket",
                "search_tickets",
                "get_similar_tickets",
                "get_ticket",
            ],
            "resources": False,
            "prompts": False,
        },
    },
    "conductor": {
        "url": "http://127.0.0.1:8794/",
        "enabled": True,
        "connect_timeout": 30,
        "timeout": 90,
        "supports_parallel_tool_calls": False,
        "tools": {
            "include": [
                "get_current_user",
                "list_projects",
                "get_project",
                "list_project_workspaces",
                "create_workspace",
                "get_workspace",
                "rename_workspace",
                "archive_workspace",
                "list_workspace_sessions",
                "create_session",
                "get_session",
                "rename_session",
                "archive_session",
                "list_session_messages",
                "send_session_message",
                "get_message",
                "get_workspace_status",
                "get_session_status",
                "cancel_session",
                "query_conductor_sql",
            ],
            "resources": False,
            "prompts": False,
        },
    },
}


def configure(path: Path) -> None:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict):
        raise SystemExit("Hermes config must be a YAML object")

    platform_toolsets = data.setdefault("platform_toolsets", {})
    slack = platform_toolsets.setdefault("slack", [])
    for toolset in ("autodev-memory", "conductor"):
        if toolset not in slack:
            slack.append(toolset)

    servers = data.setdefault("mcp_servers", {})
    servers.update(MCP_SERVERS)
    rendered = yaml.safe_dump(data, sort_keys=False)
    with tempfile.NamedTemporaryFile(
        mode="w",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as temporary:
        temporary.write(rendered)
        temporary_path = Path(temporary.name)
    try:
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "config",
        type=Path,
        help="Hermes config.yaml path",
    )
    args = parser.parse_args()
    configure(args.config)


if __name__ == "__main__":
    main()

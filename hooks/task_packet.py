#!/usr/bin/env python3
"""Build bounded task packets for managed child-agent delegation."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from memory_context import _append_telemetry, read_cache, render_task_packet


VALID_TYPES = {
    "gotcha", "pattern", "preference", "diagnosis", "reference", "solution",
    "architecture", "glossary",
}


def _frontmatter(path: Path) -> dict[str, Any]:
    """Parse only scalar and scalar-list YAML used by local agent definitions."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    if not text.startswith("---\n"):
        return {}
    block = text.split("---\n", 2)[1]
    result: dict[str, Any] = {}
    current = ""
    for raw in block.splitlines():
        item = re.match(r"^\s+-\s+(.+?)\s*$", raw)
        if item and current:
            result.setdefault(current, []).append(item.group(1).strip("\"'"))
            continue
        match = re.match(r"^([A-Za-z0-9_-]+):\s*(.*?)\s*$", raw)
        if not match:
            continue
        current, value = match.groups()
        if not value:
            result[current] = []
        elif value.startswith("[") and value.endswith("]"):
            result[current] = [
                part.strip().strip("\"'") for part in value[1:-1].split(",") if part.strip()
            ]
        else:
            result[current] = value.strip("\"'")
    return result


def _as_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str)]
    return []


def find_agent(cwd: Path, agent_type: str) -> Path | None:
    name = Path(agent_type).name.removesuffix(".md") + ".md"
    roots = [
        cwd / ".claude" / "agents",
        cwd / "agents",
        Path.home() / ".claude" / "agents",
        Path(__file__).resolve().parent.parent / "agents",
    ]
    return next((root / name for root in roots if (root / name).is_file()), None)


def selection_for_agent(cwd: Path, agent_type: str) -> tuple[list[str], list[str]]:
    agent = find_agent(cwd, agent_type)
    meta = _frontmatter(agent) if agent else {}
    tags = _as_list(meta.get("memory_tags"))
    types = [x for x in _as_list(meta.get("memory_types")) if x in VALID_TYPES]
    return list(dict.fromkeys(tags)), list(dict.fromkeys(types))


def load_api_config() -> tuple[str, str]:
    values: dict[str, str] = {}
    env_file = Path.home() / ".config" / "autodev-memory" / ".env"
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for raw in lines:
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].lstrip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key.strip()):
            values[key.strip()] = value.strip().strip("\"'")
    url = os.environ.get("AUTODEV_MEMORY_API_URL", values.get("AUTODEV_MEMORY_API_URL", ""))
    token = os.environ.get("AUTODEV_MEMORY_API_TOKEN", values.get("AUTODEV_MEMORY_API_TOKEN", ""))
    return url.rstrip("/"), token


def fetch_entries(
    project: str,
    repo: str,
    tags: list[str],
    types: list[str],
    exclude_ids: list[str],
    timeout: float = 10,
) -> dict[str, Any]:
    if not tags and not types:
        return {"entries": [], "count": 0}
    url, token = load_api_config()
    if not url or not token:
        return {"entries": [], "count": 0}
    body = json.dumps({
        "project": project,
        "repo": repo,
        "tags": tags,
        "types": types,
        "exclude_ids": exclude_ids,
        "limit": 12,
    }).encode()
    request = urllib.request.Request(
        url + "/entries/by-skill",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Hook-Source": "managed-task-packet",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            parsed = json.loads(response.read())
            return parsed if isinstance(parsed, dict) else {"entries": [], "count": 0}
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {"entries": [], "count": 0}


def build_task_packet(
    *, cwd: Path, agent_type: str, session_id: str, project: str, repo: str,
    cache_dir: Path, telemetry_file: Path | None, provider: str, mechanism: str,
) -> str:
    manifest = read_cache(cache_dir, session_id, project, repo)
    tags, types = selection_for_agent(cwd, agent_type)
    entries = fetch_entries(
        project, repo, tags, types,
        [x for x in (manifest or {}).get("exclude_ids", []) if isinstance(x, str)],
    )
    packet = render_task_packet(manifest, entries)
    _append_telemetry(
        telemetry_file,
        event="child_packet",
        provider=provider,
        mechanism=mechanism,
        status="delivered" if manifest else "base_unavailable",
        packet_version=(manifest or {}).get("packet_version", "unavailable"),
        chars=len(packet),
    )
    return packet

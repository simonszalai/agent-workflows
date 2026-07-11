#!/usr/bin/env python3
"""Build bounded task packets for managed child-agent delegation."""

from __future__ import annotations

import json
import os
import re
import secrets
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from memory_context import (
    _append_telemetry,
    read_cache,
    render_task_packet,
    telemetry_session_key,
)


VALID_TYPES = {
    "gotcha", "pattern", "preference", "diagnosis", "reference", "solution",
    "architecture", "glossary",
}


@dataclass
class RetrievalOutcome:
    """Metadata-only result of deterministic loading, semantic selection, and expansion."""

    status: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    by_skill_count: int = 0
    search_count: int = 0
    selected_ids: list[str] = field(default_factory=list)
    corpus_generation: str = ""
    expansion_status: str = "not_applicable"
    expanded_ids: list[str] = field(default_factory=list)
    failure_stage: str = ""
    delivery_note: str = ""

    def packet_response(self) -> dict[str, Any]:
        return {
            "entries": self.entries,
            "corpus_generation": self.corpus_generation,
            "delivery_note": self.delivery_note,
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


def _post(path: str, body: dict[str, Any], *, repo: str, timeout: float = 10) -> dict[str, Any]:
    url, token = load_api_config()
    if not url or not token:
        raise RuntimeError("configuration_unavailable")
    request = urllib.request.Request(
        url + path,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Hook-Source": "managed-task-packet",
            "X-Repo": repo,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        parsed = json.loads(response.read())
    if not isinstance(parsed, dict):
        raise ValueError("invalid_response")
    return parsed


def retrieve_task_context(
    *, project: str, repo: str, prompt: str, tags: list[str], types: list[str],
    exclude_ids: list[str], corpus_generation: str, external_no_mcp: bool,
) -> RetrievalOutcome:
    """Load role rules, rank semantic gaps from the actual task, then optionally pre-expand."""
    by_skill: dict[str, Any] = {"entries": [], "count": 0}
    search: dict[str, Any] = {"results": [], "query_count": 0}
    attempted = False
    failures: list[str] = []
    if tags or types:
        attempted = True
        try:
            by_skill = _post("/entries/by-skill", {
                "project": project, "repo": repo, "tags": tags, "types": types,
                "exclude_ids": exclude_ids, "limit": 12, "scope_mode": "current_repo",
            }, repo=repo)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError, ValueError):
            failures.append("by_skill")
    if prompt.strip():
        attempted = True
        try:
            search = _post("/search", {
                "project": project,
                "searches": [{"text": prompt, "keywords": tags}],
                "limit": 5,
                "exclude_ids": exclude_ids,
                "detail": "compact",
                "scope_mode": "current_repo",
            }, repo=repo)
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError, ValueError):
            failures.append("search")
    if attempted and len(failures) == int(bool(tags or types)) + int(bool(prompt.strip())):
        return RetrievalOutcome(
            status="failed", failure_stage="selection",
            corpus_generation=corpus_generation,
            delivery_note=("Task-memory selection was unavailable; only the critical base was "
                           "delivered. Do not infer that task-specific memories were checked."),
        )

    selected: list[dict[str, Any]] = []
    seen: set[str] = set(exclude_ids)
    search_results = search.get("results", [])
    skill_entries = by_skill.get("entries", [])
    for raw, id_key in [*((item, "entry_id") for item in search_results if isinstance(item, dict)),
                        *((item, "id") for item in skill_entries if isinstance(item, dict))]:
        entry_id = str(raw.get(id_key, ""))
        if not entry_id or entry_id in seen or len(selected) >= 5:
            continue
        seen.add(entry_id)
        selected.append({
            "id": entry_id,
            "title": raw.get("title", ""),
            "summary": raw.get("summary") or raw.get("matched_chunk") or raw.get("matched_excerpt") or "",
            "type": raw.get("type", "memory"),
        })
    generation = str(search.get("corpus_generation") or corpus_generation or "")
    outcome = RetrievalOutcome(
        status=("partial" if selected and failures else "selected" if selected
                else "failed" if failures else "no_match" if attempted else "not_applicable"),
        entries=selected,
        by_skill_count=len(skill_entries) if isinstance(skill_entries, list) else 0,
        search_count=len(search_results) if isinstance(search_results, list) else 0,
        selected_ids=[str(entry["id"]) for entry in selected],
        corpus_generation=generation,
        failure_stage="+".join(failures),
    )

    if external_no_mcp and 2 <= len(selected) <= 5 and generation:
        try:
            expanded = _post("/entries/expand", {
                "project": project, "repo": repo, "scope_mode": "current_repo",
                "corpus_generation": generation, "entry_ids": outcome.selected_ids,
            }, repo=repo)
            by_id = {
                str(item.get("entry_id")): item.get("entry", {})
                for item in expanded.get("items", []) if isinstance(item, dict)
                and item.get("status") == "expanded" and isinstance(item.get("entry"), dict)
            }
            for entry in selected:
                full = by_id.get(str(entry["id"]))
                if full:
                    entry["content"] = full.get("content", "")
            outcome.expanded_ids = list(by_id)
            if len(by_id) == len(selected):
                outcome.expansion_status = "expanded"
            elif by_id:
                outcome.expansion_status = "partial"
                outcome.status = "partial"
                outcome.failure_stage = "expansion"
            else:
                outcome.expansion_status = "unavailable"
                outcome.status = "partial"
                outcome.failure_stage = "expansion"
        except (OSError, urllib.error.URLError, json.JSONDecodeError, RuntimeError, ValueError):
            outcome.expansion_status = "failed"
            outcome.status = "partial"
            outcome.failure_stage = "expansion"
        if outcome.expansion_status == "expanded":
            outcome.delivery_note = (
                "This external agent has no memory tool; expanded content is included only where "
                "it fits. Any omitted body is explicitly not delivered."
            )
        else:
            outcome.delivery_note = (
                "This external agent has no memory tool and full expansion was unavailable. Treat "
                "the summaries as leads, not complete instructions."
            )
    elif external_no_mcp:
        outcome.expansion_status = "not_applicable"
        outcome.delivery_note = (
            "This external agent has no memory tool; fewer than two expandable results were "
            "available, so no full memory body was delivered."
        )
    else:
        outcome.delivery_note = (
            "Use the full IDs and corpus generation above with scoped memory expansion if more "
            "detail is needed; a selected hit is not proof that its body was used."
        )
    if failures:
        outcome.delivery_note = (
            "Some task-selection stages were unavailable (" + ", ".join(failures)
            + "); do not infer complete retrieval. " + outcome.delivery_note
        )
    return outcome


def build_task_packet(
    *, cwd: Path, agent_type: str, session_id: str, project: str, repo: str,
    cache_dir: Path, telemetry_file: Path | None, provider: str, mechanism: str,
    task_prompt: str = "",
) -> str:
    manifest = read_cache(cache_dir, session_id, project, repo)
    delegation_id = secrets.token_hex(12)
    tags, types = selection_for_agent(cwd, agent_type)
    outcome = retrieve_task_context(
        project=project, repo=repo, prompt=task_prompt, tags=tags, types=types,
        exclude_ids=[x for x in (manifest or {}).get("exclude_ids", []) if isinstance(x, str)],
        corpus_generation=str((manifest or {}).get("corpus_generation", "")),
        external_no_mcp=mechanism.startswith("external"),
    )
    packet_status = (
        "base_unavailable" if not manifest
        else "delivered" if outcome.status in {"selected", "no_match", "not_applicable"}
        else "partial"
    )
    packet_response = outcome.packet_response()
    packet_response.update(
        delegation_id=delegation_id,
        packet_status=packet_status,
        packet_version=(manifest or {}).get("packet_version", "unavailable"),
    )
    packet = render_task_packet(manifest, packet_response)
    session_key = telemetry_session_key(telemetry_file, session_id)
    _append_telemetry(
        telemetry_file,
        event="task_selection", provider=provider, mechanism=mechanism,
        status=outcome.status, by_skill_count=outcome.by_skill_count,
        search_count=outcome.search_count, selected_count=len(outcome.selected_ids),
        selected_ids=outcome.selected_ids, expansion_status=outcome.expansion_status,
        expanded_ids=outcome.expanded_ids, failure_stage=outcome.failure_stage or None,
        delegation_id=delegation_id, corpus_generation=outcome.corpus_generation or "unavailable",
        session_key=session_key,
    )
    _append_telemetry(
        telemetry_file,
        event="child_packet",
        provider=provider,
        mechanism=mechanism,
        status=packet_status,
        packet_version=(manifest or {}).get("packet_version", "unavailable"),
        corpus_generation=outcome.corpus_generation or "unavailable",
        render_hash=(manifest or {}).get("render_hash", "unavailable"),
        chars=len(packet),
        delegation_id=delegation_id,
        session_key=session_key,
    )
    return packet

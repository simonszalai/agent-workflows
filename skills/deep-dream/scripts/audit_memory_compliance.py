#!/usr/bin/env python3
"""Audit recent Claude/Codex memory delivery locally without emitting prompt bodies or IDs."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_session_log import parse_session  # noqa: E402


def _session_key(key: bytes, session_id: str) -> str:
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()[:24]


def _recent(path: Path, cutoff: float) -> bool:
    try:
        return path.stat().st_mtime >= cutoff
    except OSError:
        return False


def _telemetry(path: Path, cutoff: datetime) -> tuple[bytes | None, dict[str, list[dict[str, Any]]]]:
    try:
        key = (path.parent / "telemetry.key").read_bytes()
    except OSError:
        key = None
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    try:
        lines = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return key, grouped
    with lines:
        for raw in lines:
            try:
                event = json.loads(raw)
                stamp = datetime.fromisoformat(str(event.get("timestamp", "")).replace("Z", "+00:00"))
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if stamp >= cutoff and isinstance(event.get("session_key"), str):
                grouped[event["session_key"]].append(event)
    return key, grouped


def _classifications(parsed: dict[str, Any], telemetry: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    mechanisms = parsed.get("summary", {}).get("memory_delivery_mechanisms", [])
    if mechanisms or any(event.get("event") == "parent_packet"
                         and event.get("status") in {"delivered", "fallback"}
                         for event in telemetry):
        labels.append("packet_delivered")
    if "native_session_start" in mechanisms and parsed.get("summary", {}).get("session_role") == "child":
        labels.append("child_native_session_start")
    if "explicit_task_packet" in mechanisms:
        labels.append("explicit_task_packet")
    selection = [event for event in telemetry if event.get("event") == "task_selection"]
    if selection:
        labels.append("selection_attempted")
        latest = selection[-1]
        if latest.get("status") in {"selected", "partial"} and latest.get("selected_count", 0):
            labels.append("selection_confirmed")
        expansion = latest.get("expansion_status")
        if expansion not in {None, "not_applicable"}:
            labels.append("expansion_attempted")
        if expansion == "expanded":
            labels.append("expansion_confirmed")
    tool_events = parsed.get("events", [])
    for event in tool_events:
        names = [str(event.get("tool", "")), *[str(value)
                 for value in event.get("nested_tool_attempts", [])]]
        is_search = any("autodev" in name.lower() and
                        any(token in name.lower() for token in ("search", "by_skill"))
                        for name in names)
        is_expand = any("autodev" in name.lower() and "expand" in name.lower() for name in names)
        if event.get("kind") == "tool_attempt":
            if is_search and "selection_attempted" not in labels:
                labels.append("selection_attempted")
            if is_expand and "expansion_attempted" not in labels:
                labels.append("expansion_attempted")
        direct = str(event.get("tool", ""))
        direct_search = "autodev" in direct.lower() and any(
            token in direct.lower() for token in ("search", "by_skill"))
        direct_expand = "autodev" in direct.lower() and "expand" in direct.lower()
        if event.get("kind") in {"tool_result", "mcp_result"} and event.get("status") == "completed":
            if direct_search and "selection_confirmed" not in labels:
                labels.append("selection_confirmed")
            if direct_expand and "expansion_confirmed" not in labels:
                labels.append("expansion_confirmed")
    if any(event.get("status") in {"unavailable", "failed", "base_unavailable"}
           for event in telemetry):
        labels.append("unavailable")
    if not labels:
        labels.append("not_applicable")
    return list(dict.fromkeys(labels))


def audit(
    claude_root: Path, codex_root: Path, telemetry_file: Path, days: int,
    include_locators: bool = False, restricted_diagnostics: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff_dt = now - timedelta(days=days)
    cutoff = cutoff_dt.timestamp()
    telemetry_key, telemetry = _telemetry(telemetry_file, cutoff_dt)
    diagnostic_key = os.urandom(32)
    records: list[dict[str, Any]] = []

    for parent in sorted(claude_root.rglob("*.jsonl")) if claude_root.exists() else []:
        if "subagents" in parent.parts or not _recent(parent, cutoff):
            continue
        parsed = parse_session(parent, "claude", include_locators, diagnostic_key)
        sid = parent.stem
        session_events = telemetry.get(_session_key(telemetry_key, sid), []) if telemetry_key else []
        children_dir = parent.with_suffix("") / "subagents"
        children = []
        for child in sorted(children_dir.glob("*.jsonl")) if children_dir.is_dir() else []:
            child_parsed = parse_session(child, "claude", include_locators, diagnostic_key)
            first_hash = next((event.get("message_hash") for event in child_parsed["events"]
                               if event.get("kind") == "human_message" and event.get("message_hash")), None)
            children.append((child, child_parsed, first_hash))
        used_children: set[Path] = set()
        for event in parsed["events"]:
            if event.get("tool") != "Agent":
                continue
            delegated = event.get("delegated_prompt_hash")
            match = next(((path, value) for path, value, first in children
                          if path not in used_children and delegated and first == delegated), None)
            child_path, child_parsed = match if match else (None, None)
            if child_path:
                used_children.add(child_path)
            combined = child_parsed or {"summary": {}, "events": []}
            labels = _classifications(combined, session_events)
            if event.get("delegation_mechanism") == "claude_agent_explicit_task_packet" \
                    and "explicit_task_packet" not in labels:
                labels.insert(0, "explicit_task_packet")
                labels.insert(0, "packet_delivered")
            elif (event.get("delegation_mechanism") == "claude_agent_without_observed_packet"
                  and labels == ["not_applicable"]
                  and (event.get("agent_type") or "generic") != "generic"):
                labels = ["unavailable"]
            record: dict[str, Any] = {
                "provider": "claude", "mechanism": "Agent",
                "correlation": "confirmed" if child_path else "unconfirmed",
                "agent_type": event.get("agent_type") or "unknown",
                "classifications": list(dict.fromkeys(labels)),
            }
            if include_locators:
                record.update(parent_path=str(parent), child_path=str(child_path) if child_path else None)
            if restricted_diagnostics:
                record["delegation_hash"] = delegated
            records.append(record)

    for path in sorted(codex_root.rglob("*.jsonl")) if codex_root.exists() else []:
        if not _recent(path, cutoff):
            continue
        parsed = parse_session(path, "codex", include_locators, diagnostic_key)
        session_id = ""
        try:
            for raw in path.open(encoding="utf-8", errors="replace"):
                item = json.loads(raw)
                if item.get("type") == "session_meta":
                    session_id = str(item.get("payload", {}).get("id") or
                                     item.get("payload", {}).get("session_id") or "")
                    break
        except (OSError, json.JSONDecodeError):
            pass
        session_events = (telemetry.get(_session_key(telemetry_key, session_id), [])
                          if telemetry_key and session_id else [])
        mechanisms = parsed.get("summary", {}).get("delegation_mechanisms", [])
        if not mechanisms and not parsed.get("summary", {}).get("memory_delivery_mechanisms"):
            continue
        record = {
            "provider": "codex",
            "mechanism": mechanisms or ["session"],
            "certainty": ("source_only" if "managed_codex_nested_attempt" in mechanisms
                          else "direct_or_session"),
            "classifications": _classifications(parsed, session_events),
        }
        if include_locators:
            record["path"] = str(path)
        records.append(record)

    # External adapters may not persist provider session logs. Represent their locally confirmed
    # selection/delivery telemetry without pretending a child transcript was correlated.
    for events in telemetry.values():
        for event in events:
            if (str(event.get("mechanism", "")).startswith("external")
                    and event.get("event") == "child_packet"):
                records.append({
                    "provider": event.get("provider", "unknown"),
                    "mechanism": event.get("mechanism"),
                    "certainty": "adapter_telemetry",
                    "classifications": _classifications({"summary": {}}, events),
                })

    counts = Counter(label for record in records for label in record["classifications"])
    return {
        "window_days": days,
        "record_count": len(records),
        "classification_counts": dict(sorted(counts.items())),
        "records": records,
        "privacy": {
            "prompt_bodies_emitted": False,
            "prompt_hashes_emitted": restricted_diagnostics,
            "diagnostic_hash_scope": (
                "per-run keyed; do not persist or upload"
                if restricted_diagnostics else "disabled"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--claude-root", type=Path, default=Path.home() / ".claude/projects")
    parser.add_argument("--codex-root", type=Path, default=Path.home() / ".codex/sessions")
    parser.add_argument("--telemetry-file", type=Path,
                        default=Path.home() / ".cache/autodev-memory/telemetry.jsonl")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--include-locators", action="store_true")
    parser.add_argument("--restricted-diagnostics", action="store_true")
    args = parser.parse_args()
    print(json.dumps(audit(args.claude_root, args.codex_root, args.telemetry_file, args.days,
                           args.include_locators, args.restricted_diagnostics), indent=2))


if __name__ == "__main__":
    main()

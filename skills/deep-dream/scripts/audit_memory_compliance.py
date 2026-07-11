#!/usr/bin/env python3
"""Audit recent Claude/Codex memory delivery locally without emitting prompt bodies or IDs."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from parse_session_log import parse_session  # noqa: E402


REPORT_FIELD_TYPES: dict[str, type | tuple[type, ...]] = {
    "provider": str,
    "mechanism": (str, list),
    "correlation": str,
    "certainty": str,
    "agent_type": str,
    "classifications": list,
    "status": str,
    "packet_version": str,
    "corpus_generation": str,
    "selected_count": int,
    "expanded_count": int,
    "expansion_status": str,
    "parent_path": str,
    "child_path": (str, type(None)),
    "path": str,
    "render_hash": (str, type(None)),
    "selected_ids": list,
    "expanded_ids": list,
    "delivery_id": (str, type(None)),
    "delegation_hash": (str, type(None)),
}
REPORT_TOKEN = re.compile(r"^[A-Za-z0-9._:+-]{1,128}$")
REPORT_GENERATION = re.compile(r"^[0-9a-f]{64}$")
REPORT_CLASSIFICATIONS = {
    "packet_delivered", "child_native_session_start", "explicit_task_packet",
    "selection_attempted", "selection_confirmed", "expansion_attempted",
    "expansion_confirmed", "unavailable", "not_applicable",
}


def _append_record(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    """Enforce the metadata-only report schema before a record can leave the audit."""
    unknown = set(record) - set(REPORT_FIELD_TYPES)
    if unknown:
        raise ValueError(f"unknown compliance report fields: {sorted(unknown)}")
    required = {"provider", "mechanism", "classifications", "status", "packet_version",
                "corpus_generation", "selected_count", "expanded_count", "expansion_status"}
    if not required.issubset(record):
        raise ValueError("compliance report record is missing required typed fields")
    for key, value in record.items():
        if not isinstance(value, REPORT_FIELD_TYPES[key]):
            raise TypeError(f"invalid compliance report field type: {key}")
        if isinstance(value, list) and key in {"classifications", "selected_ids", "expanded_ids"} \
                and not all(isinstance(item, str) for item in value):
            raise TypeError(f"compliance report list must contain strings: {key}")
    if record["provider"] not in {"claude", "codex", "grok", "unknown"}:
        raise ValueError("invalid compliance report provider")
    mechanisms = record["mechanism"] if isinstance(record["mechanism"], list) \
        else [record["mechanism"]]
    if not mechanisms or not all(isinstance(item, str) and REPORT_TOKEN.fullmatch(item)
                                 for item in mechanisms):
        raise ValueError("invalid compliance report mechanism")
    if not set(record["classifications"]).issubset(REPORT_CLASSIFICATIONS):
        raise ValueError("invalid compliance report classification")
    if record["status"] not in {
        "delivered", "fallback", "partial", "unavailable", "failed", "base_unavailable", "unknown",
    }:
        raise ValueError("invalid compliance report status")
    if record["packet_version"] not in {"v1", "v2", "unavailable", "unknown"}:
        raise ValueError("invalid compliance report packet version")
    if record["corpus_generation"] not in {"legacy", "unavailable", "unknown"} \
            and not REPORT_GENERATION.fullmatch(record["corpus_generation"]):
        raise ValueError("invalid compliance report corpus generation")
    records.append(record)


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
            if stamp < cutoff:
                continue
            if isinstance(event.get("session_key"), str):
                grouped[event["session_key"]].append(event)
            elif isinstance(event.get("delegation_id"), str):
                grouped[f"delivery:{event['delegation_id']}"].append(event)
    return key, grouped


def _classifications(parsed: dict[str, Any], telemetry: list[dict[str, Any]]) -> list[str]:
    labels: list[str] = []
    delivery_events = [event for event in parsed.get("events", [])
                       if event.get("kind") == "memory_context"]
    delivered_statuses = {"delivered", "fallback", "partial"}
    unavailable_statuses = {"unavailable", "failed", "base_unavailable"}
    if (any(event.get("delivery_status") in delivered_statuses for event in delivery_events)
            or any(event.get("event") in {"parent_packet", "child_packet"}
                   and event.get("status") in delivered_statuses for event in telemetry)):
        labels.append("packet_delivered")
    if (any(event.get("mechanism") == "native_session_start"
            and event.get("delivery_status") in delivered_statuses for event in delivery_events)
            and parsed.get("summary", {}).get("session_role") == "child"):
        labels.append("child_native_session_start")
    if any(event.get("mechanism") == "explicit_task_packet" for event in delivery_events):
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
        direct_identity = ":".join(
            value for value in (str(event.get("server", "")), str(event.get("tool", ""))) if value
        )
        names = [direct_identity, *[str(value)
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
        direct = direct_identity
        direct_search = "autodev" in direct.lower() and any(
            token in direct.lower() for token in ("search", "by_skill"))
        direct_expand = "autodev" in direct.lower() and "expand" in direct.lower()
        if event.get("kind") in {"tool_result", "mcp_result"} and event.get("status") == "completed":
            if direct_search and "selection_confirmed" not in labels:
                labels.append("selection_confirmed")
            if direct_expand and "expansion_confirmed" not in labels:
                labels.append("expansion_confirmed")
    if (any(event.get("delivery_status") in unavailable_statuses for event in delivery_events)
            or any(event.get("status") in unavailable_statuses for event in telemetry)):
        labels.append("unavailable")
    if not labels:
        labels.append("not_applicable")
    return list(dict.fromkeys(labels))


def _typed_delivery_metadata(
    parsed: dict[str, Any], telemetry: list[dict[str, Any]], restricted: bool,
) -> dict[str, Any]:
    """Project evidence into the report's metadata-only, allowlisted schema."""
    packet_events = [event for event in telemetry
                     if event.get("event") in {"parent_packet", "child_packet"}]
    selection_events = [event for event in telemetry if event.get("event") == "task_selection"]
    parsed_packets = [event for event in parsed.get("events", [])
                      if event.get("kind") == "memory_context"]
    packet = packet_events[-1] if packet_events else {}
    parsed_packet = parsed_packets[-1] if parsed_packets else {}
    selection = selection_events[-1] if selection_events else {}
    result = {
        "status": packet.get("status", parsed_packet.get("delivery_status", "unknown")),
        "packet_version": packet.get("packet_version", parsed_packet.get("packet_version", "unknown")),
        "corpus_generation": packet.get(
            "corpus_generation", parsed_packet.get("corpus_generation", "unknown")
        ),
        "selected_count": int(selection.get("selected_count", 0) or 0),
        "expanded_count": len(selection.get("expanded_ids", []))
        if isinstance(selection.get("expanded_ids", []), list) else 0,
        "expansion_status": selection.get("expansion_status", "not_applicable"),
    }
    if restricted:
        result.update(
            render_hash=packet.get("render_hash", parsed_packet.get("render_hash")),
            selected_ids=selection.get("selected_ids", []),
            expanded_ids=selection.get("expanded_ids", []),
            delivery_id=packet.get("delegation_id", parsed_packet.get("delivery_id")),
        )
    return result


def audit(
    claude_root: Path, codex_root: Path, telemetry_file: Path, days: int,
    include_locators: bool = False, restricted_diagnostics: bool = False,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    cutoff_dt = now - timedelta(days=days)
    cutoff = cutoff_dt.timestamp()
    telemetry_key, telemetry = _telemetry(telemetry_file, cutoff_dt)
    telemetry_by_delivery: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for grouped_events in telemetry.values():
        for event in grouped_events:
            if isinstance(event.get("delegation_id"), str):
                telemetry_by_delivery[event["delegation_id"]].append(event)
    diagnostic_key = os.urandom(32)
    records: list[dict[str, Any]] = []

    for parent in sorted(claude_root.rglob("*.jsonl")) if claude_root.exists() else []:
        if "subagents" in parent.parts or not _recent(parent, cutoff):
            continue
        parsed = parse_session(parent, "claude", include_locators, diagnostic_key,
                               include_correlation=True)
        sid = parent.stem
        session_events = telemetry.get(_session_key(telemetry_key, sid), []) if telemetry_key else []
        children_dir = parent.with_suffix("") / "subagents"
        children = []
        for child in sorted(children_dir.glob("*.jsonl")) if children_dir.is_dir() else []:
            child_parsed = parse_session(child, "claude", include_locators, diagnostic_key,
                                         include_correlation=True)
            first_hash = next((event.get("message_hash") for event in child_parsed["events"]
                               if event.get("kind") == "human_message" and event.get("message_hash")), None)
            delivery_ids = {event.get("delivery_id") for event in child_parsed["events"]
                            if event.get("kind") == "memory_context" and event.get("delivery_id")}
            children.append((child, child_parsed, first_hash, delivery_ids))

        parent_events = [event for event in session_events if event.get("event") == "parent_packet"]
        if parent_events:
            parent_record: dict[str, Any] = {
                "provider": "claude", "mechanism": "session",
                "correlation": "telemetry", "classifications": _classifications(parsed, parent_events),
                **_typed_delivery_metadata(parsed, parent_events, restricted_diagnostics),
            }
            if include_locators:
                parent_record["parent_path"] = str(parent)
            _append_record(records, parent_record)
        used_children: set[Path] = set()
        for event in parsed["events"]:
            if event.get("tool") != "Agent":
                continue
            delegated = event.get("delegated_prompt_hash")
            delivery_id = event.get("delivery_id")
            match = next(((path, value) for path, value, _first, delivery_ids in children
                          if path not in used_children and delivery_id
                          and delivery_id in delivery_ids), None)
            if match is None:
                match = next(((path, value) for path, value, first, _delivery_ids in children
                              if path not in used_children and delegated and first == delegated), None)
            child_path, child_parsed = match if match else (None, None)
            if child_path:
                used_children.add(child_path)
            combined = child_parsed or {"summary": {}, "events": []}
            child_events = telemetry_by_delivery.get(str(delivery_id), []) if delivery_id else []
            labels = _classifications(combined, child_events)
            if event.get("delegation_mechanism") == "claude_agent_explicit_task_packet" \
                    and "explicit_task_packet" not in labels:
                labels.insert(0, "explicit_task_packet")
            elif (event.get("delegation_mechanism") == "claude_agent_without_observed_packet"
                  and labels == ["not_applicable"]
                  and (event.get("agent_type") or "generic") != "generic"):
                labels = ["unavailable"]
            record: dict[str, Any] = {
                "provider": "claude", "mechanism": "Agent",
                "correlation": "confirmed" if child_path else "unconfirmed",
                "agent_type": event.get("agent_type") or "unknown",
                "classifications": list(dict.fromkeys(labels)),
                **_typed_delivery_metadata(combined, child_events, restricted_diagnostics),
            }
            if include_locators:
                record.update(parent_path=str(parent), child_path=str(child_path) if child_path else None)
            if restricted_diagnostics:
                record["delegation_hash"] = delegated
                record["delivery_id"] = delivery_id
            _append_record(records, record)

    for path in sorted(codex_root.rglob("*.jsonl")) if codex_root.exists() else []:
        if not _recent(path, cutoff):
            continue
        parsed = parse_session(path, "codex", include_locators, diagnostic_key,
                               include_correlation=True)
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
        has_memory_tools = any(
            "autodev" in ":".join((str(event.get("server", "")), str(event.get("tool", "")))).lower()
            for event in parsed.get("events", [])
        )
        if (not mechanisms and not parsed.get("summary", {}).get("memory_delivery_mechanisms")
                and not session_events and not has_memory_tools):
            continue
        delivery_ids = {event.get("delivery_id") for event in parsed.get("events", [])
                        if event.get("kind") == "memory_context" and event.get("delivery_id")}
        record_delivery_ids = delivery_ids or {None}
        for delivery_id in record_delivery_ids:
            matching = (telemetry_by_delivery.get(str(delivery_id), [])
                        if delivery_id else session_events)
            filtered = {
                **parsed,
                "events": [
                    event for event in parsed.get("events", [])
                    if event.get("kind") != "memory_context"
                    or not delivery_id or event.get("delivery_id") == delivery_id
                ],
            }
            record = {
                "provider": "codex",
                "mechanism": mechanisms or ["session"],
                "certainty": ("source_only" if "managed_codex_nested_attempt" in mechanisms
                              else "direct_or_session"),
                "classifications": _classifications(filtered, matching),
                **_typed_delivery_metadata(filtered, matching, restricted_diagnostics),
            }
            if include_locators:
                record["path"] = str(path)
            if restricted_diagnostics:
                record["delivery_id"] = delivery_id
            _append_record(records, record)

    # External adapters may not persist provider session logs. Represent their locally confirmed
    # selection/delivery telemetry without pretending a child transcript was correlated.
    for delivery_id, matching in telemetry_by_delivery.items():
        if not any(str(event.get("mechanism", "")).startswith("external") for event in matching):
            continue
        for event in matching:
            if event.get("event") != "child_packet":
                continue
            record = {
                "provider": event.get("provider", "unknown"),
                "mechanism": event.get("mechanism"),
                "certainty": "adapter_telemetry",
                "classifications": _classifications({"summary": {}, "events": []}, matching),
                **_typed_delivery_metadata({"summary": {}, "events": []}, matching,
                                           restricted_diagnostics),
            }
            if restricted_diagnostics:
                record["delivery_id"] = delivery_id
            _append_record(records, record)

    counts = Counter(label for record in records for label in record["classifications"])
    return {
        "window_days": days,
        "record_count": len(records),
        "classification_counts": dict(sorted(counts.items())),
        "records": records,
        "privacy": {
            "prompt_bodies_emitted": False,
            "prompt_hashes_emitted": restricted_diagnostics,
            "entry_ids_emitted": restricted_diagnostics,
            "render_hashes_emitted": restricted_diagnostics,
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

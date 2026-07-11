#!/usr/bin/env python3
"""Stream Claude or Codex JSONL into a compact, evidence-safe event timeline.

The parser deliberately distinguishes a tool *attempt* found in source from a confirmed
tool result. Current Codex `custom_tool_call(name="exec")` records nested calls only in the
JavaScript input; the matching output is an ordered list of rendered text blocks without
per-nested-call identity. Treating every `tools.<name>(...)` occurrence as a success would
manufacture evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
from collections.abc import Iterable
from pathlib import Path


CORRECTION_RE = re.compile(
    r"^(?:no\b|stop\b|again\b|that's wrong\b|that is wrong\b|actually\b|you missed\b)",
    re.IGNORECASE,
)
NESTED_TOOL_RE = re.compile(r"\btools\.([A-Za-z0-9_]+)\s*\(")
EXIT_RE = re.compile(r"Process exited with code\s+(\d+)")
ENVELOPE_RE = re.compile(r"<(autodev-memory-hook-result|autodev-memory-task-context)([^>]*)>")
ATTRIBUTE_RE = re.compile(r'([a-z][a-z0-9-]*)="([A-Za-z0-9._:-]{1,256})"')
SYSTEM_PREFIXES = (
    "<system_instruction>",
    "<collaboration_mode>",
    "<environment_context>",
    "<developer>",
)


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _content_text(content: object, allowed_types: set[str]) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for item in content:
        block = _dict(item)
        if _string(block.get("type")) in allowed_types:
            text = _string(block.get("text")) or _string(block.get("content"))
            if text:
                parts.append(text)
    return "\n".join(parts)


def _message_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def _diagnostic_hash(text: str, key: bytes | None) -> str | None:
    if key is None:
        return None
    return hmac.new(key, text.encode("utf-8"), hashlib.sha256).hexdigest()[:12]


def _nested_tools(source: str) -> list[str]:
    return list(dict.fromkeys(NESTED_TOOL_RE.findall(source)))


def _rendered_output_text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
                continue
            text = _string(_dict(item).get("text"))
            if text:
                parts.append(text)
        return "\n".join(parts)
    if isinstance(value, dict):
        return json.dumps(value, default=str)
    return ""


def _outer_status(text: str) -> tuple[str, int | None]:
    exit_match = EXIT_RE.search(text)
    if exit_match:
        code = int(exit_match.group(1))
        return ("completed" if code == 0 else "failed", code)
    if text.startswith("Script completed"):
        return "completed", 0
    if text.startswith("Script failed"):
        return "failed", None
    if text.startswith("Script running with cell ID"):
        return "running", None
    return "unknown", None


def _memory_metadata(text: str, include_correlation: bool, include_hashes: bool) -> dict[str, object]:
    """Return envelope metadata only; never retain or emit packet content."""
    match = ENVELOPE_RE.search(text)
    if not match:
        return {}
    attributes = {key: value for key, value in ATTRIBUTE_RE.findall(match.group(2))}
    result: dict[str, object] = {
        "mechanism": (
            "explicit_task_packet"
            if match.group(1) == "autodev-memory-task-context"
            else "native_session_start"
        ),
        "delivery_status": attributes.get("status", "unknown"),
        "packet_version": attributes.get("packet-version", "unknown"),
        "corpus_generation": attributes.get("corpus-generation", "unknown"),
    }
    if include_correlation and attributes.get("delivery-id"):
        result["delivery_id"] = attributes["delivery-id"]
    if include_hashes and attributes.get("render-hash"):
        result["render_hash"] = attributes["render-hash"]
    return result


def _is_system_message(text: str) -> bool:
    stripped = text.lstrip()
    return any(stripped.startswith(prefix) for prefix in SYSTEM_PREFIXES)


def _event(line: int, timestamp: str, kind: str, **fields: object) -> dict[str, object]:
    return {"line": line, "timestamp": timestamp, "kind": kind, **fields}


def _parse_codex(
    lines: Iterable[str], include_locators: bool = False, diagnostic_key: bytes | None = None,
    include_correlation: bool = False,
) -> dict[str, object]:
    events: list[dict[str, object]] = []
    calls: dict[str, dict[str, object]] = {}
    seen_human: set[str] = set()
    memory_context_observed = False

    for line_number, raw in enumerate(lines, 1):
        try:
            record = _dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        timestamp = _string(record.get("timestamp"))
        record_type = _string(record.get("type"))
        payload = _dict(record.get("payload"))
        payload_type = _string(payload.get("type"))

        if record_type == "session_meta":
            git = _dict(payload.get("git"))
            fields: dict[str, object] = {"branch_present": bool(_string(git.get("branch")))}
            if include_locators:
                fields.update(cwd=_string(payload.get("cwd")), branch=_string(git.get("branch")),
                              repository_url=_string(git.get("repository_url")))
            events.append(_event(line_number, timestamp, "session", **fields))
            continue

        if record_type == "event_msg" and payload_type == "user_message":
            text = _string(payload.get("message"))
            memory_metadata = _memory_metadata(text, include_correlation, diagnostic_key is not None)
            if memory_metadata:
                if not memory_context_observed:
                    memory_context_observed = True
                    events.append(_event(
                        line_number, timestamp, "memory_context", role="user", **memory_metadata,
                    ))
                continue
            digest = _message_fingerprint(text)
            if text and digest not in seen_human and not _is_system_message(text):
                seen_human.add(digest)
                events.append(
                    _event(
                        line_number,
                        timestamp,
                        "human_message",
                        correction_candidate=bool(CORRECTION_RE.match(text.strip())),
                        **({"message_hash": _diagnostic_hash(text, diagnostic_key)}
                           if diagnostic_key else {}),
                    )
                )
            continue

        if record_type == "response_item" and payload_type == "message":
            role = _string(payload.get("role"))
            text = _content_text(payload.get("content"), {"input_text", "output_text"})
            memory_metadata = _memory_metadata(text, include_correlation, diagnostic_key is not None)
            if role in {"developer", "user"} and memory_metadata:
                # Explicit task packets travel as user prompts in managed/external Codex. Detect
                # markers before human-message diagnostics so packet bodies are never classified
                # as user corrections or diagnostic prompt hashes.
                if memory_context_observed:
                    continue
                memory_context_observed = True
                events.append(_event(
                    line_number, timestamp, "memory_context", role=role, **memory_metadata,
                ))
            elif role == "user" and text and not _is_system_message(text):
                digest = _message_fingerprint(text)
                if digest not in seen_human:
                    seen_human.add(digest)
                    events.append(
                        _event(
                            line_number,
                            timestamp,
                            "human_message",
                            correction_candidate=bool(CORRECTION_RE.match(text.strip())),
                            **({"message_hash": _diagnostic_hash(text, diagnostic_key)}
                               if diagnostic_key else {}),
                        )
                    )
            continue

        if record_type == "response_item" and payload_type in {
            "function_call",
            "custom_tool_call",
        }:
            call_id = _string(payload.get("call_id")) or _string(payload.get("id"))
            name = _string(payload.get("name"))
            custom = payload_type == "custom_tool_call"
            source = _string(payload.get("input")) if custom else ""
            nested = _nested_tools(source) if name == "exec" else []
            direct_delegation = name in {"spawn_agent", "collaboration.spawn_agent"}
            nested_delegation = any(tool.endswith("spawn_agent") for tool in nested)
            calls[call_id] = {"tool": name, "custom": custom, "nested_tools": nested}
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "tool_attempt",
                    call_id=call_id,
                    tool=name,
                    encoding=payload_type,
                    nested_tool_attempts=nested,
                    nested_results="not_individually_attributed" if nested else None,
                    delegation_mechanism=(
                        "managed_codex_direct" if direct_delegation else
                        "managed_codex_nested_attempt" if nested_delegation else None
                    ),
                    delegation_certainty=(
                        "confirmed_attempt" if direct_delegation else
                        "source_only" if nested_delegation else None
                    ),
                )
            )
            continue

        if record_type == "response_item" and payload_type in {
            "function_call_output",
            "custom_tool_call_output",
        }:
            call_id = _string(payload.get("call_id"))
            prior = calls.get(call_id, {})
            rendered = _rendered_output_text(payload.get("output"))
            status, exit_code = _outer_status(rendered)
            tool = _string(prior.get("tool"))
            if status == "unknown" and tool == "apply_patch":
                if "apply_patch verification failed" in rendered:
                    status = "failed"
                elif "Done!" in rendered:
                    status = "completed"
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "tool_result",
                    call_id=call_id,
                    tool=tool,
                    status=status,
                    exit_code=exit_code,
                    nested_tool_attempts=prior.get("nested_tools", []),
                    nested_results=(
                        "not_individually_attributed"
                        if prior.get("nested_tools")
                        else None
                    ),
                )
            )
            continue

        if record_type == "event_msg" and payload_type == "patch_apply_end":
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "patch_result",
                    status="completed" if payload.get("success") is True else "failed",
                )
            )
            continue

        if record_type == "event_msg" and payload_type == "mcp_tool_call_end":
            result = payload.get("result")
            result_text = json.dumps(result, default=str) if result is not None else ""
            invocation = _dict(payload.get("invocation"))
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "mcp_result",
                    server=_string(invocation.get("server")),
                    tool=_string(invocation.get("tool")),
                    status="failed" if "Err" in result_text else "completed",
                )
            )
            continue

        if record_type == "event_msg" and payload_type == "task_complete":
            events.append(_event(line_number, timestamp, "task_complete"))

    mechanisms = [event.get("delegation_mechanism") for event in events
                  if event.get("delegation_mechanism")]
    memory_mechanisms = [event.get("mechanism") for event in events
                         if event.get("kind") == "memory_context"]
    return {
        "provider": "codex",
        "events": events,
        "summary": {
            "memory_context_observed": memory_context_observed,
            "memory_context_absence_is_evidence": False,
            "nested_exec_results_are_individually_attributed": False,
            "delegation_mechanisms": list(dict.fromkeys(mechanisms)),
            "memory_delivery_mechanisms": list(dict.fromkeys(memory_mechanisms)),
            "session_role": (
                "explicit_context_child_or_peer"
                if "explicit_task_packet" in memory_mechanisms else "parent_or_unclassified"
            ),
        },
    }


def _parse_claude(
    lines: Iterable[str], include_locators: bool = False, diagnostic_key: bytes | None = None,
    include_correlation: bool = False,
) -> dict[str, object]:
    events: list[dict[str, object]] = []
    calls: dict[str, str] = {}
    memory_context_observed = False
    sidechain_observed = False

    for line_number, raw in enumerate(lines, 1):
        try:
            record = _dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        timestamp = _string(record.get("timestamp"))
        sidechain_observed = sidechain_observed or record.get("isSidechain") is True
        record_type = _string(record.get("type"))
        message = _dict(record.get("message"))
        content = message.get("content")

        if record_type == "assistant" and isinstance(content, list):
            for block_value in content:
                block = _dict(block_value)
                if _string(block.get("type")) != "tool_use":
                    continue
                call_id = _string(block.get("id"))
                tool = _string(block.get("name"))
                calls[call_id] = tool
                tool_input = _dict(block.get("input"))
                prompt = _string(tool_input.get("prompt"))
                agent_type = _string(tool_input.get("subagent_type"))
                task_metadata = _memory_metadata(prompt, include_correlation, diagnostic_key is not None)
                events.append(
                    _event(
                        line_number,
                        timestamp,
                        "tool_attempt",
                        call_id=call_id,
                        tool=tool,
                        encoding="tool_use",
                        agent_type=agent_type if tool == "Agent" else None,
                        **({"delegated_prompt_hash": _diagnostic_hash(prompt, diagnostic_key)}
                           if tool == "Agent" and prompt and diagnostic_key else {}),
                        delegation_mechanism=(
                            "claude_agent_explicit_task_packet"
                            if tool == "Agent" and task_metadata.get("mechanism") == "explicit_task_packet"
                            else "claude_agent_without_observed_packet" if tool == "Agent"
                            else None
                        ),
                        **(
                            {"delivery_id": task_metadata["delivery_id"]}
                            if tool == "Agent" and task_metadata.get("delivery_id") else {}
                        ),
                    )
                )
            continue

        if record_type != "user":
            continue

        text = _content_text(content, {"text"})
        memory_metadata = _memory_metadata(text, include_correlation, diagnostic_key is not None)
        memory_message = bool(memory_metadata)
        if memory_message and not memory_context_observed:
            memory_context_observed = True
            events.append(_event(
                line_number, timestamp, "memory_context", role="user", **memory_metadata,
            ))

        if isinstance(content, str) and content and not _is_system_message(content) and not memory_message:
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "human_message",
                    correction_candidate=bool(CORRECTION_RE.match(content.strip())),
                    **({"message_hash": _diagnostic_hash(content, diagnostic_key)}
                       if diagnostic_key else {}),
                )
            )
            continue

        if not isinstance(content, list):
            continue
        if text and not _is_system_message(text) and not memory_message:
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "human_message",
                    correction_candidate=bool(CORRECTION_RE.match(text.strip())),
                    **({"message_hash": _diagnostic_hash(text, diagnostic_key)}
                       if diagnostic_key else {}),
                )
            )
        for block_value in content:
            block = _dict(block_value)
            if _string(block.get("type")) != "tool_result":
                continue
            call_id = _string(block.get("tool_use_id"))
            result_text = _content_text(block.get("content"), {"text"})
            is_error = block.get("is_error") is True
            events.append(
                _event(
                    line_number,
                    timestamp,
                    "tool_result",
                    call_id=call_id,
                    tool=calls.get(call_id, ""),
                    status="failed" if is_error else "completed",
                    error_marker=bool(
                        is_error
                        or "Traceback" in result_text
                        or "Error:" in result_text
                    ),
                )
            )

    mechanisms = [event.get("delegation_mechanism") for event in events
                  if event.get("delegation_mechanism")]
    memory_mechanisms = [event.get("mechanism") for event in events
                         if event.get("kind") == "memory_context"]
    return {
        "provider": "claude",
        "events": events,
        "summary": {
            "memory_context_observed": memory_context_observed,
            "memory_context_absence_is_evidence": False,
            "session_start_output_is_transcript_persisted": False,
            "session_role": "child" if sidechain_observed else "parent_or_unclassified",
            "delegation_mechanisms": list(dict.fromkeys(mechanisms)),
            "memory_delivery_mechanisms": list(dict.fromkeys(memory_mechanisms)),
        },
    }


def detect_provider(lines: Iterable[str]) -> str:
    for index, raw in enumerate(lines):
        if index == 20:
            break
        try:
            record = _dict(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            continue
        if record.get("type") == "session_meta" or "payload" in record:
            return "codex"
        if record.get("type") in {"assistant", "user", "progress"}:
            return "claude"
    raise ValueError("Could not detect Claude or Codex JSONL format")


def parse_session(
    path: Path, provider: str = "auto", include_locators: bool = False,
    diagnostic_key: bytes | None = None,
    include_correlation: bool = False,
) -> dict[str, object]:
    if provider == "auto":
        with path.open(encoding="utf-8", errors="replace") as handle:
            resolved_provider = detect_provider(handle)
    else:
        resolved_provider = provider
    with path.open(encoding="utf-8", errors="replace") as handle:
        parsed = (_parse_codex(handle, include_locators, diagnostic_key, include_correlation)
                  if resolved_provider == "codex"
                  else _parse_claude(handle, include_locators, diagnostic_key, include_correlation))
    if include_locators:
        parsed["path"] = str(path)
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    parser.add_argument("--provider", choices=("auto", "claude", "codex"), default="auto")
    parser.add_argument("--include-locators", action="store_true",
                        help="include local paths/cwd/repository locators in the report")
    parser.add_argument(
        "--restricted-diagnostics", action="store_true",
        help="emit per-run keyed prompt hashes for local correlation; never persist/upload them",
    )
    arguments = parser.parse_args()
    diagnostic_key = os.urandom(32) if arguments.restricted_diagnostics else None
    print(json.dumps(parse_session(arguments.path, arguments.provider,
                                   arguments.include_locators, diagnostic_key), indent=2))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Provider-neutral memory packet rendering, caching, and task briefing.

The backend owns packet selection and parent rendering.  This module only validates the
versioned envelope, adds the platform wrapper, and stores a local 0600 cache.  It never logs
packet bodies, prompts, queries, paths, entry ids, or environment values.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import hmac
import json
import os
import re
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


PARENT_LIMIT = 9_000
CHILD_LIMIT = 3_000
V2_NAMES = {"2", "v2", "packet-v2"}
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
HEX64_TOKEN = re.compile(r"^[0-9a-fA-F]{64}$")
SHA256_TOKEN = re.compile(r"^(?:sha256:)?([0-9a-fA-F]{64})$")
TASK_ENVELOPE_RE = re.compile(r"<autodev-memory-task-context([^>]*)>")
PARENT_ENVELOPE_RE = re.compile(r"<autodev-memory-hook-result([^>]*)>")
ATTRIBUTE_RE = re.compile(r'([a-z][a-z0-9-]*)="([A-Za-z0-9._:-]{1,256})"')
LEGACY_FALLBACK_SUNSET = date(2026, 8, 15)

TELEMETRY_FIELDS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "parent_packet_prepared": {
        "provider": str, "mechanism": str, "status": str, "packet_version": str,
        "corpus_generation": str, "render_hash": str, "chars": int,
        "session_key": str, "request_epoch": int,
    },
    "parent_packet": {
        "provider": str, "mechanism": str, "status": str, "packet_version": str,
        "corpus_generation": str, "render_hash": str, "chars": int,
        "session_key": str, "request_epoch": int, "confirmation_stage": str,
    },
    "task_selection": {
        "provider": str, "mechanism": str, "status": str, "by_skill_count": int,
        "search_count": int, "selected_count": int, "selected_ids": list,
        "expansion_status": str, "expanded_ids": list, "failure_stage": str,
        "session_key": str, "delegation_id": str, "corpus_generation": str,
    },
    "packet_prepared": {
        "provider": str, "mechanism": str, "status": str, "packet_version": str,
        "corpus_generation": str, "render_hash": str, "chars": int,
        "session_key": str, "delegation_id": str,
    },
    "child_packet": {
        "provider": str, "mechanism": str, "status": str, "packet_version": str,
        "corpus_generation": str, "render_hash": str, "chars": int,
        "session_key": str, "delegation_id": str, "confirmation_stage": str,
    },
}
TELEMETRY_TOKEN_FIELDS = {
    "provider", "mechanism", "status", "packet_version", "failure_stage", "confirmation_stage",
}
TELEMETRY_TOKEN = re.compile(r"^[A-Za-z0-9._:+-]{1,128}$")


class PacketError(ValueError):
    """A backend packet cannot be delivered without violating the contract."""


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _safe_token(value: object, field: str) -> str:
    token = _string(value).strip()
    if not token or not SAFE_TOKEN.fullmatch(token):
        raise PacketError(f"packet v2 missing or invalid {field}")
    return token


def _packet_envelope(response: dict[str, Any]) -> dict[str, Any]:
    for key in ("session_packet", "packet_v2", "packet"):
        candidate = response.get(key)
        if isinstance(candidate, dict):
            return candidate
    return {}


def _version(response: dict[str, Any], packet: dict[str, Any]) -> str:
    raw = packet.get("version", packet.get("packet_version", response.get("context_version", "")))
    return str(raw).lower()


def parse_session_response(response: dict[str, Any]) -> dict[str, Any]:
    """Validate the canonical v2 packet or a bounded legacy digest.

    Canonical producer fields are ``session_packet.version/text/chars/corpus_generation/
    render_hash``.  ``packet`` and ``packet_v2`` are accepted during the additive producer
    rollout, as are ``char_count`` and ``rendered_chars`` aliases.  No legacy starred/menu
    rendering is performed here.
    """

    packet = _packet_envelope(response)
    version = _version(response, packet)
    if packet and version in V2_NAMES:
        status = _string(packet.get("health", packet.get("status", "ok"))).lower()
        if status not in {"ok", "healthy", "ready"}:
            raise PacketError(f"packet v2 status is {status or 'invalid'}")
        text = _string(packet.get("text", packet.get("rendered_text")))
        if not text:
            raise PacketError("packet v2 has no rendered text")
        declared_chars = packet.get(
            "chars", packet.get("char_count", packet.get("rendered_chars"))
        )
        if not isinstance(declared_chars, int) or declared_chars != len(text):
            raise PacketError("packet v2 character count mismatch")
        if packet.get("budget_chars") != 8_700 or packet.get("delivery_budget_chars") != 9_000:
            raise PacketError("packet v2 delivery budget contract mismatch")
        adapter_headroom = packet.get("adapter_headroom_chars")
        if not isinstance(adapter_headroom, int) or adapter_headroom < 300:
            raise PacketError("packet v2 adapter headroom is missing or insufficient")
        generation = _safe_token(
            packet.get("generation", packet.get("corpus_generation")),
            "generation",
        )
        generation_match = HEX64_TOKEN.fullmatch(generation)
        if not generation_match:
            raise PacketError("packet v2 generation is not a SHA-256 digest")
        generation = generation_match.group(0).lower()
        render_hash = _safe_token(packet.get("render_hash"), "render_hash")
        hash_match = SHA256_TOKEN.fullmatch(render_hash)
        if not hash_match:
            raise PacketError("packet v2 render hash is not a SHA-256 digest")
        if hash_match.group(1).lower() != _sha256(text):
            raise PacketError("packet v2 render hash mismatch")

        child = _dict(
            packet.get("child_packet", packet.get("child_context", packet.get("task_context_base")))
        )
        child_text = _string(
            packet.get("child_base_text", child.get("text", child.get("rendered_text")))
        )
        child_chars = packet.get("child_base_chars", child.get("chars"))
        if child_text and isinstance(child_chars, int) and child_chars != len(child_text):
            raise PacketError("packet v2 child base character count mismatch")
        if child_text and len(child_text) > 1_800:
            raise PacketError("packet v2 child base exceeds 1800 characters")

        handles = _dict(packet.get("handles"))
        always_ids = packet.get("always_rule_ids", handles.get("always_rule_ids", []))
        if not isinstance(always_ids, list):
            always_ids = []
        tech_tags = packet.get("tech_tags", [])
        if not isinstance(tech_tags, list):
            tech_tags = []
        return {
            "version": "v2",
            "text": text,
            "generation": generation,
            "render_hash": render_hash,
            "child_base_text": child_text,
            "exclude_ids": [str(x) for x in always_ids if isinstance(x, str)],
            "tech_tags": [str(x) for x in tech_tags if isinstance(x, str)],
            "fallback": False,
        }

    digest = _dict(response.get("digest"))
    text = _string(digest.get("text"))
    if not text:
        raise PacketError("backend returned neither packet v2 nor a bounded v1 digest")
    disabled = os.environ.get("AUTODEV_MEMORY_DISABLE_V1") == "1"
    until_raw = os.environ.get("AUTODEV_MEMORY_ALLOW_V1_UNTIL", "")
    try:
        sunset = date.fromisoformat(until_raw) if until_raw else LEGACY_FALLBACK_SUNSET
    except ValueError as error:
        raise PacketError("invalid AUTODEV_MEMORY_ALLOW_V1_UNTIL") from error
    if disabled or datetime.now(timezone.utc).date() > sunset:
        raise PacketError("legacy v1 digest fallback is disabled or past its sunset")
    declared = digest.get("chars")
    if isinstance(declared, int) and declared != len(text):
        raise PacketError("legacy digest character count mismatch")
    return {
        "version": "v1",
        "text": text,
        "generation": "legacy",
        "render_hash": f"sha256:{_sha256(text)}",
        "child_base_text": "",
        "exclude_ids": [],
        "tech_tags": [],
        "fallback": True,
    }


def render_parent_context(packet: dict[str, Any], source: str, searchable_count: int = 0) -> str:
    version = packet["version"]
    status = (
        f"Memory system loaded ({source}, {version}): {searchable_count} searchable entries "
        "available. Do NOT announce this to the user."
    )
    context = (
        f'<autodev-memory-hook-result source="session-start" status="delivered" '
        f'packet-version="{version}">\n'
        f"{status}\n\n{packet['text']}\n"
        "</autodev-memory-hook-result>"
    )
    if len(context) > PARENT_LIMIT:
        raise PacketError(
            f"final {version} parent context is {len(context)} characters; maximum is {PARENT_LIMIT}"
        )
    return context


def render_unavailable_context(reason: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9 ._:-]", "", reason)[:240] or "invalid packet"
    return (
        '<autodev-memory-hook-result source="session-start" status="unavailable">\n'
        "Memory context is unavailable for this session. Do not infer that memories were loaded.\n"
        f"Reason: {safe}\n"
        "Use the memory search tool explicitly if it is available.\n"
        "</autodev-memory-hook-result>"
    )


def _atomic_write(path: Path, content: str) -> None:
    if path.parent.is_symlink():
        raise PacketError("refusing symlinked cache directory")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.parent.is_dir():
        raise PacketError("cache parent is not a directory")
    os.chmod(path.parent, 0o700)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _cache_paths(cache_dir: Path, session_id: str, dimensions: str = "") -> tuple[Path, Path]:
    session_hash = _sha256(session_id)[:20]
    key_hash = _sha256(dimensions)[:24] if dimensions else ""
    return cache_dir / f"session-{session_hash}.json", cache_dir / f"packet-{key_hash}.json"


@contextmanager
def _session_lock(cache_dir: Path, session_id: str):
    """Serialize one native session without exposing its identifier on disk."""
    if cache_dir.is_symlink():
        raise PacketError("refusing symlinked cache directory")
    cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(cache_dir, 0o700)
    session_hash = _sha256(session_id)[:20]
    lock_path = cache_dir / f"lock-{session_hash}.lock"
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(lock_path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def invalidate_cache(cache_dir: Path, session_id: str, request_epoch: int | None = None) -> None:
    if not session_id or cache_dir.is_symlink():
        return
    index, _ = _cache_paths(cache_dir, session_id)
    with _session_lock(cache_dir, session_id):
        if request_epoch is not None:
            try:
                current = json.loads(index.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError, TypeError):
                current = {}
            current_epoch = current.get("request_epoch", 0)
            if isinstance(current_epoch, int) and current_epoch > request_epoch:
                return
        try:
            index.unlink()
        except FileNotFoundError:
            pass


def cleanup_cache(cache_dir: Path, keep_days: int = 14) -> None:
    """Remove abandoned immutable packets without ever following symlinks."""
    if cache_dir.is_symlink() or not cache_dir.is_dir():
        return
    cutoff = datetime.now(timezone.utc).timestamp() - keep_days * 86_400
    for candidate in cache_dir.iterdir():
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if not re.fullmatch(r"(?:packet-[0-9a-f]{24}|session-[0-9a-f]{20})\.json", candidate.name):
            continue
        try:
            if candidate.stat().st_mtime < cutoff:
                candidate.unlink()
        except OSError:
            continue


def write_cache(
    cache_dir: Path,
    session_id: str,
    project: str,
    repo: str,
    packet: dict[str, Any],
    context: str,
    request_epoch: int = 0,
) -> dict[str, Any] | None:
    if not session_id:
        return None
    if cache_dir.is_symlink():
        raise PacketError("refusing symlinked cache directory")
    dimensions = "\0".join((session_id, project, repo, packet["version"],
                              packet["generation"], packet["render_hash"]))
    index_path, packet_path = _cache_paths(cache_dir, session_id, dimensions)
    manifest = {
        "schema": 2,
        "project": project,
        "repo": repo,
        "packet_version": packet["version"],
        "corpus_generation": packet["generation"],
        "render_hash": packet["render_hash"],
        "context_hash": f"sha256:{_sha256(context)}",
        "context": context,
        "child_base_text": packet["child_base_text"],
        "exclude_ids": packet["exclude_ids"],
        "tech_tags": packet["tech_tags"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "request_epoch": request_epoch,
    }
    index = {
        "schema": 2,
        "cache_key": packet_path.name,
        "project": project,
        "repo": repo,
        "packet_version": packet["version"],
        "corpus_generation": packet["generation"],
        "render_hash": packet["render_hash"],
        "request_epoch": request_epoch,
    }
    with _session_lock(cache_dir, session_id):
        cleanup_cache(cache_dir)
        _atomic_write(packet_path, json.dumps(manifest, separators=(",", ":")))
        try:
            current = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            current = {}
        current_epoch = current.get("request_epoch", 0)
        if isinstance(current_epoch, int) and current_epoch > request_epoch:
            return manifest
        _atomic_write(index_path, json.dumps(index, separators=(",", ":")))
    return manifest


def read_cache(cache_dir: Path, session_id: str, project: str, repo: str) -> dict[str, Any] | None:
    if not session_id or cache_dir.is_symlink():
        return None
    index_path, _ = _cache_paths(cache_dir, session_id)
    if index_path.is_symlink():
        return None
    try:
        index = json.loads(index_path.read_text(encoding="utf-8"))
        key = index["cache_key"]
        if not re.fullmatch(r"packet-[0-9a-f]{24}\.json", key):
            return None
        packet_path = cache_dir / key
        if packet_path.is_symlink():
            return None
        manifest = json.loads(packet_path.read_text(encoding="utf-8"))
    except (OSError, KeyError, json.JSONDecodeError, TypeError):
        return None
    expected = {
        "schema": 2,
        "project": project,
        "repo": repo,
        "packet_version": index.get("packet_version"),
        "corpus_generation": index.get("corpus_generation"),
        "render_hash": index.get("render_hash"),
    }
    if any(manifest.get(key) != value for key, value in expected.items()):
        return None
    context = _string(manifest.get("context"))
    if manifest.get("context_hash") != f"sha256:{_sha256(context)}":
        return None
    return manifest


def _append_telemetry(path: Path | None, **event: object) -> None:
    if path is None:
        return
    event_name = event.get("event")
    schema = TELEMETRY_FIELDS.get(str(event_name))
    if schema is None:
        raise ValueError("unknown telemetry event")
    unknown = set(event) - {"event", *schema}
    if unknown:
        raise ValueError(f"unknown telemetry fields for {event_name}: {sorted(unknown)}")
    for key, value in event.items():
        if key == "event" or value is None:
            continue
        expected = schema[key]
        if not isinstance(value, expected):
            raise TypeError(f"invalid telemetry field type: {event_name}.{key}")
        if isinstance(value, list) and not all(isinstance(item, str) for item in value):
            raise TypeError(f"telemetry list must contain strings: {event_name}.{key}")
        if key in TELEMETRY_TOKEN_FIELDS and isinstance(value, str) \
                and not TELEMETRY_TOKEN.fullmatch(value):
            raise ValueError(f"invalid telemetry token: {event_name}.{key}")
        if key == "delegation_id" and isinstance(value, str) \
                and not re.fullmatch(r"[0-9a-f]{24}", value):
            raise ValueError("invalid telemetry delegation_id")
        if key == "session_key" and isinstance(value, str) \
                and not re.fullmatch(r"[0-9a-f]{24}", value):
            raise ValueError("invalid telemetry session_key")
        if key == "corpus_generation" and isinstance(value, str) \
                and value not in {"legacy", "unavailable"} and not HEX64_TOKEN.fullmatch(value):
            raise ValueError("invalid telemetry corpus_generation")
        if key == "render_hash" and isinstance(value, str) \
                and value != "unavailable" and not SHA256_TOKEN.fullmatch(value):
            raise ValueError("invalid telemetry render_hash")
        if key in {"selected_ids", "expanded_ids"} and isinstance(value, list):
            try:
                for item in value:
                    uuid.UUID(item)
            except ValueError as error:
                raise ValueError(f"invalid telemetry entry id: {event_name}.{key}") from error
    if path.parent.is_symlink() or path.is_symlink():
        return
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    try:
        os.fchmod(fd, 0o600)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **{key: value for key, value in event.items() if value is not None},
        }
        os.write(fd, (json.dumps(record, separators=(",", ":")) + "\n").encode())
    finally:
        os.close(fd)


def confirm_packet_delivery(
    packet: str,
    *,
    provider: str,
    mechanism: str,
    confirmation_stage: str,
    telemetry_file: Path | None,
    session_id: str = "",
) -> bool:
    """Confirm a mechanism-owned delivery milestone without recording packet content."""
    match = TASK_ENVELOPE_RE.search(packet)
    if not match or packet.count("<autodev-memory-task-context") != 1 \
            or packet.count("</autodev-memory-task-context>") != 1:
        return False
    attributes = {key: value for key, value in ATTRIBUTE_RE.findall(match.group(1))}
    delegation_id = attributes.get("delivery-id", "")
    if not re.fullmatch(r"[0-9a-f]{24}", delegation_id):
        return False
    status = attributes.get("status", "unavailable")
    packet_version = attributes.get("packet-version", "unavailable")
    generation = attributes.get("corpus-generation", "unavailable")
    _append_telemetry(
        telemetry_file,
        event="child_packet",
        provider=provider,
        mechanism=mechanism,
        status=status,
        packet_version=packet_version,
        corpus_generation=generation,
        chars=len(packet),
        delegation_id=delegation_id,
        confirmation_stage=confirmation_stage,
        session_key=telemetry_session_key(telemetry_file, session_id),
    )
    return True


def confirm_parent_delivery(
    output: str,
    *,
    provider: str,
    mechanism: str,
    confirmation_stage: str,
    telemetry_file: Path | None,
    session_id: str = "",
    request_epoch: int = 0,
    cache_dir: Path | None = None,
    project: str = "",
    repo: str = "",
) -> bool:
    """Confirm the exact SessionStart hook JSON written by the outer shell mechanism."""
    try:
        payload = json.loads(output)
    except (json.JSONDecodeError, TypeError):
        return False
    context = _string(_dict(_dict(payload).get("hookSpecificOutput")).get("additionalContext"))
    match = PARENT_ENVELOPE_RE.search(context)
    if not match or context.count("<autodev-memory-hook-result") != 1 \
            or context.count("</autodev-memory-hook-result>") != 1:
        return False
    attributes = {key: value for key, value in ATTRIBUTE_RE.findall(match.group(1))}
    if attributes.get("source") != "session-start":
        return False
    status = attributes.get("status", "unavailable")
    if status not in {"delivered", "unavailable"}:
        return False
    packet_version = attributes.get("packet-version", "unknown")
    generation = "unavailable"
    render_hash = "unavailable"
    if status == "delivered":
        if packet_version not in {"v1", "v2"}:
            return False
        manifest = (read_cache(cache_dir, session_id, project, repo)
                    if cache_dir is not None and session_id and project and repo else None)
        if manifest is not None:
            if _string(manifest.get("context")) != context \
                    or manifest.get("packet_version") != packet_version:
                return False
            generation = _string(manifest.get("corpus_generation")) or "unavailable"
            render_hash = _string(manifest.get("render_hash")) or "unavailable"
            status = "fallback" if packet_version == "v1" else "delivered"
    _append_telemetry(
        telemetry_file,
        event="parent_packet",
        provider=provider,
        mechanism=mechanism,
        status=status,
        packet_version=packet_version,
        corpus_generation=generation,
        render_hash=render_hash,
        chars=len(context),
        confirmation_stage=confirmation_stage,
        session_key=telemetry_session_key(telemetry_file, session_id),
        request_epoch=request_epoch,
    )
    return True


def telemetry_session_key(path: Path | None, session_id: str) -> str | None:
    """Return a local-only keyed session pseudonym usable to join audit evidence."""
    if path is None or not session_id or path.parent.is_symlink():
        return None
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key_path = path.parent / "telemetry.key"
    if key_path.is_symlink():
        return None
    try:
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY
                     | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        fd = -1
    if fd >= 0:
        try:
            os.write(fd, os.urandom(32))
            os.fsync(fd)
        finally:
            os.close(fd)
    key = b""
    for _ in range(5):
        try:
            key = key_path.read_bytes()
            os.chmod(key_path, 0o600)
        except OSError:
            return None
        if len(key) >= 32:
            break
        time.sleep(0.01)
    if len(key) < 32:
        return None
    return hmac.new(key, session_id.encode(), hashlib.sha256).hexdigest()[:24]


def hook_output(context: str) -> dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }


def _escape_task_envelope(text: str) -> str:
    return (text.replace("<autodev-memory-task-context",
                         "&lt;autodev-memory-task-context")
                .replace("</autodev-memory-task-context>",
                         "&lt;/autodev-memory-task-context&gt;"))


def render_task_packet(manifest: dict[str, Any] | None, response: dict[str, Any]) -> str:
    base = _string((manifest or {}).get("child_base_text"))
    entries = response.get("entries", [])
    if not isinstance(entries, list):
        entries = []
    lines: list[str] = []
    detail_blocks: list[str] = []
    selected: list[str] = []
    for raw in entries:
        entry = _dict(raw)
        entry_id = _string(entry.get("id"))
        title = _escape_task_envelope(_string(entry.get("title")))
        summary = _escape_task_envelope(_string(entry.get("summary")))
        kind = _escape_task_envelope(_string(entry.get("type"))) or "memory"
        if not entry_id or not title:
            continue
        selected.append(entry_id)
        line = f"- [{kind}] {title} ({entry_id}): {summary or 'full content was unavailable'}"
        lines.append(line)
        content = _escape_task_envelope(_string(entry.get("content"))).strip()
        if content:
            detail_blocks.append(f"### Expanded memory {entry_id}\n{content}")

    base_section = (base.strip() or
                    "Critical session memory base is unavailable. Do not infer that always-apply "
                    "rules were delivered; search explicitly at task risk boundaries.")
    generation = _string(response.get("corpus_generation"))
    if generation:
        lines.insert(0, f"Corpus generation: {generation}")
    sections = [x for x in (base_section, "\n".join(lines).strip(), "\n\n".join(detail_blocks)) if x]
    if selected:
        sections.append(
            "Selected memory handles are the full IDs above. "
            + ("Expanded content is included where it fit the task budget. " if detail_blocks else "")
            + _string(response.get("delivery_note"))
        )
    else:
        sections.append(
            "No automatic task memories were selected. Search autodev memory for task-specific "
            "gotchas when the task touches an indexed area; report unavailable if the tool cannot be used."
        )
    attributes = {
        "status": _string(response.get("packet_status")) or ("delivered" if manifest else "base_unavailable"),
        "packet-version": (
            _string(response.get("packet_version"))
            or _string((manifest or {}).get("packet_version"))
            or "unavailable"
        ),
        "corpus-generation": generation or "unavailable",
        "delivery-id": _string(response.get("delegation_id")),
    }
    rendered_attributes = " ".join(
        f'{key}="{value}"' for key, value in attributes.items() if SAFE_TOKEN.fullmatch(value)
    )
    opening = f"<autodev-memory-task-context {rendered_attributes}>"
    packet = opening + "\n" + "\n\n".join(sections) + "\n</autodev-memory-task-context>"
    if len(packet) > CHILD_LIMIT:
        # Drop whole expanded bodies first, then whole result lines; never slice semantic text.
        while detail_blocks and len(packet) > CHILD_LIMIT:
            detail_blocks.pop()
            sections = [x for x in (base_section, "\n".join(lines).strip(),
                                    "\n\n".join(detail_blocks)) if x]
            if selected:
                sections.append(
                    "Selected memory handles are the full IDs above. Expanded content that did not "
                    "fit was omitted as a whole; do not infer it was delivered. "
                    + _string(response.get("delivery_note"))
                )
            packet = (
                opening + "\n"
                + "\n\n".join(sections)
                + "\n</autodev-memory-task-context>"
            )
        while len(lines) > (1 if generation else 0) and len(packet) > CHILD_LIMIT:
            lines.pop()
            selected.pop()
            sections = [x for x in (base_section, "\n".join(lines).strip()) if x]
            sections.append(
                "Selected memory handles are the full IDs above. Additional selections were omitted "
                "as whole entries to preserve the task budget. " + _string(response.get("delivery_note"))
            )
            packet = (opening + "\n" + "\n\n".join(sections)
                      + "\n</autodev-memory-task-context>")
    if len(packet) > CHILD_LIMIT:
        raise PacketError("backend child base leaves no room within the 3000-character task budget")
    return packet


def detect_provider() -> str:
    if any(os.environ.get(key) for key in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_ENTRYPOINT")):
        return "claude"
    if any(os.environ.get(key) for key in ("CODEX_THREAD_ID", "CODEX_WORKING_DIR")):
        return "codex"
    return "unknown"


def _main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    render = sub.add_parser("render-session")
    render.add_argument("--project", required=True)
    render.add_argument("--repo", required=True)
    render.add_argument("--session-id", default="")
    render.add_argument("--source", default="startup")
    render.add_argument("--cache-dir", type=Path, required=True)
    render.add_argument("--telemetry-file", type=Path)
    render.add_argument("--request-epoch", type=int, default=0)

    task = sub.add_parser("render-task")
    task.add_argument("--project", required=True)
    task.add_argument("--repo", required=True)
    task.add_argument("--session-id", required=True)
    task.add_argument("--cache-dir", type=Path, required=True)
    task.add_argument("--telemetry-file", type=Path)
    task.add_argument("--provider", choices=["claude", "codex", "grok"], default=None)
    task.add_argument("--mechanism", default="prompt_rewrite")

    invalidate = sub.add_parser("invalidate")
    invalidate.add_argument("--session-id", required=True)
    invalidate.add_argument("--cache-dir", type=Path, required=True)
    invalidate.add_argument("--request-epoch", type=int)

    confirm = sub.add_parser("confirm-child")
    confirm.add_argument("--provider", choices=["claude", "codex", "grok"], required=True)
    confirm.add_argument("--mechanism", required=True)
    confirm.add_argument("--confirmation-stage", required=True)
    confirm.add_argument("--telemetry-file", type=Path, required=True)
    confirm.add_argument("--session-id", default="")

    confirm_parent = sub.add_parser("confirm-parent")
    confirm_parent.add_argument("--provider", choices=["claude", "codex", "grok", "unknown"],
                                required=True)
    confirm_parent.add_argument("--mechanism", required=True)
    confirm_parent.add_argument("--confirmation-stage", required=True)
    confirm_parent.add_argument("--telemetry-file", type=Path, required=True)
    confirm_parent.add_argument("--session-id", default="")
    confirm_parent.add_argument("--request-epoch", type=int, default=0)
    confirm_parent.add_argument("--cache-dir", type=Path)
    confirm_parent.add_argument("--project", default="")
    confirm_parent.add_argument("--repo", default="")

    args = parser.parse_args()
    if args.command == "invalidate":
        invalidate_cache(args.cache_dir, args.session_id, args.request_epoch)
        return 0
    if args.command == "confirm-child":
        packet = os.sys.stdin.read()
        return 0 if confirm_packet_delivery(
            packet,
            provider=args.provider,
            mechanism=args.mechanism,
            confirmation_stage=args.confirmation_stage,
            telemetry_file=args.telemetry_file,
            session_id=args.session_id,
        ) else 2
    if args.command == "confirm-parent":
        output = os.sys.stdin.read()
        return 0 if confirm_parent_delivery(
            output,
            provider=args.provider,
            mechanism=args.mechanism,
            confirmation_stage=args.confirmation_stage,
            telemetry_file=args.telemetry_file,
            session_id=args.session_id,
            request_epoch=args.request_epoch,
            cache_dir=args.cache_dir,
            project=args.project,
            repo=args.repo,
        ) else 2

    try:
        payload = _dict(json.load(os.sys.stdin))
    except (json.JSONDecodeError, TypeError):
        payload = {}
    if args.command == "render-session":
        session_key = telemetry_session_key(args.telemetry_file, args.session_id)
        try:
            response_project = _string(payload.get("project"))
            response_repo = _string(payload.get("repo"))
            if response_project and response_project != args.project:
                raise PacketError("packet v2 project does not match the requested scope")
            if response_repo and response_repo != args.repo:
                raise PacketError("packet v2 repo does not match the requested scope")
            packet = parse_session_response(_dict(payload))
            menu = _dict(payload.get("knowledge_menu"))
            corpus = _dict(payload.get("corpus"))
            searchable_count = payload.get(
                "searchable_count",
                corpus.get("searchable_count", corpus.get("searchable", menu.get("count", 0))),
            )
            if not isinstance(searchable_count, int):
                searchable_count = 0
            context = render_parent_context(packet, args.source, searchable_count)
            write_cache(args.cache_dir, args.session_id, args.project, args.repo, packet, context,
                        args.request_epoch)
            _append_telemetry(
                args.telemetry_file,
                event="parent_packet_prepared",
                provider=detect_provider(),
                mechanism="session_start",
                status="fallback_ready" if packet["fallback"] else "ready",
                packet_version=packet["version"],
                corpus_generation=packet["generation"],
                render_hash=packet["render_hash"],
                chars=len(context),
                session_key=session_key,
                request_epoch=args.request_epoch,
            )
            print(json.dumps(hook_output(context)))
            return 0
        except PacketError as error:
            invalidate_cache(args.cache_dir, args.session_id, args.request_epoch)
            _append_telemetry(
                args.telemetry_file,
                event="parent_packet_prepared",
                provider=detect_provider(),
                mechanism="session_start",
                status="unavailable",
                packet_version="unknown",
                corpus_generation=None,
                render_hash=None,
                chars=0,
                session_key=session_key,
                request_epoch=args.request_epoch,
            )
            print(json.dumps(hook_output(render_unavailable_context(str(error)))))
            return 2

    manifest = read_cache(args.cache_dir, args.session_id, args.project, args.repo)
    packet = render_task_packet(manifest, _dict(payload))
    _append_telemetry(
        args.telemetry_file,
        event="child_packet",
        provider=args.provider or detect_provider(),
        mechanism=args.mechanism,
        status="delivered",
        packet_version=_string((manifest or {}).get("packet_version")) or "unavailable",
        corpus_generation=_string((manifest or {}).get("corpus_generation")) or "unavailable",
        render_hash=_string((manifest or {}).get("render_hash")) or "unavailable",
        chars=len(packet),
    )
    print(packet)
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

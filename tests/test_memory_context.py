from __future__ import annotations

import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "hooks"))

from memory_context import (  # noqa: E402
    PacketError, _append_telemetry, parse_session_response, read_cache, render_parent_context,
    render_task_packet, write_cache,
)
from task_packet import selection_for_agent  # noqa: E402


def response(text: str = "critical rule", child: str = "child rule") -> dict[str, object]:
    return {
        "context_version": "v2",
        "packet": {
            "text": text,
            "chars": len(text),
            "budget_chars": 8700,
            "delivery_budget_chars": 9000,
            "adapter_headroom_chars": 300,
            "generation": "g-12",
            "render_hash": "sha256:" + hashlib.sha256(text.encode()).hexdigest(),
            "child_base_text": child,
            "child_base_chars": len(child),
            "handles": {"always_rule_ids": ["11111111-1111-1111-1111-111111111111"]},
        },
        "corpus": {"searchable_count": 27},
    }


class MemoryContextTest(unittest.TestCase):
    def test_canonical_producer_fixture_is_consumed(self) -> None:
        fixture = json.loads((ROOT / "tests/fixtures/session-packet-v2.json").read_text())
        packet = parse_session_response(fixture)
        self.assertEqual(packet["version"], "v2")
        self.assertEqual(packet["child_base_text"], "## Critical memory rules\n- rule")

    def test_v2_is_validated_without_client_catalog_reconstruction(self) -> None:
        packet = parse_session_response(response())
        context = render_parent_context(packet, "startup", 27)
        self.assertIn("critical rule", context)
        self.assertNotIn("knowledge menu", context.lower())
        self.assertLessEqual(len(context), 9000)

    def test_mismatch_and_oversize_fail_instead_of_slicing(self) -> None:
        broken = response()
        broken["packet"]["chars"] = 1
        with self.assertRaises(PacketError):
            parse_session_response(broken)
        packet = parse_session_response(response("x" * 8900))
        with self.assertRaises(PacketError):
            render_parent_context(packet, "startup")
        overflow = response()
        overflow["packet"]["health"] = "overflow"
        with self.assertRaises(PacketError):
            parse_session_response(overflow)

    def test_legacy_accepts_only_bounded_digest(self) -> None:
        packet = parse_session_response({
            "starred": {"entries": [{"content": "must not leak"}]},
            "knowledge_menu": {"items": [{"title": "must not render"}]},
            "digest": {"text": "legacy digest", "chars": 13},
        })
        self.assertEqual(packet["version"], "v1")
        self.assertEqual(packet["text"], "legacy digest")

    def test_cache_is_session_and_repo_scoped_atomic_0600(self) -> None:
        packet = parse_session_response(response())
        context = render_parent_context(packet, "startup")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_cache(root, "session-a", "p", "r", packet, context)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertIsNotNone(read_cache(root, "session-a", "p", "r"))
            self.assertIsNone(read_cache(root, "session-b", "p", "r"))
            self.assertIsNone(read_cache(root, "session-a", "p", "other"))
            for path in root.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_task_packet_drops_whole_entries_and_stays_bounded(self) -> None:
        manifest = {"child_base_text": "critical child base", "packet_version": "v2"}
        entries = {"entries": [
            {"id": f"{index:08d}-aaaa-bbbb-cccc-dddddddddddd", "title": f"Rule {index}",
             "summary": "summary " * 40, "type": "gotcha"}
            for index in range(30)
        ]}
        packet = render_task_packet(manifest, entries)
        self.assertLessEqual(len(packet), 3000)
        self.assertTrue(packet.endswith("</autodev-memory-task-context>"))
        self.assertNotIn("summar", packet[-10:])

    def test_agent_frontmatter_declares_bounded_selection_types(self) -> None:
        tags, types = selection_for_agent(ROOT, "builder")
        self.assertEqual(tags, [])
        self.assertEqual(types, ["gotcha", "pattern", "architecture"])

    def test_telemetry_fixture_contains_metadata_only(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "telemetry.jsonl"
            _append_telemetry(path, event="child_packet", provider="codex",
                              mechanism="managed_delegation", status="delivered",
                              packet_version="v2", chars=123)
            record = json.loads(path.read_text())
            self.assertEqual(set(record), {"timestamp", "event", "provider", "mechanism",
                                           "status", "packet_version", "chars"})
            self.assertNotIn("prompt", path.read_text().lower())


if __name__ == "__main__":
    unittest.main()

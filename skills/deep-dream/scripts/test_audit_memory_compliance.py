from __future__ import annotations

import hashlib
import hmac
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from audit_memory_compliance import _classifications, audit  # noqa: E402


class AuditMemoryComplianceTest(unittest.TestCase):
    def test_recursive_claude_correlation_and_telemetry_are_coarse_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claude = root / "claude"
            codex = root / "codex"
            cache = root / "cache"
            claude.mkdir()
            codex.mkdir()
            cache.mkdir()
            sid = "session-one"
            delivery_id = "a" * 24
            envelope = (
                f'<autodev-memory-task-context status="delivered" packet-version="v2" '
                f'corpus-generation="{"b" * 64}" delivery-id="{delivery_id}">'
                "rules</autodev-memory-task-context>"
            )
            delegated_prompt = "private task\n" + envelope
            parent = claude / f"{sid}.jsonl"
            parent.write_text(json.dumps({
                "type": "assistant", "message": {"content": [{
                    "type": "tool_use", "id": "a1", "name": "Agent",
                    "input": {"subagent_type": "reviewer", "prompt": delegated_prompt},
                }]},
            }))
            child_dir = claude / sid / "subagents"
            child_dir.mkdir(parents=True)
            (child_dir / "agent-one.jsonl").write_text(json.dumps({
                "type": "user", "isSidechain": True,
                "message": {"content": delegated_prompt},
            }))
            key = b"k" * 32
            (cache / "telemetry.key").write_bytes(key)
            session_key = hmac.new(key, sid.encode(), hashlib.sha256).hexdigest()[:24]
            (cache / "telemetry.jsonl").write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "task_selection", "session_key": session_key,
                "status": "selected", "selected_count": 2, "expansion_status": "expanded",
                "expanded_ids": ["id-1", "id-2"], "selected_ids": ["id-1", "id-2"],
                "delegation_id": delivery_id, "corpus_generation": "b" * 64,
            }) + "\n" + json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "child_packet", "session_key": session_key,
                "provider": "claude", "mechanism": "prompt_rewrite", "status": "delivered",
                "packet_version": "v2", "corpus_generation": "b" * 64,
                "delegation_id": delivery_id, "chars": 100,
                "confirmation_stage": "pretool_output_emitted",
            }) + "\n")
            report = audit(claude, codex, cache / "telemetry.jsonl", 1)
            self.assertEqual(report["record_count"], 1)
            record = report["records"][0]
            self.assertEqual(record["correlation"], "confirmed")
            self.assertIn("selection_confirmed", record["classifications"])
            self.assertIn("expansion_confirmed", record["classifications"])
            self.assertEqual(record["packet_version"], "v2")
            self.assertEqual(record["corpus_generation"], "b" * 64)
            self.assertEqual(record["selected_count"], 2)
            self.assertEqual(record["expanded_count"], 2)
            self.assertNotIn("delegation_hash", record)
            self.assertNotIn("selected_ids", record)
            self.assertNotIn("delivery_id", record)
            self.assertNotIn("private task", json.dumps(report))

    def test_unavailable_marker_is_never_classified_delivered(self) -> None:
        parsed = {"summary": {"session_role": "child"}, "events": [{
            "kind": "memory_context", "mechanism": "explicit_task_packet",
            "delivery_status": "unavailable", "packet_version": "unavailable",
        }]}
        labels = _classifications(parsed, [])
        self.assertIn("explicit_task_packet", labels)
        self.assertIn("unavailable", labels)
        self.assertNotIn("packet_delivered", labels)

    def test_packet_preparation_is_never_delivery_evidence(self) -> None:
        telemetry = [{
            "event": "packet_prepared", "status": "delivered",
            "delegation_id": "a" * 24,
        }]
        self.assertNotIn(
            "packet_delivered",
            _classifications({"summary": {}, "events": []}, telemetry),
        )

    def test_task_telemetry_is_not_shared_across_sibling_delegations(self) -> None:
        selected = [{
            "event": "task_selection", "delegation_id": "a" * 24,
            "status": "selected", "selected_count": 1, "expansion_status": "not_applicable",
        }]
        self.assertIn("selection_confirmed", _classifications({"summary": {}, "events": []}, selected))
        self.assertNotIn("selection_confirmed", _classifications({"summary": {}, "events": []}, []))

    def test_direct_mcp_certainty_combines_server_and_tool(self) -> None:
        parsed = {"summary": {}, "events": [{
            "kind": "mcp_result", "server": "autodev-memory", "tool": "search",
            "status": "completed",
        }]}
        self.assertIn("selection_confirmed", _classifications(parsed, []))

    def test_external_delegations_join_only_their_own_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            claude, codex, cache = root / "claude", root / "codex", root / "cache"
            claude.mkdir()
            codex.mkdir()
            cache.mkdir()
            now = datetime.now(timezone.utc).isoformat()
            rows = []
            for index, delivery_id in enumerate(("a" * 24, "b" * 24), 1):
                rows.extend([
                    {"timestamp": now, "event": "task_selection", "delegation_id": delivery_id,
                     "provider": "codex", "mechanism": "external_build", "status": "selected",
                     "selected_count": index, "expanded_ids": [],
                     "expansion_status": "not_applicable", "corpus_generation": "c" * 64},
                    {"timestamp": now, "event": "child_packet", "delegation_id": delivery_id,
                     "provider": "codex", "mechanism": "external_build", "status": "delivered",
                     "packet_version": "v2", "corpus_generation": "c" * 64, "chars": 100,
                     "confirmation_stage": "validated_provider_response"},
                ])
            telemetry = cache / "telemetry.jsonl"
            telemetry.write_text("\n".join(json.dumps(row) for row in rows) + "\n")
            report = audit(claude, codex, telemetry, 1)
            self.assertEqual(sorted(record["selected_count"] for record in report["records"]), [1, 2])


if __name__ == "__main__":
    unittest.main()

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
from audit_memory_compliance import audit  # noqa: E402


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
            parent = claude / f"{sid}.jsonl"
            parent.write_text(json.dumps({
                "type": "assistant", "message": {"content": [{
                    "type": "tool_use", "id": "a1", "name": "Agent",
                    "input": {"subagent_type": "reviewer", "prompt": "private task"},
                }]},
            }))
            child_dir = claude / sid / "subagents"
            child_dir.mkdir(parents=True)
            (child_dir / "agent-one.jsonl").write_text(json.dumps({
                "type": "user", "isSidechain": True,
                "message": {"content": "private task"},
            }))
            key = b"k" * 32
            (cache / "telemetry.key").write_bytes(key)
            session_key = hmac.new(key, sid.encode(), hashlib.sha256).hexdigest()[:24]
            (cache / "telemetry.jsonl").write_text(json.dumps({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "task_selection", "session_key": session_key,
                "status": "selected", "selected_count": 2, "expansion_status": "expanded",
            }) + "\n")
            report = audit(claude, codex, cache / "telemetry.jsonl", 1)
            self.assertEqual(report["record_count"], 1)
            record = report["records"][0]
            self.assertEqual(record["correlation"], "confirmed")
            self.assertIn("selection_confirmed", record["classifications"])
            self.assertIn("expansion_confirmed", record["classifications"])
            self.assertNotIn("delegation_hash", record)
            self.assertNotIn("private task", json.dumps(report))


if __name__ == "__main__":
    unittest.main()

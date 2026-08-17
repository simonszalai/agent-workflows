from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "bin" / "session-usage-report"


def write_jsonl(directory: str, name: str, records: list[dict]) -> Path:
    path = Path(directory) / name
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


class SessionUsageReportTest(unittest.TestCase):
    def run_report(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPORT), str(path)],
            capture_output=True, text=True,
        )

    def test_cursor_role_message_tool_use_is_counted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_jsonl(directory, "cursor.jsonl", [
                {"role": "user", "message": {"content": [{"type": "text", "text": "land the PR"}]}},
                {"role": "assistant", "message": {"content": [
                    {"type": "text", "text": "running checks"},
                    {"type": "tool_use", "name": "Read", "input": {"path": "SKILL.md"}},
                    {"type": "tool_use", "name": "Shell", "input": {"command": "ci-local --run"}},
                    {"type": "tool_use", "name": "Shell", "input": {"command": "ci-local --run"}},
                ]}},
            ])
            result = self.run_report(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("| MAIN | 1 |", result.stdout)
            self.assertIn("Read", result.stdout)
            self.assertIn("Shell", result.stdout)
            self.assertIn("2× ci-local --run", result.stdout)

    def test_claude_message_role_still_counts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_jsonl(directory, "claude.jsonl", [
                {"type": "queue-operation", "operation": "enqueue", "timestamp": "2026-08-17T13:00:00Z"},
                {
                    "type": "assistant",
                    "timestamp": "2026-08-17T13:00:01Z",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "checking"},
                            {"type": "tool_use", "name": "Bash", "input": {"command": "git status"}},
                            {"type": "tool_use", "name": "mcp__autodev-memory__get_ticket",
                             "input": {"ticket_id": "F0123"}},
                        ],
                        "usage": {
                            "input_tokens": 10,
                            "output_tokens": 20,
                            "cache_creation_input_tokens": 4,
                            "cache_read_input_tokens": 6,
                        },
                    },
                },
            ])
            result = self.run_report(path)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("| MAIN | 1 | 20 | 10 | 4 |", result.stdout)
            self.assertIn("Bash", result.stdout)
            self.assertIn("mcp__autodev-memory__get_ticket", result.stdout)

    def test_unknown_shape_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_jsonl(directory, "opaque.jsonl", [
                {"kind": "model", "payload": {"turns": 35, "tools": 126}},
            ])
            result = self.run_report(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported log shape", result.stderr)

    def test_empty_file_fails_loud(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = write_jsonl(directory, "empty.jsonl", [])
            result = self.run_report(path)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported log shape", result.stderr)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from parse_session_log import parse_session


class ParseSessionLogTest(unittest.TestCase):
    def parse(self, records: list[dict[str, object]], provider: str) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "session.jsonl"
            path.write_text("\n".join(json.dumps(record) for record in records))
            return parse_session(path, provider)

    def test_current_codex_exec_reports_nested_calls_as_attempts_only(self) -> None:
        records = [
            {
                "timestamp": "2026-07-10T10:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "exec",
                    "call_id": "call-1",
                    "input": (
                        "const a = await tools.exec_command({cmd: 'true'});\n"
                        "const b = await tools.mcp__autodev_memory__search({});"
                    ),
                },
            },
            {
                "timestamp": "2026-07-10T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "call-1",
                    "output": [
                        {"type": "input_text", "text": "Script completed\n"},
                        {"type": "input_text", "text": "combined rendered output"},
                    ],
                },
            },
        ]

        parsed = self.parse(records, "codex")
        events = parsed["events"]
        self.assertIsInstance(events, list)
        attempt = events[0]
        result = events[1]
        self.assertEqual(
            attempt["nested_tool_attempts"],
            ["exec_command", "mcp__autodev_memory__search"],
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["nested_results"], "not_individually_attributed")

    def test_old_codex_function_call_nonzero_exit_is_failed(self) -> None:
        records = [
            {
                "timestamp": "2026-07-08T10:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": "exec_command",
                    "call_id": "call-2",
                    "arguments": "{}",
                },
            },
            {
                "timestamp": "2026-07-08T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": "call-2",
                    "output": "Process exited with code 7",
                },
            },
        ]

        parsed = self.parse(records, "codex")
        result = parsed["events"][1]
        self.assertEqual(result["tool"], "exec_command")
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["exit_code"], 7)

    def test_custom_apply_patch_failure_is_detected_without_output_body(self) -> None:
        records = [
            {
                "timestamp": "2026-07-10T10:00:00Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call",
                    "name": "apply_patch",
                    "call_id": "patch-1",
                    "input": "*** Begin Patch",
                },
            },
            {
                "timestamp": "2026-07-10T10:00:01Z",
                "type": "response_item",
                "payload": {
                    "type": "custom_tool_call_output",
                    "call_id": "patch-1",
                    "output": ["apply_patch verification failed: expected context missing"],
                },
            },
        ]

        parsed = self.parse(records, "codex")
        result = parsed["events"][1]
        self.assertEqual(result["tool"], "apply_patch")
        self.assertEqual(result["status"], "failed")
        self.assertNotIn("expected context missing", json.dumps(parsed))

    def test_codex_developer_memory_context_is_observed_without_copying_content(self) -> None:
        message = {
            "timestamp": "2026-07-10T10:00:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "developer",
                "content": [
                    {
                        "type": "input_text",
                        "text": "<autodev-memory-hook-result>secret body</autodev-memory-hook-result>",
                    }
                ],
            },
        }
        records = [message, message]

        parsed = self.parse(records, "codex")
        self.assertTrue(parsed["summary"]["memory_context_observed"])
        self.assertEqual(parsed["events"][0]["kind"], "memory_context")
        self.assertEqual(len(parsed["events"]), 1)
        self.assertNotIn("secret body", json.dumps(parsed))

    def test_claude_tool_use_and_error_result_are_correlated(self) -> None:
        records = [
            {
                "timestamp": "2026-07-10T10:00:00Z",
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "id": "tool-1", "name": "Bash", "input": {}}
                    ]
                },
            },
            {
                "timestamp": "2026-07-10T10:00:01Z",
                "type": "user",
                "message": {
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "tool-1",
                            "is_error": True,
                            "content": "Error: failed",
                        }
                    ]
                },
            },
        ]

        parsed = self.parse(records, "claude")
        result = parsed["events"][1]
        self.assertEqual(result["tool"], "Bash")
        self.assertEqual(result["status"], "failed")

    def test_claude_list_text_human_message_is_not_dropped(self) -> None:
        records = [
            {
                "timestamp": "2026-07-10T10:00:00Z",
                "type": "user",
                "message": {
                    "content": [
                        {"type": "text", "text": "No, keep the repository-qualified id."}
                    ]
                },
            }
        ]

        parsed = self.parse(records, "claude")
        self.assertEqual(parsed["events"][0]["kind"], "human_message")
        self.assertTrue(parsed["events"][0]["correction_candidate"])
        self.assertNotIn("repository-qualified", json.dumps(parsed))


if __name__ == "__main__":
    unittest.main()

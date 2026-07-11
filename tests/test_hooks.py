from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HookContractTest(unittest.TestCase):
    def test_external_explicit_packet_suppresses_ambient_session_start(self) -> None:
        env = os.environ.copy()
        env["AUTODEV_MEMORY_EXPLICIT_PACKET"] = "1"
        result = subprocess.run(
            [str(ROOT / "hooks/autodev-memory-session-start.sh")],
            input="not even json", capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})

    def test_pre_agent_never_double_injects_existing_task_packet(self) -> None:
        payload = {
            "tool_name": "Agent",
            "tool_input": {"prompt":
                "task <autodev-memory-task-context>x</autodev-memory-task-context>"},
        }
        result = subprocess.run(
            [str(ROOT / "hooks/autodev-memory-pre-agent.sh")],
            input=json.dumps(payload), capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout), {})

    def test_pre_agent_marker_word_alone_does_not_suppress_real_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "tool_name": "Agent", "session_id": "session",
                "cwd": str(ROOT),
                "tool_input": {
                    "subagent_type": "builder",
                    "prompt": "Review the phrase autodev-memory-task-context safely",
                },
            }
            env = os.environ.copy()
            env["HOME"] = directory
            result = subprocess.run(
                [str(ROOT / "hooks/autodev-memory-pre-agent.sh")],
                input=json.dumps(payload), capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]["prompt"]
            self.assertEqual(updated.count("<autodev-memory-task-context"), 1)
            self.assertIn("Review the phrase", updated)

    def test_managed_codex_rejects_preexisting_duplicate_or_unbalanced_envelopes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "message"
            for message in (
                "<autodev-memory-task-context>x</autodev-memory-task-context>\n"
                "<autodev-memory-task-context>y</autodev-memory-task-context>",
                "<autodev-memory-task-context>unclosed",
            ):
                path.write_text(message)
                result = subprocess.run(
                    [str(ROOT / "bin/managed-codex-delegation"), "--message-file", str(path),
                     "--agent-type", "reviewer", "--session-id", "session"],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()

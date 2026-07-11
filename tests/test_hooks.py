from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HookContractTest(unittest.TestCase):
    @staticmethod
    def _run_with_broken_stdout(command: list[str], *, payload: dict[str, object],
                                env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        """Run with a pipe whose read side is already closed, forcing the exact write to fail."""
        read_fd, write_fd = os.pipe()
        os.close(read_fd)
        try:
            return subprocess.run(
                command, input=json.dumps(payload), stdout=write_fd, stderr=subprocess.PIPE,
                text=True, env=env,
            )
        finally:
            os.close(write_fd)

    @staticmethod
    def _session_env(directory: str) -> tuple[dict[str, str], dict[str, object]]:
        root = Path(directory)
        fake_bin = root / "bin"
        fake_bin.mkdir(exist_ok=True)
        fixture = json.loads((ROOT / "tests/fixtures/session-packet-v2.json").read_text())
        fixture["repo"] = "agent-workflows"
        response = root / "session-response.json"
        response.write_text(json.dumps(fixture))
        curl = fake_bin / "curl"
        curl.write_text('#!/bin/sh\ncat "$FAKE_SESSION_RESPONSE"\nprintf "\\n200\\n"\n')
        curl.chmod(0o755)
        env = os.environ.copy()
        env.update({
            "HOME": directory,
            "PATH": str(fake_bin) + os.pathsep + env["PATH"],
            "AUTODEV_MEMORY_API_TOKEN": "test-only-token",
            "FAKE_SESSION_RESPONSE": str(response),
            "CLAUDE_SESSION_ID": "parent-session",
        })
        payload: dict[str, object] = {
            "source": "startup", "session_id": "parent-session", "cwd": str(ROOT),
        }
        return env, payload

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
            events = [json.loads(line) for line in (
                Path(directory) / ".cache/autodev-memory/telemetry.jsonl"
            ).read_text().splitlines()]
            self.assertEqual([event["event"] for event in events],
                             ["task_selection", "packet_prepared", "child_packet"])
            self.assertEqual(events[-1]["confirmation_stage"], "pretool_output_emitted")

    def test_pre_agent_installed_layout_resolves_same_version_helper(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks = home / ".claude/hooks"
            unmanaged = home / ".claude/bin"
            store = home / ".local/share/agent-workflows"
            version = store / "versions" / ("a" * 40)
            version_hooks = version / "hooks"
            version_bin = version / "bin"
            hooks.mkdir(parents=True)
            unmanaged.mkdir(parents=True)
            version_hooks.mkdir(parents=True)
            version_bin.mkdir(parents=True)
            (version_hooks / "autodev-memory-pre-agent.sh").write_bytes(
                (ROOT / "hooks/autodev-memory-pre-agent.sh").read_bytes()
            )
            (version_hooks / "autodev-memory-pre-agent.sh").chmod(0o755)
            (version_hooks / "memory_context.py").write_bytes(
                (ROOT / "hooks/memory_context.py").read_bytes()
            )
            (store / "current").symlink_to(Path("versions") / ("a" * 40))
            (hooks / "autodev-memory-pre-agent.sh").symlink_to(
                store / "current/hooks/autodev-memory-pre-agent.sh"
            )
            helper = version_bin / "autodev-memory-task-packet"
            helper.write_text(
                "#!/bin/sh\n"
                "cat >/dev/null\n"
                "printf '%s\\n' '<autodev-memory-task-context status=\"delivered\" "
                "packet-version=\"v2\" corpus-generation=\""
                + "0" * 64
                + "\" delivery-id=\"canary\">safe</autodev-memory-task-context>'\n"
            )
            helper.chmod(0o755)
            untrusted = unmanaged / "autodev-memory-task-packet"
            untrusted.write_text(
                "#!/bin/sh\ncat >/dev/null\n"
                "printf '%s\\n' '<autodev-memory-task-context>UNTRUSTED</autodev-memory-task-context>'\n"
            )
            untrusted.chmod(0o755)
            payload = {
                "tool_name": "Agent",
                "session_id": "installed-session",
                "cwd": str(ROOT),
                "tool_input": {"subagent_type": "reviewer", "prompt": "installed canary"},
            }
            env = os.environ.copy()
            env["HOME"] = str(home)
            result = subprocess.run(
                [str(hooks / "autodev-memory-pre-agent.sh")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            updated = json.loads(result.stdout)["hookSpecificOutput"]["updatedInput"]["prompt"]
            self.assertIn("installed canary", updated)
            self.assertEqual(updated.count("<autodev-memory-task-context"), 1)
            self.assertNotIn("UNTRUSTED", updated)

    def test_pre_agent_installed_layout_fails_closed_when_realpath_fails(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            hooks = home / ".claude/hooks"
            unmanaged = home / ".claude/bin"
            fake_bin = home / "fake-bin"
            hooks.mkdir(parents=True)
            unmanaged.mkdir(parents=True)
            fake_bin.mkdir()
            (hooks / "autodev-memory-pre-agent.sh").symlink_to(
                ROOT / "hooks/autodev-memory-pre-agent.sh"
            )
            executed = home / "unmanaged-executed"
            helper = unmanaged / "autodev-memory-task-packet"
            helper.write_text(f"#!/bin/sh\ntouch '{executed}'\n")
            helper.chmod(0o755)
            python = fake_bin / "python3"
            python.write_text("#!/bin/sh\nexit 9\n")
            python.chmod(0o755)
            payload = {
                "tool_name": "Agent",
                "session_id": "installed-session",
                "cwd": str(ROOT),
                "tool_input": {"subagent_type": "reviewer", "prompt": "installed canary"},
            }
            env = os.environ.copy()
            env["HOME"] = str(home)
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [str(hooks / "autodev-memory-pre-agent.sh")],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {})
            self.assertFalse(executed.exists())

    def test_pre_agent_output_failure_never_confirms_prepared_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            python = fake_bin / "python3"
            python.write_text(
                "#!/bin/sh\n"
                "if [ \"$1\" = \"-c\" ]; then exit 9; fi\n"
                f'exec "{sys.executable}" "$@"\n'
            )
            python.chmod(0o755)
            payload = {
                "tool_name": "Agent", "session_id": "session", "cwd": str(ROOT),
                "tool_input": {"subagent_type": "builder", "prompt": "private task"},
            }
            env = os.environ.copy()
            env["HOME"] = directory
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [str(ROOT / "hooks/autodev-memory-pre-agent.sh")],
                input=json.dumps(payload), capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), {})
            events = [json.loads(line) for line in (
                root / ".cache/autodev-memory/telemetry.jsonl"
            ).read_text().splitlines()]
            self.assertIn("packet_prepared", [event["event"] for event in events])
            self.assertNotIn("child_packet", [event["event"] for event in events])

    def test_pre_agent_stdout_failure_never_confirms_prepared_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            payload = {
                "tool_name": "Agent", "session_id": "session", "cwd": str(ROOT),
                "tool_input": {"subagent_type": "builder", "prompt": "private task"},
            }
            env = os.environ.copy()
            env["HOME"] = directory
            result = self._run_with_broken_stdout(
                [str(ROOT / "hooks/autodev-memory-pre-agent.sh")], payload=payload, env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            events = [json.loads(line) for line in (
                Path(directory) / ".cache/autodev-memory/telemetry.jsonl"
            ).read_text().splitlines()]
            self.assertIn("packet_prepared", [event["event"] for event in events])
            self.assertNotIn("child_packet", [event["event"] for event in events])

    def test_session_start_confirms_only_after_outer_stdout_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env, payload = self._session_env(directory)
            result = subprocess.run(
                [str(ROOT / "hooks/autodev-memory-session-start.sh")],
                input=json.dumps(payload), capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            context = json.loads(result.stdout)["hookSpecificOutput"]["additionalContext"]
            self.assertIn('status="delivered"', context)
            events = [json.loads(line) for line in (
                Path(directory) / ".cache/autodev-memory/telemetry.jsonl"
            ).read_text().splitlines()]
            self.assertEqual([event["event"] for event in events],
                             ["parent_packet_prepared", "parent_packet"])
            self.assertEqual(events[-1]["confirmation_stage"],
                             "session_start_output_emitted")
            self.assertEqual(events[-1]["status"], "delivered")
            self.assertEqual(events[-1]["corpus_generation"], "0" * 64)
            self.assertEqual(events[-1]["chars"], len(context))
            self.assertNotIn("Memory Rules", json.dumps(events))

    def test_session_start_stdout_failure_leaves_parent_preparation_unconfirmed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            env, payload = self._session_env(directory)
            result = self._run_with_broken_stdout(
                [str(ROOT / "hooks/autodev-memory-session-start.sh")], payload=payload, env=env,
            )
            self.assertNotEqual(result.returncode, 0)
            events = [json.loads(line) for line in (
                Path(directory) / ".cache/autodev-memory/telemetry.jsonl"
            ).read_text().splitlines()]
            self.assertEqual([event["event"] for event in events],
                             ["parent_packet_prepared"])

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

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import json
import os
import re
import tempfile
import subprocess
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module(path: Path, name: str):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ExternalMemoryContractTest(unittest.TestCase):
    @staticmethod
    def packet(delivery_id: str = "a" * 24) -> str:
        return (
            '<autodev-memory-task-context status="delivered" packet-version="v2" '
            f'corpus-generation="{"b" * 64}" delivery-id="{delivery_id}">\n'
            "memory\n</autodev-memory-task-context>"
        )

    def test_valid_single_packet_is_accepted_by_both_adapters(self) -> None:
        packet = "<autodev-memory-task-context>\nx\n</autodev-memory-task-context>"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packet"
            path.write_text(packet)
            for script, name in (("external-agent", "external_agent"),
                                 ("external-build", "external_build")):
                loaded = module(ROOT / "bin" / script, name)
                self.assertEqual(loaded.read_memory_context(str(path)), packet)

    def test_oversize_packet_is_rejected(self) -> None:
        loaded = module(ROOT / "bin/external-agent", "external_agent_oversize")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packet"
            path.write_text("<autodev-memory-task-context>" + "x" * 3000
                            + "</autodev-memory-task-context>")
            with self.assertRaises(SystemExit):
                loaded.read_memory_context(str(path))

    def test_grok_sidecars_default_to_grok_4_5(self) -> None:
        loaded = module(ROOT / "bin/external-agent", "external_agent_grok_model")
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout='{"text":"{}"}', stderr="",
        )
        with mock.patch.object(loaded.subprocess, "run", return_value=completed) as run:
            loaded.run_grok("prompt", {}, None, ROOT, 30)

        command = run.call_args.args[0]
        self.assertEqual(loaded.GROK_DEFAULT_MODEL, "grok-4.5")
        self.assertEqual(command[command.index("-m") + 1], "grok-4.5")

    def test_task_prompt_uses_stdin_and_is_absent_from_output_and_telemetry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            telemetry = root / "telemetry.jsonl"
            command = [
                str(ROOT / "bin/autodev-memory-task-packet"), "--cwd", str(ROOT),
                "--project", "p", "--repo", "r", "--session-id", "s",
                "--agent-type", "builder", "--provider", "codex",
                "--mechanism", "external_build", "--task-prompt-stdin",
                "--cache-dir", str(root / "cache"), "--telemetry-file", str(telemetry),
            ]
            result = subprocess.run(command, input="private prompt canary", text=True,
                                    capture_output=True, env={"HOME": str(root), "PATH": "/usr/bin:/bin"})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("private prompt canary", result.stdout)
            self.assertNotIn("private prompt canary", telemetry.read_text())
            self.assertNotIn("private prompt canary", " ".join(command))
            delivery_id = re.search(r'delivery-id="([0-9a-f]{24})"', result.stdout).group(1)
            events = [json.loads(line) for line in telemetry.read_text().splitlines()]
            self.assertEqual({event["delegation_id"] for event in events}, {delivery_id})

    def test_every_executable_external_recipe_creates_a_packet_and_fallback(self) -> None:
        recipes = [
            "skills/ticket-plan/SKILL.md", "skills/review/SKILL.md",
            "skills/investigate/SKILL.md", "skills/research/SKILL.md",
            "skills/build/SKILL.md", "skills/resolve-review/SKILL.md",
            "skills/epic-plan/SKILL.md",
        ]
        for relative in recipes:
            text = (ROOT / relative).read_text()
            self.assertIn("autodev-memory-task-packet", text, relative)
            self.assertIn("--task-prompt-stdin", text, relative)
            self.assertIn("Memory context is unavailable", text, relative)
            self.assertLess(text.index("autodev-memory-task-packet"),
                            max(text.rfind("external-agent --task"),
                                text.rfind("external-build --task")), relative)

    def test_external_agent_crash_does_not_confirm_prepared_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\nexit 7\n")
            codex.chmod(0o755)
            packet = root / "packet.md"
            packet.write_text(self.packet())
            telemetry = root / "telemetry.jsonl"
            telemetry.write_text(json.dumps({
                "event": "packet_prepared", "delegation_id": "a" * 24,
            }) + "\n")
            env = os.environ.copy()
            env["HOME"] = directory
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [str(ROOT / "bin/external-agent"), "--task", "research",
                 "--provider", "codex", "--question", "inspect code", "--repo", str(ROOT),
                 "--memory-context-file", str(packet), "--telemetry-file", str(telemetry)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            events = [json.loads(line) for line in telemetry.read_text().splitlines()]
            self.assertEqual([event["event"] for event in events], ["packet_prepared"])

    def test_external_agent_confirms_only_after_valid_provider_response(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/bin/sh\n"
                "out=''\nprev=''\n"
                "for arg in \"$@\"; do [ \"$prev\" = '-o' ] && out=\"$arg\"; prev=\"$arg\"; done\n"
                "input=$(cat)\n"
                "echo \"$input\" | grep -q '<autodev-memory-task-context' || exit 8\n"
                "printf '%s' '{\"key\":\"codex\",\"files_searched\":1,\"occurrences\":[],"
                "\"summary\":\"ok\",\"questions_for_synthesis\":[]}' > \"$out\"\n"
            )
            codex.chmod(0o755)
            packet = root / "packet.md"
            packet.write_text(self.packet())
            telemetry = root / "telemetry.jsonl"
            env = os.environ.copy()
            env["HOME"] = directory
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [str(ROOT / "bin/external-agent"), "--task", "research",
                 "--provider", "codex", "--question", "inspect code", "--repo", str(ROOT),
                 "--memory-context-file", str(packet), "--telemetry-file", str(telemetry)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            event = json.loads(telemetry.read_text())
            self.assertEqual(event["event"], "child_packet")
            self.assertEqual(event["confirmation_stage"], "validated_provider_response")

    def test_external_build_timeout_does_not_confirm_prepared_packet(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\nsleep 5\n")
            codex.chmod(0o755)
            packet = root / "packet.md"
            packet.write_text(self.packet())
            todo = root / "todo.md"
            todo.write_text("Implement nothing")
            telemetry = root / "telemetry.jsonl"
            telemetry.write_text(json.dumps({
                "event": "packet_prepared", "delegation_id": "a" * 24,
            }) + "\n")
            env = os.environ.copy()
            env["HOME"] = directory
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = subprocess.run(
                [str(ROOT / "bin/external-build"), "--task", "build", "--todo-file", str(todo),
                 "--repo", str(ROOT), "--timeout", "1", "--memory-context-file", str(packet),
                 "--telemetry-file", str(telemetry)],
                capture_output=True, text=True, env=env,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            events = [json.loads(line) for line in telemetry.read_text().splitlines()]
            self.assertEqual([event["event"] for event in events], ["packet_prepared"])


if __name__ == "__main__":
    unittest.main()

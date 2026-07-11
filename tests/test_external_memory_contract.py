from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import tempfile
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def module(path: Path, name: str):
    spec = importlib.util.spec_from_loader(name, SourceFileLoader(name, str(path)))
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


class ExternalMemoryContractTest(unittest.TestCase):
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

    def test_every_executable_external_recipe_creates_a_packet_and_fallback(self) -> None:
        recipes = [
            "skills/auto-plan/SKILL.md", "skills/review/SKILL.md",
            "skills/investigate/SKILL.md", "skills/research/SKILL.md",
            "skills/build-fable/SKILL.md", "skills/resolve-review-fable/SKILL.md",
        ]
        for relative in recipes:
            text = (ROOT / relative).read_text()
            self.assertIn("autodev-memory-task-packet", text, relative)
            self.assertIn("--task-prompt-stdin", text, relative)
            self.assertIn("Memory context is unavailable", text, relative)
            self.assertLess(text.index("autodev-memory-task-packet"),
                            max(text.rfind("external-agent --task"),
                                text.rfind("external-build --task")), relative)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "bin/install-agent-workflows"


class InstallerTest(unittest.TestCase):
    def run_install(self, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(INSTALLER), "--source", str(ROOT), "--home", str(home), *args],
            capture_output=True, text=True,
        )

    def test_fresh_upgrade_and_rollback_in_temporary_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            settings = home / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"unrelated": {"keep": True}}))
            first = self.run_install(home, "--version", "test-v1")
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual((home / ".local/share/agent-workflows/current").readlink(),
                             Path("versions/test-v1"))
            self.assertTrue((home / ".claude/hooks/autodev-memory-session-start.sh").is_symlink())
            self.assertTrue(json.loads(settings.read_text())["unrelated"]["keep"])

            second = self.run_install(home, "--version", "test-v2")
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((home / ".local/share/agent-workflows/current").readlink(),
                             Path("versions/test-v2"))
            rollback = self.run_install(home, "--rollback")
            self.assertEqual(rollback.returncode, 0, rollback.stderr)
            self.assertEqual((home / ".local/share/agent-workflows/current").readlink(),
                             Path("versions/test-v1"))

    def test_unmanaged_collision_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            collision = home / ".claude/agents/builder.md"
            collision.parent.mkdir(parents=True)
            collision.write_text("mine")
            result = self.run_install(home, "--version", "collision")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(collision.read_text(), "mine")
            self.assertFalse((home / ".local/share/agent-workflows/current").exists())


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "bin/install-agent-workflows"


class InstallerTest(unittest.TestCase):
    def source_repo(self, root: Path) -> Path:
        source = root / "source"
        for name in ("agents", "commands", "skills", "hooks", "workflows", "bin"):
            (source / name).mkdir(parents=True, exist_ok=True)
        for relative in (
            "hooks/autodev-memory-session-start.sh", "hooks/autodev-memory-pre-agent.sh",
            "hooks/memory_context.py", "hooks/task_packet.py", "bin/autodev-memory-task-packet",
            "bin/install-agent-workflows",
            "bin/.protected-route-security-floor",
        ):
            shutil.copy2(ROOT / relative, source / relative)
        (source / "agents/builder.md").write_text("builder v1")
        (source / "skills/example").mkdir()
        (source / "skills/example/SKILL.md").write_text("skill")
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c",
                        "user.email=test@example.com", "commit", "-qm", "v1"], check=True)
        return source

    def commit(self, source: Path, message: str) -> str:
        subprocess.run(["git", "-C", str(source), "add", "."], check=True)
        subprocess.run(["git", "-C", str(source), "-c", "user.name=test", "-c",
                        "user.email=test@example.com", "commit", "-qm", message], check=True)
        return subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                              capture_output=True, text=True, check=True).stdout.strip()

    def run_install(self, source: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(INSTALLER), "--source", str(source), "--home", str(home), *args],
            capture_output=True, text=True,
        )

    def test_fresh_upgrade_and_rollback_in_temporary_home(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            home = root / "home"
            settings = home / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"unrelated": {"keep": True}}))
            first_commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                          capture_output=True, text=True, check=True).stdout.strip()
            first = self.run_install(source, home)
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual((home / ".local/share/agent-workflows/current").readlink(),
                             Path(f"versions/{first_commit}"))
            self.assertTrue((home / ".claude/hooks/autodev-memory-session-start.sh").is_symlink())
            self.assertTrue(json.loads(settings.read_text())["unrelated"]["keep"])

            (source / "agents/builder.md").unlink()
            (source / "agents/reviewer.md").write_text("reviewer v2")
            second_commit = self.commit(source, "v2")
            second = self.run_install(source, home)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual((home / ".local/share/agent-workflows/current").readlink(),
                             Path(f"versions/{second_commit}"))
            self.assertFalse((home / ".claude/agents/builder.md").exists())
            self.assertFalse((home / ".claude/agents/builder.md").is_symlink())
            self.assertTrue((home / ".claude/agents/reviewer.md").is_symlink())
            rollback = self.run_install(source, home, "--rollback")
            self.assertEqual(rollback.returncode, 0, rollback.stderr)
            self.assertEqual((home / ".local/share/agent-workflows/current").readlink(),
                             Path(f"versions/{first_commit}"))
            self.assertTrue((home / ".claude/agents/builder.md").is_symlink())
            self.assertFalse((home / ".claude/agents/reviewer.md").exists())
            self.assertFalse((home / ".claude/agents/reviewer.md").is_symlink())

    def test_security_floor_removes_pre_floor_version_and_blocks_rollback(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            marker = source / "bin/.protected-route-security-floor"
            marker.unlink()
            pre_floor = self.commit(source, "pre-floor")
            home = root / "home"
            first = self.run_install(source, home, "--version", pre_floor)
            self.assertEqual(first.returncode, 0, first.stderr)

            shutil.copy2(ROOT / "bin/.protected-route-security-floor", marker)
            floor = self.commit(source, "security floor")
            second = self.run_install(source, home, "--version", floor)
            self.assertEqual(second.returncode, 0, second.stderr)
            versions = home / ".local/share/agent-workflows/versions"
            self.assertFalse((versions / pre_floor).exists())
            self.assertTrue((versions / floor).is_dir())
            self.assertIsNone(json.loads((home / ".local/share/agent-workflows/previous.json")
                                         .read_text())["version_target"])
            rollback = self.run_install(source, home, "--rollback")
            self.assertNotEqual(rollback.returncode, 0)
            self.assertIn("no target", rollback.stderr)

    def test_legacy_root_symlink_is_migrated_and_first_rollback_restores_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            home = root / "home"
            (home / ".claude").mkdir(parents=True)
            legacy = home / ".claude/agents"
            legacy.symlink_to(source / "agents")
            result = self.run_install(source, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(legacy.is_dir())
            self.assertFalse(legacy.is_symlink())
            self.assertTrue((legacy / "builder.md").is_symlink())
            rollback = self.run_install(source, home, "--rollback")
            self.assertEqual(rollback.returncode, 0, rollback.stderr)
            self.assertTrue(legacy.is_symlink())
            self.assertEqual(legacy.resolve(), (source / "agents").resolve())

    def test_unmanaged_collision_is_not_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            home = root / "home"
            collision = home / ".claude/agents/builder.md"
            collision.parent.mkdir(parents=True)
            collision.write_text("mine")
            result = self.run_install(source, home)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(collision.read_text(), "mine")
            self.assertFalse((home / ".local/share/agent-workflows/current").exists())

    def test_legacy_rollback_collision_is_preflighted_before_live_state_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            home = root / "home"
            (home / ".claude").mkdir(parents=True)
            legacy = home / ".claude/agents"
            legacy.symlink_to(source / "agents")
            installed = self.run_install(source, home)
            self.assertEqual(installed.returncode, 0, installed.stderr)
            current = home / ".local/share/agent-workflows/current"
            active_target = current.readlink()
            collision = legacy / "operator-owned.txt"
            collision.write_text("keep")

            rollback = self.run_install(source, home, "--rollback")
            self.assertNotEqual(rollback.returncode, 0)
            self.assertEqual(current.readlink(), active_target)
            self.assertTrue((legacy / "builder.md").is_symlink())
            self.assertEqual(collision.read_text(), "keep")

            collision.unlink()
            rollback = self.run_install(source, home, "--rollback")
            self.assertEqual(rollback.returncode, 0, rollback.stderr)
            self.assertTrue(legacy.is_symlink())

    def test_dirty_worktree_is_not_copied_into_commit_named_version(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            home = root / "home"
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            (source / "agents/builder.md").write_text("dirty")
            result = self.run_install(source, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            installed = home / f".local/share/agent-workflows/versions/{commit}/agents/builder.md"
            self.assertEqual(installed.read_text(), "builder v1")

    def test_existing_version_checksum_mismatch_and_unsafe_revision_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_repo(root)
            home = root / "home"
            first = self.run_install(source, home)
            self.assertEqual(first.returncode, 0, first.stderr)
            commit = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"],
                                    capture_output=True, text=True, check=True).stdout.strip()
            artifact = home / f".local/share/agent-workflows/versions/{commit}/agents/builder.md"
            os.chmod(artifact, 0o644)
            artifact.write_text("tampered")
            mismatch = self.run_install(source, home)
            self.assertNotEqual(mismatch.returncode, 0)
            unsafe = self.run_install(source, root / "other-home", "--version", "..")
            self.assertNotEqual(unsafe.returncode, 0)


if __name__ == "__main__":
    unittest.main()

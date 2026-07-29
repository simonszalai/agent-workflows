from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINKER = ROOT / "bin/link-agent-workflows-live"


class LiveLinksTest(unittest.TestCase):
    def source_tree(self, root: Path) -> Path:
        source = root / "agent-workflows"
        for name in ("agents", "skills", "hooks", "workflows", "bin"):
            (source / name).mkdir(parents=True)
        (source / "agents/builder.md").write_text("builder")
        (source / "skills/example").mkdir()
        (source / "skills/example/SKILL.md").write_text("example")
        executable = source / "bin/tool"
        executable.write_text("#!/bin/sh\n")
        executable.chmod(0o755)
        return source

    def run_linker(self, source: Path, home: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(LINKER), "--source", str(source), "--home", str(home)],
            capture_output=True,
            text=True,
        )

    def test_migrates_per_item_links_to_folder_links(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            home = root / "home"
            settings = home / ".claude/settings.json"
            settings.parent.mkdir(parents=True)
            settings.write_text(json.dumps({"unrelated": {"keep": True}}))
            external = root / "external-skill"
            external.mkdir()
            (source / "skills/external").symlink_to(external)
            store = home / ".local/share/agent-workflows/current"
            for name in ("agents", "skills", "hooks", "workflows", "bin"):
                (store / name).mkdir(parents=True)
            (store / "skills/example").mkdir()

            for destination in (
                home / ".claude/skills",
                home / ".agents/skills",
                home / ".codex/skills",
            ):
                destination.mkdir(parents=True)
                (destination / "example").symlink_to(store / "skills/example")
            (home / ".claude/skills/external").symlink_to(source / "skills/external")
            codex_system = home / ".codex/skills/.system"
            codex_system.mkdir()
            (home / ".local/bin").mkdir(parents=True)
            (home / ".local/bin/tool").symlink_to(store / "bin/tool")

            result = self.run_linker(source, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((home / ".claude/skills").resolve(), (source / "skills").resolve())
            self.assertEqual((home / ".agents/skills").resolve(), (source / "skills").resolve())
            self.assertTrue(codex_system.is_dir())
            self.assertEqual(
                (home / ".codex/skills/agent-workflows").resolve(),
                (source / "skills").resolve(),
            )
            self.assertFalse((home / ".codex/skills/example").exists())
            self.assertEqual((home / ".local/bin/tool").resolve(), (source / "bin/tool").resolve())
            merged = json.loads(settings.read_text())
            self.assertTrue(merged["unrelated"]["keep"])
            self.assertEqual(len(merged["hooks"]["SessionStart"]), 1)
            self.assertEqual(
                len(json.loads((home / ".codex/hooks.json").read_text())["hooks"]["PreToolUse"]),
                1,
            )
            self.assertFalse((home / ".local/share/agent-workflows").exists())

            (source / "skills/new-skill").mkdir()
            (source / "skills/new-skill/SKILL.md").write_text("new")
            self.assertTrue((home / ".claude/skills/new-skill/SKILL.md").is_file())
            self.assertTrue((home / ".agents/skills/new-skill/SKILL.md").is_file())
            self.assertTrue(
                (home / ".codex/skills/agent-workflows/new-skill/SKILL.md").is_file()
            )

    def test_refuses_unmanaged_root_content_before_mutating(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            home = root / "home"
            skills = home / ".claude/skills"
            skills.mkdir(parents=True)
            unmanaged = skills / "private-skill"
            unmanaged.mkdir()

            result = self.run_linker(source, home)
            self.assertNotEqual(result.returncode, 0)
            self.assertTrue(skills.is_dir())
            self.assertFalse(skills.is_symlink())
            self.assertTrue(unmanaged.is_dir())
            self.assertFalse((home / ".claude/agents").exists())

    def test_preserves_unrelated_shared_bin_and_codex_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            home = root / "home"
            personal_skill = home / ".codex/skills/personal"
            personal_skill.mkdir(parents=True)
            unrelated_bin = home / ".local/bin/unrelated"
            unrelated_bin.parent.mkdir(parents=True)
            unrelated_bin.write_text("keep")
            unrelated_bin.chmod(0o755)

            result = self.run_linker(source, home)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(personal_skill.is_dir())
            self.assertEqual(unrelated_bin.read_text(), "keep")
            self.assertTrue(os.access(unrelated_bin, os.X_OK))

    def test_refuses_bin_collision_before_mutating_roots(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.source_tree(root)
            home = root / "home"
            collision = home / ".local/bin/tool"
            collision.parent.mkdir(parents=True)
            collision.write_text("mine")

            result = self.run_linker(source, home)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(collision.read_text(), "mine")
            self.assertFalse((home / ".claude/skills").exists())


if __name__ == "__main__":
    unittest.main()

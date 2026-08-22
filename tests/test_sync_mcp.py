from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "bin/sync-mcp"


class SyncMcpTest(unittest.TestCase):
    def make_repo(self, root: Path, remote: str) -> Path:
        repo = root / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(["git", "-C", str(repo), "remote", "add", "origin", remote], check=True)
        return repo

    def test_project_render_is_idempotent_for_all_four_clients(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = self.make_repo(
                Path(directory), "https://github.com/TS-Value-Software/ts-api.git",
            )
            (repo / ".mcp.json").write_text('{\n\t"mcpServers": {}\n}\n')
            (repo / ".cursor").mkdir()
            (repo / ".cursor/mcp.json").write_text(json.dumps({
                "mcpServers": {
                    "render": {"type": "http", "url": "http://127.0.0.1:8765/render"},
                    "team-owned": {"command": "team-server"},
                }
            }))
            result = subprocess.run(
                [str(SYNC), "--project", "--cwd", str(repo)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            claude = json.loads((repo / ".mcp.json").read_text())["mcpServers"]
            cursor = json.loads((repo / ".cursor/mcp.json").read_text())["mcpServers"]
            self.assertEqual(set(claude), {"autodev-memory", "conductor", "context7"})
            self.assertEqual(
                claude["autodev-memory"]["command"], "sh",
            )
            self.assertIn('"$HOME/.local/bin/mcp-bridge"',
                          claude["autodev-memory"]["args"][1])
            self.assertEqual(claude["conductor"]["type"], "http")
            self.assertEqual(claude["context7"]["url"], "https://mcp.context7.com/mcp")
            self.assertNotIn("render", cursor)
            self.assertIn("team-owned", cursor)
            self.assertIn("[mcp_servers.autodev-memory]",
                          (repo / ".codex/config.toml").read_text())
            self.assertIn("enabled = true", (repo / ".grok/config.toml").read_text())
            self.assertTrue((repo / ".mcp.json").read_text().startswith('{\n\t"mcpServers"'))
            self.assertTrue((repo / ".cursor/mcp.json").read_text().startswith(
                '{\n\t"mcpServers"',
            ))

            checked = subprocess.run(
                [str(SYNC), "--project", "--check", "--cwd", str(repo)],
                capture_output=True, text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_user_sync_preserves_unmanaged_entries_and_removes_project_only_amaru(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            (home / ".claude.json").write_text(json.dumps({
                "projects": {"keep": {"trusted": True}},
                "mcpServers": {
                    "amaru": {"type": "http", "url": "https://old.invalid"},
                    "personal": {"command": "personal-server"},
                },
            }))
            (home / ".codex").mkdir()
            (home / ".codex/config.toml").write_text(
                '[mcp_servers.1password]\ncommand = "1password-mcp"\n\n'
                '[mcp_servers.context7]\nurl = "http://127.0.0.1:8793/"\n'
            )
            result = subprocess.run(
                [str(SYNC), "--user", "--home", str(home)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            claude = json.loads((home / ".claude.json").read_text())
            self.assertTrue(claude["projects"]["keep"]["trusted"])
            self.assertEqual(
                set(claude["mcpServers"]), {"conductor", "context7", "personal"},
            )
            codex = (home / ".codex/config.toml").read_text()
            self.assertIn("[mcp_servers.1password]", codex)
            self.assertEqual(codex.count("[mcp_servers.context7]"), 1)
            self.assertTrue((home / ".cursor/mcp.json").is_file())
            self.assertTrue((home / ".grok/config.toml").is_file())

    def test_cloud_user_scope_includes_exact_project_servers(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(root, "https://github.com/amaru-wellness/amaru-mcp.git")
            home = root / "home"
            result = subprocess.run(
                [str(SYNC), "--user", "--include-project", "--cwd", str(repo),
                 "--home", str(home)],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            servers = json.loads((home / ".cursor/mcp.json").read_text())["mcpServers"]
            self.assertEqual(
                set(servers), {"amaru", "autodev-memory", "conductor", "context7"},
            )
            self.assertIn("amaru", (home / ".codex/config.toml").read_text())


if __name__ == "__main__":
    unittest.main()

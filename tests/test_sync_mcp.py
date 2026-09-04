from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "bin/sync-mcp"


class SyncMcpTest(unittest.TestCase):
    def codex_env_vars(self, path: Path, server: str) -> list[str]:
        text = path.read_text()
        marker = f"[mcp_servers.{server}]"
        self.assertIn(marker, text)
        block = text.split(marker, 1)[1].split("\n[", 1)[0]
        matched = re.search(r"(?ms)^env_vars = \[(.*?)\]$", block)
        self.assertIsNotNone(matched)
        assert matched is not None
        return re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', matched.group(1))

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
            (repo / "biome.json").write_text(
                '{"formatter":{"indentStyle":"tab"}}\n',
            )
            (repo / ".mcp.json").write_text('{\n  "mcpServers": {}\n}\n')
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
            self.assertEqual(claude["conductor"]["type"], "stdio")
            self.assertEqual(claude["conductor"]["command"], "sh")
            self.assertIn(
                '"$HOME/.local/bin/mcp-bridge" conductor',
                claude["conductor"]["args"][1],
            )
            self.assertEqual(claude["context7"]["url"], "https://mcp.context7.com/mcp")
            self.assertNotIn("render", cursor)
            self.assertIn("team-owned", cursor)
            self.assertIn("[mcp_servers.autodev-memory]",
                          (repo / ".codex/config.toml").read_text())
            self.assertEqual(
                self.codex_env_vars(repo / ".codex/config.toml", "autodev-memory"),
                ["TS_OP_SERVICE_ACCOUNT_TOKEN"],
            )
            self.assertEqual(
                self.codex_env_vars(repo / ".codex/config.toml", "conductor"),
                ["CONDUCTOR_API_TOKEN", "CONDUCTOR_API_KEY", "CONDUCTOR_API_URL"],
            )
            grok = (repo / ".grok/config.toml").read_text()
            self.assertIn("enabled = true", grok)
            self.assertNotIn("env_vars", grok)
            for servers in (claude, cursor):
                self.assertNotIn("env_vars", servers["autodev-memory"])
                self.assertNotIn("env_vars", servers["conductor"])
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
            self.assertFalse((home / ".claude.json").read_text().endswith("\n"))

            checked = subprocess.run(
                [str(SYNC), "--user", "--check", "--home", str(home)],
                capture_output=True, text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

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
            self.assertEqual(
                self.codex_env_vars(home / ".codex/config.toml", "autodev-memory"),
                ["TS_OP_SERVICE_ACCOUNT_TOKEN"],
            )
            self.assertEqual(
                self.codex_env_vars(home / ".codex/config.toml", "conductor"),
                ["CONDUCTOR_API_TOKEN", "CONDUCTOR_API_KEY", "CONDUCTOR_API_URL"],
            )
            self.assertNotIn("env_vars", (home / ".grok/config.toml").read_text())

            checked = subprocess.run(
                [str(SYNC), "--user", "--include-project", "--check",
                 "--cwd", str(repo), "--home", str(home)],
                capture_output=True, text=True,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_environment_values_are_never_rendered(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = self.make_repo(
                root, "https://github.com/TS-Value-Software/ts-prefect.git",
            )
            sentinels = {
                "TS_OP_SERVICE_ACCOUNT_TOKEN": "test-ts-credential-value",
                "CONDUCTOR_API_TOKEN": "test-conductor-token-value",
                "CONDUCTOR_API_KEY": "test-conductor-key-value",
                "CONDUCTOR_API_URL": "https://credential-value.invalid",
            }
            result = subprocess.run(
                [str(SYNC), "--project", "--cwd", str(repo)],
                capture_output=True, text=True, env={**os.environ, **sentinels},
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            rendered = "\n".join(
                path.read_text()
                for path in (
                    repo / ".mcp.json",
                    repo / ".codex/config.toml",
                    repo / ".cursor/mcp.json",
                    repo / ".grok/config.toml",
                )
            )
            for value in sentinels.values():
                self.assertNotIn(value, rendered)

    def test_manifest_rejects_malformed_or_duplicate_env_vars(self) -> None:
        invalid_values = (
            ("not-a-list", "must be an array of strings"),
            (["VALID_NAME", 7], "must be an array of strings"),
            (["NOT-VALID"], "invalid environment variable name"),
            (["DUPLICATE", "DUPLICATE"], "contains duplicate names"),
        )
        for env_vars, expected in invalid_values:
            with self.subTest(env_vars=env_vars):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    manifest = root / "mcp.json"
                    manifest.write_text(json.dumps({
                        "schema_version": 1,
                        "global_servers": {
                            "conductor": {
                                "transport": "stdio-bridge",
                                "profile": "conductor",
                                "env_vars": env_vars,
                            },
                        },
                        "project_servers": {},
                        "managed_server_names": ["conductor"],
                    }))
                    result = subprocess.run(
                        [str(SYNC), "--user", "--home", str(root / "home"),
                         "--manifest", str(manifest)],
                        capture_output=True, text=True,
                    )
                    self.assertEqual(result.returncode, 2)
                    self.assertIn(expected, result.stderr)


if __name__ == "__main__":
    unittest.main()

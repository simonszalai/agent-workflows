from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "hermes"


class FakeFastMCP:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def tool(self) -> object:
        return lambda function: function


def load_conductor_server(state_dir: Path) -> types.ModuleType:
    httpx = types.ModuleType("httpx")
    httpx.Client = object
    mcp = types.ModuleType("mcp")
    mcp_server = types.ModuleType("mcp.server")
    fastmcp = types.ModuleType("mcp.server.fastmcp")
    fastmcp.FastMCP = FakeFastMCP
    modules = {
        "httpx": httpx,
        "mcp": mcp,
        "mcp.server": mcp_server,
        "mcp.server.fastmcp": fastmcp,
    }
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    old_credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    old_state = os.environ.get("STATE_DIRECTORY")
    os.environ["CREDENTIALS_DIRECTORY"] = str(state_dir)
    os.environ["STATE_DIRECTORY"] = str(state_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "hermes_conductor_server",
            HERMES / "conductor" / "server.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, previous_module in previous.items():
            if previous_module is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous_module
        if old_credentials is None:
            os.environ.pop("CREDENTIALS_DIRECTORY", None)
        else:
            os.environ["CREDENTIALS_DIRECTORY"] = old_credentials
        if old_state is None:
            os.environ.pop("STATE_DIRECTORY", None)
        else:
            os.environ["STATE_DIRECTORY"] = old_state


class HermesConductorTests(unittest.TestCase):
    def test_repo_and_branch_scope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            self.assertEqual(server.validate_repo("ts-prefect"), "ts-prefect")
            self.assertEqual(server.validate_branch(None, "ts-prefect"), "staging")
            self.assertIsNone(server.validate_branch(None, "ts-dashboard"))
            for invalid in ("", "../repo", "owner/repo", "https:repo"):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(server.SafeError):
                        server.validate_repo(invalid)
            for invalid in ("../main", "main..x", "@{x}", "a//b"):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(server.SafeError):
                        server.validate_branch(invalid, "ts-dashboard")

    def test_message_response_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            payload = {
                "data": [
                    {
                        "id": "message_123",
                        "sessionId": "session_123",
                        "sessionIndex": 1,
                        "type": "assistant",
                        "content": "x" * 90_000,
                        "receivedAt": "2026-07-31T00:00:00Z",
                    }
                ],
                "offset": 0,
                "hasMore": False,
            }
            result = server.bounded_messages(payload)
            self.assertLess(len(str(result)), 82_000)
            self.assertIn("[truncated]", result["messages"][0]["content"])

    def test_database_initializes_without_launching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            server.init_db()
            self.assertTrue((Path(directory) / "workspaces.sqlite3").is_file())
            self.assertEqual(server.list_launches(), {"launches": []})


class HermesAssetTests(unittest.TestCase):
    def test_services_are_loopback_secret_boundaries(self) -> None:
        conductor = (HERMES / "systemd" / "hermes-conductor.service").read_text()
        autodev = (HERMES / "systemd" / "hermes-autodev-mcp.service").read_text()
        for service in (conductor, autodev):
            self.assertIn("LoadCredential=", service)
            self.assertIn("NoNewPrivileges=true", service)
            self.assertIn("ProtectSystem=strict", service)
            self.assertIn("ProtectHome=true", service)
            self.assertNotIn("Environment=CONDUCTOR_API_KEY=", service)
            self.assertNotIn("Environment=AUTODEV_MEMORY_API_TOKEN=", service)
        self.assertIn("Environment=MCP_PROXY_PORT=8792", autodev)
        self.assertIn("port=8794", (HERMES / "conductor" / "server.py").read_text())

    def test_configure_is_idempotent(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "hermes_configure",
            HERMES / "configure.py",
        )
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.yaml"
            config.write_text("platform_toolsets:\n  slack:\n  - clarify\n")
            module.configure(config)
            first = config.read_text()
            module.configure(config)
            self.assertEqual(config.read_text(), first)
            data = yaml.safe_load(first)
            self.assertEqual(
                data["mcp_servers"]["conductor"]["tools"]["include"],
                [
                    "get_launch_policy",
                    "launch_workspace",
                    "list_launches",
                    "get_session_status",
                    "read_session_messages",
                ],
            )

    def test_executables_have_execute_bits(self) -> None:
        for relative in ("install.sh", "bin/run-autodev-memory", "conductor/server.py"):
            mode = (HERMES / relative).stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, relative)

    def test_runbook_names_the_current_ts_scoped_token(self) -> None:
        runbook = (HERMES / "README.md").read_text()
        self.assertIn("TS/TS_AUTODEV_MEMORY_API_TOKEN", runbook)
        self.assertNotIn("AUTODEV-sensitive/HERMES_AUTODEV_MEMORY_TOKEN", runbook)


if __name__ == "__main__":
    unittest.main()

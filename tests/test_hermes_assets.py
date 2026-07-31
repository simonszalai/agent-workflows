from __future__ import annotations

import importlib.util
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "hermes"


class FakeFastMCP:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.tools: list[str] = []

    def tool(self) -> object:
        def register(function: object) -> object:
            self.tools.append(function.__name__)
            return function

        return register


def load_conductor_server(temporary_dir: Path) -> types.ModuleType:
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
    os.environ["CREDENTIALS_DIRECTORY"] = str(temporary_dir)
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


EXPECTED_CONDUCTOR_OPERATIONS = {
    "get_current_user": ("GET", "/me"),
    "list_projects": ("GET", "/v0/projects"),
    "get_project": ("GET", "/v0/projects/{projectId}"),
    "list_project_workspaces": ("GET", "/v0/projects/{projectId}/workspaces"),
    "create_workspace": ("POST", "/v0/workspaces"),
    "get_workspace": ("GET", "/v0/workspaces/{workspaceId}"),
    "rename_workspace": ("POST", "/v0/workspaces/{workspaceId}/rename"),
    "archive_workspace": ("POST", "/v0/workspaces/{workspaceId}/archive"),
    "list_workspace_sessions": ("GET", "/v0/workspaces/{workspaceId}/sessions"),
    "create_session": ("POST", "/v0/sessions"),
    "get_session": ("GET", "/v0/sessions/{sessionId}"),
    "rename_session": ("POST", "/v0/sessions/{sessionId}/rename"),
    "archive_session": ("POST", "/v0/sessions/{sessionId}/archive"),
    "list_session_messages": ("GET", "/v0/sessions/{sessionId}/messages"),
    "send_session_message": ("POST", "/v0/sessions/{sessionId}/messages"),
    "get_message": ("GET", "/v0/messages/{messageId}"),
    "get_workspace_status": ("GET", "/v0/workspaces/{workspaceId}/status"),
    "get_session_status": ("GET", "/v0/sessions/{sessionId}/status"),
    "cancel_session": ("POST", "/v0/sessions/{sessionId}/cancel"),
    "query_conductor_sql": ("POST", "/v0/sql"),
}


class HermesConductorTests(unittest.TestCase):
    def test_every_openapi_operation_has_one_registered_tool(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            self.assertEqual(server.OFFICIAL_OPERATION_TOOLS, EXPECTED_CONDUCTOR_OPERATIONS)
            self.assertEqual(set(server.mcp.tools), set(EXPECTED_CONDUCTOR_OPERATIONS))
            self.assertEqual(len(server.mcp.tools), 20)

    def test_create_workspace_exposes_the_full_request(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            with mock.patch.object(
                server,
                "conductor_request",
                return_value={"workspaceId": "workspace"},
            ) as request:
                result = server.create_workspace(
                    repository_url="https://github.com/example/repo.git",
                    branch="feature/full-api",
                    name="full-api",
                    session_name="initial session",
                    agent="codex",
                    model="gpt-5.5",
                    effort="high",
                    env={"FEATURE_FLAG": "1"},
                    channel="beta",
                )
            self.assertEqual(result, {"workspaceId": "workspace"})
            request.assert_called_once_with(
                "POST",
                "/v0/workspaces",
                "workspace.create",
                params={"channel": "beta"},
                json_body={
                    "repositoryUrl": "https://github.com/example/repo.git",
                    "branch": "feature/full-api",
                    "name": "full-api",
                    "sessionName": "initial session",
                    "agent": "codex",
                    "model": "gpt-5.5",
                    "effort": "high",
                    "env": {"FEATURE_FLAG": "1"},
                },
            )

    def test_create_workspace_requires_exactly_one_source(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            for arguments in (
                {},
                {"project_id": "project", "repository_url": "https://example.com/repo.git"},
            ):
                with self.subTest(arguments=arguments):
                    with self.assertRaises(server.SafeError):
                        server.create_workspace(**arguments)

    def test_path_ids_are_encoded_and_message_pagination_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            with mock.patch.object(
                server,
                "conductor_request",
                return_value={"data": []},
            ) as request:
                server.list_session_messages(
                    "session/with space",
                    limit=12,
                    after_message_id="message-1",
                )
            request.assert_called_once_with(
                "GET",
                "/v0/sessions/session%2Fwith%20space/messages",
                "session.messages.list",
                params={"limit": 12, "after": "message-1"},
            )
            with self.assertRaises(server.SafeError):
                server.list_session_messages(
                    "session",
                    offset=1,
                    after_message_id="message-1",
                )

    def test_sql_tool_passes_read_only_api_query(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = load_conductor_server(Path(directory))
            with mock.patch.object(
                server,
                "conductor_request",
                return_value={"rows": [], "rowCount": 0, "truncated": False},
            ) as request:
                result = server.query_conductor_sql(
                    "SELECT workspace_id FROM session_transcripts_view"
                )
            self.assertEqual(result["rowCount"], 0)
            request.assert_called_once_with(
                "POST",
                "/v0/sql",
                "sql.query",
                json_body={
                    "query": "SELECT workspace_id FROM session_transcripts_view",
                },
            )


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
            with tempfile.TemporaryDirectory() as server_directory:
                server = load_conductor_server(Path(server_directory))
            self.assertEqual(
                set(data["mcp_servers"]["conductor"]["tools"]["include"]),
                set(server.OFFICIAL_OPERATION_TOOLS),
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

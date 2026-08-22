from __future__ import annotations

import base64
import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BRIDGE = ROOT / "bin/mcp-bridge"


class RecordingHandler(BaseHTTPRequestHandler):
    requests: list[dict[str, object]] = []

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        self.requests.append({
            "authorization": self.headers.get("Authorization"),
            "body": body,
        })
        response = {"jsonrpc": "2.0", "id": body.get("id"), "result": {"ok": True}}
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format: str, *args: object) -> None:
        pass


class McpBridgeTest(unittest.TestCase):
    def test_stdio_bridge_resolves_exact_project_and_waf_encodes_writes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
            RecordingHandler.requests = []
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)

            config = root / "project-tools.json"
            config.write_text(json.dumps({
                "schema_version": 1,
                "projects": {
                    "testproj": {
                        "repo_remotes": ["github.com/acme/test-repo"],
                        "service_account": {
                            "token_env": "TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
                            "keychain_item": "op-testproj-token",
                            "vaults": ["TESTVAULT"],
                        },
                        "autodev_memory": {
                            "url": f"http://127.0.0.1:{server.server_port}",
                            "token_ref": "op://TESTVAULT/Autodev memory/api_token",
                        },
                        "render": {
                            "api_key_ref": "op://TESTVAULT/Render/api_key",
                            "workspace": {"id": "tea-test"},
                        },
                    }
                },
            }))
            repo = root / "repo"
            repo.mkdir()
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            subprocess.run([
                "git", "-C", str(repo), "remote", "add", "origin",
                "https://github.com/acme/test-repo.git",
            ], check=True)
            fake_op = root / "op"
            fake_op.write_text(
                '#!/bin/sh\n'
                '[ "${OP_SERVICE_ACCOUNT_TOKEN:-}" = "service-account" ] || exit 31\n'
                '[ -z "${WRONG_OP_SERVICE_ACCOUNT_TOKEN:-}" ] || exit 32\n'
                'printf "%s" "restricted-bearer"\n'
            )
            fake_op.chmod(0o755)
            messages = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-06-18", "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                }},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                    "name": "create_entry",
                    "arguments": {"content": "SELECT * FROM secret_table", "title": "safe"},
                }},
            ]
            env = os.environ.copy()
            env.update({
                "PROJECT_TOOLS_CONFIG": str(config),
                "TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN": "service-account",
                "WRONG_OP_SERVICE_ACCOUNT_TOKEN": "wrong-account",
                "OP_REAL_BIN": str(fake_op),
                "HOME": str(root / "home"),
                # A Conductor-launched shell may retain path hints for another
                # workspace. The bridge must prefer the MCP child's Git cwd.
                "CONDUCTOR_ROOT_PATH": str(root / "stale-root"),
                "CONDUCTOR_WORKSPACE_PATH": str(root / "stale-workspace"),
            })
            result = subprocess.run(
                [str(BRIDGE), "autodev-memory", "--project", "testproj"],
                input="".join(json.dumps(message) + "\n" for message in messages),
                capture_output=True, text=True, env=env, cwd=repo, timeout=30,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            responses = [json.loads(line) for line in result.stdout.splitlines()]
            self.assertEqual([response["id"] for response in responses], [1, 2])
            self.assertEqual(len(RecordingHandler.requests), 2)
            for request in RecordingHandler.requests:
                self.assertEqual(request["authorization"], "Bearer restricted-bearer")
            arguments = RecordingHandler.requests[1]["body"]["params"]["arguments"]
            self.assertTrue(arguments["content"].startswith("@@B64@@"))
            decoded = base64.b64decode(arguments["content"][7:]).decode()
            self.assertEqual(decoded, "SELECT * FROM secret_table")
            self.assertEqual(arguments["title"], "safe")

    def test_conductor_bridge_uses_env_bearer_and_skips_waf_transform(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        RecordingHandler.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        messages = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            }},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "create_workspace",
                "arguments": {"description": "SELECT * FROM plans", "name": "ws"},
            }},
        ]
        env = os.environ.copy()
        env.update({
            "CONDUCTOR_API_URL": f"http://127.0.0.1:{server.server_port}",
            "CONDUCTOR_API_KEY": "workspace-scoped-key",
        })
        result = subprocess.run(
            [str(BRIDGE), "conductor"],
            input="".join(json.dumps(message) + "\n" for message in messages),
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        responses = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual([response["id"] for response in responses], [1, 2])
        self.assertEqual(len(RecordingHandler.requests), 2)
        for request in RecordingHandler.requests:
            self.assertEqual(request["authorization"], "Bearer workspace-scoped-key")
        arguments = RecordingHandler.requests[1]["body"]["params"]["arguments"]
        self.assertEqual(arguments["description"], "SELECT * FROM plans")

    def test_conductor_bridge_prefers_explicit_token_over_workspace_key(self) -> None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), RecordingHandler)
        RecordingHandler.requests = []
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        message = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
        env = os.environ.copy()
        env.update({
            "CONDUCTOR_API_URL": f"http://127.0.0.1:{server.server_port}",
            "CONDUCTOR_API_TOKEN": "explicit-token",
            "CONDUCTOR_API_KEY": "workspace-scoped-key",
        })
        result = subprocess.run(
            [str(BRIDGE), "conductor"],
            input=json.dumps(message) + "\n",
            capture_output=True, text=True, env=env, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            RecordingHandler.requests[0]["authorization"], "Bearer explicit-token",
        )


if __name__ == "__main__":
    unittest.main()

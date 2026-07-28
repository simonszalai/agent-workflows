from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "bin" / "hermes-gateway-activation"
LOADER = importlib.machinery.SourceFileLoader("hermes_gateway_activation", str(COMMAND))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
if SPEC is None:
    raise RuntimeError("cannot load gateway activation")
GATEWAY = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = GATEWAY
LOADER.exec_module(GATEWAY)


def handoff() -> dict[str, object]:
    return {
        "schema": GATEWAY.HANDOFF_SCHEMA,
        "status": "pass",
        "provider": {
            "ticket": "F0023",
            "path": "bin/hermes-activation",
            "contract": "e0006-m3/v1",
            "output_schema": "e0006-m3/v1",
            "merge_sha": GATEWAY.PROVIDER_COMMIT,
            "tree_sha": GATEWAY.PROVIDER_TREE,
        },
        "items": [
            {
                "name": "HERMES_AUTODEV_MEMORY_TOKEN",
                "ref": GATEWAY.H.MEMORY_REF,
                "item_id": "memory-item-id",
                "state": "existing",
            },
            {
                "name": "HERMES_GATEWAY_TOKEN",
                "ref": GATEWAY.H.GATEWAY_REF,
                "item_id": "gateway-item-id",
                "state": "existing",
            },
        ],
        "deployments": [
            {
                "label": "initial_active",
                "deploy_id": "deploy-initial",
                "state": "live",
                "valid_config_count": 1,
                "invalid_config_count": 0,
            },
            {
                "label": "inert",
                "deploy_id": "deploy-inert",
                "state": "live",
                "valid_config_count": 0,
                "invalid_config_count": 0,
            },
            {
                "label": "final_active",
                "deploy_id": "deploy-final",
                "state": "live",
                "valid_config_count": 1,
                "invalid_config_count": 0,
            },
        ],
        "admin_matrix": {"evidence_id": "admin-evidence", "status": "pass"},
        "direct_canary": {
            "run_id": "direct-run-id",
            "ticket_id": "F0001",
            "evidence_id": "direct-evidence",
            "status": "pass",
            "cleanup": "pass",
        },
        "evidence_artifact_id": "final-evidence",
    }


@contextmanager
def fake_http(handler_type: type[BaseHTTPRequestHandler]):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_type)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class GatewayActivationTests(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")
        path.chmod(0o600)

    def run_prepare(self, root: Path, receipt: Path, handoff_path: Path) -> subprocess.CompletedProcess:
        env_path = root / "mcp-gateway" / "gateway.env"
        env = {
            **os.environ,
            "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
            "HERMES_GATEWAY_ACTIVATION_TEST_ROOT": str(root),
        }
        return subprocess.run(
            [
                str(COMMAND),
                "prepare",
                "--handoff-receipt",
                str(handoff_path),
                "--gateway-env",
                str(env_path),
                "--receipt",
                str(receipt),
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_prepare_writes_only_canonical_refs_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gateway = root / "mcp-gateway"
            gateway.mkdir()
            env_path = gateway / "gateway.env"
            env_path.write_text("EXISTING=op://SAFE/item/value\n", encoding="utf-8")
            env_path.chmod(0o640)
            (gateway / "routes.json").write_text(json.dumps({"routes": {
                prefix: {
                    "clientTokenEnv": "HERMES_GATEWAY_TOKEN",
                    "allowTools": ["safe"],
                }
                for prefix in (
                    "hermes/autodev-memory",
                    "hermes/render",
                    "hermes/slack",
                )
            }}), encoding="utf-8")
            handoff_path = root / "handoff.json"
            receipt = root / "receipt.json"
            self.write_json(handoff_path, handoff())

            first = self.run_prepare(root, receipt, handoff_path)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            output = json.loads(first.stdout)
            self.assertTrue(output["result"]["changed"])
            text = env_path.read_text(encoding="utf-8")
            for name, reference in GATEWAY.ENV_ROWS:
                self.assertEqual(text.count(f"{name}={reference}"), 1)
            self.assertNotIn("memory-item-id", text)
            self.assertNotIn("gateway-item-id", text)
            self.assertEqual(stat.S_IMODE(env_path.stat().st_mode), 0o640)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)

            second = self.run_prepare(root, receipt, handoff_path)
            self.assertEqual(second.returncode, 0)
            self.assertFalse(json.loads(second.stdout)["result"]["changed"])

    def test_prepare_rejects_unknown_secret_like_and_wrong_revision_handoffs(self) -> None:
        mutations = []
        unknown = handoff()
        unknown["unknown"] = True
        mutations.append((unknown, "handoff_shape_mismatch"))
        secret = handoff()
        secret["items"][0]["token"] = "never-visible"
        mutations.append((secret, "handoff_shape_mismatch"))
        revision = handoff()
        revision["provider"]["tree_sha"] = "wrong-tree"
        mutations.append((revision, "handoff_provider_revision_mismatch"))
        for value, expected in mutations:
            with self.subTest(expected=expected), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                gateway = root / "mcp-gateway"
                gateway.mkdir()
                (gateway / "gateway.env").write_text("", encoding="utf-8")
                (gateway / "routes.json").write_text('{"routes":{}}', encoding="utf-8")
                handoff_path = root / "handoff.json"
                self.write_json(handoff_path, value)
                result = self.run_prepare(root, root / "receipt.json", handoff_path)
                self.assertNotEqual(result.returncode, 0)
                output = json.loads(result.stdout)
                self.assertEqual(output["result"]["code"], expected)
                self.assertNotIn("never-visible", result.stdout + result.stderr)

    def test_prepare_rejects_conflicting_ref_and_arbitrary_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gateway = root / "mcp-gateway"
            gateway.mkdir()
            env_path = gateway / "gateway.env"
            env_path.write_text(
                "HERMES_GATEWAY_TOKEN=op://WRONG/item/value\n", encoding="utf-8"
            )
            (gateway / "routes.json").write_text('{"routes":{}}', encoding="utf-8")
            handoff_path = root / "handoff.json"
            self.write_json(handoff_path, handoff())
            result = self.run_prepare(root, root / "receipt.json", handoff_path)
            self.assertEqual(
                json.loads(result.stdout)["result"]["code"],
                "gateway_env_conflicting_ref",
            )

            env = {
                **os.environ,
                "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                "HERMES_GATEWAY_ACTIVATION_TEST_ROOT": str(root),
            }
            arbitrary = root / "other.env"
            arbitrary.write_text("", encoding="utf-8")
            result = subprocess.run(
                [
                    str(COMMAND), "prepare", "--handoff-receipt", str(handoff_path),
                    "--gateway-env", str(arbitrary), "--receipt", str(root / "other.json"),
                ],
                text=True, capture_output=True, env=env, check=False,
            )
            self.assertEqual(
                json.loads(result.stdout)["result"]["code"],
                "gateway_env_path_invalid",
            )

    def test_custom_http_auth_uses_gateway_header_without_authorization(self) -> None:
        observed: dict[str, str | None] = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                observed["gateway"] = self.headers.get("x-mcp-gateway-token")
                observed["authorization"] = self.headers.get("authorization")
                size = int(self.headers.get("content-length", "0"))
                self.rfile.read(size)
                body = b'{"ok":true}'
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args: object) -> None:
                return

        with fake_http(Handler) as base:
            client = GATEWAY.H.HttpClient(
                base,
                b"gateway-canary-credential",
                auth_header="X-MCP-Gateway-Token",
                auth_scheme="",
            )
            response = client.request("POST", "/", {"safe": True}, accepted={200})
            self.assertEqual(response.body, {"ok": True})
        self.assertEqual(observed["gateway"], "gateway-canary-credential")
        self.assertIsNone(observed["authorization"])

    def test_probe_covers_full_gateway_negative_boundary_without_secret_receipts(self) -> None:
        state = GATEWAY.State(
            GATEWAY.STATE_SCHEMA,
            "gateway-run-id",
            GATEWAY.CANARY_PREFIX + "gateway-run-id",
            None,
            "prepare",
            1.0,
            301.0,
            [],
            0,
            0,
            None,
        )
        health = mock.MagicMock()
        response = health.__enter__.return_value
        response.status = 200
        response.read.return_value = json.dumps({
            "ok": True,
            "routes": [
                "hermes/autodev-memory",
                "hermes/render",
                "hermes/slack",
            ],
        }).encode()
        calls: list[tuple[str, bytes, object]] = []

        def request(path: str, credential: bytes, body: object = None):
            calls.append((path, credential, body))
            if path in ("/hermes/render", "/shared/autodev-memory"):
                if isinstance(body, dict) and body.get("method") == "tools/list":
                    if path == "/hermes/render" and credential == b"h" * 32:
                        return 200, b'{"result":{"tools":[{"name":"get_service"}]}}'
                    return 401, b'{"error":"unauthorized"}'
                return 403, b'{"error":"denied"}'
            return 403, b'{"error":"denied"}'

        with mock.patch.dict(os.environ, {
            "HERMES_GATEWAY_TOKEN": "h" * 32,
            "MCP_GATEWAY_TOKEN": "d" * 32,
        }, clear=False), mock.patch.object(
            GATEWAY.urllib.request, "urlopen", return_value=health
        ), mock.patch.object(GATEWAY, "raw_request", side_effect=request):
            GATEWAY.probe_gateway(state)

        self.assertEqual(state.checks, list(GATEWAY.CHECKS[:6]))
        called_render_tools = {
            call[2]["params"]["name"]
            for call in calls
            if call[0] == "/hermes/render"
            and isinstance(call[2], dict)
            and call[2].get("method") == "tools/call"
        }
        self.assertEqual(called_render_tools, set(GATEWAY.FORBIDDEN_RENDER))
        serialized = json.dumps(asdict(state))
        self.assertNotIn("h" * 32, serialized)
        self.assertNotIn("d" * 32, serialized)

    def test_secret_audit_rejects_credentials_and_deadline_is_enforced(self) -> None:
        with self.assertRaisesRegex(GATEWAY.SafeError, "secret_leak_detected"):
            GATEWAY.assert_secret_free([b'{"field":"credential-canary"}'], (
                b"credential-canary",
            ))
        state = GATEWAY.State(
            GATEWAY.STATE_SCHEMA,
            "expired-run",
            GATEWAY.CANARY_PREFIX + "expired-run",
            "F0001",
            "awaiting_admin_approval",
            1.0,
            301.0,
            list(GATEWAY.CHECKS[:10]),
            10,
            3,
            None,
        )
        with mock.patch.object(GATEWAY.time, "time", return_value=302.0):
            with self.assertRaisesRegex(GATEWAY.SafeError, "canary_deadline_exceeded"):
                GATEWAY.tool(mock.MagicMock(), state, "get_ticket", {})

    def test_closed_matrix_includes_server_approval_pickup_and_cleanup(self) -> None:
        self.assertEqual(len(GATEWAY.CHECKS), len(set(GATEWAY.CHECKS)))
        for required in (
            "origin_status_source_identity",
            "self_approval_and_execution_status_denied",
            "cross_ticket_write_denied",
            "admin_approval_observed",
            "owner_edit_clears_approval",
            "admin_reapproval_observed",
            "scoped_pickup_exact",
            "terminal_cleanup",
            "render_mutations_denied_zero_dispatch",
            "jsonrpc_batch_and_rest_bypass_rejected",
            "tools_list_filtered_fail_closed",
            "secret_free_audit",
        ):
            self.assertIn(required, GATEWAY.CHECKS)


if __name__ == "__main__":
    unittest.main()

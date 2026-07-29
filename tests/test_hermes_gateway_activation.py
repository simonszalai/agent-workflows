from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import re
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

    def run_env_command(
        self,
        command: str,
        root: Path,
        receipt: Path,
        handoff_path: Path,
        env_path: Path | None = None,
    ) -> subprocess.CompletedProcess:
        gateway = root / "mcp-gateway"
        env_path = env_path or (
            gateway / "gateway.local.env"
            if (gateway / "gateway.local.env").is_file()
            else gateway / "gateway.env"
        )
        env = {
            **os.environ,
            "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
            "HERMES_GATEWAY_ACTIVATION_TEST_ROOT": str(root),
        }
        return subprocess.run(
            [
                str(COMMAND),
                command,
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

            first = self.run_env_command("prepare", root, receipt, handoff_path, env_path)
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

            second = self.run_env_command("prepare", root, receipt, handoff_path, env_path)
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
                result = self.run_env_command(
                    "prepare", root, root / "receipt.json", handoff_path,
                    gateway / "gateway.env",
                )
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
            result = self.run_env_command(
                "prepare", root, root / "receipt.json", handoff_path, env_path
            )
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

    def test_local_override_is_the_only_prepare_and_rollback_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            gateway = root / "mcp-gateway"
            gateway.mkdir()
            tracked = gateway / "gateway.env"
            local = gateway / "gateway.local.env"
            tracked.write_text("TRACKED=unchanged\n", encoding="utf-8")
            local.write_text("LOCAL=effective\n", encoding="utf-8")
            tracked_before = tracked.read_bytes()
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
            self.write_json(handoff_path, handoff())

            prepared = self.run_env_command(
                "prepare", root, root / "prepare.json", handoff_path, local
            )
            self.assertEqual(prepared.returncode, 0, prepared.stdout + prepared.stderr)
            prepared_result = json.loads(prepared.stdout)["result"]
            self.assertEqual(
                prepared_result["gateway_env"],
                {"basename": "gateway.local.env", "status": "refs_present"},
            )
            self.assertNotIn("refs", prepared_result)
            self.assertEqual(tracked.read_bytes(), tracked_before)

            rejected = self.run_env_command(
                "prepare", root, root / "wrong.json", handoff_path, tracked
            )
            self.assertEqual(
                json.loads(rejected.stdout)["result"]["code"],
                "gateway_env_path_invalid",
            )

            rolled_back = self.run_env_command(
                "rollback", root, root / "rollback.json", handoff_path, local
            )
            self.assertEqual(
                rolled_back.returncode, 0, rolled_back.stdout + rolled_back.stderr
            )
            rollback_result = json.loads(rolled_back.stdout)["result"]
            self.assertEqual(rollback_result["gateway_env"], {
                "basename": "gateway.local.env",
                "status": "refs_absent",
            })
            for name, _ref in GATEWAY.ENV_ROWS:
                self.assertNotIn(f"{name}=", local.read_text(encoding="utf-8"))
            self.assertEqual(tracked.read_bytes(), tracked_before)

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
                        return (
                            200,
                            b'{"jsonrpc":"2.0","id":2,"result":'
                            b'{"tools":[{"name":"get_service"}]}}',
                        )
                    return 401, b'{"error":"unauthorized"}'
                return 403, b'{"error":"denied"}'
            return 403, b'{"error":"denied"}'

        with tempfile.NamedTemporaryFile() as audit_log, mock.patch.dict(
            os.environ,
            {
                "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                "HERMES_GATEWAY_ACTIVATION_TEST_LOG": audit_log.name,
                "HERMES_GATEWAY_TOKEN": "h" * 32,
                "MCP_GATEWAY_TOKEN": "d" * 32,
            },
            clear=False,
        ), mock.patch.object(
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

    def test_tools_list_probe_accepts_only_filtered_or_audited_fail_closed(self) -> None:
        filtered = (
            200,
            b'{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"get_service"}]}}',
            b"",
        )
        filtered_with_forbidden_text = (
            200,
            b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
            b'{"name":"get_service","description":"does not call trigger_deploy"}]}}',
            b"",
        )
        denied_body = GATEWAY.TOOLS_LIST_DENIAL_BODY

        def audit(
            *,
            route: str = "hermes/render",
            reason: str = "unsupported_content_type",
            outcome: str = "denied",
            extra: dict[str, object] | None = None,
        ) -> bytes:
            event: dict[str, object] = {
                "event": "mcp_gateway_tool_list_filter_denied",
                "route": route,
                "reason": reason,
                "outcome": outcome,
            }
            event.update(extra or {})
            return (
                "2026-07-28T18:00:00.000Z tool list filter denied "
                + json.dumps(event, separators=(",", ":"))
                + "\n"
            ).encode()

        accepted = (filtered, filtered_with_forbidden_text) + tuple(
            (403, denied_body, audit(reason=reason))
            for reason in sorted(GATEWAY.TOOLS_LIST_DENIAL_REASONS)
        )
        rejected = (
            (403, denied_body, b""),
            (403, denied_body, audit(route="hermes/other")),
            (403, denied_body, audit(outcome="allowed")),
            (403, denied_body, audit(reason="future_unreviewed_reason")),
            (
                403,
                denied_body,
                b'2026-07-28T18:00:00.000Z tool list filter denied '
                b'{"event":"mcp_gateway_tool_list_filter_denied",'
                b'"route":"hermes/other","route":"hermes/render",'
                b'"reason":"unsupported_content_type","outcome":"denied"}\n',
            ),
            (403, b' { "error":"upstream tools/list response denied" } ', audit()),
            (
                403,
                b'{"error":"concealed","error":"upstream tools/list response denied"}',
                audit(),
            ),
            (
                403,
                b'{"error":"upstream tools/list response denied","extra":true}',
                audit(),
            ),
            (418, b'{"error":"teapot"}', b""),
            (
                200,
                b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
                b'{"name":"trigger_deploy"}]}}',
                b"",
            ),
            (
                200,
                b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
                b'{"name":"delete_service"}]}}',
                b"",
            ),
            (
                200,
                b'{"jsonrpc":"2.0","id":2,"result":{"tools":[]},'
                b'"error":{"code":-32603}}',
                b"",
            ),
            (
                200,
                b'{"jsonrpc":"2.0","id":2,"result":{"tools":'
                b'[{"name":"trigger\\u005fdeploy"}]},'
                b'"result":{"tools":[{"name":"get_service"}]}}',
                b"",
            ),
            (
                200,
                b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
                b'{"name":"get_service","inputSchema":{"default":NaN}}]}}',
                b"",
            ),
            (
                200,
                b'{"jsonrpc":"2.0","id":2,"result":{"tools":['
                b'{"name":"get_service","inputSchema":{"default":Infinity}}]}}',
                b"",
            ),
        )

        for status, body, audit_bytes in accepted:
            with self.subTest(status=status, accepted=True), tempfile.TemporaryDirectory() as temp:
                log = Path(temp) / "gateway.log"
                log.write_bytes(b"existing log line\n")

                def request(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
                    with log.open("ab") as stream:
                        stream.write(audit_bytes)
                    return status, body

                with mock.patch.dict(os.environ, {
                    "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                    "HERMES_GATEWAY_ACTIVATION_TEST_LOG": str(log),
                }, clear=False), mock.patch.object(
                    GATEWAY, "raw_request", side_effect=request
                ):
                    self.assertEqual(
                        GATEWAY.probe_tools_list(b"h" * 32, (b"h" * 32, b"d" * 32)),
                        body,
                    )

        for status, body, audit_bytes in rejected:
            with self.subTest(status=status, accepted=False), tempfile.TemporaryDirectory() as temp:
                log = Path(temp) / "gateway.log"
                log.write_bytes(b"existing log line\n")

                def request(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
                    with log.open("ab") as stream:
                        stream.write(audit_bytes)
                    return status, body

                with mock.patch.dict(os.environ, {
                    "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                    "HERMES_GATEWAY_ACTIVATION_TEST_LOG": str(log),
                }, clear=False), mock.patch.object(
                    GATEWAY, "raw_request", side_effect=request
                ), self.assertRaisesRegex(GATEWAY.SafeError, "tools_list_filter_failed"):
                    GATEWAY.probe_tools_list(b"h" * 32, (b"h" * 32, b"d" * 32))

        secret = b"h" * 32
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "gateway.log"
            log.write_bytes(b"")

            def secret_request(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
                with log.open("ab") as stream:
                    stream.write(audit(extra={"detail": secret.decode()}))
                return 403, denied_body

            with mock.patch.dict(os.environ, {
                "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                "HERMES_GATEWAY_ACTIVATION_TEST_LOG": str(log),
            }, clear=False), mock.patch.object(
                GATEWAY, "raw_request", side_effect=secret_request
            ), self.assertRaisesRegex(GATEWAY.SafeError, "secret_leak_detected"):
                GATEWAY.probe_tools_list(secret, (secret, b"d" * 32))

    def test_tools_list_probe_bounds_the_audit_log_append(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            log = Path(temp) / "gateway.log"
            log.write_bytes(b"")

            def request(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
                with log.open("ab") as stream:
                    stream.write(b"x" * (GATEWAY.MAX_AUDIT_LOG_BYTES + 1))
                return 403, GATEWAY.TOOLS_LIST_DENIAL_BODY

            with mock.patch.dict(os.environ, {
                "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                "HERMES_GATEWAY_ACTIVATION_TEST_LOG": str(log),
            }, clear=False), mock.patch.object(
                GATEWAY, "raw_request", side_effect=request
            ), self.assertRaisesRegex(GATEWAY.SafeError, "gateway_audit_log_too_large"):
                GATEWAY.probe_tools_list(b"h" * 32, (b"h" * 32, b"d" * 32))

    def test_filtered_tools_list_does_not_require_audit_log_proof(self) -> None:
        body = (
            b'{"jsonrpc":"2.0","id":2,"result":'
            b'{"tools":[{"name":"get_service"}]}}'
        )
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing.log"
            with mock.patch.dict(os.environ, {
                "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                "HERMES_GATEWAY_ACTIVATION_TEST_LOG": str(missing),
            }, clear=False), mock.patch.object(
                GATEWAY, "raw_request", return_value=(200, body)
            ):
                self.assertEqual(
                    GATEWAY.probe_tools_list(b"h" * 32, (b"h" * 32, b"d" * 32)),
                    body,
                )

            noisy = Path(temp) / "noisy.log"
            noisy.write_bytes(b"")

            def noisy_request(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
                with noisy.open("ab") as stream:
                    stream.write(b"x" * (GATEWAY.MAX_AUDIT_LOG_BYTES + 1))
                return 200, body

            with mock.patch.dict(os.environ, {
                "HERMES_GATEWAY_ACTIVATION_TEST_MODE": "1",
                "HERMES_GATEWAY_ACTIVATION_TEST_LOG": str(noisy),
            }, clear=False), mock.patch.object(
                GATEWAY, "raw_request", side_effect=noisy_request
            ):
                self.assertEqual(
                    GATEWAY.probe_tools_list(b"h" * 32, (b"h" * 32, b"d" * 32)),
                    body,
                )

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

    def test_prepare_canary_denies_merged_does_not_deny_in_progress_and_reads_back_safe_state(
        self,
    ) -> None:
        state = GATEWAY.State(
            GATEWAY.STATE_SCHEMA,
            "policy-run",
            GATEWAY.CANARY_PREFIX + "policy-run",
            None,
            "prepare",
            1.0,
            301.0,
            list(GATEWAY.CHECKS[:6]),
            0,
            0,
            None,
        )
        calls: list[tuple[str, dict[str, object]]] = []
        ticket = {
            "id": "F0001",
            "repo": state.repo,
            "origin": "hermes",
            "status": "backlog",
            "execution_approved_at": None,
            "execution_approved_by": None,
        }

        class Client:
            def tool(
                self, name: str, arguments: dict[str, object]
            ) -> dict[str, object]:
                calls.append((name, arguments))
                if name == "create_ticket":
                    return {"ticket_id": "F0001"}
                if name == "get_ticket":
                    return {"ticket": dict(ticket)}
                if name == "update_ticket" and arguments.get("status") == "merged":
                    return {"error": GATEWAY.MERGED_STATUS_DENIAL}
                if name == "update_ticket" and arguments.get("approve_execution") is True:
                    return {"error": "Execution approval requires the admin principal"}
                if name == "update_ticket" and arguments.get("repo") != state.repo:
                    return {
                        "error": (
                            "This principal may mutate only tickets created by the same origin"
                        )
                    }
                if name == "create_artifact":
                    return {"artifact_id": "artifact-plan"}
                if name == "update_ticket" and arguments.get("status") == "planned":
                    ticket["status"] = "planned"
                    return {"status": "updated"}
                if name == "next_ticket":
                    return {"ticket": None}
                raise AssertionError((name, arguments))

        with tempfile.TemporaryDirectory() as temp, mock.patch.object(
            GATEWAY, "probe_gateway"
        ), mock.patch.object(
            GATEWAY, "memory_client", return_value=Client()
        ), mock.patch.object(
            GATEWAY.time, "time", return_value=2.0
        ):
            GATEWAY.prepare_canary(state, Path(temp) / "receipt.json")

        status_updates = [
            arguments["status"]
            for name, arguments in calls
            if name == "update_ticket" and "status" in arguments
        ]
        self.assertEqual(status_updates, ["merged", "planned"])
        self.assertNotIn("in_progress", status_updates)
        merged_index = next(
            index
            for index, (name, arguments) in enumerate(calls)
            if name == "update_ticket" and arguments.get("status") == "merged"
        )
        self.assertEqual(calls[merged_index + 1][0], "get_ticket")
        self.assertEqual(state.checks, list(GATEWAY.CHECKS[:10]))
        self.assertEqual(state.phase, "awaiting_admin_approval")

    def test_exact_merged_denial_rejects_wrong_envelopes_and_messages(self) -> None:
        invalid = (
            {},
            {"status": "updated"},
            {"error": GATEWAY.MERGED_STATUS_DENIAL, "code": "ticket_status_denied"},
            {"error": "Execution approval requires the admin principal"},
        )
        for result in invalid:
            with self.subTest(result=result), self.assertRaisesRegex(
                GATEWAY.SafeError, "canary_execution_denial_missing"
            ):
                GATEWAY.expect_exact_denial(
                    result,
                    GATEWAY.MERGED_STATUS_DENIAL,
                    "canary_execution_denial_missing",
                )

    def test_post_merged_denial_readback_rejects_changed_or_approved_ticket(self) -> None:
        state = GATEWAY.State(
            GATEWAY.STATE_SCHEMA,
            "readback-run",
            GATEWAY.CANARY_PREFIX + "readback-run",
            "F0001",
            "prepare",
            1.0,
            301.0,
            list(GATEWAY.CHECKS[:7]),
            0,
            0,
            None,
        )
        base = {
            "id": state.ticket_id,
            "repo": state.repo,
            "origin": "hermes",
            "status": "backlog",
            "execution_approved_at": None,
            "execution_approved_by": None,
        }
        unsafe = (
            {**base, "status": "in_progress"},
            {
                **base,
                "execution_approved_at": "2026-07-29T00:00:00Z",
                "execution_approved_by": "admin",
            },
        )
        for ticket in unsafe:
            client = mock.MagicMock()
            client.tool.return_value = {"ticket": ticket}
            with self.subTest(ticket=ticket), mock.patch.object(
                GATEWAY.time, "time", return_value=2.0
            ), self.assertRaisesRegex(
                GATEWAY.SafeError, "canary_ticket_state_mismatch"
            ):
                GATEWAY.get_ticket(
                    client, state, status="backlog", approved=False
                )

    def test_closed_matrix_includes_server_approval_pickup_and_cleanup(self) -> None:
        self.assertEqual(len(GATEWAY.CHECKS), len(set(GATEWAY.CHECKS)))
        self.assertEqual(GATEWAY.CHECKS, (
            "gateway_health_routes",
            "render_mutations_denied_zero_dispatch",
            "token_cross_routes_rejected",
            "jsonrpc_batch_and_rest_bypass_rejected",
            "tools_list_filtered_fail_closed",
            "secret_free_audit",
            "origin_status_source_identity",
            "self_approval_and_execution_status_denied",
            "cross_ticket_write_denied",
            "unapproved_pickup_empty",
            "admin_approval_observed",
            "owner_edit_clears_approval",
            "cleared_approval_pickup_empty",
            "admin_reapproval_observed",
            "scoped_pickup_exact",
            "terminal_cleanup",
        ))
        self.assertEqual(len(GATEWAY.CHECKS), 16)

    def test_tools_list_denial_reasons_match_gateway_emissions(self) -> None:
        proxy = (ROOT / "mcp-gateway" / "lib" / "proxy.mjs").read_text(encoding="utf-8")
        tool_filter = (
            ROOT / "mcp-gateway" / "lib" / "tool-filter.mjs"
        ).read_text(encoding="utf-8")
        emitted = set(re.findall(r'denyResponse\("([^"]+)"', proxy))
        emitted.update(re.findall(r'error\.reason \|\| "([^"]+)"', proxy))
        emitted.update(re.findall(r'ToolFilterError\("([^"]+)"', tool_filter))
        self.assertEqual(emitted, set(GATEWAY.TOOLS_LIST_DENIAL_REASONS))


if __name__ == "__main__":
    unittest.main()

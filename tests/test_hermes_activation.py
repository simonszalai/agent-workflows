from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
COMMAND = ROOT / "bin" / "hermes-activation"
LOADER = importlib.machinery.SourceFileLoader("hermes_activation", str(COMMAND))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
if SPEC is None:
    raise RuntimeError("cannot load hermes-activation")
HERMES = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = HERMES
LOADER.exec_module(HERMES)


class FakeOp:
    def __init__(self, inventory: list[object], created: dict[str, object] | None = None) -> None:
        self.inventory = inventory
        self.created = created
        self.json_calls: list[list[str]] = []
        self.read_calls: list[str] = []
        self.values = {
            HERMES.MEMORY_REF: b"m" * 40,
            HERMES.GATEWAY_REF: b"g" * 40,
            HERMES.RENDER_REF: b"r" * 40,
        }

    def json(self, arguments: list[str]) -> object:
        self.json_calls.append(arguments)
        if arguments[:2] == ["item", "list"]:
            return self.inventory
        if self.created is None:
            raise HERMES.SafeError("op_contract_mismatch")
        return self.created

    def read(self, reference: str) -> bytes:
        self.read_calls.append(reference)
        return self.values[reference]


def item_row(name: str, item_id: str) -> dict[str, object]:
    return {
        "id": item_id,
        "title": name,
        "category": "PASSWORD",
        "vault": {"name": HERMES.VAULT},
    }


class HermesContractTest(unittest.TestCase):
    def test_contract_and_fixed_inventory_are_frozen(self) -> None:
        self.assertEqual(HERMES.CONTRACT, "e0006-m3/v1")
        self.assertEqual(HERMES.OUTPUT_SCHEMA, "e0006-m3/v1")
        self.assertEqual(
            [item.name for item in HERMES.ITEMS],
            ["HERMES_AUTODEV_MEMORY_TOKEN", "HERMES_GATEWAY_TOKEN"],
        )
        self.assertEqual(HERMES.RENDER_SERVICE, "srv-d70oq214tr6s73ch3dbg")
        self.assertEqual(HERMES.RENDER_KEY, "AUTODEV_MEMORY_RESTRICTED_TOKENS")

    def test_parser_has_only_reviewed_command_family(self) -> None:
        parser = HERMES.parser()
        accepted = (
            ["items", "ensure"],
            ["memory", "apply", "--mode", "active"],
            ["render", "wait", "--deploy-id", "dep-123", "--timeout-receipt", "/tmp/r"],
            [
                "render",
                "cancel",
                "--deploy-id",
                "dep-123",
                "--timeout-receipt",
                "/tmp/t",
                "--canceled-receipt",
                "/tmp/c",
            ],
            ["memory", "canary", "--phase", "cleanup", "--state-receipt", "/tmp/s"],
        )
        for arguments in accepted:
            with self.subTest(arguments=arguments):
                parser.parse_args(arguments)
        with self.assertRaises(SystemExit):
            parser.parse_args(["memory", "apply", "--mode", "active", "--url", "https://x"])
        with self.assertRaises(SystemExit):
            parser.parse_args(["items", "ensure", "--vault", "other"])

    def test_result_allowlist_rejects_unknown_and_secret_fields(self) -> None:
        with self.assertRaises(HERMES.SafeError):
            HERMES.success_result("memory apply", {"value": "not-allowed"})
        with self.assertRaises(HERMES.SafeError):
            HERMES.success_result(
                "memory apply",
                {
                    "mode": "active",
                    "service": HERMES.RENDER_SERVICE,
                    "key": HERMES.RENDER_KEY,
                    "deploy_id": "dep-123",
                    "extra": "no",
                },
            )

    def test_receipt_write_is_atomic_and_private(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            value = HERMES.success_result(
                "render wait",
                {
                    "service": HERMES.RENDER_SERVICE,
                    "deploy_id": "dep-123",
                    "state": "live",
                    "resume_command": None,
                },
            )
            HERMES.atomic_write_json(receipt, value)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertEqual(HERMES.validate_envelope(json.loads(receipt.read_text())), value)
            self.assertEqual(list(Path(directory).glob(".receipt.json.*")), [])

    def test_receipt_loader_rejects_symlink_and_open_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "target"
            target.write_text("{}")
            target.chmod(0o600)
            link = root / "link"
            link.symlink_to(target)
            with self.assertRaises(HERMES.SafeError):
                HERMES.load_json_receipt(link)
            target.chmod(0o644)
            with self.assertRaises(HERMES.SafeError):
                HERMES.load_json_receipt(target)


class HermesItemEnsureTest(unittest.TestCase):
    def test_two_existing_items_are_ordered_and_not_created(self) -> None:
        fake = FakeOp(
            [
                item_row(HERMES.GATEWAY_ITEM, "item-gateway"),
                item_row(HERMES.MEMORY_ITEM, "item-memory"),
            ]
        )
        result = HERMES.ensure_items(fake)
        self.assertEqual([item.name for item in result], [HERMES.MEMORY_ITEM, HERMES.GATEWAY_ITEM])
        self.assertEqual([item.state for item in result], ["existing", "existing"])
        self.assertEqual(fake.read_calls, [HERMES.MEMORY_REF, HERMES.GATEWAY_REF])
        self.assertEqual(len(fake.json_calls), 1)

    def test_missing_item_uses_exact_generator_argv_without_assignment(self) -> None:
        created = {
            "id": "item-memory",
            "title": HERMES.MEMORY_ITEM,
            "category": "PASSWORD",
            "vault": {"name": HERMES.VAULT},
            "fields": [{"id": "password", "purpose": "PASSWORD"}],
        }
        fake = FakeOp([item_row(HERMES.GATEWAY_ITEM, "item-gateway")], created)
        result = HERMES.ensure_items(fake)
        create = fake.json_calls[1]
        self.assertEqual(result[0].state, "created")
        self.assertIn("--generate-password", create)
        self.assertEqual([argument for argument in create if "=" in argument], ["--format=json"])
        self.assertNotIn("value", create)

    def test_ambiguous_or_reused_identity_fails_closed(self) -> None:
        duplicate = FakeOp(
            [
                item_row(HERMES.MEMORY_ITEM, "item-one"),
                item_row(HERMES.MEMORY_ITEM, "item-two"),
            ]
        )
        with self.assertRaisesRegex(HERMES.SafeError, "op_item_ambiguous"):
            HERMES.ensure_items(duplicate)
        reused = FakeOp(
            [
                item_row(HERMES.MEMORY_ITEM, "item-same"),
                item_row(HERMES.GATEWAY_ITEM, "item-same"),
            ]
        )
        with self.assertRaisesRegex(HERMES.SafeError, "op_item_id_reused"):
            HERMES.ensure_items(reused)

    def test_equal_values_fail_without_derived_output(self) -> None:
        fake = FakeOp(
            [
                item_row(HERMES.MEMORY_ITEM, "item-memory"),
                item_row(HERMES.GATEWAY_ITEM, "item-gateway"),
            ]
        )
        fake.values[HERMES.GATEWAY_REF] = fake.values[HERMES.MEMORY_REF]
        with self.assertRaisesRegex(HERMES.SafeError, "op_values_reused"):
            HERMES.ensure_items(fake)

    def test_created_second_item_read_failure_preserves_both_safe_receipts(self) -> None:
        created = {
            "id": "item-gateway",
            "title": HERMES.GATEWAY_ITEM,
            "category": "PASSWORD",
            "vault": {"name": HERMES.VAULT},
            "fields": [{"id": "password", "purpose": "PASSWORD"}],
        }
        fake = FakeOp([item_row(HERMES.MEMORY_ITEM, "item-memory")], created)

        def fail_gateway(reference: str) -> bytes:
            if reference == HERMES.GATEWAY_REF:
                raise HERMES.SafeError("read_failed", exit_code=4)
            return b"m" * 40

        fake.read = fail_gateway
        with self.assertRaises(HERMES.SafeError) as caught:
            HERMES.ensure_items(fake)
        self.assertEqual(caught.exception.code, "partial_item_ensure")
        self.assertEqual(
            [item["name"] for item in caught.exception.safe_result["items"]],
            [HERMES.MEMORY_ITEM, HERMES.GATEWAY_ITEM],
        )

    def test_created_first_item_second_existing_read_failure_preserves_boundary(self) -> None:
        created = {
            "id": "item-memory",
            "title": HERMES.MEMORY_ITEM,
            "category": "PASSWORD",
            "vault": {"name": HERMES.VAULT},
            "fields": [{"id": "password", "purpose": "PASSWORD"}],
        }
        fake = FakeOp([item_row(HERMES.GATEWAY_ITEM, "item-gateway")], created)

        def fail_gateway(reference: str) -> bytes:
            if reference == HERMES.GATEWAY_REF:
                raise HERMES.SafeError("read_failed", exit_code=4)
            return b"m" * 40

        fake.read = fail_gateway
        with self.assertRaises(HERMES.SafeError) as caught:
            HERMES.ensure_items(fake)
        self.assertEqual(caught.exception.code, "partial_item_ensure")
        self.assertEqual(len(caught.exception.safe_result["items"]), 2)


class HermesOpClientBoundTest(unittest.TestCase):
    def _script(self, root: Path, body: str) -> Path:
        executable = root / "fake-op"
        executable.write_text("#!/usr/bin/env python3\n" + body)
        executable.chmod(0o755)
        return executable

    def test_combined_output_cap_bounds_stdout_and_stderr(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                body = (
                    "import sys\n"
                    f"sys.{stream}.buffer.write(b'x' * ({HERMES.MAX_CHILD_BYTES} + 1))\n"
                    f"sys.{stream}.flush()\n"
                )
                client = HERMES.OpClient(str(self._script(root, body)), timeout=2)
                with self.assertRaisesRegex(HERMES.SafeError, "op_response_too_large"):
                    client._run(["item", "list", "--format=json"])

    def test_timeout_while_child_is_writing_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            body = (
                "import sys, time\n"
                "while True:\n"
                "    sys.stderr.buffer.write(b'x' * 1024)\n"
                "    sys.stderr.flush()\n"
                "    time.sleep(0.01)\n"
            )
            client = HERMES.OpClient(str(self._script(root, body)), timeout=0.05)
            with self.assertRaises(HERMES.SafeError) as caught:
                client._run(["item", "list", "--format=json"])
            self.assertIn(caught.exception.code, {"op_timeout", "op_response_too_large"})


class FakeRenderHttp:
    def __init__(self, secret: str, statuses: list[str] | None = None) -> None:
        self.secret = secret
        self.statuses = statuses or []
        self.calls: list[tuple[str, str]] = []

    def request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        accepted: set[int],
    ) -> object:
        self.calls.append((method, path))
        if method == "PUT":
            payload = body
            if not isinstance(payload, dict):
                raise AssertionError("missing body")
            value = payload["value"]
            if value != "[]":
                decoded = json.loads(value)
                self._assert_policy(decoded)
            return HERMES.HttpResponse(
                200,
                {"key": HERMES.RENDER_KEY, "value": value},
            )
        if method == "POST" and path.endswith("/deploys"):
            self.assert_trigger(body)
            return HERMES.HttpResponse(
                201,
                {"id": "dep-safe-123", "status": "created", "trigger": "api"},
            )
        if method == "POST" and path.endswith("/cancel"):
            return HERMES.HttpResponse(
                200,
                {"id": "dep-safe-123", "status": "update_in_progress"},
            )
        if method == "GET":
            state = self.statuses.pop(0)
            return HERMES.HttpResponse(200, {"id": path.rsplit("/", 1)[-1], "status": state})
        raise AssertionError((method, path, accepted))

    def _assert_policy(self, value: object) -> None:
        if not isinstance(value, list) or len(value) != 1:
            raise AssertionError("policy shape")
        policy = value[0]
        if not isinstance(policy, dict):
            raise AssertionError("policy row")
        self.assert_equal(policy["token"], self.secret)
        expected = {
            "project": "autodev",
            "origin": "hermes",
            "knowledge": "read",
            "tickets": "rw",
            "epics": "none",
            "config": "read",
            "approvals": "none",
        }
        for key, expected_value in expected.items():
            self.assert_equal(policy[key], expected_value)

    @staticmethod
    def assert_equal(left: object, right: object) -> None:
        if left != right:
            raise AssertionError((left, right))

    @staticmethod
    def assert_trigger(body: object) -> None:
        if body != {"clearCache": "do_not_clear"}:
            raise AssertionError(body)


class HermesMemoryApplyTest(unittest.TestCase):
    def test_active_writes_exact_key_then_triggers_once(self) -> None:
        secret = "runtime-" + "x" * 36
        fake = FakeRenderHttp(secret)
        client = HERMES.RenderClient(fake)
        result = client.apply("active", secret.encode())
        self.assertEqual(result.deploy_id, "dep-safe-123")
        self.assertEqual(
            fake.calls,
            [
                (
                    "PUT",
                    f"/v1/services/{HERMES.RENDER_SERVICE}/env-vars/{HERMES.RENDER_KEY}",
                ),
                ("POST", f"/v1/services/{HERMES.RENDER_SERVICE}/deploys"),
            ],
        )
        self.assertNotIn(secret, repr(fake.calls))

    def test_inert_is_literal_empty_list(self) -> None:
        fake = FakeRenderHttp("unused")
        client = HERMES.RenderClient(fake)
        result = client.apply("inert", None)
        self.assertEqual(result.mode, "inert")
        self.assertEqual(len(fake.calls), 2)

    def test_trigger_failure_reports_partial_boundary(self) -> None:
        fake = FakeRenderHttp("unused")

        def fail_trigger(
            method: str,
            path: str,
            body: object | None = None,
            *,
            accepted: set[int],
        ) -> object:
            if method == "PUT":
                return HERMES.HttpResponse(
                    200,
                    {"key": HERMES.RENDER_KEY, "value": "[]"},
                )
            raise HERMES.SafeError("external_http_failure", exit_code=4)

        fake.request = fail_trigger
        with self.assertRaises(HERMES.SafeError) as caught:
            HERMES.RenderClient(fake).apply("inert", None)
        self.assertEqual(caught.exception.code, "deploy_trigger_unknown_after_env_write")
        self.assertEqual(caught.exception.exit_code, HERMES.EXIT_UNKNOWN)
        self.assertEqual(caught.exception.safe_result["state"], "unknown")

    def test_render_responses_reject_missing_mismatched_and_extra_fields(self) -> None:
        fake = FakeRenderHttp("unused")
        variants = (
            {},
            {"key": "OTHER", "value": "[]"},
            {"key": HERMES.RENDER_KEY, "value": "[]", "extra": True},
        )
        for response_body in variants:
            with self.subTest(response_body=response_body):
                fake.request = mock.Mock(
                    return_value=HERMES.HttpResponse(200, response_body)
                )
                with self.assertRaises(HERMES.SafeError):
                    HERMES.RenderClient(fake).apply("inert", None)

    def test_trigger_acceptance_without_exact_id_is_unknown_and_not_retried(self) -> None:
        fake = FakeRenderHttp("unused")
        fake.request = mock.Mock(
            side_effect=[
                HERMES.HttpResponse(
                    200,
                    {"key": HERMES.RENDER_KEY, "value": "[]"},
                ),
                HERMES.HttpResponse(202, {}),
            ]
        )
        with self.assertRaises(HERMES.SafeError) as caught:
            HERMES.RenderClient(fake).apply("inert", None)
        self.assertEqual(caught.exception.exit_code, HERMES.EXIT_UNKNOWN)
        self.assertEqual(fake.request.call_count, 2)

    def test_deploy_contract_rejects_unknown_or_mismatched_identity(self) -> None:
        variants = (
            {},
            {"id": "dep-safe-123", "extra": True},
            {"id": "dep-other", "status": "created"},
            {"id": "dep-safe-123", "status": "invented"},
        )
        for value in variants:
            with self.subTest(value=value), self.assertRaises(HERMES.SafeError):
                HERMES.validate_render_deploy(
                    value,
                    deploy_id="dep-safe-123",
                    require_status=True,
                )


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class HermesRenderWaitCancelTest(unittest.TestCase):
    def test_documented_status_inventory_is_exact(self) -> None:
        self.assertEqual(
            HERMES.ALL_DEPLOY_STATES,
            {
                "created",
                "queued",
                "build_in_progress",
                "pre_deploy_in_progress",
                "update_in_progress",
                "live",
                "deactivated",
                "build_failed",
                "pre_deploy_failed",
                "update_failed",
                "canceled",
            },
        )

    def test_wait_reaches_live_without_mutation(self) -> None:
        fake = FakeRenderHttp("unused", ["created", "build_in_progress", "live"])
        clock = FakeClock()
        client = HERMES.RenderClient(
            fake,
            clock=clock,
            sleeper=clock.sleep,
            poll_seconds=1,
            wait_seconds=10,
        )
        with tempfile.TemporaryDirectory() as directory:
            state = client.wait("dep-safe-123", Path(directory) / "timeout")
        self.assertEqual(state, "live")
        self.assertTrue(all(method == "GET" for method, _path in fake.calls))

    def test_timeout_is_unknown_and_writes_private_exact_id_receipt(self) -> None:
        fake = FakeRenderHttp("unused", ["queued"] * 4)
        clock = FakeClock()
        client = HERMES.RenderClient(
            fake,
            clock=clock,
            sleeper=clock.sleep,
            poll_seconds=1,
            wait_seconds=2,
        )
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "timeout"
            with self.assertRaisesRegex(HERMES.SafeError, "render_wait_timeout") as caught:
                client.wait("dep-safe-123", receipt)
            self.assertEqual(caught.exception.exit_code, 5)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            stored = json.loads(receipt.read_text())
            self.assertEqual(stored["deploy_id"], "dep-safe-123")
            self.assertEqual(stored["state"], "unknown")

    def test_cancel_requires_matching_receipt_and_proves_canceled(self) -> None:
        fake = FakeRenderHttp("unused", ["queued", "update_in_progress", "canceled"])
        clock = FakeClock()
        client = HERMES.RenderClient(
            fake,
            clock=clock,
            sleeper=clock.sleep,
            poll_seconds=1,
            wait_seconds=10,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeout = root / "timeout"
            canceled = root / "canceled"
            HERMES.atomic_write_json(
                timeout,
                {
                    "schema": HERMES.TIMEOUT_RECEIPT_SCHEMA,
                    "service": HERMES.RENDER_SERVICE,
                    "deploy_id": "dep-safe-123",
                    "state": "unknown",
                    "started_at": 0.0,
                    "deadline_at": 1.0,
                },
            )
            self.assertEqual(
                client.cancel("dep-safe-123", timeout, canceled),
                "canceled",
            )
            self.assertEqual(json.loads(canceled.read_text())["state"], "canceled")
        self.assertFalse(any(method == "PUT" for method, _path in fake.calls))

    def test_cancel_resume_never_replays_post_and_accepts_already_canceled(self) -> None:
        fake = FakeRenderHttp("unused", ["canceled"])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeout = root / "timeout"
            canceled = root / "canceled"
            HERMES.atomic_write_json(
                timeout,
                {
                    "schema": HERMES.TIMEOUT_RECEIPT_SCHEMA,
                    "service": HERMES.RENDER_SERVICE,
                    "deploy_id": "dep-safe-123",
                    "state": "unknown",
                    "started_at": 1.0,
                    "deadline_at": 2.0,
                },
            )
            HERMES.atomic_write_json(
                canceled,
                {
                    "schema": HERMES.CANCELED_RECEIPT_SCHEMA,
                    "service": HERMES.RENDER_SERVICE,
                    "deploy_id": "dep-safe-123",
                    "state": "cancel_requested",
                },
            )
            state = HERMES.RenderClient(fake).cancel(
                "dep-safe-123",
                timeout,
                canceled,
            )
            self.assertEqual(state, "canceled")
            self.assertEqual(json.loads(canceled.read_text())["state"], "canceled")
        self.assertFalse(any(method == "POST" for method, _path in fake.calls))

    def test_cancel_response_drift_leaves_recoverable_requested_receipt(self) -> None:
        fake = FakeRenderHttp("unused", ["queued"])

        def request(
            method: str,
            path: str,
            body: object | None = None,
            *,
            accepted: set[int],
        ) -> object:
            if method == "GET":
                return HERMES.HttpResponse(
                    200,
                    {"id": "dep-safe-123", "status": "queued"},
                )
            return HERMES.HttpResponse(200, {"id": "wrong-deploy"})

        fake.request = request
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            timeout = root / "timeout"
            canceled = root / "canceled"
            HERMES.atomic_write_json(
                timeout,
                {
                    "schema": HERMES.TIMEOUT_RECEIPT_SCHEMA,
                    "service": HERMES.RENDER_SERVICE,
                    "deploy_id": "dep-safe-123",
                    "state": "unknown",
                    "started_at": 1.0,
                    "deadline_at": 2.0,
                },
            )
            with self.assertRaises(HERMES.SafeError) as caught:
                HERMES.RenderClient(fake).cancel(
                    "dep-safe-123",
                    timeout,
                    canceled,
                )
            self.assertEqual(caught.exception.code, "cancel_unknown")
            self.assertEqual(json.loads(canceled.read_text())["state"], "cancel_requested")


class StatefulFakeMemory:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.repo = HERMES.CANARY_REPO_PREFIX + run_id
        self.ticket_id = "F9001"
        self.ticket: dict[str, object] | None = None
        self.artifacts: list[dict[str, object]] = []
        self.human_tags = {"area": "security-operations"}
        self.calls: list[tuple[str, object]] = []

    def seed_ticket(self) -> None:
        self.ticket = {
            "id": self.ticket_id,
            "project": HERMES.PROJECT,
            "repo": self.repo,
            "title": HERMES.CANARY_TITLE_PREFIX + self.run_id,
            "type": "feature",
            "status": "backlog",
            "origin": "hermes",
            "tags": {"canary": HERMES.CANARY_TAG, "run_id": self.run_id},
            "execution_approved_at": None,
            "execution_approved_by": None,
        }
        self.artifacts = [{"id": "artifact-source", "artifact_type": "source"}]

    def approve(self) -> None:
        if self.ticket is None:
            raise AssertionError("missing ticket")
        self.ticket["execution_approved_at"] = "2026-07-25T12:00:00+00:00"
        self.ticket["execution_approved_by"] = "admin"

    def _context(self) -> dict[str, object]:
        if self.ticket is None:
            raise AssertionError("missing ticket")
        return {
            "ticket": dict(self.ticket),
            "artifacts": [dict(item) for item in self.artifacts],
            "open_comment_count": 0,
            "context_version": "sha256:fake",
            "detail": "light",
        }

    def tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
        self.calls.append((name, json.loads(json.dumps(arguments))))
        if name == "create_ticket":
            if set(arguments) != {
                "project",
                "repo",
                "title",
                "type",
                "description",
                "status",
                "summary_bullets",
                "tags",
                "command",
                "agent",
            }:
                raise AssertionError(("create_ticket schema", arguments))
            self.seed_ticket()
            return {
                "status": "created",
                "ticket_id": self.ticket_id,
                "slug": "bounded-canary",
            }
        if name == "list_tickets":
            if set(arguments) != {"project", "repo", "limit"}:
                raise AssertionError(("list_tickets schema", arguments))
            tickets = [] if self.ticket is None else [dict(self.ticket)]
            return {"tickets": tickets, "count": len(tickets)}
        if name == "get_ticket":
            if set(arguments) != {
                "project",
                "repo",
                "ticket_id",
                "detail",
                "include_events",
            }:
                raise AssertionError(("get_ticket schema", arguments))
            if arguments["repo"] == HERMES.HUMAN_TICKET_REPO:
                return {
                    "ticket": {
                        "id": HERMES.HUMAN_TICKET_ID,
                        "project": HERMES.PROJECT,
                        "repo": HERMES.HUMAN_TICKET_REPO,
                        "origin": "admin",
                        "tags": dict(self.human_tags),
                    },
                    "artifacts": [],
                    "open_comment_count": 0,
                    "context_version": "sha256:human",
                    "detail": "light",
                }
            return self._context()
        if name == "update_ticket":
            common = {"project", "repo", "ticket_id", "command", "agent"}
            variants = (
                common | {"status"},
                common | {"tags"},
                common | {"approve_execution"},
                common | {"summary_bullets"},
            )
            if set(arguments) not in variants:
                raise AssertionError(("update_ticket schema", arguments))
            if arguments["repo"] == HERMES.HUMAN_TICKET_REPO:
                return {
                    "error": "This principal may mutate only tickets created by the same origin"
                }
            if arguments.get("approve_execution") is True:
                return {"error": "Execution approval requires the admin principal"}
            if arguments.get("status") == "merged":
                return {
                    "error": "Restricted principals cannot set status 'merged' during planning"
                }
            if self.ticket is None:
                raise AssertionError("missing ticket")
            if arguments.get("status") == "abandoned":
                self.ticket["status"] = "abandoned"
            if "summary_bullets" in arguments:
                self.ticket["summary_bullets"] = list(arguments["summary_bullets"])
            self.ticket["execution_approved_at"] = None
            self.ticket["execution_approved_by"] = None
            return {
                "status": "updated",
                "ticket_id": self.ticket_id,
                "ticket": dict(self.ticket),
            }
        if name == "next_ticket":
            if set(arguments) != {"project", "repo"}:
                raise AssertionError(("next_ticket schema", arguments))
            if (
                self.ticket is not None
                and self.ticket["status"] == "planned"
                and self.ticket["execution_approved_at"] is not None
            ):
                return self._context()
            return {"ticket": None, "message": "No planned or backlog tickets found"}
        raise AssertionError((name, arguments))

    def batch(
        self,
        project: str,
        operations: list[dict[str, object]],
        *,
        mode: str,
    ) -> dict[str, object]:
        if project != HERMES.PROJECT or mode != "atomic" or len(operations) != 1:
            raise AssertionError(("batch schema", project, mode, operations))
        self.calls.append(
            (
                "batch",
                {
                    "project": project,
                    "mode": mode,
                    "operations": json.loads(json.dumps(operations)),
                },
            )
        )
        operation = operations[0]
        if frozenset(operation) not in {
            frozenset({"operation_id", "idempotency_key", "repo", "ticket_id", "ticket_update"}),
            frozenset(
                {
                    "operation_id",
                    "idempotency_key",
                    "repo",
                    "ticket_id",
                    "artifact",
                    "ticket_update",
                }
            ),
        }:
            raise AssertionError(("batch operation schema", operation))
        update = operation.get("ticket_update")
        if update == {"status": "merged"}:
            return {
                "mode": "atomic",
                "committed": False,
                "complete": False,
                "results": [
                    {
                        "operation_id": operation["operation_id"],
                        "ticket_id": self.ticket_id,
                        "repo": self.repo,
                        "status": "failed",
                        "error_type": "TicketPolicyError",
                        "code": "ticket_status_denied",
                        "detail": (
                            "Restricted principals cannot set status 'merged' during planning"
                        ),
                    }
                ],
            }
        if self.ticket is None:
            raise AssertionError("missing ticket")
        self.ticket["status"] = "planned"
        self.artifacts.append({"id": "artifact-plan", "artifact_type": "plan"})
        return {
            "mode": "atomic",
            "committed": True,
            "complete": True,
            "results": [
                {
                    "operation_id": operation["operation_id"],
                    "ticket_id": self.ticket_id,
                    "repo": self.repo,
                    "status": "applied",
                    "artifact_id": "artifact-plan",
                    "ticket_status": "planned",
                }
            ],
        }


class StatefulFakeMemoryHttp:
    def __init__(self, service: StatefulFakeMemory) -> None:
        self.service = service
        self.calls: list[tuple[str, str, object]] = []

    def request(
        self,
        method: str,
        path: str,
        body: object | None = None,
        *,
        accepted: set[int],
    ) -> object:
        self.calls.append((method, path, json.loads(json.dumps(body))))
        if method != "POST" or accepted != {200} or not isinstance(body, dict):
            raise AssertionError(("memory transport", method, path, body, accepted))
        if path == HERMES.MCP_PATH:
            if set(body) != {"jsonrpc", "id", "method", "params"}:
                raise AssertionError(("MCP envelope", body))
            if body["jsonrpc"] != "2.0" or body["method"] != "tools/call":
                raise AssertionError(("MCP request", body))
            params = body["params"]
            if not isinstance(params, dict) or set(params) != {"name", "arguments"}:
                raise AssertionError(("MCP params", params))
            result = self.service.tool(params["name"], params["arguments"])
            return HERMES.HttpResponse(
                200,
                {
                    "jsonrpc": "2.0",
                    "id": body["id"],
                    "result": {
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(result, separators=(",", ":")),
                            }
                        ],
                        "isError": False,
                    },
                },
            )
        if path == HERMES.BATCH_PATH:
            if set(body) != {"project", "mode", "operations"}:
                raise AssertionError(("REST batch body", body))
            return HERMES.HttpResponse(
                200,
                self.service.batch(
                    body["project"],
                    body["operations"],
                    mode=body["mode"],
                ),
            )
        raise AssertionError(("memory path", path))


class HermesMemoryCanaryTest(unittest.TestCase):
    def _initial_state(self, run_id: str) -> HERMES.CanaryState:
        started = time.time()
        return HERMES.CanaryState(
            schema=HERMES.CANARY_RECEIPT_SCHEMA,
            run_id=run_id,
            repo=HERMES.CANARY_REPO_PREFIX + run_id,
            ticket_id=None,
            phase="prepare",
            started_at=started,
            deadline_at=started + HERMES.CANARY_SECONDS,
            checks=[],
            cleanup=None,
            requests=0,
            mutations=0,
            embedding_writes=0,
            cleanup_requests=0,
            cleanup_mutations=0,
        )

    def test_receipt_is_closed_and_selector_is_derived_from_run_id(self) -> None:
        value = {
            "schema": HERMES.CANARY_RECEIPT_SCHEMA,
            "run_id": "run-safe-123",
            "repo": HERMES.CANARY_REPO_PREFIX + "run-safe-123",
            "ticket_id": "F9001",
            "phase": "prepare",
            "started_at": 1.0,
            "deadline_at": 301.0,
            "checks": [HERMES.CANARY_CHECKS[0]],
            "cleanup": None,
            "requests": 2,
            "mutations": 1,
            "embedding_writes": 1,
            "cleanup_requests": 0,
            "cleanup_mutations": 0,
        }
        state = HERMES.CanaryState.from_receipt(value)
        self.assertEqual(state.repo, HERMES.CANARY_REPO_PREFIX + state.run_id)
        tampered = dict(value)
        tampered["repo"] = "another-repo"
        with self.assertRaises(HERMES.SafeError):
            HERMES.CanaryState.from_receipt(tampered)
        unknown = dict(value)
        unknown["extra"] = True
        with self.assertRaises(HERMES.SafeError):
            HERMES.CanaryState.from_receipt(unknown)
        lowered = dict(value)
        lowered["requests"] = 1
        with self.assertRaises(HERMES.SafeError):
            HERMES.CanaryState.from_receipt(lowered)
        missing_identity = dict(value)
        missing_identity["ticket_id"] = None
        with self.assertRaises(HERMES.SafeError):
            HERMES.CanaryState.from_receipt(missing_identity)
        skipped_check = dict(value)
        skipped_check["checks"] = [HERMES.CANARY_CHECKS[1]]
        with self.assertRaises(HERMES.SafeError):
            HERMES.CanaryState.from_receipt(skipped_check)

    def test_preflight_requires_fresh_true_one(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "preflight"
            HERMES.atomic_write_json(
                path,
                {
                    "schema": HERMES.PREFLIGHT_SCHEMA,
                    "status": "pass",
                    "evidence_id": "evidence-123",
                    "valid_config_count": 1,
                    "invalid_config_count": 0,
                    "observed_at": time.time(),
                },
            )
            HERMES.validate_preflight(path)
            value = json.loads(path.read_text())
            value["valid_config_count"] = 0
            HERMES.atomic_write_json(path, value)
            with self.assertRaises(HERMES.SafeError):
                HERMES.validate_preflight(path)

    def test_stateful_fake_executes_all_phases_and_exact_public_schemas(self) -> None:
        run_id = "run-safe-stateful"
        fake = StatefulFakeMemory(run_id)
        transport = StatefulFakeMemoryHttp(fake)
        memory = HERMES.MemoryClient(transport)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            state = self._initial_state(run_id)
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            HERMES.Canary(memory, state, receipt).prepare()

            fake.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(memory, state, receipt).after_approval()

            fake.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(memory, state, receipt).after_reapproval()

            complete = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            self.assertEqual(complete.phase, "complete")
            self.assertEqual(complete.cleanup, "pass")
            self.assertEqual(complete.checks, list(HERMES.CANARY_CHECKS))
            self.assertLessEqual(complete.requests, HERMES.MAX_CANARY_REQUESTS)
            self.assertLessEqual(complete.mutations, HERMES.MAX_CANARY_MUTATIONS)
            self.assertEqual(complete.embedding_writes, 2)
            self.assertEqual(fake.ticket["status"], "abandoned")
            self.assertIsNone(fake.ticket["execution_approved_at"])
            self.assertIsNone(fake.ticket["execution_approved_by"])
            create_arguments = next(
                arguments
                for name, arguments in fake.calls
                if name == "create_ticket"
            )
            self.assertIn("description", create_arguments)
            self.assertNotIn("summary", create_arguments)
            self.assertNotIn("source", create_arguments)
            approval_arguments = [
                arguments
                for name, arguments in fake.calls
                if name == "update_ticket"
                and isinstance(arguments, dict)
                and arguments.get("approve_execution") is True
            ]
            self.assertEqual(len(approval_arguments), 1)
            self.assertTrue(
                all(
                    method == "POST"
                    and path in {HERMES.MCP_PATH, HERMES.BATCH_PATH}
                    for method, path, _body in transport.calls
                )
            )
            batch_operations = [
                arguments for name, arguments in fake.calls if name == "batch"
            ]
            self.assertTrue(
                all(
                    operation["project"] == HERMES.PROJECT
                    and operation["mode"] == "atomic"
                    and "operation_id" in operation["operations"][0]
                    and "ticket_update" in operation["operations"][0]
                    and "operation" not in operation["operations"][0]
                    for operation in batch_operations
                )
            )

    def test_cleanup_reserve_survives_normal_cap_exhaustion(self) -> None:
        run_id = "run-safe-cleanup"
        fake = StatefulFakeMemory(run_id)
        fake.seed_ticket()
        fake.ticket["status"] = "planned"
        state = self._initial_state(run_id)
        state.ticket_id = fake.ticket_id
        state.phase = "awaiting_admin_approval"
        state.checks = list(HERMES.CANARY_CHECKS[:6])
        state.requests = HERMES.MAX_CANARY_NORMAL_REQUESTS
        state.mutations = 2
        state.embedding_writes = 2
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            HERMES.Canary(fake, state, receipt).cleanup()
            complete = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
        self.assertEqual(complete.requests, HERMES.MAX_CANARY_NORMAL_REQUESTS + 3)
        self.assertEqual(complete.cleanup_requests, 3)
        self.assertLessEqual(complete.requests, HERMES.MAX_CANARY_REQUESTS)
        self.assertLessEqual(
            complete.cleanup_requests,
            HERMES.MAX_CANARY_CLEANUP_REQUESTS,
        )
        self.assertEqual(complete.cleanup, "pass")

    def test_ambiguous_create_is_reconciled_by_fixed_repo_selector(self) -> None:
        run_id = "run-safe-reconcile"

        class AmbiguousCreateMemory(StatefulFakeMemory):
            def __init__(self, value: str) -> None:
                super().__init__(value)
                self.failed_once = False

            def tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
                result = super().tool(name, arguments)
                if name == "create_ticket" and not self.failed_once:
                    self.failed_once = True
                    raise HERMES.SafeError(
                        "external_transport_failure",
                        exit_code=HERMES.EXIT_EXTERNAL,
                    )
                return result

        fake = AmbiguousCreateMemory(run_id)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            state = self._initial_state(run_id)
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            HERMES.Canary(fake, state, receipt).prepare()
            saved = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
        self.assertEqual(saved.ticket_id, fake.ticket_id)
        self.assertEqual(saved.phase, "awaiting_admin_approval")
        self.assertEqual(
            [name for name, _arguments in fake.calls].count("create_ticket"),
            1,
        )
        self.assertIn("list_tickets", [name for name, _arguments in fake.calls])

    def test_delayed_ambiguous_create_is_reconciled_only_by_cleanup_selector(self) -> None:
        run_id = "run-safe-delayed-reconcile"

        class DelayedCreateMemory(StatefulFakeMemory):
            def __init__(self, value: str) -> None:
                super().__init__(value)
                self.hide_reconcile_once = True

            def tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
                result = super().tool(name, arguments)
                if name == "create_ticket":
                    raise HERMES.SafeError(
                        "external_transport_failure",
                        exit_code=HERMES.EXIT_EXTERNAL,
                    )
                if name == "list_tickets" and self.hide_reconcile_once:
                    self.hide_reconcile_once = False
                    return {"tickets": [], "count": 0}
                return result

        fake = DelayedCreateMemory(run_id)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            state = self._initial_state(run_id)
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            with self.assertRaisesRegex(HERMES.SafeError, "canary_create_unknown"):
                HERMES.Canary(fake, state, receipt).prepare()
            self.assertIsNone(state.ticket_id)

            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(fake, state, receipt).cleanup()
            complete = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))

        self.assertEqual(complete.ticket_id, fake.ticket_id)
        self.assertEqual(complete.phase, "complete")
        self.assertEqual(complete.checks, [HERMES.CANARY_CHECKS[-1]])
        self.assertEqual(
            [name for name, _arguments in fake.calls].count("create_ticket"),
            1,
        )

    def test_cleanup_resume_after_lost_update_response_never_replays_completed_mutation(
        self,
    ) -> None:
        run_id = "run-safe-cleanup-resume"

        class AmbiguousCleanupMemory(StatefulFakeMemory):
            def __init__(self, value: str) -> None:
                super().__init__(value)
                self.lose_update_once = True

            def tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
                result = super().tool(name, arguments)
                if (
                    name == "update_ticket"
                    and arguments.get("status") == "abandoned"
                    and self.lose_update_once
                ):
                    self.lose_update_once = False
                    raise HERMES.SafeError(
                        "external_transport_failure",
                        exit_code=HERMES.EXIT_EXTERNAL,
                    )
                return result

        fake = AmbiguousCleanupMemory(run_id)
        fake.seed_ticket()
        fake.ticket["status"] = "planned"
        state = self._initial_state(run_id)
        state.ticket_id = fake.ticket_id
        state.phase = "awaiting_admin_approval"
        state.checks = list(HERMES.CANARY_CHECKS[:6])
        state.requests = 13
        state.mutations = 2
        state.embedding_writes = 2
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            with self.assertRaisesRegex(HERMES.SafeError, "external_transport_failure"):
                HERMES.Canary(fake, state, receipt).cleanup()

            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(fake, state, receipt).cleanup()
            complete = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))

        abandoned_updates = [
            arguments
            for name, arguments in fake.calls
            if name == "update_ticket"
            and isinstance(arguments, dict)
            and arguments.get("status") == "abandoned"
        ]
        self.assertEqual(len(abandoned_updates), 1)
        self.assertEqual(complete.cleanup_requests, HERMES.MAX_CANARY_CLEANUP_REQUESTS)
        self.assertEqual(complete.cleanup, "pass")

    def test_owner_edit_checkpoint_resumes_without_replaying_ambiguous_mutation(self) -> None:
        run_id = "run-safe-owner-resume"

        class AmbiguousOwnerEditMemory(StatefulFakeMemory):
            def __init__(self, value: str) -> None:
                super().__init__(value)
                self.lose_edit_once = True

            def tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
                result = super().tool(name, arguments)
                if (
                    name == "update_ticket"
                    and "summary_bullets" in arguments
                    and self.lose_edit_once
                ):
                    self.lose_edit_once = False
                    raise HERMES.SafeError(
                        "external_transport_failure",
                        exit_code=HERMES.EXIT_EXTERNAL,
                    )
                return result

        fake = AmbiguousOwnerEditMemory(run_id)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            state = self._initial_state(run_id)
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            HERMES.Canary(fake, state, receipt).prepare()
            fake.approve()

            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            with self.assertRaisesRegex(HERMES.SafeError, "external_transport_failure"):
                HERMES.Canary(fake, state, receipt).after_approval()

            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(fake, state, receipt).after_approval()
            fake.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(fake, state, receipt).after_reapproval()

        owner_edits = [
            arguments
            for name, arguments in fake.calls
            if name == "update_ticket"
            and isinstance(arguments, dict)
            and "summary_bullets" in arguments
        ]
        self.assertEqual(len(owner_edits), 1)

    def test_scoped_pickup_revalidates_exact_ticket_marker_and_approval_pair(self) -> None:
        run_id = "run-safe-pickup-marker"

        class CorruptPickupMemory(StatefulFakeMemory):
            def tool(self, name: str, arguments: dict[str, object]) -> dict[str, object]:
                result = super().tool(name, arguments)
                if name == "next_ticket" and result.get("ticket") is not None:
                    corrupted = json.loads(json.dumps(result))
                    corrupted["ticket"]["tags"]["run_id"] = "other-run"
                    return corrupted
                return result

        fake = CorruptPickupMemory(run_id)
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            state = self._initial_state(run_id)
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            HERMES.Canary(fake, state, receipt).prepare()
            fake.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            HERMES.Canary(fake, state, receipt).after_approval()
            fake.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(receipt))
            with self.assertRaisesRegex(
                HERMES.SafeError,
                "canary_ticket_identity_mismatch",
            ):
                HERMES.Canary(fake, state, receipt).after_reapproval()

    def test_receipt_rejects_nonfinite_fractional_and_out_of_cap_state(self) -> None:
        value = HERMES.asdict(self._initial_state("run-safe-tamper"))
        variants = (
            ("started_at", float("nan")),
            ("deadline_at", float("inf")),
            ("requests", 1.5),
            ("requests", HERMES.MAX_CANARY_REQUESTS + 1),
            ("cleanup_requests", HERMES.MAX_CANARY_CLEANUP_REQUESTS + 1),
            ("phase", "invented"),
        )
        for key, replacement in variants:
            with self.subTest(key=key, replacement=replacement):
                tampered = dict(value)
                tampered[key] = replacement
                with self.assertRaises(HERMES.SafeError):
                    HERMES.CanaryState.from_receipt(tampered)

    def test_prepare_refuses_to_overwrite_nonterminal_checkpoint(self) -> None:
        run_id = "run-safe-existing"
        fake = StatefulFakeMemory(run_id)
        state = self._initial_state(run_id)
        state.checks = [HERMES.CANARY_CHECKS[0]]
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "state"
            HERMES.atomic_write_json(receipt, HERMES.asdict(state))
            with self.assertRaisesRegex(
                HERMES.SafeError,
                "canary_nonterminal_receipt_requires_cleanup",
            ):
                HERMES.Canary(fake, state, receipt).prepare()
        self.assertEqual(fake.calls, [])

    def test_handoff_is_closed_pass_only_and_value_free(self) -> None:
        handoff = {
            "schema": HERMES.HANDOFF_SCHEMA,
            "status": "pass",
            "provider": {
                "ticket": "F0023",
                "path": "bin/hermes-activation",
                "contract": HERMES.CONTRACT,
                "output_schema": HERMES.OUTPUT_SCHEMA,
                "merge_sha": "abc1234",
                "tree_sha": "def5678",
            },
            "items": [
                {
                    "name": HERMES.MEMORY_ITEM,
                    "ref": HERMES.MEMORY_REF,
                    "item_id": "item-memory",
                    "state": "existing",
                },
                {
                    "name": HERMES.GATEWAY_ITEM,
                    "ref": HERMES.GATEWAY_REF,
                    "item_id": "item-gateway",
                    "state": "created",
                },
            ],
            "deployments": [
                {
                    "label": "initial_active",
                    "deploy_id": "dep-one",
                    "state": "live",
                    "valid_config_count": 1,
                    "invalid_config_count": 0,
                },
                {
                    "label": "inert",
                    "deploy_id": "dep-two",
                    "state": "live",
                    "valid_config_count": 0,
                    "invalid_config_count": 0,
                },
                {
                    "label": "final_active",
                    "deploy_id": "dep-three",
                    "state": "live",
                    "valid_config_count": 1,
                    "invalid_config_count": 0,
                },
            ],
            "admin_matrix": {"evidence_id": "admin-evidence", "status": "pass"},
            "direct_canary": {
                "run_id": "run-safe",
                "ticket_id": "F9001",
                "evidence_id": "canary-evidence",
                "status": "pass",
                "cleanup": "pass",
            },
            "evidence_artifact_id": "artifact-evidence",
        }
        self.assertEqual(HERMES.validate_handoff(handoff), handoff)
        unsafe = json.loads(json.dumps(handoff))
        unsafe["direct_canary"]["value"] = "forbidden"
        with self.assertRaises(HERMES.SafeError):
            HERMES.validate_handoff(unsafe)


class HermesDisclosureTest(unittest.TestCase):
    def _fake_op(self, root: Path) -> Path:
        executable = root / "fake-op"
        executable.write_text(
            """#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

Path(os.environ["FAKE_ARGV_LOG"]).write_text(
    Path(os.environ["FAKE_ARGV_LOG"]).read_text() + json.dumps(sys.argv[1:]) + "\\n"
)
if sys.argv[1:3] == ["item", "list"]:
    print(json.dumps([
        {"id": "item-memory", "title": "HERMES_AUTODEV_MEMORY_TOKEN",
         "category": "PASSWORD", "vault": {"name": "AUTODEV-sensitive"}},
        {"id": "item-gateway", "title": "HERMES_GATEWAY_TOKEN",
         "category": "PASSWORD", "vault": {"name": "AUTODEV-sensitive"}},
    ]))
elif sys.argv[1:3] == ["read", "--no-newline"]:
    ref = sys.argv[3]
    if "AUTODEV_MEMORY" in ref:
        sys.stdout.write(os.environ["FAKE_MEMORY"])
    else:
        sys.stdout.write(os.environ["FAKE_GATEWAY"])
else:
    raise SystemExit(9)
"""
        )
        executable.chmod(0o755)
        return executable

    def test_runtime_sentinels_never_cross_public_or_persisted_channels(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_op = self._fake_op(root)
            ledger = root / "argv.log"
            ledger.write_text("")
            receipt = root / "receipt.json"
            memory = "MEMORY-SENTINEL-" + os.urandom(24).hex()
            gateway = "GATEWAY-SENTINEL-" + os.urandom(24).hex()
            environment = os.environ.copy()
            environment.update(
                {
                    "HERMES_ACTIVATION_TEST_MODE": "1",
                    "SENSITIVE_ACCESS_REASON": "Fake E0006/M3/F0023 item test",
                    "OP_BIN": str(fake_op),
                    "FAKE_ARGV_LOG": str(ledger),
                    "FAKE_MEMORY": memory,
                    "FAKE_GATEWAY": gateway,
                }
            )
            result = subprocess.run(
                [str(COMMAND), "items", "ensure", "--receipt", str(receipt)],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            visible = result.stdout + result.stderr + receipt.read_text() + ledger.read_text()
            self.assertNotIn(memory, visible)
            self.assertNotIn(gateway, visible)
            self.assertEqual(stat.S_IMODE(receipt.stat().st_mode), 0o600)
            self.assertFalse(any(path.name.startswith(".receipt.json.") for path in root.iterdir()))

    def test_apply_wait_cancel_and_canary_fake_channels_exclude_runtime_sentinels(self) -> None:
        memory_secret = "MEMORY-SENTINEL-" + os.urandom(24).hex()
        render_secret = "RENDER-SENTINEL-" + os.urandom(24).hex()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            visible: list[bytes] = []

            apply_http = FakeRenderHttp(memory_secret)
            applied = HERMES.RenderClient(apply_http).apply(
                "active",
                memory_secret.encode(),
            )
            apply_output = HERMES.success_result("memory apply", HERMES.asdict(applied))
            apply_receipt = root / "apply.json"
            HERMES.atomic_write_json(apply_receipt, apply_output)
            visible.extend((HERMES.compact_json(apply_output), apply_receipt.read_bytes()))

            wait_http = FakeRenderHttp(render_secret, ["live"])
            waited = HERMES.RenderClient(wait_http).wait(
                "dep-safe-123",
                root / "unused-timeout.json",
            )
            visible.append(
                HERMES.compact_json(
                    HERMES.success_result(
                        "render wait",
                        {
                            "service": HERMES.RENDER_SERVICE,
                            "deploy_id": "dep-safe-123",
                            "state": waited,
                            "resume_command": None,
                        },
                    )
                )
            )

            timeout = root / "timeout.json"
            canceled_receipt = root / "canceled.json"
            HERMES.atomic_write_json(
                timeout,
                {
                    "schema": HERMES.TIMEOUT_RECEIPT_SCHEMA,
                    "service": HERMES.RENDER_SERVICE,
                    "deploy_id": "dep-safe-123",
                    "state": "unknown",
                    "started_at": 1.0,
                    "deadline_at": 2.0,
                },
            )
            cancel_http = FakeRenderHttp(render_secret, ["queued", "canceled"])
            canceled = HERMES.RenderClient(cancel_http).cancel(
                "dep-safe-123",
                timeout,
                canceled_receipt,
            )
            visible.extend(
                (
                    HERMES.compact_json(
                        HERMES.success_result(
                            "render cancel",
                            {
                                "service": HERMES.RENDER_SERVICE,
                                "deploy_id": "dep-safe-123",
                                "state": canceled,
                                "canceled": True,
                            },
                        )
                    ),
                    timeout.read_bytes(),
                    canceled_receipt.read_bytes(),
                )
            )

            run_id = "run-safe-disclosure"
            fake_memory = StatefulFakeMemory(run_id)
            started = time.time()
            state = HERMES.CanaryState(
                schema=HERMES.CANARY_RECEIPT_SCHEMA,
                run_id=run_id,
                repo=HERMES.CANARY_REPO_PREFIX + run_id,
                ticket_id=None,
                phase="prepare",
                started_at=started,
                deadline_at=started + HERMES.CANARY_SECONDS,
                checks=[],
                cleanup=None,
                requests=0,
                mutations=0,
                embedding_writes=0,
                cleanup_requests=0,
                cleanup_mutations=0,
            )
            state_receipt = root / "canary.json"
            HERMES.atomic_write_json(state_receipt, HERMES.asdict(state))
            HERMES.Canary(fake_memory, state, state_receipt).prepare()
            fake_memory.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(state_receipt))
            HERMES.Canary(fake_memory, state, state_receipt).after_approval()
            fake_memory.approve()
            state = HERMES.CanaryState.from_receipt(HERMES.load_json_receipt(state_receipt))
            HERMES.Canary(fake_memory, state, state_receipt).after_reapproval()
            visible.extend(
                (
                    HERMES.compact_json(
                        HERMES.success_result("memory canary", HERMES.canary_result(state))
                    ),
                    state_receipt.read_bytes(),
                )
            )

            failed_apply = FakeRenderHttp(memory_secret)
            failed_apply.request = mock.Mock(
                side_effect=HERMES.SafeError(
                    "external_transport_failure",
                    exit_code=HERMES.EXIT_EXTERNAL,
                )
            )
            with self.assertRaises(HERMES.SafeError) as caught:
                HERMES.RenderClient(failed_apply).apply(
                    "active",
                    memory_secret.encode(),
                )
            visible.append(
                HERMES.compact_json(
                    HERMES.fixed_error_result("memory apply", caught.exception)
                )
            )

        combined = b"\n".join(visible)
        for sentinel in (memory_secret, render_secret):
            self.assertNotIn(sentinel.encode(), combined)

    def test_missing_reason_stops_before_child(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_op = self._fake_op(root)
            ledger = root / "argv.log"
            ledger.write_text("")
            environment = os.environ.copy()
            environment.update(
                {
                    "HERMES_ACTIVATION_TEST_MODE": "1",
                    "OP_BIN": str(fake_op),
                    "FAKE_ARGV_LOG": str(ledger),
                    "FAKE_MEMORY": "m" * 40,
                    "FAKE_GATEWAY": "g" * 40,
                }
            )
            environment.pop("SENSITIVE_ACCESS_REASON", None)
            result = subprocess.run(
                [str(COMMAND), "items", "ensure"],
                env=environment,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 3)
            self.assertEqual(ledger.read_text(), "")
            self.assertNotIn("m" * 40, result.stdout + result.stderr)

    def test_test_endpoint_rejects_non_loopback(self) -> None:
        with self.assertRaises(HERMES.SafeError):
            with mock.patch.dict(
                os.environ,
                {"HERMES_ACTIVATION_TEST_RENDER_BASE": "https://api.render.com"},
                clear=False,
            ):
                HERMES.test_base("RENDER", HERMES.RENDER_BASE, True)

    def test_f0020_route_refs_and_forbidden_tools_remain_exact(self) -> None:
        routes = json.loads((ROOT / "mcp-gateway" / "routes.json").read_text())["routes"]
        memory = routes["hermes/autodev-memory"]
        render = routes["hermes/render"]
        self.assertEqual(memory["authEnv"], HERMES.MEMORY_ITEM)
        self.assertEqual(memory["clientTokenEnv"], HERMES.GATEWAY_ITEM)
        self.assertEqual(memory["target"], HERMES.MEMORY_BASE + HERMES.MCP_PATH)
        self.assertEqual(render["clientTokenEnv"], HERMES.GATEWAY_ITEM)
        for forbidden in ("trigger_deploy", "update_environment_variables"):
            self.assertNotIn(forbidden, render["allowTools"])


if __name__ == "__main__":
    unittest.main()

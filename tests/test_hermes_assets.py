from __future__ import annotations

import hashlib
import importlib.util
import json
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
        for relative in (
            "bootstrap.sh",
            "install.sh",
            "verify.sh",
            "bin/hermes-schedule-alert",
            "bin/hermes-schedule-release",
            "bin/run-autodev-memory",
            "bin/run-schedule-release",
            "bin/validate-bootstrap-inputs",
            "bin/validate-schedule-release",
            "conductor/server.py",
            "schedules/runner.py",
        ):
            mode = (HERMES / relative).stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, relative)

    def test_runbook_names_the_current_ts_scoped_token(self) -> None:
        runbook = (HERMES / "README.md").read_text()
        self.assertIn("TS/Autodev memory restricted/api_token", runbook)
        self.assertNotIn("AUTODEV-sensitive/HERMES_AUTODEV_MEMORY_TOKEN", runbook)
        self.assertIn("TS/Slack/mcp_user_token", runbook)
        self.assertIn("/etc/hermes-schedules/slack.token", runbook)


def load_schedule_runner() -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(
        "hermes_schedules_runner",
        HERMES / "schedules" / "runner.py",
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cron_to_oncalendar(cron: str) -> str:
    minute, hour = cron.split()[:2]
    if hour.startswith("*/"):
        return f"*-*-* 00/{int(hour[2:])}:{int(minute):02d}:00"
    return f"*-*-* {int(hour):02d}:{int(minute):02d}:00"


class HermesScheduleTests(unittest.TestCase):
    def manifest(self) -> dict:
        return yaml.safe_load((HERMES / "schedules" / "schedules.yaml").read_text())

    def test_manifest_entries_are_complete_and_launchable(self) -> None:
        manifest = self.manifest()
        channels = manifest["slack_channels"]
        self.assertIn("#autodev-incidents", channels)
        runner = manifest["runner"]
        for key in ("poll_seconds", "retention_days_pass", "retention_days_fail"):
            self.assertIsInstance(runner[key], int)
        self.assertEqual(runner["archive_on_complete"], ["PASS"])
        for entry in manifest["schedules"]:
            with self.subTest(entry=entry.get("name")):
                self.assertIn(entry["slack_channel"], channels)
                self.assertIsInstance(entry["enabled"], bool)
                self.assertGreater(entry["max_runtime_minutes"], 0)
                if entry["name"] == "health-6h":
                    self.assertGreater(entry["remediation_max_runtime_minutes"], 0)
                self.assertTrue(entry["workspace"]["repo"])
                self.assertTrue(entry["workspace"]["branch"])
                # Scheduled runs pin the latest Codex model (Simon, 2026-08-22).
                self.assertEqual(entry["workspace"]["agent"], "codex")
                self.assertEqual(entry["workspace"]["model"], "gpt-5.6-sol")
                prompt = HERMES / "schedules" / entry["prompt"]
                self.assertTrue(prompt.is_file(), entry["prompt"])
                self.assertNotEqual(entry["prompt"], "README.md")

        approval = manifest["production_approval"]
        self.assertTrue(approval["enabled"])
        self.assertEqual(approval["hermes_slack_user_id"], "U0BKDG6QP17")
        self.assertEqual(approval["authorized_slack_users"], ["U09T4LELYES"])
        self.assertGreater(approval["expires_days"], 0)
        self.assertGreater(approval["max_runtime_minutes"], 0)
        self.assertGreater(approval["max_start_attempts"], 0)

    def test_health_contract_requires_ownership_aware_persistent_orphan_evidence(self) -> None:
        contract = (ROOT / "skills" / "references" / "scheduled-run.md").read_text()

        self.assertIn("ownership or lease clock", contract)
        self.assertIn("proof that work is stuck", contract)
        self.assertIn("confirming sample after one successful worker", contract)
        self.assertIn("cycle before emitting a red issue", contract)

    def test_health_schedule_requires_current_producer_ownership(self) -> None:
        prompt = (HERMES / "schedules" / "health-6h.md").read_text()
        contract = (ROOT / "skills" / "references" / "scheduled-run.md").read_text()

        self.assertIn("current-producer ownership gate", prompt)
        self.assertIn("scheduled-run.md §2a", prompt)
        self.assertIn("## 2a. Health finding ownership gate", contract)
        self.assertIn("A stale database row", contract)
        self.assertIn("Retired, renamed, or unowned rows", contract)
        self.assertIn("`verifier_defect`, not `code_defect`", contract)
        self.assertIn("`scraper_executions` contains execution writers", contract)
        self.assertIn("`record.source_meta.scraper_id`", contract)

    def test_health_schedule_tags_and_dispatches_every_actionable_cluster(self) -> None:
        prompt = (HERMES / "schedules" / "health-6h.md").read_text().replace("\n", " ")

        self.assertIn("complete every actionable cluster in the bounded result", prompt)
        self.assertIn("append `ticket:<ID>` to every verified failed/crashed flow run", prompt)
        self.assertIn("one cloud `/ticket-flow <ID>` workspace per emitted issue", prompt)
        self.assertIn("supervises it through staging verification", prompt)
        self.assertIn("final issue/fix/evidence reply", prompt)
        for obsolete_promise in (
            "never create a follow-up conductor workspace",
            "remaining clusters are listed un-investigated",
            "spawn_requests",
        ):
            with self.subTest(obsolete_promise=obsolete_promise):
                self.assertNotIn(obsolete_promise, prompt.lower())

    def test_health_issue_contract_uses_exact_canonical_keys(self) -> None:
        prompt = (HERMES / "schedules" / "health-6h.md").read_text().replace("\n", " ")
        contract = (ROOT / "skills" / "references" / "scheduled-run.md").read_text()
        canonical_keys = (
            "`title`, `concrete_proof`, `representative_example`, `next_step`, "
            "`owning_ticket_id`, and `remediation_ready`"
        )
        canonical_schema = """{
  "title": "<short name>",
  "concrete_proof": "<aggregate evidence>",
  "representative_example": "<one occurrence>",
  "next_step": "<specific action>",
  "owning_ticket_id": "<ID or null>",
  "remediation_ready": true
}"""

        self.assertIn(canonical_keys, prompt)
        self.assertIn(canonical_schema, contract)
        self.assertIn("input-only legacy aliases", contract)

    def test_health_contract_defines_ticket_tag_and_cloud_remediation_boundaries(self) -> None:
        contract = (ROOT / "skills" / "references" / "scheduled-run.md").read_text()
        readme = (HERMES / "schedules" / "README.md").read_text()

        self.assertIn("## 2b. Health issue remediation", contract)
        self.assertIn("tag_ticket_flow_runs", contract)
        self.assertIn("one workspace per valid F/B/R ticket", contract)
        self.assertIn("`HEALTH_REMEDIATION_RESULT`", contract)
        self.assertIn("It never promotes\n   to production", contract)
        self.assertIn("one cloud\n`/ticket-flow` workspace per issue", readme)
        self.assertIn("its own top-level Slack message", readme)
        self.assertIn("tags Hermes", readme)
        self.assertIn("Ticket identity comes only from that one-issue thread", readme)
        self.assertIn("`SLACK_ALLOWED_CHANNELS`", readme)

    def test_health_remediation_launches_one_workspace_per_unique_ticket(self) -> None:
        runner = load_schedule_runner()
        issues = [
            {
                "title": "Issue one",
                "proof": "Proof one.",
                "example": "Example one.",
                "next_step": "Fix one.",
                "ticket_id": "B0100",
                "remediation_ready": True,
            },
            {
                "title": "Issue two",
                "proof": "Proof two.",
                "example": "Example two.",
                "next_step": "Fix two.",
                "ticket_id": "B0101",
                "remediation_ready": True,
            },
        ]
        entry = {
            "workspace": {
                "repo": "ts-prefect",
                "branch": "staging",
                "agent": "codex",
                "model": "gpt-5.6-sol",
            }
        }
        launched = [
            ("workspace-1", "session-1", "conductor://workspace-1"),
            ("workspace-2", "session-2", "conductor://workspace-2"),
        ]

        with (
            mock.patch.object(
                runner, "launch_cloud_workspace", side_effect=launched
            ) as launch,
            mock.patch.object(runner, "conductor_call") as conductor_call,
        ):
            jobs = runner.launch_health_remediations(entry, issues)

        self.assertEqual(len(jobs), 2)
        self.assertEqual(launch.call_count, 2)
        self.assertEqual(conductor_call.call_count, 2)
        for index, ticket_id in enumerate(("B0100", "B0101")):
            message = conductor_call.mock_calls[index].args[1]["message"]
            self.assertTrue(message.startswith(f"/ticket-flow {ticket_id}\n"))

        with (
            mock.patch.object(
                runner, "launch_cloud_workspace", return_value=launched[0]
            ) as launch,
            mock.patch.object(runner, "conductor_call"),
        ):
            duplicate_jobs = runner.launch_health_remediations(entry, [issues[0], issues[0]])
        self.assertEqual(launch.call_count, 1)
        self.assertIn("duplicate owning ticket", duplicate_jobs[1]["launch_error"])

        not_ready = issues[0] | {"remediation_ready": False}
        with (
            mock.patch.object(runner, "launch_cloud_workspace") as launch,
            mock.patch.object(runner, "conductor_call"),
        ):
            not_ready_jobs = runner.launch_health_remediations(entry, [not_ready])
        launch.assert_not_called()
        self.assertIn("did not attest", not_ready_jobs[0]["launch_error"])

    def test_every_schedule_has_a_matching_vancouver_timer(self) -> None:
        for entry in self.manifest()["schedules"]:
            with self.subTest(entry=entry["name"]):
                timer = HERMES / "systemd" / f"hermes-schedule@{entry['name']}.timer"
                content = timer.read_text()
                expected = cron_to_oncalendar(entry["cron"])
                self.assertIn(
                    f"OnCalendar={expected} America/Vancouver",
                    content,
                )
                self.assertIn(f'cron "{entry["cron"]}"', content)
                self.assertIn("Persistent=true", content)

    def test_schedule_units_keep_the_secret_boundary(self) -> None:
        units = (
            "hermes-schedule@.service",
            "hermes-schedule-alert@.service",
            "hermes-schedule-watchdog.service",
            "hermes-schedule-approval.service",
        )
        for unit in units:
            with self.subTest(unit=unit):
                content = (HERMES / "systemd" / unit).read_text()
                self.assertIn(
                    "LoadCredential=slack.token:/etc/hermes-schedules/slack.token",
                    content,
                )
                self.assertIn("User=hermes-schedules", content)
                self.assertIn("NoNewPrivileges=true", content)
                self.assertIn("ProtectSystem=strict", content)
                self.assertIn("ProtectHome=true", content)
                self.assertNotIn("Environment=SLACK", content)
        template = (HERMES / "systemd" / "hermes-schedule@.service").read_text()
        self.assertIn("OnFailure=hermes-schedule-alert@%i.service", template)
        watchdog = (HERMES / "systemd" / "hermes-schedule-watchdog.service").read_text()
        self.assertIn("OnFailure=hermes-schedule-watchdog-alert.service", watchdog)
        watchdog_timer = (
            HERMES / "systemd" / "hermes-schedule-watchdog.timer"
        ).read_text()
        self.assertIn("America/Vancouver", watchdog_timer)
        approval_timer = (
            HERMES / "systemd" / "hermes-schedule-approval.timer"
        ).read_text()
        self.assertIn("OnUnitActiveSec=1m", approval_timer)
        self.assertIn("Persistent=true", approval_timer)
        approval_service = (
            HERMES / "systemd" / "hermes-schedule-approval.service"
        ).read_text()
        self.assertIn("run-schedule-release approvals", approval_service)
        self.assertIn("OnFailure=hermes-schedule-alert@approval.service", approval_service)
        self.assertNotIn("LoadCredential=op.token", approval_service)

    def test_ticket_promote_accepts_only_a_bound_hermes_approval_receipt(self) -> None:
        promote = (ROOT / "skills" / "ticket-promote" / "SKILL.md").read_text()

        self.assertIn("An exact `HUMAN_PRODUCTION_APPROVAL` receipt", promote)
        self.assertIn("immutable authorized Slack user ID", promote)
        self.assertIn("pinned Hermes mention", promote)
        self.assertIn("message digest", promote)
        self.assertIn("cannot manufacture or reuse that receipt", promote)

    def test_installer_deploys_the_schedule_stack(self) -> None:
        installer = (HERMES / "install.sh").read_text()
        self.assertIn("check_credential /etc/hermes-schedules/slack.token", installer)
        self.assertIn("/opt/hermes-schedules", installer)
        self.assertIn("hermes-schedule-release install-local", installer)
        self.assertIn("validate-schedule-release", installer)
        self.assertIn('systemctl enable --now "${SCHEDULE_TIMERS[@]}"', installer)
        self.assertIn("useradd --system", installer)
        self.assertIn("hermes-schedules", installer)

    def test_result_block_parsing_round_trips(self) -> None:
        runner = load_schedule_runner()
        message = (
            "All checks ran.\n\n"
            "```\nSCHEDULED_RUN_RESULT\n"
            "status: PASS\n"
            "schedule: health-6h\n"
            "summary: all green\n"
            "checks_total: 12\n"
            "checks_failed: 0\n"
            "tickets_touched: [F0100, F0101]\n"
            "rc_fingerprints: []\n"
            'issues: [{"title":"Worker offline",'
            '"concrete_proof":"No heartbeat in 15m",'
            '"representative_example":"Worker alpha missed three polls",'
            '"next_step":"Restart worker alpha","owning_ticket_id":"B0100",'
            '"remediation_ready":true}]\n'
            "```\n"
        )
        parsed = runner.parse_result_block(message)
        self.assertEqual(parsed["status"], "PASS")
        self.assertEqual(parsed["summary"], "all green")
        self.assertEqual(parsed["tickets_touched"], ["F0100", "F0101"])
        self.assertEqual(parsed["rc_fingerprints"], [])
        self.assertEqual(
            parsed["issues"],
            [
                {
                    "title": "Worker offline",
                    "proof": "No heartbeat in 15m",
                    "example": "Worker alpha missed three polls",
                    "next_step": "Restart worker alpha",
                    "ticket_id": "B0100",
                    "remediation_ready": True,
                }
            ],
        )
        issues = runner.health_issues(parsed, "one check failed", "FAIL")
        self.assertEqual(
            runner.health_parent_message("❌", issues, "one check failed"),
            "❌ [health-6h] 1 issue\n• Worker offline — ticket `B0100`",
        )
        self.assertIsNone(runner.parse_result_block("no marker here"))
        self.assertIsNone(
            runner.parse_result_block("SCHEDULED_RUN_RESULT\nstatus: MAYBE\n")
        )
        self.assertIsNone(
            runner.parse_result_block(
                "SCHEDULED_RUN_RESULT\nstatus: FAIL\nissues: not-json\n"
            )
        )
        needs_more_time = runner.parse_result_block(
            "SCHEDULED_RUN_RESULT\n"
            "status: NEEDS_MORE_TIME\n"
            "summary: provider operation is still progressing\n"
            "resume_command: wait-provider-deploy deploy-123\n"
        )
        self.assertEqual(needs_more_time["status"], "NEEDS_MORE_TIME")
        self.assertEqual(
            needs_more_time["resume_command"],
            "wait-provider-deploy deploy-123",
        )
        self.assertIsNone(
            runner.parse_result_block(
                "SCHEDULED_RUN_RESULT\nstatus: NEEDS_MORE_TIME\n"
            )
        )

    def test_session_result_reads_paginated_nested_agent_output(self) -> None:
        runner = load_schedule_runner()
        filler = [
            {
                "content": {
                    "rawPayload": {
                        "event": {
                            "type": "item.completed",
                            "item": {"type": "toolCall", "id": f"tool-{index}"},
                        }
                    }
                }
            }
            for index in range(205)
        ]
        result_text = (
            "Health check complete.\n"
            "SCHEDULED_RUN_RESULT\n"
            "status: BLOCKED\n"
            "summary: three actionable failures were confirmed\n"
            "checks_total: 36\n"
            "checks_failed: 3\n"
        )
        messages = [
            *filler,
            {
                "content": {
                    "rawPayload": {
                        "event": {
                            "type": "item.completed",
                            "item": {"type": "agentMessage", "text": result_text},
                        }
                    }
                }
            },
            {"content": {"rawPayload": {"event": {"type": "turn.completed"}}}},
        ]
        offsets: list[int] = []

        def conductor_call(tool: str, arguments: dict[str, object]) -> dict[str, object]:
            self.assertEqual(tool, "list_session_messages")
            self.assertEqual(arguments["limit"], 100)
            offset = int(arguments["offset"])
            offsets.append(offset)
            page = messages[offset : offset + 100]
            return {
                "data": page,
                "hasMore": offset + len(page) < len(messages),
            }

        with mock.patch.object(runner, "conductor_call", side_effect=conductor_call):
            snapshot = runner.read_session_result("session-1")

        self.assertEqual(offsets, [0, 100, 200])
        self.assertTrue(snapshot["turn_completed"])
        self.assertEqual(snapshot["result"]["status"], "BLOCKED")
        self.assertEqual(snapshot["result"]["checks_failed"], "3")

    def test_poll_waits_for_terminal_output_materialization(self) -> None:
        runner = load_schedule_runner()
        result = {
            "status": "BLOCKED",
            "summary": "three actionable failures were confirmed",
        }
        statuses = iter(
            [
                {"status": "working"},
                {"status": "idle"},
                {"status": "idle"},
            ]
        )
        snapshots = iter(
            [
                {"result": None, "turn_completed": False},
                {"result": result, "turn_completed": True},
            ]
        )

        with (
            mock.patch.object(
                runner,
                "conductor_call",
                side_effect=lambda tool, arguments: next(statuses),
            ),
            mock.patch.object(
                runner, "read_session_result", side_effect=lambda session_id: next(snapshots)
            ) as read_result,
            mock.patch.object(runner.time, "sleep"),
        ):
            outcome = runner.poll_session("session-1", 1, 0)

        self.assertEqual(outcome, ("finished", result))
        self.assertEqual(read_result.call_count, 2)

    def test_health_issue_legacy_aliases_are_normalized(self) -> None:
        runner = load_schedule_runner()

        self.assertEqual(
            runner.parse_health_issues(
                [
                    {
                        "title": " Worker offline ",
                        "proof": " No heartbeat in 15m ",
                        "example": " Worker alpha missed three polls ",
                        "next_step": " Restart worker alpha ",
                        "ticket_id": " B0100 ",
                    }
                ]
            ),
            [
                {
                    "title": "Worker offline",
                    "proof": "No heartbeat in 15m",
                    "example": "Worker alpha missed three polls",
                    "next_step": "Restart worker alpha",
                    "ticket_id": "B0100",
                    "remediation_ready": False,
                }
            ],
        )

    def test_health_remediation_prompt_and_result_are_structured(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "proof": "No heartbeat arrived in fifteen minutes.",
            "example": "Worker alpha missed three polls.",
            "next_step": "Repair the worker heartbeat.",
            "ticket_id": "B0100",
        }

        prompt = runner.remediation_prompt(issue)

        self.assertTrue(prompt.startswith("/ticket-flow B0100\n"))
        self.assertIn('"title":"Worker offline"', prompt)
        self.assertIn("Independently confirm the root cause", prompt)
        self.assertIn("land it on `staging`", prompt)
        self.assertIn("Do not promote to production", prompt)
        self.assertIn("HEALTH_REMEDIATION_RESULT", prompt)

        transcript = (
            "Ticket flow complete.\n"
            "HEALTH_REMEDIATION_RESULT\n"
            '{"status":"STAGING_VERIFIED","ticket_id":"B0100",'
            '"issue":"A dead worker stopped all scheduled jobs.",'
            '"fix":"The worker now restarts after a stale heartbeat.",'
            '"verification":"Staging run run-1 passed with evidence artifact art-1."}\n'
        )
        self.assertEqual(
            runner.parse_remediation_result(transcript),
            {
                "status": "STAGING_VERIFIED",
                "ticket_id": "B0100",
                "issue": "A dead worker stopped all scheduled jobs.",
                "fix": "The worker now restarts after a stale heartbeat.",
                "verification": "Staging run run-1 passed with evidence artifact art-1.",
            },
        )

    def test_health_remediation_result_rejects_unverified_or_wrong_ticket_types(self) -> None:
        runner = load_schedule_runner()
        for status, ticket_id in (
            ("PASS", "B0100"),
            ("STAGING_VERIFIED", "E0100"),
        ):
            with self.subTest(status=status, ticket_id=ticket_id):
                transcript = (
                    "HEALTH_REMEDIATION_RESULT\n"
                    f'{{"status":"{status}","ticket_id":"{ticket_id}",'
                    '"issue":"Issue.","fix":"Fix.","verification":"Evidence."}'
                )
                self.assertIsNone(runner.parse_remediation_result(transcript))

    def test_health_remediation_supervisor_yields_valid_terminal_result(self) -> None:
        runner = load_schedule_runner()
        job = {
            "issue": {
                "title": "Worker offline",
                "proof": "No heartbeat arrived.",
                "example": "Worker alpha missed three polls.",
                "next_step": "Repair the worker.",
                "ticket_id": "B0100",
                "remediation_ready": True,
            },
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": False,
            "terminal_idle_confirmations": 0,
        }
        result = {
            "status": "STAGING_VERIFIED",
            "ticket_id": "B0100",
            "issue": "A dead worker stopped jobs.",
            "fix": "The worker now restarts safely.",
            "verification": "Staging run run-1 passed with evidence artifact art-1.",
        }

        with (
            mock.patch.object(
                runner, "conductor_call", return_value={"status": "completed"}
            ),
            mock.patch.object(
                runner, "read_session_remediation_result", return_value=(result, True)
            ),
            mock.patch.object(runner.time, "sleep") as sleep,
        ):
            completed = list(runner.supervise_health_remediations([job], 10, 1))

        self.assertEqual(completed[0][1]["status"], "STAGING_VERIFIED")
        sleep.assert_not_called()

    def test_health_remediation_supervisor_fails_closed_per_issue(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "proof": "No heartbeat arrived.",
            "example": "Worker alpha missed three polls.",
            "next_step": "Repair the worker.",
            "ticket_id": "B0100",
            "remediation_ready": True,
        }
        launch_failure = {
            "issue": issue,
            "workspace_id": None,
            "session_id": None,
            "deep_link": None,
            "launch_error": "workspace launch failed",
            "saw_working": False,
            "terminal_idle_confirmations": 0,
        }

        with (
            mock.patch.object(runner, "conductor_call") as conductor_call,
            mock.patch.object(runner.time, "sleep") as sleep,
        ):
            completed = list(
                runner.supervise_health_remediations([launch_failure], 10, 1)
            )

        self.assertEqual(len(completed), 1)
        self.assertEqual(completed[0][1]["status"], "STOPPED")
        self.assertIn("workspace launch failed", completed[0][1]["fix"])
        conductor_call.assert_not_called()
        sleep.assert_not_called()

        errored_job = launch_failure | {
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": True,
        }
        untrustworthy_success = {
            "status": "STAGING_VERIFIED",
            "ticket_id": "B0100",
            "issue": "A dead worker stopped jobs.",
            "fix": "The worker now restarts safely.",
            "verification": "Staging run run-1 passed with artifact art-1.",
        }
        with (
            mock.patch.object(
                runner, "conductor_call", return_value={"status": "errored"}
            ),
            mock.patch.object(
                runner,
                "read_session_remediation_result",
                return_value=(untrustworthy_success, True),
            ),
        ):
            completed = list(runner.supervise_health_remediations([errored_job], 10, 1))

        self.assertEqual(completed[0][1]["status"], "STOPPED")
        self.assertIn("session errored", completed[0][1]["fix"])

    def test_production_result_and_prompt_require_a_bound_approval_receipt(self) -> None:
        runner = load_schedule_runner()
        candidate = {
            "ticket_id": "B0100",
            "title": "Worker offline",
            "channel": "C-health",
            "thread_ts": "100.000001",
            "staging_reply_ts": "100.000002",
            "workspace_id": "workspace-1",
            "workspace_link": "conductor://workspace-1",
            "state": "queued",
            "created_at": "2026-09-03T08:00:00+00:00",
            "expires_at": "2026-09-17T08:00:00+00:00",
            "approval_message_ts": "100.000003",
            "approved_by": "U-SIMON",
            "approval_text_sha256": "abc123",
            "approval_hermes_user_id": "U0HERMES123",
            "promotion_session_id": None,
            "promotion_session_link": None,
            "deadline_at": None,
            "start_attempts": 0,
            "terminal_idle_confirmations": 0,
        }

        prompt = runner.production_prompt(candidate)

        self.assertTrue(prompt.startswith("/ticket-promote B0100\n"))
        self.assertIn("HUMAN_PRODUCTION_APPROVAL", prompt)
        self.assertIn('"slack_user_id":"U-SIMON"', prompt)
        self.assertIn('"slack_message_ts":"100.000003"', prompt)
        self.assertIn('"slack_message_sha256":"abc123"', prompt)
        self.assertIn('"hermes_user_id":"U0HERMES123"', prompt)
        self.assertIn("one-use message digest", prompt)
        self.assertIn("does not authorize a parity bypass", prompt)
        self.assertIn("HEALTH_PRODUCTION_RESULT", prompt)

        transcript = (
            "Production verification complete.\n"
            "HEALTH_PRODUCTION_RESULT\n"
            '{"status":"PROD_VERIFIED","ticket_id":"B0100",'
            '"issue":"A dead worker stopped scheduled jobs.",'
            '"fix":"The worker now recovers stale heartbeats.",'
            '"verification":"Production run run-2 passed with artifact art-2."}'
        )
        self.assertEqual(
            runner.parse_production_result(transcript),
            {
                "status": "PROD_VERIFIED",
                "ticket_id": "B0100",
                "issue": "A dead worker stopped scheduled jobs.",
                "fix": "The worker now recovers stale heartbeats.",
                "verification": "Production run run-2 passed with artifact art-2.",
            },
        )
        self.assertIsNone(
            runner.parse_production_result(
                "HEALTH_PRODUCTION_RESULT\n"
                '{"status":"STAGING_VERIFIED","ticket_id":"B0100",'
                '"issue":"Issue.","fix":"Fix.","verification":"Evidence."}'
            )
        )
        self.assertIsNone(
            runner.parse_production_result(
                "HEALTH_PRODUCTION_RESULT\n"
                '{"status":"PROD_VERIFIED","ticket_id":"B0100",'
                '"issue":"Issue.","fix":"Fix.","verification":"Evidence.",'
                '"unexpected":"field"}'
            )
        )
        self.assertIsNone(
            runner.parse_production_result(
                "HEALTH_PRODUCTION_RESULT\n"
                '{"status":"PROD_VERIFIED","ticket_id":"B0100",'
                '"issue":"Issue.","fix":"Fix.","verification":"Evidence."}'
                "\nextra trailing text"
            )
        )

    def test_natural_production_approval_requires_hermes_and_clear_intent(self) -> None:
        runner = load_schedule_runner()

        for text in (
            "<@U0HERMES123> I approve this for production",
            "Approved, <@U0HERMES123> — please proceed",
            "<@U0HERMES123> looks good; ship it",
            "<@U0HERMES123> go ahead and deploy this",
            "<@U0HERMES123> green light for production",
        ):
            with self.subTest(accepted=text):
                self.assertTrue(
                    runner.is_natural_production_approval(text, "U0HERMES123")
                )

        for text in (
            "I approve this for production",
            "<@U0HERMES123> do not approve this",
            "<@U0HERMES123> I cannot approve this",
            "<@U0HERMES123> can I approve this?",
            "<@U0HERMES123> I might approve this later",
            "<@U0HERMES123> I approve if the final check passes",
            "<@U0HERMES123> I approve staging only",
            "approve prod B0100",
        ):
            with self.subTest(rejected=text):
                self.assertFalse(
                    runner.is_natural_production_approval(text, "U0HERMES123")
                )

    def test_slack_production_approval_is_thread_bound_authorized_and_single_use(
        self,
    ) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "proof": "No heartbeat arrived.",
            "example": "Worker alpha missed three polls.",
            "next_step": "Repair the worker.",
            "ticket_id": "B0100",
            "remediation_ready": True,
        }
        job = {
            "issue": issue,
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": True,
            "terminal_idle_confirmations": 0,
        }
        settings = {
            "authorized_slack_users": ["U-SIMON"],
            "hermes_slack_user_id": "U0HERMES123",
        }
        messages = [
            {
                "ts": "100.000003",
                "user": "U-OTHER",
                "text": "<@U0HERMES123> I approve this",
            },
            {
                "ts": "100.000004",
                "user": "U-SIMON",
                "text": "<@U0HERMES123> I do not approve this",
            },
            {
                "ts": "100.000005",
                "user": "U-SIMON",
                "text": "<@U0HERMES123> looks good — ship it",
            },
        ]

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner, "state_dir", return_value=Path(directory)):
                runner.register_production_candidate(
                    job,
                    channel="C-health",
                    thread_ts="100.000001",
                    staging_reply_ts="100.000002",
                    expires_days=14,
                )
                with (
                    mock.patch.object(
                        runner, "slack_thread_page", return_value=messages
                    ) as page,
                    mock.patch.object(runner, "post_message") as post,
                ):
                    runner.scan_slack_approvals("token", settings)
                    runner.scan_slack_approvals("token", settings)

                candidate = runner.candidates_in_states("queued")[0]
                self.assertEqual(candidate["approval_message_ts"], "100.000005")
                self.assertEqual(candidate["approved_by"], "U-SIMON")
                self.assertEqual(
                    candidate["approval_text_sha256"],
                    hashlib.sha256(
                        "<@U0HERMES123> looks good — ship it".encode()
                    ).hexdigest(),
                )
                self.assertEqual(
                    candidate["approval_hermes_user_id"], "U0HERMES123"
                )
                self.assertEqual(page.call_count, 1)
                self.assertEqual(post.call_count, 2)
                self.assertIn("not authorized", post.mock_calls[0].args[2])
                self.assertIn("approval recorded", post.mock_calls[1].args[2])

    def test_production_preflight_and_success_recheck_use_ticket_truth(self) -> None:
        runner = load_schedule_runner()
        staged = {
            "ticket": {
                "id": "B0100",
                "slug": "worker-offline",
                "repo": "ts-prefect",
                "status": "staging_verified",
            },
            "artifacts": [
                {
                    "id": "staging-artifact-1",
                    "artifact_type": "verification_evidence",
                    "metadata": {"environment": "staging", "verdict": "PASS"},
                    "created_at": "2026-09-03T07:59:00+00:00",
                }
            ],
        }
        completed = {
            "ticket": {
                "id": "B0100",
                "slug": "worker-offline",
                "repo": "ts-prefect",
                "status": "completed",
            },
            "artifacts": [
                {
                    "id": "artifact-1",
                    "artifact_type": "verification_evidence",
                    "metadata": {"environment": "production", "verdict": "PASS"},
                    "created_at": "2026-09-03T09:00:00+00:00",
                }
            ],
        }

        with mock.patch.object(
            runner, "autodev_call", return_value=staged
        ) as autodev_call:
            self.assertEqual(
                runner.staging_ticket_preflight("B0100"),
                (
                    True,
                    "ticket is staging_verified with PASS evidence staging-artifact-1",
                ),
            )
        autodev_call.assert_called_once_with(
            "get_ticket",
            {
                "project": "ts",
                "repo": "ts-prefect",
                "ticket_id": "B0100",
                "detail": "light",
                "include_events": False,
            },
        )
        with mock.patch.object(runner, "autodev_call", return_value=completed):
            verified, evidence = runner.production_ticket_verified(
                "B0100", "100.000003"
            )
        self.assertTrue(verified)
        self.assertIn("artifact-1", evidence)

        stale = completed | {
            "artifacts": [
                completed["artifacts"][0]
                | {"created_at": "1970-01-01T00:01:39+00:00"}
            ]
        }
        with mock.patch.object(runner, "autodev_call", return_value=stale):
            verified, evidence = runner.production_ticket_verified(
                "B0100", "100.000003"
            )
        self.assertFalse(verified)
        self.assertIn("recorded after approval", evidence)

        not_staged = staged | {"ticket": staged["ticket"] | {"status": "planned"}}
        with mock.patch.object(runner, "autodev_call", return_value=not_staged):
            ready, reason = runner.staging_ticket_preflight("B0100")
        self.assertFalse(ready)
        self.assertIn("not 'staging_verified'", reason)

    def test_production_queue_starts_only_one_ticket(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Issue",
            "proof": "Proof.",
            "example": "Example.",
            "next_step": "Fix.",
            "ticket_id": "B0100",
            "remediation_ready": True,
        }
        jobs = []
        for ticket_id in ("B0100", "B0101"):
            jobs.append(
                {
                    "issue": issue | {"ticket_id": ticket_id, "title": ticket_id},
                    "workspace_id": f"workspace-{ticket_id}",
                    "session_id": f"session-{ticket_id}",
                    "deep_link": f"conductor://workspace-{ticket_id}",
                    "launch_error": None,
                    "saw_working": True,
                    "terminal_idle_confirmations": 0,
                }
            )

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner, "state_dir", return_value=Path(directory)):
                for index, job in enumerate(jobs, start=1):
                    runner.register_production_candidate(
                        job,
                        channel="C-health",
                        thread_ts="100.000001",
                        staging_reply_ts=f"100.00000{index + 1}",
                        expires_days=14,
                    )
                with runner.approval_connection() as connection:
                    connection.execute(
                        """
                        UPDATE approval_candidates
                        SET state = 'queued', approval_message_ts = '100.000010',
                            approved_by = 'U-SIMON'
                        WHERE ticket_id = 'B0100'
                        """
                    )
                    connection.execute(
                        """
                        UPDATE approval_candidates
                        SET state = 'queued', approval_message_ts = '100.000011',
                            approved_by = 'U-SIMON'
                        WHERE ticket_id = 'B0101'
                        """
                    )
                with (
                    mock.patch.object(
                        runner, "staging_ticket_preflight", return_value=(True, "ready")
                    ),
                    mock.patch.object(
                        runner,
                        "ensure_promotion_session",
                        return_value=("promotion-1", "conductor://promotion-1"),
                    ) as ensure,
                    mock.patch.object(runner, "post_message"),
                ):
                    self.assertTrue(
                        runner.start_next_production(
                            "token",
                            {"max_runtime_minutes": 480},
                            {"agent": "codex", "model": "gpt-5.6-sol"},
                        )
                    )

                ensure.assert_called_once()
                self.assertEqual(len(runner.candidates_in_states("launching")), 1)
                self.assertEqual(len(runner.candidates_in_states("queued")), 1)

    def test_production_start_failures_stop_after_the_reviewed_retry_budget(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "proof": "No heartbeat arrived.",
            "example": "Worker alpha missed three polls.",
            "next_step": "Repair the worker.",
            "ticket_id": "B0100",
            "remediation_ready": True,
        }
        job = {
            "issue": issue,
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": True,
            "terminal_idle_confirmations": 0,
        }

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner, "state_dir", return_value=Path(directory)):
                runner.register_production_candidate(
                    job,
                    channel="C-health",
                    thread_ts="100.000001",
                    staging_reply_ts="100.000002",
                    expires_days=14,
                )
                with runner.approval_connection() as connection:
                    connection.execute(
                        """
                        UPDATE approval_candidates
                        SET state = 'queued', approval_message_ts = '100.000003',
                            approved_by = 'U-SIMON'
                        WHERE ticket_id = 'B0100'
                        """
                    )
                with mock.patch.object(
                    runner,
                    "staging_ticket_preflight",
                    side_effect=runner.RunnerError("Autodev unavailable"),
                ):
                    self.assertFalse(
                        runner.start_next_production(
                            "token", {"max_start_attempts": 2}, {"agent": "codex"}
                        )
                    )
                    self.assertEqual(
                        runner.candidates_in_states("queued")[0]["start_attempts"], 1
                    )
                    self.assertFalse(
                        runner.start_next_production(
                            "token", {"max_start_attempts": 2}, {"agent": "codex"}
                        )
                    )

                stopped = runner.candidates_in_states("stopped")[0]
                self.assertEqual(stopped["ticket_id"], "B0100")
                with runner.approval_connection() as connection:
                    terminal_result = connection.execute(
                        "SELECT terminal_result_json FROM approval_candidates "
                        "WHERE ticket_id = 'B0100'"
                    ).fetchone()[0]
                self.assertIn("startup could not complete after 2 attempts", terminal_result)

    def test_production_result_is_durable_and_retried_to_slack(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "proof": "No heartbeat arrived.",
            "example": "Worker alpha missed three polls.",
            "next_step": "Repair the worker.",
            "ticket_id": "B0100",
            "remediation_ready": True,
        }
        job = {
            "issue": issue,
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": True,
            "terminal_idle_confirmations": 0,
        }
        result = {
            "status": "PROD_VERIFIED",
            "ticket_id": "B0100",
            "issue": "A dead worker stopped scheduled jobs.",
            "fix": "The worker now recovers stale heartbeats.",
            "verification": "Production run run-2 passed with artifact art-2.",
        }

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner, "state_dir", return_value=Path(directory)):
                runner.register_production_candidate(
                    job,
                    channel="C-health",
                    thread_ts="100.000001",
                    staging_reply_ts="100.000002",
                    expires_days=14,
                )
                with runner.approval_connection() as connection:
                    connection.execute(
                        """
                        UPDATE approval_candidates
                        SET state = 'running', approval_message_ts = '100.000003',
                            approved_by = 'U-SIMON',
                            promotion_session_link = 'conductor://promotion-1'
                        WHERE ticket_id = 'B0100'
                        """
                    )
                candidate = runner.candidates_in_states("running")[0]
                with mock.patch.object(
                    runner,
                    "production_ticket_verified",
                    return_value=(True, "production PASS evidence artifact art-2"),
                ) as verified:
                    runner.finalize_production_candidate(candidate, result)
                verified.assert_called_once_with("B0100", "100.000003")

                with runner.approval_connection() as connection:
                    persisted = connection.execute(
                        "SELECT state, terminal_result_json, result_posted_at "
                        "FROM approval_candidates WHERE ticket_id = 'B0100'"
                    ).fetchone()
                self.assertEqual(persisted["state"], "prod_verified")
                self.assertIsNotNone(persisted["terminal_result_json"])
                self.assertIsNone(persisted["result_posted_at"])

                with mock.patch.object(
                    runner,
                    "post_message",
                    side_effect=[runner.RunnerError("Slack unavailable"), "100.000004"],
                ) as post:
                    with self.assertRaises(runner.RunnerError):
                        runner.post_pending_production_results("token")
                    runner.post_pending_production_results("token")

                self.assertEqual(post.call_count, 2)
                self.assertEqual(
                    post.mock_calls[0].kwargs["client_msg_id"],
                    post.mock_calls[1].kwargs["client_msg_id"],
                )
                self.assertIn(
                    "B0100 — production verified", post.mock_calls[1].args[2]
                )
                with runner.approval_connection() as connection:
                    posted_at = connection.execute(
                        "SELECT result_posted_at FROM approval_candidates "
                        "WHERE ticket_id = 'B0100'"
                    ).fetchone()[0]
                self.assertIsNotNone(posted_at)

    def test_failed_production_requires_an_approval_after_the_failure_reply(self) -> None:
        runner = load_schedule_runner()
        job = {
            "issue": {
                "title": "Worker offline",
                "proof": "No heartbeat arrived.",
                "example": "Worker alpha missed three polls.",
                "next_step": "Repair the worker.",
                "ticket_id": "B0100",
                "remediation_ready": True,
            },
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": True,
            "terminal_idle_confirmations": 0,
        }

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner, "state_dir", return_value=Path(directory)):
                runner.register_production_candidate(
                    job,
                    channel="C-health",
                    thread_ts="100.000001",
                    staging_reply_ts="100.000002",
                    expires_days=14,
                )
                with runner.approval_connection() as connection:
                    connection.execute(
                        """
                        UPDATE approval_candidates
                        SET state = 'running', approval_message_ts = '100.000003',
                            approved_by = 'U-SIMON'
                        WHERE ticket_id = 'B0100'
                        """
                    )
                candidate = runner.candidates_in_states("running")[0]
                runner.finalize_production_candidate(
                    candidate,
                    runner.stopped_production(candidate, "the session failed"),
                )
                with mock.patch.object(
                    runner, "post_message", return_value="100.000010"
                ):
                    runner.post_pending_production_results("token")

                messages = [
                    {
                        "ts": "100.000009",
                        "user": "U-SIMON",
                        "text": "<@U0HERMES123> I approve this",
                    },
                    {
                        "ts": "100.000011",
                        "user": "U-SIMON",
                        "text": "<@U0HERMES123> I approve this",
                    },
                ]
                with (
                    mock.patch.object(
                        runner, "slack_thread_page", return_value=messages
                    ),
                    mock.patch.object(runner, "post_message"),
                ):
                    runner.scan_slack_approvals(
                        "token",
                        {
                            "authorized_slack_users": ["U-SIMON"],
                            "hermes_slack_user_id": "U0HERMES123",
                        },
                    )

                queued = runner.candidates_in_states("queued")[0]
                self.assertEqual(queued["approval_not_before_ts"], "100.000010")
                self.assertEqual(queued["approval_message_ts"], "100.000011")

    def test_retention_preserves_workspaces_with_open_production_approval(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "proof": "No heartbeat arrived.",
            "example": "Worker alpha missed three polls.",
            "next_step": "Repair the worker.",
            "ticket_id": "B0100",
            "remediation_ready": True,
        }
        job = {
            "issue": issue,
            "workspace_id": "workspace-1",
            "session_id": "session-1",
            "deep_link": "conductor://workspace-1",
            "launch_error": None,
            "saw_working": True,
            "terminal_idle_confirmations": 0,
        }
        manifest = {
            "runner": {"retention_days_pass": 3, "retention_days_fail": 14},
            "schedules": [{"name": "health-6h"}],
        }

        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(runner, "state_dir", return_value=Path(directory)):
                Path(directory, "health-6h.history.jsonl").write_text(
                    json.dumps(
                        {
                            "completed_at": "2026-01-01T00:00:00+00:00",
                            "status": "AWAITING_PROD_APPROVAL",
                            "workspace_id": "workspace-1",
                            "archived": False,
                        }
                    )
                    + "\n"
                )
                runner.register_production_candidate(
                    job,
                    channel="C-health",
                    thread_ts="100.000001",
                    staging_reply_ts="100.000002",
                    expires_days=14,
                )
                with mock.patch.object(runner, "conductor_call") as conductor_call:
                    runner.apply_retention(manifest)
                conductor_call.assert_not_called()

                runner.set_candidate_state("B0100", "expired")
                with mock.patch.object(runner, "conductor_call") as conductor_call:
                    runner.apply_retention(manifest)
                conductor_call.assert_called_once_with(
                    "archive_workspace", {"workspace_id": "workspace-1"}
                )

    def test_dream_result_block_and_noop_report_are_structured(self) -> None:
        runner = load_schedule_runner()
        message = (
            "SCHEDULED_RUN_RESULT\n"
            "status: PASS\n"
            "schedule: nightly-dream\n"
            "summary: bounded consolidation completed\n"
            "checks_total: 4\n"
            "checks_failed: 0\n"
            "tickets_touched: []\n"
            "rc_fingerprints: []\n"
            'dream_report: {"what":"Reviewed tickets, memories, and graph candidates; '
            'prepared two proposals and applied no changes.","why":"No memory action '
            'survived the safety gate and graph work is proposal-only.","how":"Used bounded '
            'evidence, root-cause deduplication, and the adversarial gate.",'
            '"memory_actions":[],"ticket_consolidations":[],"proposals":['
            '"Repair one stale memory — needs human review",'
            '"Collapse one graph cluster — graph writes require approval"],'
            '"graph_plan":"One graph cleanup candidate is ready for review.",'
            '"scope":["Tickets: last 14 days","Memory: 50 entries",'
            '"Graph: bounded production sample"]}\n'
        )

        parsed = runner.parse_result_block(message)

        self.assertIsNotNone(parsed)
        report = parsed["dream_report"]
        self.assertEqual(report["memory_actions"], [])
        self.assertEqual(len(report["proposals"]), 2)
        self.assertEqual(
            runner.nightly_dream_parent_message("✅", report),
            "✅ [nightly-dream] No changes applied · 0 memory actions · "
            "0 tickets consolidated · 0 graph writes · 2 proposals",
        )

    def test_nightly_dream_parent_counts_applied_actions(self) -> None:
        runner = load_schedule_runner()
        report = {
            "what": "Applied three safe consolidations.",
            "why": "Each action survived the adversarial gate.",
            "how": "Compared bounded ticket and memory evidence.",
            "memory_actions": [
                "mem-1 — repaired — stale fact corrected",
                "mem-2 — superseded — canonical replacement exists",
            ],
            "ticket_consolidations": [
                "B0100 — extended — recurring root cause matched",
            ],
            "proposals": [],
            "graph_plan": "No graph cleanup candidate survived review.",
            "scope": ["Tickets: last 14 days"],
        }

        self.assertEqual(
            runner.nightly_dream_parent_message("✅", report),
            "✅ [nightly-dream] 3 changes applied · 2 memory actions · "
            "1 ticket consolidated · 0 graph writes · 0 proposals",
        )

    def test_nightly_dream_report_rejects_missing_scope(self) -> None:
        runner = load_schedule_runner()
        report = {
            "what": "Reviewed the bounded evidence.",
            "why": "No change was necessary.",
            "how": "Applied the adversarial gate.",
            "memory_actions": [],
            "ticket_consolidations": [],
            "proposals": [],
            "graph_plan": "No graph plan was produced.",
            "scope": [],
        }

        self.assertIsNone(runner.parse_dream_report(report))

    def test_matching_health_issue_aliases_are_accepted(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Worker offline",
            "concrete_proof": "No heartbeat in 15m",
            "proof": " No heartbeat in 15m ",
            "representative_example": "Worker alpha missed three polls",
            "example": " Worker alpha missed three polls ",
            "next_step": "Restart worker alpha",
            "owning_ticket_id": "B0100",
            "ticket_id": " B0100 ",
            "remediation_ready": True,
        }

        self.assertIsNotNone(runner.parse_health_issues([issue]))

    def test_conflicting_health_issue_aliases_are_rejected(self) -> None:
        runner = load_schedule_runner()
        canonical_issue = {
            "title": "Worker offline",
            "concrete_proof": "No heartbeat in 15m",
            "representative_example": "Worker alpha missed three polls",
            "next_step": "Restart worker alpha",
            "owning_ticket_id": "B0100",
            "remediation_ready": True,
        }
        conflicts = {
            "proof": "A different aggregate finding",
            "example": "A different occurrence",
            "ticket_id": "B0200",
        }

        for legacy_key, conflicting_value in conflicts.items():
            with self.subTest(legacy_key=legacy_key):
                issue = canonical_issue | {legacy_key: conflicting_value}
                self.assertIsNone(runner.parse_health_issues([issue]))

    def test_malformed_health_issue_evidence_is_rejected(self) -> None:
        runner = load_schedule_runner()
        valid_issue = {
            "title": "Worker offline",
            "concrete_proof": "No heartbeat in 15m",
            "representative_example": "Worker alpha missed three polls",
            "next_step": "Restart worker alpha",
            "owning_ticket_id": "B0100",
            "remediation_ready": True,
        }
        malformed_issues = {
            "missing proof": {
                key: value
                for key, value in valid_issue.items()
                if key != "concrete_proof"
            },
            "blank proof": valid_issue | {"concrete_proof": "  "},
            "missing example": {
                key: value
                for key, value in valid_issue.items()
                if key != "representative_example"
            },
            "non-string example": valid_issue | {"representative_example": 7},
            "non-string ticket": valid_issue | {"owning_ticket_id": 100},
            "non-boolean readiness": valid_issue | {"remediation_ready": "yes"},
        }

        for case, issue in malformed_issues.items():
            with self.subTest(case=case):
                self.assertIsNone(runner.parse_health_issues([issue]))

    def test_health_report_parent_is_one_issue_list(self) -> None:
        runner = load_schedule_runner()
        result = {
            "issues": [
                {
                    "title": "Discord monitor cannot fetch channels",
                    "proof": "Twelve verified Discord API 403 responses in six hours.",
                    "example": "The SNDK channel failed at 07:15 UTC.",
                    "next_step": "Restore the monitor's channel access.",
                    "ticket_id": "B0349",
                    "remediation_ready": True,
                },
                {
                    "title": "Tradable scheduler is stale",
                    "proof": "No successful run completed inside the freshness window.",
                    "example": "The latest tradable run is eight hours old.",
                    "next_step": "Restart the stalled tradable schedule.",
                    "ticket_id": "B0365",
                    "remediation_ready": True,
                },
            ]
        }
        issues = runner.health_issues(result, "two checks failed", "FAIL")

        self.assertEqual(
            runner.health_parent_message("❌", issues, "two checks failed"),
            "❌ [health-6h] 2 issues\n"
            "• Discord monitor cannot fetch channels — ticket `B0349`\n"
            "• Tradable scheduler is stale — ticket `B0365`",
        )

    def test_health_report_falls_back_when_run_has_no_structured_issue(self) -> None:
        runner = load_schedule_runner()
        issues = runner.health_issues(None, "agent session errored", "FAIL")

        self.assertEqual(
            issues,
            [
                {
                    "title": "Scheduled health run failed",
                    "proof": "agent session errored",
                    "example": "The run did not return structured issue evidence.",
                    "next_step": "Open the run thread and inspect the scheduler failure.",
                    "ticket_id": None,
                    "remediation_ready": False,
                }
            ],
        )

    def test_health_schedule_posts_one_top_level_message_per_issue(self) -> None:
        runner = load_schedule_runner()
        manifest = {
            "runner": {"poll_seconds": 1},
            "slack_channels": {
                "#autodev-health": "C-health",
                "#autodev-incidents": "C-incidents",
            },
            "production_approval": {
                "enabled": True,
                "hermes_slack_user_id": "U0HERMES123",
                "authorized_slack_users": ["U-SIMON"],
                "expires_days": 14,
            },
            "schedules": [
                {
                    "name": "health-6h",
                    "enabled": True,
                    "prompt": "health-6h.md",
                    "slack_channel": "#autodev-health",
                    "max_runtime_minutes": 90,
                    "remediation_max_runtime_minutes": 420,
                }
            ],
        }
        result = {
            "status": "FAIL",
            "summary": "two checks failed",
            "issues": [
                {
                    "title": "Discord monitor cannot fetch channels",
                    "proof": "Discord returned twelve HTTP 403 responses.",
                    "example": "The SNDK channel failed at 07:15 UTC.",
                    "next_step": "Restore the monitor's channel access.",
                    "ticket_id": "B0349",
                    "remediation_ready": True,
                },
                {
                    "title": "Tradable scheduler is stale",
                    "proof": "No successful run completed in eight hours.",
                    "example": "The 06:00 UTC run never started.",
                    "next_step": "Restart the stalled tradable schedule.",
                    "ticket_id": "B0365",
                    "remediation_ready": True,
                },
            ],
        }
        normalized_issues = runner.parse_health_issues(result["issues"])
        self.assertIsNotNone(normalized_issues)
        jobs = [
            {
                "issue": normalized_issues[0],
                "workspace_id": "remediation-1",
                "session_id": "session-1",
                "deep_link": "conductor://remediation-1",
                "launch_error": None,
                "saw_working": True,
                "terminal_idle_confirmations": 0,
            },
            {
                "issue": normalized_issues[1],
                "workspace_id": "remediation-2",
                "session_id": "session-2",
                "deep_link": "conductor://remediation-2",
                "launch_error": None,
                "saw_working": True,
                "terminal_idle_confirmations": 0,
            },
        ]
        remediations = [
            (
                jobs[0],
                {
                    "status": "STAGING_VERIFIED",
                    "ticket_id": "B0349",
                    "issue": (
                        "Expired Discord access caused every monitored channel request "
                        "to return 403."
                    ),
                    "fix": "The monitor now refreshes and validates channel access before polling.",
                    "verification": (
                        "Staging run flow-123 passed on revision abc123 with evidence "
                        "artifact art-1."
                    ),
                },
            ),
            (
                jobs[1],
                {
                    "status": "STAGING_VERIFIED",
                    "ticket_id": "B0365",
                    "issue": (
                        "A stale schedule lease prevented the tradable scheduler from "
                        "starting."
                    ),
                    "fix": "The lease recovery path now releases expired scheduler ownership.",
                    "verification": (
                        "Staging run flow-456 passed on revision def456 with evidence "
                        "artifact art-2."
                    ),
                },
            ),
        ]
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(runner, "load_manifest", return_value=manifest),
                mock.patch.object(runner, "state_dir", return_value=Path(directory)),
                mock.patch.object(runner, "read_slack_token", return_value="token"),
                mock.patch.object(
                    runner,
                    "launch_workspace",
                    return_value=("workspace", "session", "conductor://run"),
                ),
                mock.patch.object(runner, "conductor_call"),
                mock.patch.object(
                    runner,
                    "poll_session",
                    return_value=("finished", result),
                ),
                mock.patch.object(
                    runner,
                    "launch_health_remediations",
                    return_value=jobs,
                ),
                mock.patch.object(
                    runner,
                    "supervise_health_remediations",
                    return_value=iter(remediations),
                ),
                mock.patch.object(
                    runner,
                    "post_message",
                    side_effect=["parent", "incident", "reply-1", "reply-2"],
                ) as post,
                mock.patch.object(
                    runner,
                    "message_permalink",
                    return_value="https://slack.example/thread",
                ),
                mock.patch.object(
                    runner, "register_production_candidate"
                ) as register_candidate,
                mock.patch.object(runner, "record_run"),
            ):
                exit_code = runner.run_schedule("health-6h")

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            post.mock_calls,
            [
                mock.call(
                    "token",
                    "C-health",
                    "❌ [health-6h] 2 issues — 2/2 remediation workspaces started\n"
                    "• Discord monitor cannot fetch channels — ticket `B0349` — "
                    "<conductor://remediation-1|Open workspace>\n"
                    "• Tradable scheduler is stale — ticket `B0365` — "
                    "<conductor://remediation-2|Open workspace>",
                ),
                mock.call(
                    "token",
                    "C-incidents",
                    "❌ *health-6h needs attention* <@U09T4LELYES>\n"
                    "*Discord monitor cannot fetch channels*\n"
                    "> *Proof:* Discord returned twelve HTTP 403 responses.\n"
                    "> *Example:* The SNDK channel failed at 07:15 UTC.\n"
                    "> *Next:* Restore the monitor's channel access.\n"
                    "> *Ticket:* `B0349`\n"
                    "\n"
                    "*Tradable scheduler is stale*\n"
                    "> *Proof:* No successful run completed in eight hours.\n"
                    "> *Example:* The 06:00 UTC run never started.\n"
                    "> *Next:* Restart the stalled tradable schedule.\n"
                    "> *Ticket:* `B0365`\n"
                    "\n"
                    "• *Details:* <https://slack.example/thread|Open the run thread>",
                ),
                mock.call(
                    "token",
                    "C-health",
                    "✅ *B0349 — Discord monitor cannot fetch channels — staging verified*\n"
                    "• *Issue:* Expired Discord access caused every monitored channel "
                    "request to return 403.\n"
                    "• *Fix:* The monitor now refreshes and validates channel access before "
                    "polling.\n"
                    "• *Verification:* Staging run flow-123 passed on revision abc123 with "
                    "evidence artifact art-1.\n"
                    "• *Workspace:* <conductor://remediation-1|Open in Conductor>\n"
                    "• *Approve production:* Reply in this issue's thread, tag @Hermes, "
                    "and clearly approve in your own words — for example, “@Hermes I "
                    "approve this for production.”",
                ),
                mock.call(
                    "token",
                    "C-health",
                    "✅ *B0365 — Tradable scheduler is stale — staging verified*\n"
                    "• *Issue:* A stale schedule lease prevented the tradable scheduler "
                    "from starting.\n"
                    "• *Fix:* The lease recovery path now releases expired scheduler "
                    "ownership.\n"
                    "• *Verification:* Staging run flow-456 passed on revision def456 with "
                    "evidence artifact art-2.\n"
                    "• *Workspace:* <conductor://remediation-2|Open in Conductor>\n"
                    "• *Approve production:* Reply in this issue's thread, tag @Hermes, "
                    "and clearly approve in your own words — for example, “@Hermes I "
                    "approve this for production.”",
                ),
            ],
        )
        self.assertEqual(
            register_candidate.mock_calls,
            [
                mock.call(
                    jobs[0],
                    channel="C-health",
                    thread_ts="reply-1",
                    staging_reply_ts="reply-1",
                    expires_days=14,
                ),
                mock.call(
                    jobs[1],
                    channel="C-health",
                    thread_ts="reply-2",
                    staging_reply_ts="reply-2",
                    expires_days=14,
                ),
            ],
        )

    def test_waitable_schedule_result_does_not_page_incidents(self) -> None:
        runner = load_schedule_runner()
        manifest = {
            "runner": {"poll_seconds": 1},
            "slack_channels": {
                "#autodev-nightly": "C-nightly",
                "#autodev-incidents": "C-incidents",
            },
            "schedules": [
                {
                    "name": "waitable-test",
                    "enabled": True,
                    "prompt": "nightly-verify-promote.md",
                    "slack_channel": "#autodev-nightly",
                    "max_runtime_minutes": 150,
                }
            ],
        }
        result = {
            "status": "NEEDS_MORE_TIME",
            "summary": "provider deployment is healthy and still progressing",
            "checks_total": "1",
            "checks_failed": "0",
            "tickets_touched": ["F0001"],
            "rc_fingerprints": [],
            "resume_command": "wait-provider-deploy deploy-123",
        }
        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(runner, "load_manifest", return_value=manifest),
                mock.patch.object(runner, "state_dir", return_value=Path(directory)),
                mock.patch.object(runner, "read_slack_token", return_value="token"),
                mock.patch.object(
                    runner,
                    "launch_workspace",
                    return_value=("workspace", "session", "conductor://run"),
                ),
                mock.patch.object(runner, "conductor_call"),
                mock.patch.object(
                    runner,
                    "poll_session",
                    return_value=("finished", result),
                ),
                mock.patch.object(
                    runner,
                    "post_message",
                    side_effect=["parent", "reply"],
                ) as post,
                mock.patch.object(runner, "message_permalink") as permalink,
                mock.patch.object(runner, "record_run") as record_run,
            ):
                exit_code = runner.run_schedule("waitable-test")

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(post.mock_calls), 2)
        self.assertEqual(
            post.mock_calls[0],
            mock.call(
                "token",
                "C-nightly",
                "⏳ [waitable-test] provider deployment is healthy and still progressing",
            ),
        )
        permalink.assert_not_called()
        record_run.assert_called_once_with("waitable-test", "NEEDS_MORE_TIME", "workspace")

    def test_nightly_dream_posts_structured_reply_without_machine_dump(self) -> None:
        runner = load_schedule_runner()
        manifest = {
            "runner": {"poll_seconds": 1},
            "slack_channels": {
                "#autodev-nightly": "C-nightly",
                "#autodev-incidents": "C-incidents",
            },
            "schedules": [
                {
                    "name": "nightly-dream",
                    "enabled": True,
                    "prompt": "nightly-dream.md",
                    "slack_channel": "#autodev-nightly",
                    "max_runtime_minutes": 150,
                }
            ],
        }
        report = {
            "what": "Reviewed bounded tickets, memories, and graph candidates.",
            "why": "No mutation survived the safety gate.",
            "how": "Used bounded evidence, deduplication, and adversarial review.",
            "memory_actions": [],
            "ticket_consolidations": [],
            "proposals": [
                "Repair one stale memory — needs human review",
                "Collapse one graph cluster — graph writes require approval",
            ],
            "graph_plan": "One graph cleanup candidate is ready for review.",
            "scope": [
                "Tickets: last 14 days",
                "Memory: 50 entries",
                "Graph: bounded production sample",
            ],
        }
        result = {
            "status": "PASS",
            "summary": "bounded consolidation completed",
            "checks_total": "4",
            "checks_failed": "0",
            "tickets_touched": [],
            "rc_fingerprints": [],
            "dream_report": report,
        }
        started = runner.datetime.fromisoformat("2026-08-05T03:30:00+00:00")

        with tempfile.TemporaryDirectory() as directory:
            with (
                mock.patch.object(runner, "load_manifest", return_value=manifest),
                mock.patch.object(runner, "state_dir", return_value=Path(directory)),
                mock.patch.object(runner, "read_slack_token", return_value="token"),
                mock.patch.object(runner, "utc_now", return_value=started),
                mock.patch.object(
                    runner,
                    "launch_workspace",
                    return_value=("workspace-1", "session-1", "conductor://workspace-1"),
                ),
                mock.patch.object(runner, "conductor_call"),
                mock.patch.object(
                    runner,
                    "poll_session",
                    return_value=("finished", result),
                ),
                mock.patch.object(
                    runner,
                    "post_message",
                    side_effect=["parent", "reply"],
                ) as post,
                mock.patch.object(runner, "record_run"),
            ):
                exit_code = runner.run_schedule("nightly-dream")

        self.assertEqual(exit_code, 0)
        self.assertEqual(
            post.mock_calls[0],
            mock.call(
                "token",
                "C-nightly",
                "✅ [nightly-dream] No changes applied · 0 memory actions · "
                "0 tickets consolidated · 0 graph writes · 2 proposals",
            ),
        )
        reply = post.mock_calls[1].args[2]
        for section in (
            "*What was done*",
            "*Why*",
            "*How*",
            "*Memory actions (0)*",
            "*Tickets consolidated (0)*",
            "*Graph writes (0)*",
            "*Proposals (2)*",
            "*Graph plan*",
            "*Scope reviewed*",
            "*Run details*",
        ):
            with self.subTest(section=section):
                self.assertIn(section, reply)
        self.assertIn("• Checks: 4 total · 0 failed", reply)
        self.assertIn("<conductor://workspace-1|Open in Conductor>", reply)
        self.assertNotIn("SCHEDULED_RUN_RESULT", reply)
        self.assertNotIn("```", reply)
        self.assertEqual(post.mock_calls[1].kwargs, {"thread_ts": "parent"})

    def test_generic_incident_message_is_concise_and_evidence_first(self) -> None:
        runner = load_schedule_runner()
        result = {
            "checks_total": "12",
            "checks_failed": "3",
            "tickets_touched": ["B0347", "F0298"],
            "blocked_on": "Grant the scheduler permission to update admin-origin tickets.",
        }

        self.assertEqual(
            runner.incident_message(
                "nightly-verify-promote",
                "BLOCKED",
                "verification evidence could not be saved",
                result,
                [],
                "https://slack.example/thread",
            ),
            "⛔ *nightly-verify-promote needs attention* <@U09T4LELYES>\n"
            "• *What happened:* verification evidence could not be saved\n"
            "• *Proof:* The run reported 3 failed checks out of 12.\n"
            "• *Tickets:* `B0347`, `F0298`\n"
            "• *Next:* Grant the scheduler permission to update admin-origin tickets.\n"
            "• *Details:* <https://slack.example/thread|Open the run thread>",
        )

    def test_incident_message_limits_issue_detail_to_three_items(self) -> None:
        runner = load_schedule_runner()
        issues = [
            {
                "title": f"Issue {number}",
                "proof": f"Proof {number}.",
                "example": f"Example {number}.",
                "next_step": f"Fix {number}.",
                "ticket_id": f"B{number:04d}",
            }
            for number in range(1, 5)
        ]

        message = runner.incident_message(
            "health-6h", "FAIL", "four issues", {"issues": issues}, issues, None
        )

        self.assertIn("*Issue 3*\n> *Proof:* Proof 3.", message)
        self.assertNotIn("*Issue 4*", message)
        self.assertIn("*1 more issues:* See the linked run thread.", message)

    def test_incident_message_does_not_style_ticket_failure_as_code(self) -> None:
        runner = load_schedule_runner()
        issue = {
            "title": "Truth Social polling is blocked",
            "proof": "The source circuit is open.",
            "example": "The latest poller run skipped Truth Social.",
            "next_step": "Review the open circuit evidence.",
            "ticket_id": "No owning ticket could be assigned because MCP tools are unavailable.",
        }

        message = runner.incident_message(
            "health-6h", "FAIL", "one issue", {"issues": [issue]}, [issue], None
        )

        self.assertIn(
            "> *Ticket:* No owning ticket could be assigned because MCP tools are unavailable.",
            message,
        )
        self.assertNotIn("`No owning ticket", message)

    def test_system_alerts_use_human_readable_evidence_bullets(self) -> None:
        runner = load_schedule_runner()

        self.assertEqual(
            runner.unit_failure_message("health-6h", "hermes-schedule@health-6h.service"),
            "❌ *health-6h scheduler service failed* <@U09T4LELYES>\n"
            "• *Proof:* systemd marked `hermes-schedule@health-6h.service` as failed.\n"
            "• *Example:* `journalctl -u hermes-schedule@health-6h.service` shows the "
            "traceback.\n"
            "• *Next:* Inspect the traceback, fix the service, then restart the unit.",
        )
        self.assertEqual(
            runner.watchdog_message("health-6h", "last report 22.3h ago", 6),
            "⚠️ *health-6h has stopped reporting* <@U09T4LELYES>\n"
            "• *Proof:* last report 22.3h ago; expected a report every 6h.\n"
            "• *Example:* Check `systemctl status hermes-schedule@health-6h.service` on "
            "Hermes.\n"
            "• *Next:* Restore the timer or runner, then confirm the next Slack report "
            "arrives.",
        )

    def test_watchdog_interval_inference_matches_manifest_crons(self) -> None:
        runner = load_schedule_runner()
        self.assertEqual(runner.cron_interval_hours("0 2 * * *"), 24)
        self.assertEqual(runner.cron_interval_hours("30 3 * * *"), 24)
        self.assertEqual(runner.cron_interval_hours("0 */6 * * *"), 6)
        with self.assertRaises(runner.RunnerError):
            runner.cron_interval_hours("not a cron")

    def test_disabled_schedule_is_skipped_without_credentials(self) -> None:
        runner = load_schedule_runner()
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "schedules.yaml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "deployment_contract_version": 1,
                        "slack_channels": {"#autodev-incidents": "C000"},
                        "schedules": [
                            {
                                "name": "staged-run",
                                "cron": "0 2 * * *",
                                "prompt": "staged-run.md",
                                "workspace": {"repo": "ts-prefect", "branch": "staging"},
                                "slack_channel": "#autodev-incidents",
                                "max_runtime_minutes": 30,
                                "enabled": False,
                            }
                        ],
                    }
                )
            )
            with mock.patch.object(runner, "MANIFEST_PATH", manifest):
                with mock.patch.object(runner, "conductor_call") as conductor:
                    with mock.patch.object(runner, "read_slack_token") as slack:
                        exit_code = runner.run_schedule("staged-run")
        self.assertEqual(exit_code, 0)
        conductor.assert_not_called()
        slack.assert_not_called()


if __name__ == "__main__":
    unittest.main()


class HermesArchiveOnCompleteTests(unittest.TestCase):
    def _runner_with_state(self, tmp: str):
        runner = load_schedule_runner()
        os.environ["STATE_DIRECTORY"] = tmp
        return runner

    def test_pass_archives_immediately_and_marks_history(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner_with_state(tmp)
            runner.record_run("health-6h", "PASS", "ws-1")
            with mock.patch.object(runner, "conductor_call", return_value={}) as call:
                archived = runner.archive_completed_workspace(
                    {"runner": {"archive_on_complete": ["PASS"]}}, "health-6h", "PASS", "ws-1"
                )
            self.assertTrue(archived)
            call.assert_called_once_with("archive_workspace", {"workspace_id": "ws-1"})
            history = runner.history_path("health-6h").read_text().splitlines()
            self.assertTrue(json.loads(history[-1])["archived"])

    def test_fail_and_needs_more_time_are_left_open_by_default(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner_with_state(tmp)
            with mock.patch.object(runner, "conductor_call") as call:
                for status in ("FAIL", "BLOCKED", "NEEDS_MORE_TIME"):
                    self.assertFalse(
                        runner.archive_completed_workspace({"runner": {}}, "x", status, "ws-2")
                    )
            call.assert_not_called()

    def test_archive_failure_is_best_effort(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            runner = self._runner_with_state(tmp)
            runner.record_run("x", "PASS", "ws-3")
            with mock.patch.object(
                runner, "conductor_call", side_effect=runner.RunnerError("boom")
            ):
                self.assertFalse(
                    runner.archive_completed_workspace({"runner": {}}, "x", "PASS", "ws-3")
                )
            self.assertFalse(json.loads(runner.history_path("x").read_text())["archived"])

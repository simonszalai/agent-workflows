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
        for relative in (
            "install.sh",
            "bin/run-autodev-memory",
            "conductor/server.py",
            "schedules/runner.py",
        ):
            mode = (HERMES / relative).stat().st_mode
            self.assertTrue(mode & stat.S_IXUSR, relative)

    def test_runbook_names_the_current_ts_scoped_token(self) -> None:
        runbook = (HERMES / "README.md").read_text()
        self.assertIn("TS/TS_AUTODEV_MEMORY_API_TOKEN", runbook)
        self.assertNotIn("AUTODEV-sensitive/HERMES_AUTODEV_MEMORY_TOKEN", runbook)
        self.assertIn("TS/TS_SLACK_MCP_USER_TOKEN", runbook)
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
        for entry in manifest["schedules"]:
            with self.subTest(entry=entry.get("name")):
                self.assertIn(entry["slack_channel"], channels)
                self.assertIsInstance(entry["enabled"], bool)
                self.assertGreater(entry["max_runtime_minutes"], 0)
                self.assertTrue(entry["workspace"]["repo"])
                self.assertTrue(entry["workspace"]["branch"])
                prompt = HERMES / "schedules" / entry["prompt"]
                self.assertTrue(prompt.is_file(), entry["prompt"])
                self.assertNotEqual(entry["prompt"], "README.md")

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

    def test_health_schedule_investigates_clusters_in_current_workspace(self) -> None:
        prompt = (HERMES / "schedules" / "health-6h.md").read_text().replace("\n", " ")

        self.assertIn(
            "bounded cluster investigation within the current scheduled workspace",
            prompt,
        )
        self.assertIn("one durable owning ticket with investigation evidence", prompt)
        self.assertIn("recurrences extend that ticket by `rc_fingerprint`", prompt)
        self.assertIn("Never create a follow-up Conductor workspace", prompt)
        self.assertIn("never emit or request spawn placeholders", prompt)
        for obsolete_promise in (
            "spawn one investigation workspace",
            "would spawn",
            "spawn_requests",
        ):
            with self.subTest(obsolete_promise=obsolete_promise):
                self.assertNotIn(obsolete_promise, prompt.lower())

    def test_health_issue_contract_uses_exact_canonical_keys(self) -> None:
        prompt = (HERMES / "schedules" / "health-6h.md").read_text().replace("\n", " ")
        contract = (ROOT / "skills" / "references" / "scheduled-run.md").read_text()
        canonical_keys = (
            "`title`, `concrete_proof`, `representative_example`, `next_step`, "
            "and `owning_ticket_id`"
        )
        canonical_schema = """{
  "title": "<short name>",
  "concrete_proof": "<aggregate evidence>",
  "representative_example": "<one occurrence>",
  "next_step": "<specific action>",
  "owning_ticket_id": "<ID or null>"
}"""

        self.assertIn(canonical_keys, prompt)
        self.assertIn(canonical_schema, contract)
        self.assertIn("input-only legacy aliases", contract)

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
        self.assertIn("OnFailure=hermes-schedule-alert@watchdog.service", watchdog)
        watchdog_timer = (
            HERMES / "systemd" / "hermes-schedule-watchdog.timer"
        ).read_text()
        self.assertIn("America/Vancouver", watchdog_timer)

    def test_installer_deploys_the_schedule_stack(self) -> None:
        installer = (HERMES / "install.sh").read_text()
        self.assertIn("check_credential /etc/hermes-schedules/slack.token", installer)
        self.assertIn("/opt/hermes-schedules", installer)
        self.assertIn("hermes/schedules/requirements.txt", installer)
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
            '"next_step":"Restart worker alpha","owning_ticket_id":"B0100"}]\n'
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
                }
            ],
        )
        issues = runner.health_issues(parsed, "one check failed", "FAIL")
        self.assertEqual(
            runner.health_parent_message("❌", issues, "one check failed"),
            "❌ [health-6h] 1 issue\n• Worker offline — ticket `B0100`",
        )
        self.assertEqual(
            runner.health_issue_reply(issues[0]),
            "*Worker offline*\n"
            "• *Proof:* No heartbeat in 15m\n"
            "• *Example:* Worker alpha missed three polls\n"
            "• *Next:* Restart worker alpha\n"
            "• *Ticket:* `B0100`",
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
                }
            ],
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
        }

        for case, issue in malformed_issues.items():
            with self.subTest(case=case):
                self.assertIsNone(runner.parse_health_issues([issue]))

    def test_health_report_is_one_parent_list_and_one_reply_per_issue(self) -> None:
        runner = load_schedule_runner()
        result = {
            "issues": [
                {
                    "title": "Discord monitor cannot fetch channels",
                    "proof": "Twelve verified Discord API 403 responses in six hours.",
                    "example": "The SNDK channel failed at 07:15 UTC.",
                    "next_step": "Restore the monitor's channel access.",
                    "ticket_id": "B0349",
                },
                {
                    "title": "Tradable scheduler is stale",
                    "proof": "No successful run completed inside the freshness window.",
                    "example": "The latest tradable run is eight hours old.",
                    "next_step": "Restart the stalled tradable schedule.",
                    "ticket_id": "B0365",
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
        self.assertEqual(
            [runner.health_issue_reply(issue) for issue in issues],
            [
                "*Discord monitor cannot fetch channels*\n"
                "• *Proof:* Twelve verified Discord API 403 responses in six hours.\n"
                "• *Example:* The SNDK channel failed at 07:15 UTC.\n"
                "• *Next:* Restore the monitor's channel access.\n"
                "• *Ticket:* `B0349`",
                "*Tradable scheduler is stale*\n"
                "• *Proof:* No successful run completed inside the freshness window.\n"
                "• *Example:* The latest tradable run is eight hours old.\n"
                "• *Next:* Restart the stalled tradable schedule.\n"
                "• *Ticket:* `B0365`",
            ],
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
                }
            ],
        )
        self.assertEqual(
            runner.health_issue_reply(issues[0]),
            "*Scheduled health run failed*\n"
            "• *Proof:* agent session errored\n"
            "• *Example:* The run did not return structured issue evidence.\n"
            "• *Next:* Open the run thread and inspect the scheduler failure.\n"
            "• *Ticket:* `No ticket assigned`",
        )

    def test_health_schedule_posts_exactly_one_reply_per_issue(self) -> None:
        runner = load_schedule_runner()
        manifest = {
            "runner": {"poll_seconds": 1},
            "slack_channels": {
                "#autodev-health": "C-health",
                "#autodev-incidents": "C-incidents",
            },
            "schedules": [
                {
                    "name": "health-6h",
                    "enabled": True,
                    "prompt": "health-6h.md",
                    "slack_channel": "#autodev-health",
                    "max_runtime_minutes": 90,
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
                },
                {
                    "title": "Tradable scheduler is stale",
                    "proof": "No successful run completed in eight hours.",
                    "example": "The 06:00 UTC run never started.",
                    "next_step": "Restart the stalled tradable schedule.",
                    "ticket_id": "B0365",
                },
            ],
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
                    side_effect=["parent", "reply-1", "reply-2", "incident"],
                ) as post,
                mock.patch.object(
                    runner,
                    "message_permalink",
                    return_value="https://slack.example/thread",
                ),
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
                    "❌ [health-6h] 2 issues\n"
                    "• Discord monitor cannot fetch channels — ticket `B0349`\n"
                    "• Tradable scheduler is stale — ticket `B0365`",
                ),
                mock.call(
                    "token",
                    "C-health",
                    "*Discord monitor cannot fetch channels*\n"
                    "• *Proof:* Discord returned twelve HTTP 403 responses.\n"
                    "• *Example:* The SNDK channel failed at 07:15 UTC.\n"
                    "• *Next:* Restore the monitor's channel access.\n"
                    "• *Ticket:* `B0349`",
                    thread_ts="parent",
                ),
                mock.call(
                    "token",
                    "C-health",
                    "*Tradable scheduler is stale*\n"
                    "• *Proof:* No successful run completed in eight hours.\n"
                    "• *Example:* The 06:00 UTC run never started.\n"
                    "• *Next:* Restart the stalled tradable schedule.\n"
                    "• *Ticket:* `B0365`",
                    thread_ts="parent",
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
            ],
        )

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

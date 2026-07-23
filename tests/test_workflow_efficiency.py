from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_POLLING_FRAGMENTS = (
    "run_in_background`, then wait",
    "poll the output file rather than",
    "wait for the background command to finish",
    "waiter performs at most 3 re-runs",
    "background it and repeatedly read",
)
MODEL_POLLING_DIRECTIVES = (
    re.compile(
        r"(?:call|invoke|use|run|read|check)\s+`?"
        r"(?:wait_agent|write_stdin|wait)\b.{0,120}"
        r"(?:again|until|every|repeat|periodic|loop)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:again|until|every|repeat|periodic|loop)\w*.{0,120}"
        r"(?:wait_agent|write_stdin|wait)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:call|invoke|use|run|read|check)\s+`?"
        r"(?:gh pr checks|gh run view|prefect.{0,40}inspect|"
        r"flow-run inspect|render.{0,40}(?:status|deploy|read)).{0,120}"
        r"(?:again|until|every|repeat|periodic|loop)",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:run|launch|start).{0,100}background.{0,160}"
        r"(?:then|and).{0,60}(?:wait|poll|read|check)",
        re.IGNORECASE,
    ),
)


def model_polling_guidance_violations(text: str) -> list[str]:
    violations = [fragment for fragment in FORBIDDEN_POLLING_FRAGMENTS
                  if fragment.lower() in text.lower()]
    for paragraph in re.split(r"\n\s*\n", text):
        normalized = " ".join(paragraph.split())
        lowered = normalized.lower()
        if any(marker in lowered for marker in (
            "never", "do not", "must not", "prohibited", "rather than", "instead of"
        )):
            continue
        if any(pattern.search(normalized) for pattern in MODEL_POLLING_DIRECTIVES):
            violations.append(normalized[:240])
    return violations


def run_script(name: str, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(ROOT / "bin" / name), *args], capture_output=True,
                          text=True, env=env, check=False)


class WorkflowEfficiencyTest(unittest.TestCase):
    def test_e0026_retro_contracts_are_present_and_consistent(self) -> None:
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        epic = (ROOT / "skills/epic-flow/SKILL.md").read_text()
        milestone = (ROOT / "skills/milestone-flow/SKILL.md").read_text()
        review = (ROOT / "skills/review/SKILL.md").read_text()
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        ticket_build = (ROOT / "skills/ticket-build/SKILL.md").read_text()
        build = (ROOT / "skills/build/SKILL.md").read_text()

        for contract in (guide, verify):
            self.assertIn("every long-lived reader", contract)
            self.assertIn("zero new undefined-object failures", contract)
            self.assertIn("zero new infrastructure quarantines", contract)
            self.assertIn("schema truth", contract.lower())
            self.assertIn("FAILED-state observability", contract)

        for contract in (epic, milestone, review):
            self.assertIn('fork_turns: "none"', contract)
            self.assertIn("smallest explicit numeric count", contract)
            self.assertNotIn('fork_turns: "all"', contract)

        for contract in (ticket_flow, ticket_build, milestone):
            self.assertIn("first compaction", contract)
            self.assertIn("fixed context/token budget", contract)
            self.assertIn('fork_turns: "none"', contract)

        self.assertIn("Model-driven polling is absolutely prohibited", economy)
        self.assertIn("bin/wait-ci", economy)
        self.assertIn("bin/wait-prefect-flow", economy)
        self.assertIn("deterministic bounded poller", economy)
        self.assertIn("one blocking foreground", economy)
        self.assertIn("deterministic bounded poller", milestone)
        self.assertNotIn("run_in_background`, then wait", build)

        for contract in (economy, ticket_build, milestone):
            self.assertIn("bin/compact-exec", contract)
            self.assertIn("output_file", contract)
            self.assertIn("rerun_command", contract)

        for contract in (epic, milestone, ticket_flow):
            self.assertIn("current.json", contract)
            self.assertIn("SHA-256", contract)
            self.assertIn("packet path", contract)
            self.assertIn("version/hash", contract)
        self.assertIn("16 KiB", epic)

    def test_workflow_guidance_has_no_model_driven_polling_instructions(self) -> None:
        roots = (ROOT / "skills", ROOT / "agents", ROOT / "workflows")
        paths = [path for root in roots for path in root.rglob("*")
                 if path.is_file() and path.suffix in {".md", ".toml"}]
        violations: list[str] = []
        for path in paths:
            text = path.read_text(errors="replace")
            for violation in model_polling_guidance_violations(text):
                violations.append(f"{path.relative_to(ROOT)}: {violation}")
        self.assertEqual([], violations)

    def test_model_polling_guidance_linter_rejects_common_instruction_shapes(self) -> None:
        prohibited = (
            "Call wait_agent every 30 seconds until the agent is done.",
            "Run gh pr checks, sleep, and run it again until CI passes.",
            "Invoke Prefect flow-run inspect periodically while the flow is pending.",
            "Launch the command in the background, then read its output until it exits.",
            "Use Render deployment status reads every minute until the deploy is live.",
        )
        for sample in prohibited:
            self.assertTrue(model_polling_guidance_violations(sample), sample)
        allowed = (
            "Run bin/wait-ci once as one blocking foreground command.",
            "Never call wait_agent repeatedly for the same pending condition.",
            "The deterministic script, not the model, polls until its hard deadline.",
        )
        for sample in allowed:
            self.assertEqual([], model_polling_guidance_violations(sample), sample)

    def test_skill_contracts_keep_routine_and_lfg_paths_bounded(self) -> None:
        review = (ROOT / "skills/review/SKILL.md").read_text()
        lfg = (ROOT / "skills/lfg/SKILL.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        retro = (ROOT / "skills/session-retro/SKILL.md").read_text()
        self.assertIn('fork_turns: "none"', economy)
        self.assertIn("Conductor enforcement", economy)
        self.assertIn("must not poll the parent session itself", economy)
        self.assertIn("plain review starts native-only", review)
        self.assertNotIn("/review mode:cross", lfg)
        self.assertIn("workflow-efficiency-report --before-retro", retro)

    def test_accepted_retro_changes_require_one_fresh_bounded_maintainer(self) -> None:
        conventions = (ROOT / "CLAUDE.md").read_text()
        retro = (ROOT / "skills/session-retro/SKILL.md").read_text()
        apply = (ROOT / "skills/retro-apply/SKILL.md").read_text()

        self.assertIn("/retro-apply R1,R3", retro)
        self.assertIn("request to `/retro-apply`", retro)
        self.assertIn("accepted-change-packet.md", apply)
        self.assertIn("at most 12 KiB", apply)
        self.assertIn('fork_turns="none"', apply)
        self.assertIn("Block once for its terminal result", apply)
        self.assertIn("Never silently", apply)
        self.assertNotIn('fork_turns="all"', apply)
        self.assertIn("accepts session-retro recommendations", conventions)
        self.assertIn("fresh workflow-maintainer context", conventions)

    def test_ticket_context_and_plan_fanout_inputs_are_bounded(self) -> None:
        conventions = (ROOT / "CLAUDE.md").read_text()
        auto_plan = (ROOT / "skills/ticket-plan/SKILL.md").read_text()
        fanout = (ROOT / "workflows/plan-fanout.js").read_text()
        ticket_verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()

        self.assertIn('detail="light", include_events=false', conventions)
        self.assertIn("sourceArtifactFile", auto_plan)
        self.assertIn("codebaseResearchFile", auto_plan)
        self.assertIn("priorKnowledgeFile", auto_plan)
        self.assertIn("sourceArtifactFile", fanout)
        self.assertIn("codebaseResearchFile", fanout)
        self.assertIn("priorKnowledgeFile", fanout)
        self.assertNotIn("${sourceArtifact}", fanout)
        self.assertNotIn("${codebaseResearch}", fanout)
        self.assertNotIn("${priorKnowledge}", fanout)
        self.assertIn('detail="light", include_events=false', ticket_verify)
        self.assertIn("context_version", ticket_verify)
        self.assertIn("verify-scope-dispatch.md", ticket_verify)
        self.assertIn("verify-visible-surfaces.md", ticket_verify)
        self.assertIn("verify-lifecycle-actions.md", ticket_verify)
        self.assertIn("mark the prior artifact `superseded`", ticket_verify)
        self.assertIn("Reusable query packs", ticket_verify)
        self.assertIn(".agents/verification-query-packs/", ticket_verify)
        self.assertIn("schema-fingerprint query", ticket_verify)
        for name in (
            "verify-scope-dispatch.md", "verify-visible-surfaces.md",
            "verify-lifecycle-actions.md", "verify-staging-promotion.md",
            "verify-failure-capture.md",
        ):
            self.assertTrue((ROOT / "skills/references" / name).is_file())

    def test_verification_canaries_require_mechanical_work_bounds(self) -> None:
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()

        for contract in (verify, guide):
            self.assertIn('"one run"', contract)
            self.assertIn("actual parameter schema", contract)
            self.assertIn("external calls", contract)
            self.assertRegex(contract, r"durable\s+writes")
            self.assertIn("wall-clock duration", contract)
            self.assertIn("Default-empty parameters", contract)
            self.assertIn("uncapped sequential loops", contract)
        self.assertIn("return `BLOCKED` before triggering", verify)
        self.assertIn("keep the guide unfinalized", guide)

    def test_sensitive_and_memory_guidance_use_safe_callable_routes(self) -> None:
        sensitive = (ROOT / "skills/sensitive-vault-access/SKILL.md").read_text()
        memory = (ROOT / "skills/autodev-search/SKILL.md").read_text()

        self.assertIn("ts-prefect-prod-ro", sensitive)
        self.assertIn("do not fall back to Touch ID", sensitive)
        self.assertNotIn('"Verify F0123 production schema', sensitive)
        self.assertIn("mcp__autodev_memory__search", memory)
        self.assertIn("mcp__autodev_memory__expand_entries", memory)
        self.assertNotIn("mcp__autodev-memory__", memory)

    def test_deploy_contracts_enforce_wait_preflight_redaction_and_negative_inventory(self) -> None:
        deploy = (ROOT / "skills/auto-deploy/SKILL.md").read_text()
        promote = (ROOT / "skills/ticket-promote/SKILL.md").read_text()
        create_pr = (ROOT / "skills/create-pr/SKILL.md").read_text()
        methodology = (ROOT / "skills/ticket-plan/references/plan-methodology.md").read_text()

        self.assertIn("bin/wait-ci {pr_number}", deploy)
        self.assertNotIn("gh pr checks {pr_number} --watch", deploy)
        self.assertIn("Preflight every deploy command before merge", deploy)
        self.assertIn("bin/redacted-exec", deploy)
        self.assertIn("negative inventory", deploy)
        self.assertIn("Production command preflight (before landing)", promote)
        self.assertIn("bin/redacted-exec", promote)
        self.assertIn("one final-tree health gate", promote)
        self.assertIn("--context-file", create_pr)
        self.assertIn("tree SHA equals `HEAD`", create_pr)
        self.assertIn("Record a before inventory", methodology)
        self.assertIn("live inventory contains none of the retired items", methodology)

    def test_workflow_authoring_and_promotion_contracts_are_worktree_safe(self) -> None:
        authoring = (ROOT / "skills/workflow-authoring/SKILL.md").read_text()
        promote = (ROOT / "skills/ticket-promote/SKILL.md").read_text()

        self.assertIn("bin/check-agent-workflows", authoring)
        self.assertIn("bin/verify-agent-workflows-live", authoring)
        self.assertIn("bounded discovery", authoring)
        self.assertNotIn("gh pr merge <pr_number> --squash --delete-branch", promote)
        self.assertIn('test "$(gh pr view <pr_number> --json state -q .state)" = "MERGED"',
                      promote)
        self.assertTrue(os.access(ROOT / "bin/check-agent-workflows", os.X_OK))
        self.assertTrue(os.access(ROOT / "bin/verify-agent-workflows-live", os.X_OK))

    def test_all_documented_agent_calls_use_fresh_bounded_context(self) -> None:
        for path in (ROOT / "skills").rglob("*.md"):
            lines = path.read_text().splitlines()
            for index, line in enumerate(lines):
                if "Agent(" not in line:
                    continue
                block = "\n".join(lines[index:index + 8])
                self.assertIn("fork_turns", block, f"unbounded Agent call in {path}:{index + 1}")

    def test_compact_exec_keeps_full_output_and_returns_bounded_tail(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = run_script("compact-exec", "--run-dir", directory, "--tail-bytes", "5",
                                "--", "/bin/sh", "-c", "printf 123456789; exit 3")
            self.assertEqual(result.returncode, 3)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["exit_code"], 3)
            self.assertEqual(summary["output_bytes"], 9)
            self.assertEqual(summary["tail"], "56789")
            self.assertEqual(Path(summary["output_file"]).read_text(), "123456789")
            expected = f"cd {shlex.quote(str(ROOT))} && "
            expected += shlex.join(["/bin/sh", "-c", "printf 123456789; exit 3"])
            self.assertEqual(summary["rerun_command"], expected)

    def test_compact_exec_timeout_kills_descendant_process_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "survived"
            result = run_script(
                "compact-exec", "--run-dir", directory, "--timeout", "0.1", "--",
                "/bin/sh", "-c", f"(sleep 1; touch '{marker}') & wait",
            )
            self.assertEqual(result.returncode, 124)
            self.assertTrue(json.loads(result.stdout)["timed_out"])
            time.sleep(0.7)
            self.assertFalse(marker.exists())

    def test_wait_ci_polls_with_backoff_and_emits_one_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "gh"
            fake.write_text(
                "#!/bin/sh\n"
                f"n=$(cat '{root / 'count'}' 2>/dev/null || echo 0); n=$((n+1)); "
                f"echo $n > '{root / 'count'}'\n"
                "if [ $n -eq 1 ]; then b=pending; s=IN_PROGRESS; "
                "else b=pass; s=SUCCESS; fi\n"
                "printf '[{\"name\":\"test\",\"state\":\"%s\","
                "\"bucket\":\"%s\",\"link\":\"x\"}]' \"$s\" \"$b\"\n"
            )
            fake.chmod(0o755)
            result = run_script("wait-ci", "12", "--gh", str(fake), "--timeout", "1",
                                "--initial-delay", "0", "--max-delay", "0")
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["polls"], 2)
            self.assertEqual(result.stdout.count("\n"), 1)

    def test_wait_ci_can_wait_for_one_actions_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "gh"
            fake.write_text(
                "#!/bin/sh\n"
                f"n=$(cat '{root / 'count'}' 2>/dev/null || echo 0); n=$((n+1)); "
                f"echo $n > '{root / 'count'}'\n"
                "if [ $n -eq 1 ]; then status=in_progress; conclusion=null; "
                "else status=completed; conclusion='\"success\"'; fi\n"
                "printf '{\"name\":\"deploy\",\"status\":\"%s\","
                "\"conclusion\":%s,\"url\":\"x\",\"jobs\":[]}' "
                '"$status" "$conclusion"\n'
            )
            fake.chmod(0o755)
            result = run_script("wait-ci", "--run", "99", "--gh", str(fake),
                                "--timeout", "1", "--initial-delay", "0", "--max-delay", "0")
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["kind"], "run")
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["polls"], 2)
            self.assertEqual(summary["run"]["conclusion"], "success")

    def test_wait_prefect_flow_polls_with_backoff_and_emits_one_result(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = root / "prefect"
            fake.write_text(
                "#!/bin/sh\n"
                f"n=$(cat '{root / 'count'}' 2>/dev/null || echo 0); n=$((n+1)); "
                f"echo $n > '{root / 'count'}'\n"
                "if [ $n -eq 1 ]; then t=RUNNING; n=Running; "
                "else t=COMPLETED; n=Completed; fi\n"
                "printf '{\"state\":{\"type\":\"%s\",\"name\":\"%s\"}}' \"$t\" \"$n\"\n"
            )
            fake.chmod(0o755)
            result = run_script(
                "wait-prefect-flow",
                "run-123",
                "--command-prefix",
                str(fake),
                "--timeout",
                "1",
                "--initial-delay",
                "0",
                "--max-delay",
                "0",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["state_type"], "COMPLETED")
            self.assertEqual(summary["polls"], 2)
            self.assertEqual(result.stdout.count("\n"), 1)

    def test_wait_prefect_flow_fails_loudly_on_failed_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "prefect"
            fake.write_text(
                "#!/bin/sh\n"
                "printf '{\"state\":{\"type\":\"FAILED\",\"name\":\"Failed\"}}'\n"
            )
            fake.chmod(0o755)
            result = run_script(
                "wait-prefect-flow",
                "run-failed",
                "--command-prefix",
                str(fake),
                "--timeout",
                "1",
            )
            self.assertEqual(result.returncode, 1, result.stderr)
            summary = json.loads(result.stdout)
            self.assertEqual(summary["status"], "failure")
            self.assertEqual(summary["state_type"], "FAILED")

    def test_ticket_deploy_owns_the_complete_fail_stop_chain(self) -> None:
        wrapper = (ROOT / "skills/ticket-deploy/SKILL.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()

        self.assertIn("--no-promote --produce-evidence", wrapper)
        self.assertIn("/ticket-promote <ID>", wrapper)
        self.assertIn("Stop on every outcome except exact `PASS`", wrapper)
        self.assertIn("final `completed` status", wrapper)
        self.assertIn("ticket-attributed incident cleanup", wrapper)
        self.assertIn("scripts.prefect_ops.delete_ticket_flow_runs", wrapper)
        self.assertIn("stop and ask the user for\nconfirmation", wrapper)
        self.assertIn("bin/wait-prefect-flow", verify)
        self.assertIn("preserve the failed flow-run history", verify)
        self.assertIn("structurally attributes Prefect incident flow runs", verify)
        self.assertIn("/ticket-deploy <ID> staging", ticket_flow)
        self.assertIn("/ticket-deploy <ID> full", ticket_flow)
        self.assertIn("stops after the staging verify leg", ticket_flow)
        self.assertTrue(os.access(ROOT / "bin/wait-prefect-flow", os.X_OK))

    def test_terminal_workflows_share_visible_outcome_and_closeout_contract(self) -> None:
        outcome = (ROOT / "skills/references/terminal-outcomes.md").read_text()
        workflow_names = (
            "auto-deploy",
            "ticket-deploy",
            "ticket-verify",
            "ticket-flow",
            "ticket-promote",
            "milestone-flow",
            "epic-flow",
            "encryption-verify",
            "migration-parity-check",
        )

        for workflow_name in workflow_names:
            workflow = (ROOT / f"skills/{workflow_name}/SKILL.md").read_text()
            self.assertIn("skills/references/terminal-outcomes.md", workflow, workflow_name)

        self.assertIn("# ✅ COMPLETED — READY TO CLOSE", outcome)
        self.assertIn("# ❌ STAGING VERIFICATION FAILED", outcome)
        self.assertIn("# ❌ PRODUCTION DEPLOY FAILED", outcome)
        self.assertIn("Lifecycle truth:", outcome)
        self.assertIn("Repository and release state:", outcome)
        self.assertIn("Ticket hygiene:", outcome)
        self.assertIn("Closeout check: <READY|NOT READY", outcome)
        self.assertIn("Not verified:", outcome)
        self.assertIn("raw ANSI escape sequences", outcome)
        self.assertIn("worst terminal state", outcome)
        self.assertIn("do not repeat the child's banner", outcome)
        self.assertIn("# ⚠️ STOPPED — ACTION REQUIRED", outcome)

    def test_full_auto_review_contract_separates_severity_from_decision_ownership(self) -> None:
        wrapper = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        phases = (ROOT / "skills/references/execution-phases.md").read_text()
        resolver = (ROOT / "skills/resolve-review/SKILL.md").read_text()
        review = (ROOT / "skills/review/SKILL.md").read_text()

        self.assertIn("standing approval", wrapper)
        self.assertIn("plan-conformant, deterministic, corroborated", wrapper)
        self.assertIn("Severity and decision ownership are independent", phases)
        self.assertIn("p1 finding is not `manual`", phases)
        self.assertIn("Reclassify an incorrectly labeled `manual` finding", resolver)
        self.assertIn("Do not interrupt full-auto", resolver)
        self.assertNotIn("Missing scope items are **p1 `manual`", review)

    def test_ticket_cleanup_contract_preserves_post_fix_failures(self) -> None:
        cleanup = (ROOT / "skills/references/verify-deferred-cleanup.md").read_text()
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()

        self.assertIn("exact flow-run IDs explicitly labeled", cleanup)
        self.assertIn("Do not regex every UUID", cleanup)
        self.assertIn("terminal Prefect **flow-run history only**", cleanup)
        self.assertIn("post-fix failures", cleanup)
        self.assertIn("remain visible and fail verification", cleanup)
        self.assertIn("prod_verified_needs_cleanup", cleanup)
        self.assertIn('cleanup_kind="flow_run_cleanup"', guide)
        self.assertIn("only after production behavior PASS", guide)

    def test_redacted_exec_never_emits_environment_or_labeled_secrets(self) -> None:
        environment = os.environ.copy()
        environment["PREFECT_API_AUTH_STRING"] = "operator:actual-production-secret"
        result = run_script(
            "redacted-exec", "--", "/bin/sh", "-c",
            "printf '%s\\n' \"$PREFECT_API_AUTH_STRING\"; "
            "printf '%s\\n' 'PREFECT_API_AUTH_STRING=profile-only-value' >&2; "
            "printf '%s\\n' 'Authorization: Basic encoded-credential'; "
            "printf '%s\\n' '\"api_key\": \"json-profile-value\"'",
            env=environment,
        )
        combined = result.stdout + result.stderr
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("actual-production-secret", combined)
        self.assertNotIn("profile-only-value", combined)
        self.assertNotIn("encoded-credential", combined)
        self.assertNotIn("json-profile-value", combined)
        self.assertGreaterEqual(combined.count("[REDACTED]"), 4)

    @staticmethod
    def write_session(path: Path, meta: dict, records: list[dict]) -> None:
        values = [{"type": "session_meta", "payload": meta}, *records]
        path.write_text("\n".join(json.dumps(value) for value in values) + "\n")

    def test_report_uses_real_fork_chronology_and_recursive_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root_log = root / "root.jsonl"
            child_log = root / "child.jsonl"
            grandchild_log = root / "grandchild.jsonl"

            def token(timestamp: str, total: dict) -> dict:
                return {"timestamp": timestamp, "type": "event_msg",
                        "payload": {"type": "token_count", "info": {
                            "total_token_usage": total, "last_token_usage": total}}}

            def started(timestamp: str) -> dict:
                return {"timestamp": timestamp, "type": "event_msg",
                        "payload": {"type": "task_started"}}

            self.write_session(root_log, {"id": "root"}, [
                started("2026-01-01T00:00:00Z"),
                token("2026-01-01T00:00:01Z",
                      {"input_tokens": 1000, "cached_input_tokens": 400,
                       "output_tokens": 100, "reasoning_output_tokens": 20,
                       "total_tokens": 1100}),
                {"type": "response_item", "payload": {"type": "custom_tool_call",
                    "name": "spawn_agent", "input": "{\"fork_turns\":\"all\"}"}},
                {"type": "response_item", "payload": {"type": "custom_tool_call_output",
                    "output": "Warning: truncated output\nabc"}},
                {"type": "compacted", "payload": {}},
            ])
            baseline = {"input_tokens": 500, "cached_input_tokens": 200,
                        "output_tokens": 100, "reasoning_output_tokens": 10,
                        "total_tokens": 600}
            final = {"input_tokens": 900, "cached_input_tokens": 500,
                     "output_tokens": 200, "reasoning_output_tokens": 20,
                     "total_tokens": 1100}
            self.write_session(child_log, {"id": "child", "parent_thread_id": "root"},
                               [token("2026-01-01T00:00:01Z", baseline),
                                started("2026-01-01T00:00:02Z"),
                                token("2026-01-01T00:00:03Z", final),
                                {"type": "response_item", "payload": {
                                    "type": "function_call", "name": "read_file"}},
                                {"type": "response_item", "payload": {
                                    "type": "function_call_output", "output": "ok"}},
                                {"type": "event_msg", "payload": {
                                    "type": "context_compacted"}}])
            grand_baseline = {"input_tokens": 100, "cached_input_tokens": 50,
                              "output_tokens": 10, "reasoning_output_tokens": 2,
                              "total_tokens": 110}
            grand_final = {"input_tokens": 300, "cached_input_tokens": 100,
                           "output_tokens": 50, "reasoning_output_tokens": 5,
                           "total_tokens": 350}
            self.write_session(grandchild_log, {"id": "grand", "parent_thread_id": "child"},
                               [token("2026-01-01T00:00:03Z", grand_baseline),
                                started("2026-01-01T00:00:04Z"),
                                token("2026-01-01T00:00:05Z", grand_final)])
            usage_dir = root / "usage"
            usage_dir.mkdir()
            (usage_dir / "external.json").write_text(json.dumps({
                "orchestrator_thread_id": "child", "usage_available": True,
                "usage": {"input_tokens": 12, "cached_input_tokens": 4,
                          "output_tokens": 3, "total_tokens": 15},
                "duration_ms": 250, "model": "fake-model", "repo": "/repo",
                "provider": "codex",
            }))
            result = run_script("workflow-efficiency-report", str(root_log),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(usage_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["agents"], 3)
            self.assertEqual(report["direct_children"], 1)
            self.assertEqual(report["descendants_discovered"], 2)
            self.assertEqual(report["codex_tree_usage_unique"]["total_tokens"], 1840)
            self.assertEqual(report["whole_tree_usage"]["total_tokens"], 1855)
            self.assertEqual(report["codex_tree_efficiency"]["uncached_input_tokens"], 850)
            self.assertEqual(report["codex_tree_efficiency"]["effective_non_cached_tokens"], 1090)
            self.assertEqual(report["sessions"][1]["inherited_fork_baseline"], baseline)
            self.assertEqual(report["sessions"][1]["usage_unique"]["output_tokens"], 100)
            self.assertEqual(report["tool_calls"], 2)
            self.assertEqual(report["fork_turns_modes"], {"all": 1})
            self.assertEqual(report["all_forks"], 1)
            self.assertEqual(report["truncations"], 1)
            self.assertEqual(report["compactions"], 2)
            self.assertEqual(report["external_provider_usage"]["usage"]["total_tokens"], 15)
            self.assertEqual(report["external_provider_usage"]["duration_ms"], 250)
            self.assertEqual(report["coverage"]["fork_baselines"], "complete")
            self.assertEqual(report["tool_histogram"], {"read_file": 1, "spawn_agent": 1})
            self.assertEqual(report["largest_tool_outputs"][0]["tool"], "spawn_agent")
            capped = run_script("workflow-efficiency-report", str(root_log),
                                "--sessions-root", str(root), "--max-descendants", "1",
                                "--external-usage-dir", str(usage_dir))
            capped_report = json.loads(capped.stdout)
            self.assertEqual(capped_report["descendants_discovered"], 2)
            self.assertEqual(capped_report["descendants_reported"], 1)
            self.assertTrue(capped_report["descendants_truncated"])

    def test_report_bounds_call_diagnostics_and_can_stop_before_retro(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            before = {"input_tokens": 100, "cached_input_tokens": 50,
                      "output_tokens": 10, "reasoning_output_tokens": 1,
                      "total_tokens": 110}
            after = {"input_tokens": 200, "cached_input_tokens": 100,
                     "output_tokens": 20, "reasoning_output_tokens": 2,
                     "total_tokens": 220}
            repeated_input = 'await tools.exec_command({cmd:"echo 12345",yield_time:1000})'
            self.write_session(root / "root.jsonl", {"id": "root"}, [
                {"timestamp": "2026-01-01T00:00:00Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": before, "last_token_usage": before}}},
                {"timestamp": "2026-01-01T00:00:01Z", "type": "response_item",
                 "payload": {"type": "function_call", "name": "exec",
                             "call_id": "one", "arguments": repeated_input}},
                {"timestamp": "2026-01-01T00:00:01.250Z", "type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": "one",
                             "output": "small"}},
                {"timestamp": "2026-01-01T00:00:02Z", "type": "response_item",
                 "payload": {"type": "function_call", "name": "exec",
                             "call_id": "two", "arguments": repeated_input}},
                {"timestamp": "2026-01-01T00:00:02.500Z", "type": "response_item",
                 "payload": {"type": "function_call_output", "call_id": "two",
                             "output": "larger output"}},
                {"type": "response_item", "payload": {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": "[session-retro](x)"}]}},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "after_retro", "arguments": "{}"}},
                {"timestamp": "2026-01-01T00:00:03Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": after, "last_token_usage": after}}},
            ])

            result = run_script(
                "workflow-efficiency-report", str(root / "root.jsonl"),
                "--sessions-root", str(root), "--external-usage-dir", str(root / "missing"),
                "--before-retro",
            )
            report = json.loads(result.stdout)
            self.assertEqual(report["codex_tree_usage_unique"], before)
            self.assertTrue(report["sessions"][0]["before_retro_cutoff_applied"])
            self.assertEqual(report["tool_histogram"], {"exec_command": 2})
            self.assertEqual(report["repeated_tool_calls"][0]["count"], 2)
            self.assertNotIn("echo 12345", json.dumps(report["repeated_tool_calls"]))
            self.assertEqual(report["largest_tool_outputs"][0]["output_bytes"], 13)
            self.assertEqual(report["tool_elapsed_ms"]["exec_command"], {
                "total": 750, "max": 500, "measured_calls": 2,
            })

    def test_before_retro_uses_latest_request_in_long_lived_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = {"input_tokens": 100, "cached_input_tokens": 50,
                     "output_tokens": 10, "reasoning_output_tokens": 1,
                     "total_tokens": 110}
            between = {"input_tokens": 300, "cached_input_tokens": 150,
                       "output_tokens": 30, "reasoning_output_tokens": 3,
                       "total_tokens": 330}
            after = {"input_tokens": 500, "cached_input_tokens": 250,
                     "output_tokens": 50, "reasoning_output_tokens": 5,
                     "total_tokens": 550}
            retro = {"type": "response_item", "payload": {
                "type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "[session-retro](x)"}],
            }}
            self.write_session(root / "root.jsonl", {"id": "root"}, [
                {"timestamp": "2026-01-01T00:00:00Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": first, "last_token_usage": first}}},
                retro,
                {"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": between, "last_token_usage": between}}},
                {"type": "response_item", "payload": {
                    "type": "function_call", "name": "between_retros", "arguments": "{}"}},
                retro,
                {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": after, "last_token_usage": after}}},
            ])

            result = run_script(
                "workflow-efficiency-report", str(root / "root.jsonl"),
                "--sessions-root", str(root), "--before-retro",
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads(result.stdout)
            self.assertEqual(report["codex_tree_usage_unique"], between)
            self.assertEqual(report["tool_histogram"], {"between_retros": 1})

    def test_report_marks_missing_fork_baseline_uncertain(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [])
            usage = {"input_tokens": 20, "cached_input_tokens": 10,
                     "output_tokens": 2, "reasoning_output_tokens": 1, "total_tokens": 22}
            self.write_session(root / "child.jsonl", {"id": "child",
                                                       "parent_thread_id": "root"}, [
                {"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": usage, "last_token_usage": usage}}},
            ])
            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(root / "missing"))
            report = json.loads(result.stdout)
            self.assertEqual(report["coverage"]["fork_baselines"], "uncertain")
            self.assertFalse(report["sessions"][1]["fork_baseline_known"])
            self.assertEqual(report["sessions"][1]["usage_unique"], usage)

    def test_report_uses_zero_baseline_when_no_replayed_usage_exists(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [])
            first = {"input_tokens": 20, "cached_input_tokens": 10,
                     "output_tokens": 2, "reasoning_output_tokens": 1, "total_tokens": 22}
            second = {"input_tokens": 30, "cached_input_tokens": 20,
                      "output_tokens": 3, "reasoning_output_tokens": 1, "total_tokens": 33}
            total = {key: first[key] + second[key] for key in first}
            self.write_session(root / "child.jsonl", {"id": "child",
                                                       "parent_thread_id": "root"}, [
                {"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": first, "last_token_usage": first}}},
                {"timestamp": "2026-01-01T00:00:03Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": total, "last_token_usage": second}}},
            ])
            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(root / "missing"))
            report = json.loads(result.stdout)
            child = report["sessions"][1]
            self.assertTrue(child["fork_baseline_known"])
            self.assertEqual(child["fork_baseline_method"],
                             "zero_no_usage_before_activity_boundary")
            self.assertEqual(child["usage_unique"], total)
            self.assertEqual(report["coverage"]["fork_baselines"], "complete")

    def test_report_excludes_replayed_parent_turns_before_child_trigger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [])
            replay = {"input_tokens": 100, "cached_input_tokens": 40,
                      "output_tokens": 10, "reasoning_output_tokens": 2, "total_tokens": 110}
            gross = {"input_tokens": 160, "cached_input_tokens": 70,
                     "output_tokens": 25, "reasoning_output_tokens": 4, "total_tokens": 185}
            duplicate_last = {"input_tokens": 60, "cached_input_tokens": 30,
                              "output_tokens": 15, "reasoning_output_tokens": 2,
                              "total_tokens": 75}
            self.write_session(root / "child.jsonl", {
                "id": "child", "parent_thread_id": "root"
            }, [
                {"timestamp": "2026-01-01T00:00:00.000Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:00.001Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": replay, "last_token_usage": replay}}},
                {"timestamp": "2026-01-01T00:00:00.010Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:00.020Z",
                 "type": "inter_agent_communication_metadata",
                 "payload": {"trigger_turn": True}},
                {"timestamp": "2026-01-01T00:00:01.000Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": gross, "last_token_usage": duplicate_last}}},
                # Codex can duplicate the terminal token_count; attribution must not double it.
                {"timestamp": "2026-01-01T00:00:01.001Z", "type": "event_msg",
                 "payload": {"type": "token_count", "info": {
                     "total_token_usage": gross, "last_token_usage": duplicate_last}}},
            ])
            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(root / "missing"))
            report = json.loads(result.stdout)
            child = report["sessions"][1]
            self.assertEqual(child["activity_boundary_method"],
                             "last_task_started_before_trigger_turn")
            self.assertEqual(child["inherited_fork_baseline"], replay)
            self.assertEqual(child["usage_unique"]["total_tokens"], 75)
            self.assertLessEqual(child["usage_unique"]["total_tokens"],
                                 child["usage_gross"]["total_tokens"])

    def test_report_separates_nearby_unattributed_old_unrelated_and_invalid_sidecars(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(root / "root.jsonl", {"id": "root"}, [
                {"timestamp": "2026-01-01T00:00:00Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
                {"timestamp": "2026-01-01T00:00:10Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
            ])
            usage_dir = root / "usage"
            usage_dir.mkdir()
            (usage_dir / "20260101T000004Z-near.json").write_text(json.dumps({
                "orchestrator_thread_id": "another-thread",
                "started_at": "2026-01-01T00:00:04Z",
            }))
            (usage_dir / "20200101T000000Z-old.json").write_text(json.dumps({
                "orchestrator_thread_id": "another-thread",
                "started_at": "2020-01-01T00:00:00Z",
            }))
            (usage_dir / "invalid.json").write_text("not-json")

            result = run_script("workflow-efficiency-report", str(root / "root.jsonl"),
                                "--sessions-root", str(root),
                                "--external-usage-dir", str(usage_dir))
            self.assertEqual(result.returncode, 0, result.stderr)
            external = json.loads(result.stdout)["external_provider_usage"]
            self.assertEqual(external["sidecars"], 0)
            self.assertEqual(external["unattributed_sidecars"], 1)
            self.assertEqual(external["unrelated_sidecars"], 1)
            self.assertEqual(external["invalid_sidecars"], 1)

    def test_live_verifier_distinguishes_clean_from_locally_modified_checkout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"],
                           cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            (repo / "CLAUDE.md").write_text("test\n")
            subprocess.run(["git", "add", "CLAUDE.md"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            revision = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
                capture_output=True, text=True,
            ).stdout.strip()

            clean = run_script("verify-agent-workflows-live", revision,
                               "--live-repo", str(repo))
            self.assertEqual(clean.returncode, 0, clean.stderr)
            self.assertEqual(json.loads(clean.stdout)["status"], "live")

            missing = run_script("verify-agent-workflows-live", "0" * 40,
                                 "--live-repo", str(repo))
            self.assertEqual(missing.returncode, 1, missing.stderr)
            self.assertEqual(json.loads(missing.stdout)["status"], "not_live")

            (repo / "CLAUDE.md").write_text("locally modified\n")
            dirty = run_script("verify-agent-workflows-live", revision,
                               "--live-repo", str(repo))
            self.assertEqual(dirty.returncode, 1, dirty.stderr)
            self.assertEqual(json.loads(dirty.stdout)["status"], "live_but_modified")

    def test_external_agent_sidecar_records_provider_usage_without_changing_envelope(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/bin/sh\nout=''\nprev=''\n"
                "for arg in \"$@\"; do [ \"$prev\" = '-o' ] && out=\"$arg\"; prev=\"$arg\"; done\n"
                "cat >/dev/null\n"
                "printf '%s' '{\"key\":\"codex\",\"files_searched\":1,\"occurrences\":[],"
                "\"summary\":\"all good\",\"questions_for_synthesis\":[]}' > \"$out\"\n"
                "echo '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":10,"
                "\"cached_input_tokens\":4,\"output_tokens\":2,\"total_tokens\":12}}'\n"
            )
            codex.chmod(0o755)
            packet = root / "packet"
            packet.write_text("<autodev-memory-task-context>\nx\n</autodev-memory-task-context>")
            usage_dir = root / "usage"
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            result = run_script("external-agent", "--task", "research", "--provider", "codex",
                                "--question", "inspect code", "--repo", str(ROOT),
                                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                                "--telemetry-file", str(root / "telemetry"), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["key"], "codex")
            sidecar = json.loads(next(usage_dir.glob("*.json")).read_text())
            self.assertTrue(sidecar["usage_available"])
            self.assertEqual(sidecar["usage"]["total_tokens"], 12)
            self.assertEqual(sidecar["model"], "provider_default")
            self.assertEqual(sidecar["repo"], str(ROOT.resolve()))
            self.assertRegex(sidecar["started_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertGreaterEqual(sidecar["duration_ms"], 0)
            self.assertNotIn("all good", json.dumps(sidecar))

    def test_external_agent_failure_still_writes_unavailable_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text("#!/bin/sh\ncat >/dev/null\nexit 7\n")
            codex.chmod(0o755)
            packet = root / "packet"
            packet.write_text("<autodev-memory-task-context>\nx\n</autodev-memory-task-context>")
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            usage_dir = root / "usage"
            result = run_script("external-agent", "--task", "research", "--provider", "codex",
                                "--question", "inspect code", "--repo", str(ROOT),
                                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                                "--telemetry-file", str(root / "telemetry"), env=env)
            self.assertEqual(result.returncode, 2)
            sidecar = json.loads(next(usage_dir.glob("*.json")).read_text())
            self.assertFalse(sidecar["usage_available"])
            self.assertEqual(sidecar["adapter_outcome"], "invalid_provider_output")
            self.assertEqual(sidecar["attempt_statuses"], ["exit_7", "exit_7"])


if __name__ == "__main__":
    unittest.main()

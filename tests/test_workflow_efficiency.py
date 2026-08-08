from __future__ import annotations

import hashlib
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
    def test_e0003_r3_r5_builder_chains_and_validation_ownership(self) -> None:
        build = (ROOT / "skills/build/SKILL.md").read_text()
        create_todos = (ROOT / "skills/create-build-todos/SKILL.md").read_text()
        ticket_build = (ROOT / "skills/ticket-build/SKILL.md").read_text()
        phases = (ROOT / "skills/references/execution-phases.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        intensity = (ROOT / "skills/references/execution-intensity.md").read_text()
        write_tests = (ROOT / "skills/write-tests/SKILL.md").read_text()
        review = (ROOT / "skills/review/SKILL.md").read_text()
        resolve = (ROOT / "skills/resolve-review/SKILL.md").read_text()
        builder = (ROOT / "agents/builder.md").read_text()
        reviewer = (ROOT / "agents/reviewer.md").read_text()
        external_build = (ROOT / "bin/external-build").read_text()
        external_agent = (ROOT / "bin/external-agent").read_text()
        build_planner = (ROOT / "agents/build-planner.md").read_text()
        test_strategy = (ROOT / "skills/write-tests/references/strategy.md").read_text()
        review_template = (ROOT / "skills/review/templates/review-todo.md").read_text()

        self.assertIn("coherent sequential builder chains", build)
        self.assertIn("smallest reasonable set of coherent sequential chains", build)
        self.assertIn("one **fresh** builder that owns only that chain", build)
        self.assertIn("whole ticket/epic history", build)
        self.assertIn("todo_results[]", build)
        self.assertIn('"todo_results"', external_build)
        self.assertIn('"chain_status"', external_build)
        self.assertNotIn('"verification_output"', external_build)
        self.assertNotIn("--session-file", external_build)
        self.assertNotIn('"exec", "resume"', external_build)
        self.assertIn("checkpoint every covered todo individually", build)
        self.assertIn("first incomplete todo", build)
        self.assertIn("maximum\n   complexity/risk", build)
        self.assertIn("maximum complexity/risk across each coherent chain", create_todos)
        self.assertIn("builders must not execute them", build_planner)

        for contract in (build, phases, builder):
            normalized = re.sub(r"[*_`]", "", contract.lower())
            self.assertIn("do not run", normalized)
            self.assertIn("typecheck", contract)
            self.assertIn("schema pulls", contract)
            self.assertIn("browser verification", " ".join(contract.split()))
        self.assertIn("Do not execute them or run any test suite", write_tests)
        self.assertIn("standalone `/write-tests`", write_tests)
        self.assertIn("the subagent never runs it", test_strategy)
        self.assertIn("Reviewers never rerun validation", review)
        self.assertIn("Never run test", reviewer)
        self.assertIn("Review the diff and supplied evidence only", external_agent)
        self.assertIn("suggested orchestrator validation commands", resolve)

        self.assertIn("Pre-review health gate (main orchestrator only)", ticket_build)
        self.assertIn("Final health gate (main orchestrator only)", ticket_build)
        self.assertIn("(tree SHA, exact command)", ticket_build)
        self.assertIn("If unchanged, reuse that PASS", ticket_build)
        normalized_ticket_build = " ".join(ticket_build.split())
        normalized_economy = " ".join(economy.split())
        self.assertIn("`direct`/`standard` permit one changed-tree whole-batch repair-and-rerun cycle", normalized_ticket_build)
        self.assertIn("--max-repair-runs", normalized_ticket_build)
        self.assertIn("BUDGET_EXHAUSTED", normalized_ticket_build)
        self.assertIn("deterministic autofix", normalized_ticket_build)
        self.assertIn("complete failure inventory", normalized_ticket_build)
        self.assertIn("non-short-circuit diagnostic sweep", normalized_ticket_build)
        self.assertIn("repair dispatch is forbidden while completeness is unknown", normalized_ticket_build)
        self.assertIn("never dispatch or validate one category", normalized_ticket_build)
        self.assertNotIn("one narrowly scoped repair chain", normalized_ticket_build)
        self.assertIn("`direct` and `standard` have one changed-tree whole-batch", normalized_economy)
        self.assertIn("explicit `heavy` has three", normalized_economy)
        self.assertIn("complete failure inventory", normalized_economy)
        self.assertIn("Never repair or validate one layer at a time", normalized_economy)
        self.assertIn("at most two normal full gates", " ".join(ticket_build.split()))
        self.assertIn("Reuse that recorded PASS", economy)
        self.assertIn("Plan MCP artifact is mandatory", intensity)
        self.assertIn("direct", intensity)
        self.assertIn("standard", intensity)
        self.assertIn("heavy", intensity)
        self.assertIn("one compact delivery owner", ticket_build)
        self.assertIn("Do not invoke `/create-build-todos`, `/build`, or", ticket_build)

        active_contracts = "\n".join((
            build, ticket_build, phases, intensity, economy, write_tests, review, resolve, builder,
            reviewer, external_build, external_agent, create_todos, build_planner,
            test_strategy, review_template,
        ))
        for obsolete in (
            "one builder per todo",
            "one fresh builder per todo",
            "fresh builder for that ONE todo",
            "builders run targeted checks",
            "Run ALL verification commands",
            "Run tests after each step",
            "Run all new tests to verify they pass",
            "Re-run affected tests after every fix",
        ):
            self.assertNotIn(obsolete.lower(), active_contracts.lower())

    def test_e0003_r4_finite_phase_rotation_contract(self) -> None:
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        named_paths = (
            "skills/epic-flow/SKILL.md",
            "skills/milestone-flow/SKILL.md",
            "skills/ticket-flow/SKILL.md",
            "skills/ticket-build/SKILL.md",
            "skills/build/SKILL.md",
            "skills/epic-plan/SKILL.md",
        )
        named_contracts = [(ROOT / path).read_text() for path in named_paths]

        for field in (
            "phase_name",
            "rotation_generation",
            "started_at_epoch",
            "deadline_epoch",
            "max_turns",
            "max_checkpoints",
            "max_elapsed_seconds",
            "max_packet_bytes",
            "max_tokens",
        ):
            self.assertIn(field, economy)
        for status in ("complete", "blocked", "failed", "rotate_required"):
            self.assertIn(status, economy)
        for reason in (
            "first_compaction",
            "turn_budget",
            "elapsed_budget",
            "token_budget",
        ):
            self.assertIn(reason, economy)
        self.assertIn("bin/phase-contract dispatch", economy)
        self.assertIn("bin/phase-contract result", economy)
        self.assertIn('fresh `fork_turns: "none"` replacement', economy)
        self.assertIn("old owner is\n  terminal", economy)
        self.assertIn("first incomplete unit", economy)
        self.assertIn("never rerun a completed unit", economy)
        self.assertIn("without token usage or a reliable\ncompaction event", economy)
        self.assertIn("productive, stall/sleep, and total elapsed", economy)

        for path, contract in zip(named_paths, named_contracts):
            max_turns = re.search(r"^max_turns: (\d+)$", contract, re.MULTILINE)
            self.assertIsNotNone(max_turns, path)
            self.assertLessEqual(int(max_turns.group(1)), 100, path)
            self.assertIn("Max turns", contract, path)
            self.assertIn("Max checkpoints", contract, path)
            self.assertIn("Max elapsed", contract, path)
            self.assertIn("Max tokens when exposed", contract, path)
            self.assertIn("execution-economy.md", contract, path)

        build = named_contracts[4]
        ticket_build = named_contracts[3]
        external_build = (ROOT / "bin/external-build").read_text()
        builder = (ROOT / "agents/builder.md").read_text()
        self.assertIn("coherent sequential builder chains", build)
        self.assertIn("next safe per-todo checkpoint", ticket_build)
        self.assertIn('"rotate_required"', external_build)
        self.assertIn('chain_status: "rotate_required"', builder)
        self.assertIn("orchestrator-owned validation", build)
        self.assertIn("old builder", build)

        active = "\n".join([economy, *named_contracts, builder, external_build]).lower()
        for obsolete in (
            "use judgment for the phase budget",
            "keep going while responsive",
            "continue merely because it still responds",
        ):
            self.assertNotIn(obsolete, active)
        self.assertEqual([], model_polling_guidance_violations(active))

    def test_execution_intensity_and_ticket_flow_plan_artifact_contract(self) -> None:
        intensity = (ROOT / "skills/references/execution-intensity.md").read_text()
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        ticket_plan = (ROOT / "skills/ticket-plan/SKILL.md").read_text()
        ticket_build = (ROOT / "skills/ticket-build/SKILL.md").read_text()
        milestone = (ROOT / "skills/milestone-flow/SKILL.md").read_text()
        epic = (ROOT / "skills/epic-flow/SKILL.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        phases = (ROOT / "skills/references/execution-phases.md").read_text()

        self.assertFalse((ROOT / "skills/lfg/SKILL.md").exists())
        for level in ("direct", "standard", "heavy"):
            self.assertIn(level, intensity)
        self.assertIn("Plan MCP artifact is mandatory", intensity)
        self.assertIn("intensity_floor", intensity)
        self.assertIn("execution-intensity.md", ticket_flow)
        self.assertIn("--intensity", ticket_flow)
        self.assertIn("plan MCP artifact before the first edit", ticket_flow)
        self.assertIn("MANDATORY", ticket_plan)
        self.assertIn("every intensity, including `direct`", ticket_plan)
        self.assertIn("intensity-aware", ticket_build)
        self.assertIn("intensity_floor: none", milestone)
        self.assertIn("Epic membership is sequencing, not risk", milestone)
        self.assertIn('fresh `fork_turns: "none"` `delivery_owner`', ticket_flow)
        self.assertIn("do not invoke `/ticket-plan` or `/ticket-build`", ticket_flow)
        self.assertIn("ticket-run-budget-v1", ticket_flow)
        self.assertIn("run-budget <activation_key>", ticket_flow)
        self.assertIn("expected_updated_at", ticket_flow)
        self.assertIn("BUDGET_EXHAUSTED", ticket_flow)
        self.assertIn("Permit one automatic repair/redeploy/reverify cycle", milestone)
        self.assertIn("One retrieval owner per step", milestone)
        self.assertIn("delivery ceiling = 2 * direct_steps", milestone)
        self.assertIn("bin/phase-contract epic-budget", milestone)
        self.assertIn("epic-run-budget-v1", epic)
        self.assertIn("expected_updated_at", epic)
        self.assertIn("Each milestone gets a new session", epic)
        self.assertIn("Never resume, follow up, or reuse a prior milestone owner", epic)
        self.assertIn("Every pending condition has exactly one wait owner", economy)
        self.assertIn("plan MCP artifact (mandatory", phases)
        self.assertNotIn("Knowledge retrieval gate for the wave", milestone)
        self.assertNotIn('fork_turns: "all"', ticket_flow)

    def test_ticket_workflows_treat_origin_as_audit_only(self) -> None:
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        ticket_plan = (ROOT / "skills/ticket-plan/SKILL.md").read_text()
        lifecycle = (ROOT / "skills/references/ticket-lifecycle.md").read_text()

        self.assertIn("immutable audit provenance only", ticket_flow)
        self.assertIn("Never branch delivery", ticket_flow)
        self.assertIn("immutable audit provenance, not an execution or pickup boundary", ticket_plan)
        self.assertIn("not a prerequisite", ticket_plan)
        self.assertIn("immutable audit provenance, not an ownership", lifecycle)
        self.assertIn("does not filter by origin or execution approval", lifecycle)

        combined = "\n".join((ticket_flow, ticket_plan, lifecycle))
        for retired_contract in (
            "Hermes-origin approval and pickup",
            "Hermes-origin tickets use the same statuses but have an additional",
            "cannot self-approve or set execution statuses",
            "reapproved before pickup",
            "returns a Hermes-origin",
        ):
            self.assertNotIn(retired_contract, combined)

    def test_active_workflow_docs_never_enable_all_history_dispatch(self) -> None:
        assignment = re.compile(r"fork_turns\s*(?:=|:)\s*[\"']?all\b", re.IGNORECASE)
        violations = []
        for root in (ROOT / "skills", ROOT / "agents", ROOT / "workflows"):
            for path in root.rglob("*"):
                if path.is_file() and path.suffix in {".md", ".toml", ".js"}:
                    for line_number, line in enumerate(path.read_text().splitlines(), 1):
                        if assignment.search(line) and not any(
                            marker in line.lower() for marker in ("prohibited", "never", "must not")
                        ):
                            violations.append(f"{path.relative_to(ROOT)}:{line_number}")
        self.assertEqual([], violations)

    def test_phase_contract_validator_enforces_dispatch_and_rotation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            packet = root / "packet.md"
            checkpoint = root / "checkpoint.json"
            packet.write_text("bounded packet")
            checkpoint.write_text('{"completed":["todo-1"]}')

            def reference(path: Path) -> dict[str, str]:
                return {
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            dispatch = {
                "phase_name": "implementation",
                "rotation_generation": 1,
                "coordinator_generation": 1,
                "fork_mode": "none",
                "compaction_signal": "available",
                "compactions_observed": 0,
                "first_incomplete_unit": "todo-2",
                "started_at_epoch": time.time(),
                "budget": {
                    "max_turns": 50,
                    "max_checkpoints": 8,
                    "max_elapsed_seconds": 3000,
                    "max_packet_bytes": 16384,
                    "token_usage": "unavailable",
                    "max_tokens": None,
                },
                "packet": reference(packet),
                "checkpoint": reference(checkpoint),
            }
            dispatch["deadline_epoch"] = (
                dispatch["started_at_epoch"] + dispatch["budget"]["max_elapsed_seconds"]
            )
            dispatch_path = root / "dispatch.json"
            dispatch_path.write_text(json.dumps(dispatch))
            validated = run_script("phase-contract", "dispatch", str(dispatch_path))
            self.assertEqual(validated.returncode, 0, validated.stdout)

            result = {
                "phase_name": "implementation",
                "rotation_generation": 1,
                "coordinator_generation": 1,
                "fork_mode": "none",
                "compactions_observed": 0,
                "status": "rotate_required",
                "reason": "turn_budget",
                "checkpoint": reference(checkpoint),
                "completed_scope": ["todo-1"],
                "remaining_scope": ["todo-2"],
                "usage": {
                    "turns_used": 50,
                    "checkpoints_used": 1,
                    "elapsed_seconds": 2400,
                    "productive_seconds": 2100,
                    "stall_seconds": 300,
                    "tokens_used": None,
                },
            }
            result_path = root / "result.json"
            result_path.write_text(json.dumps(result))
            validated = run_script(
                "phase-contract", "result", str(result_path), "--dispatch", str(dispatch_path)
            )
            self.assertEqual(validated.returncode, 0, validated.stdout)

            result["status"] = "complete"
            result["reason"] = None
            result["remaining_scope"] = []
            result_path.write_text(json.dumps(result))
            rejected = run_script(
                "phase-contract", "result", str(result_path), "--dispatch", str(dispatch_path)
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("must be rotate_required", rejected.stdout)

            dispatch["fork_mode"] = "all"
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("prohibited", rejected.stdout)

            dispatch["fork_mode"] = "none"
            dispatch_path.write_text(json.dumps(dispatch))
            result.update({
                "status": "complete",
                "reason": None,
                "remaining_scope": [],
                "usage": {
                    "turns_used": 1,
                    "checkpoints_used": 1,
                    "elapsed_seconds": 1,
                    "productive_seconds": 1,
                    "stall_seconds": 0,
                    "tokens_used": None,
                },
                "compactions_observed": 1,
            })
            result_path.write_text(json.dumps(result))
            rejected = run_script(
                "phase-contract", "result", str(result_path), "--dispatch", str(dispatch_path)
            )
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("first observed compaction", rejected.stdout)

    def test_e0003_r1_deployment_ownership_contract_and_workflow_surfaces(self) -> None:
        plan = (ROOT / "skills/epic-plan/SKILL.md").read_text()
        split = (ROOT / "skills/epic-split/SKILL.md").read_text()
        todos = (ROOT / "skills/create-build-todos/SKILL.md").read_text()
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()
        epic = (ROOT / "skills/epic-flow/SKILL.md").read_text()
        promote = (ROOT / "skills/ticket-promote/SKILL.md").read_text()
        ownership = (ROOT / "skills/references/deployment-ownership.md").read_text()

        for contract in (plan, split, todos, guide, epic, promote, ownership):
            self.assertIn("deployment-ownership", contract)
        for classification in ("non_secret_config", "secret_value", "manual_gate"):
            self.assertIn(classification, ownership)
            self.assertIn(classification, guide)
        self.assertIn("Third-repo config ownership is a step", split)
        self.assertIn('mode="straight_to_prod"', epic)
        self.assertIn('mode="staging_only"', epic)
        self.assertIn('mode="promotion"', epic)
        self.assertIn("Do not reuse the planning snapshot", promote)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inventory = {
                "mode": "straight_to_prod",
                "implementation_repos": ["app"],
                "guide_status": "FINALIZED",
                "assets": [{
                    "asset_id": "deploy-config",
                    "tracked_path": "deploy/service.yaml",
                    "owner_repo": "ops",
                    "destination_repo": "app",
                    "owner_source": "ops/deploy/service.yaml",
                    "workspace_path": None,
                    "requirements": [{
                        "name": "PUBLIC_BASE_URL",
                        "classification": "non_secret_config",
                        "source_owner": "ops",
                        "destination": "production",
                        "application_route": "tracked manifest",
                        "safe_state_handling": "leave prior value",
                        "verification_evidence": "read-only manifest query",
                    }, {
                        "name": "API_TOKEN",
                        "classification": "secret_value",
                        "source_owner": "security",
                        "destination": "production vault",
                        "application_route": "audited secret manager",
                        "safe_state_handling": "leave service disabled",
                        "verification_evidence": "name-only binding check",
                    }, {
                        "name": "release approval",
                        "classification": "manual_gate",
                        "source_owner": "release owner",
                        "destination": "production promotion",
                        "application_route": "recorded approval",
                        "safe_state_handling": "do not promote",
                        "verification_evidence": "approval record exists",
                    }],
                }],
            }
            path = root / "inventory.json"
            path.write_text(json.dumps(inventory))
            blocked = run_script("deployment-ownership-contract", str(path))
            self.assertEqual(blocked.returncode, 3)
            codes = {item["code"] for item in json.loads(blocked.stdout)["issues"]}
            self.assertIn("missing_owner_workspace", codes)
            self.assertIn("third_repo_step_missing", codes)

            inventory["mode"] = "staging_only"
            inventory["assets"][0]["requirements"][0]["verification_evidence"] = ""
            path.write_text(json.dumps(inventory))
            record_only = run_script("deployment-ownership-contract", str(path))
            self.assertEqual(record_only.returncode, 0)
            record_result = json.loads(record_only.stdout)
            self.assertEqual(record_result["status"], "record_only")
            self.assertIn(
                "finalized_guide_has_incomplete_rows",
                {item["code"] for item in record_result["issues"]},
            )

            inventory.update({
                "mode": "promotion",
                "recheck_of": "sha256:prior",
                "rechecked_at_epoch": time.time(),
            })
            inventory["assets"][0]["requirements"][0][
                "verification_evidence"
            ] = "read-only manifest query"
            inventory["assets"][0].update({
                "workspace_path": str(root),
                "step_ticket": "F0042",
                "depends_on": ["F0041"],
            })
            path.write_text(json.dumps(inventory))
            ready = run_script("deployment-ownership-contract", str(path))
            self.assertEqual(ready.returncode, 0, ready.stdout)
            self.assertEqual(json.loads(ready.stdout)["status"], "ready")

            inventory["assets"][0]["requirements"][0]["classification"] = "token"
            path.write_text(json.dumps(inventory))
            invalid_classification = run_script(
                "deployment-ownership-contract", str(path)
            )
            self.assertEqual(invalid_classification.returncode, 2)
            self.assertIn("classification must be one of", invalid_classification.stdout)

    def test_e0003_r2_progress_leases_renew_rotate_and_preserve_time_truth(self) -> None:
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        for path in (
            "skills/epic-flow/SKILL.md",
            "skills/milestone-flow/SKILL.md",
            "skills/ticket-flow/SKILL.md",
        ):
            self.assertIn("durable progress lease", (ROOT / path).read_text().lower())
        self.assertIn("exactly one status inspection", economy)
        self.assertIn(
            "Elapsed wall time alone is never execution failure",
            " ".join(economy.split()),
        )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.json"
            second = root / "second.json"
            first.write_text('{"completed":["one"]}')
            second.write_text('{"completed":["one","two"]}')

            def progress(path: Path, sequence: int) -> dict:
                return {
                    "kind": "checkpoint",
                    "sequence": sequence,
                    "path": str(path),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }

            now = time.time()
            lease = {
                "phase_name": "build",
                "rotation_generation": 0,
                "lease_generation": 0,
                "inspection_budget": 1,
                "renewal_budget": 1,
                "renewals_used": 0,
                "started_at_epoch": now,
                "lease_deadline_epoch": now + 5,
                "absolute_deadline_epoch": now + 100,
                "durable_progress": progress(first, 1),
            }
            lease_path = root / "lease.json"
            lease_path.write_text(json.dumps(lease))
            issued = run_script("progress-lease", "issue", str(lease_path))
            self.assertEqual(issued.returncode, 0, issued.stdout)
            self.assertEqual(json.loads(issued.stdout)["action"], "block_once")

            observation = {
                "state": "sleep",
                "inspections_used": 1,
                "observed_at_epoch": now + 6,
                "durable_progress": progress(second, 2),
            }
            observation_path = root / "observation.json"
            observation_path.write_text(json.dumps(observation))
            renewed = run_script(
                "progress-lease", "expiry", str(observation_path), "--lease", str(lease_path)
            )
            renewal = json.loads(renewed.stdout)
            self.assertEqual(renewal["action"], "renew_once")
            self.assertEqual(renewal["state"], "sleep")
            self.assertFalse(renewal["elapsed_is_failure"])

            lease["renewals_used"] = 1
            lease_path.write_text(json.dumps(lease))
            exhausted = run_script(
                "progress-lease", "expiry", str(observation_path), "--lease", str(lease_path)
            )
            self.assertEqual(json.loads(exhausted.stdout)["reason"], "renewal_already_used")
            lease["renewals_used"] = 0
            lease_path.write_text(json.dumps(lease))

            observation["durable_progress"] = progress(first, 1)
            observation_path.write_text(json.dumps(observation))
            stale = run_script(
                "progress-lease", "expiry", str(observation_path), "--lease", str(lease_path)
            )
            self.assertEqual(json.loads(stale.stdout)["reason"], "stale_progress")

            observation["state"] = "complete"
            observation.pop("durable_progress")
            observation_path.write_text(json.dumps(observation))
            terminal = run_script(
                "progress-lease", "expiry", str(observation_path), "--lease", str(lease_path)
            )
            self.assertEqual(json.loads(terminal.stdout)["action"], "consume_terminal")

            observation.update({
                "state": "unknown",
                "observed_at_epoch": now + 101,
                "durable_progress": progress(second, 2),
            })
            observation_path.write_text(json.dumps(observation))
            deadline = run_script(
                "progress-lease", "expiry", str(observation_path), "--lease", str(lease_path)
            )
            self.assertEqual(json.loads(deadline.stdout)["reason"], "absolute_deadline")

            observation["inspections_used"] = 2
            observation_path.write_text(json.dumps(observation))
            rejected = run_script(
                "progress-lease", "expiry", str(observation_path), "--lease", str(lease_path)
            )
            self.assertEqual(rejected.returncode, 2)

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
        self.assertIn("`wait-ci <pr>`", economy)
        self.assertIn("`wait-prefect-flow <flow-run-id>", economy)
        self.assertIn("must resolve through `PATH`", economy)
        self.assertIn("deterministic bounded poller", economy)
        self.assertIn("one blocking foreground", economy)
        self.assertIn("deterministic bounded poller", milestone)
        self.assertNotIn("run_in_background`, then wait", build)

        for contract in (economy, ticket_build, milestone):
            self.assertIn("bin/compact-exec", contract)
            self.assertIn("output_file", contract)
            self.assertIn("rerun_command", contract)

        for contract in (epic, milestone, ticket_flow):
            self.assertIn("milestone-packet", contract)
            self.assertIn("SHA-256", contract)
            self.assertIn("packet artifact id", contract)
            self.assertIn("version/hash", contract)
            self.assertNotIn("current.json", contract)
            self.assertNotIn(".context/epic-flow", contract)
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
            "Run wait-ci once as one blocking foreground command.",
            "Never call wait_agent repeatedly for the same pending condition.",
            "The deterministic script, not the model, polls until its hard deadline.",
        )
        for sample in allowed:
            self.assertEqual([], model_polling_guidance_violations(sample), sample)

    def test_skill_contracts_keep_routine_and_ticket_paths_bounded(self) -> None:
        review = (ROOT / "skills/review/SKILL.md").read_text()
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        intensity = (ROOT / "skills/references/execution-intensity.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        retro = (ROOT / "skills/session-retro/SKILL.md").read_text()
        self.assertIn('fork_turns: "none"', economy)
        self.assertIn("Conductor enforcement", economy)
        self.assertIn("must not poll the parent session itself", economy)
        self.assertIn("plain review starts native-only", review)
        self.assertNotIn("/review mode:cross", ticket_flow)
        self.assertIn("Plan MCP artifact is mandatory", intensity)
        self.assertIn("workflow-efficiency-report --before-retro", retro)

    def test_every_shared_agent_uses_default_communication_protocol(self) -> None:
        communication = (ROOT / "skills/autism/SKILL.md").read_text()
        conventions = (ROOT / "CLAUDE.md").read_text()

        self.assertIn("Default communication protocol for every agent", communication)
        self.assertIn("Task-specific output schemas", communication)
        self.assertIn("Load and follow the `autism` skill for all communication", conventions)
        for agent in sorted((ROOT / "agents").glob("*.md")):
            frontmatter = agent.read_text().split("---", 2)[1]
            has_list_item = "\n  - autism\n" in frontmatter
            has_inline_item = bool(re.search(r"(?m)^skills:\s*\[[^\]]*\bautism\b", frontmatter))
            self.assertTrue(has_list_item or has_inline_item, agent.name)

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
        self.assertIn("Notification ownership is exclusive", sensitive)
        self.assertIn("must not produce the user notification itself", sensitive)
        self.assertNotIn('"Verify F0123 production schema', sensitive)
        self.assertIn("mcp__autodev_memory__search", memory)
        self.assertIn("mcp__autodev_memory__expand_entries", memory)
        self.assertNotIn("mcp__autodev-memory__", memory)

    def test_deploy_contracts_enforce_wait_preflight_redaction_and_negative_inventory(self) -> None:
        deploy = (ROOT / "skills/auto-deploy/SKILL.md").read_text()
        promote = (ROOT / "skills/ticket-promote/SKILL.md").read_text()
        create_pr = (ROOT / "skills/create-pr/SKILL.md").read_text()
        methodology = (ROOT / "skills/ticket-plan/references/plan-methodology.md").read_text()

        self.assertIn("wait-ci {pr_number}", deploy)
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

    def test_deployment_wait_owners_enforce_one_fresh_conductor_leaf(self) -> None:
        owners = (
            ROOT / "skills/auto-deploy/SKILL.md",
            ROOT / "skills/ticket-promote/SKILL.md",
            ROOT / "skills/ticket-verify/SKILL.md",
            ROOT / "skills/milestone-flow/SKILL.md",
            ROOT / "skills/workflow-authoring/SKILL.md",
            ROOT / "skills/references/ci-self-heal.md",
        )
        for path in owners:
            contract = path.read_text()
            normalized = " ".join(contract.split())
            self.assertIn('fork_turns: "none"', contract, path)
            self.assertRegex(normalized, r"block(?:s)? once", path)
            self.assertNotIn("gh pr checks --watch", contract, path)
            self.assertRegex(
                normalized,
                r"(never|must not).{0,160}(polls?|repeated)",
                path,
            )

    def test_workflow_authoring_and_promotion_contracts_are_worktree_safe(self) -> None:
        authoring = (ROOT / "skills/workflow-authoring/SKILL.md").read_text()
        deploy = (ROOT / "skills/auto-deploy/SKILL.md").read_text()
        promote = (ROOT / "skills/ticket-promote/SKILL.md").read_text()
        conventions = (ROOT / "CLAUDE.md").read_text()

        self.assertIn("bin/check-agent-workflows", authoring)
        self.assertIn("bin/verify-agent-workflows-live", authoring)
        self.assertIn("bounded discovery", authoring)
        for contract in (conventions, authoring, deploy, promote):
            self.assertIn("align-merged-pr-workspace", contract)
        self.assertIn("zero-commit rebase", conventions)
        self.assertIn("normal `git rebase origin/<base>`", conventions)
        self.assertNotIn("gh pr merge <pr_number> --squash --delete-branch", promote)
        self.assertIn('test "$(gh pr view <pr_number> --json state -q .state)" = "MERGED"',
                      promote)
        self.assertTrue(os.access(ROOT / "bin/align-merged-pr-workspace", os.X_OK))
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
            self.assertEqual(summary["status"], "failure")
            self.assertEqual(summary["exit_code"], 3)
            self.assertEqual(summary["output_bytes"], 9)
            self.assertEqual(summary["tail"], "56789")
            self.assertEqual(Path(summary["output_file"]).read_text(), "123456789")
            self.assertEqual(Path(summary["output_file"]).stat().st_mode & 0o777, 0o600)
            expected = f"cd {shlex.quote(str(ROOT))} && "
            expected += shlex.join(["/bin/sh", "-c", "printf 123456789; exit 3"])
            self.assertEqual(summary["rerun_command"], expected)
            self.assertEqual(summary["head_sha"], subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
            ).stdout.strip())
            self.assertIsNotNone(summary["tree_sha"])

    def test_compact_exec_tree_sha_tracks_uncommitted_working_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"],
                           cwd=repo, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
            target = repo / "value.txt"
            target.write_text("before\n")
            subprocess.run(["git", "add", "value.txt"], cwd=repo, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=repo, check=True)
            clean = subprocess.run(
                [str(ROOT / "bin/compact-exec"), "--", "true"],
                cwd=repo, capture_output=True, text=True, check=True,
            )
            clean_summary = json.loads(clean.stdout)
            self.assertEqual(clean_summary["tree_sha"], clean_summary["head_tree_sha"])
            target.write_text("after\n")
            dirty = subprocess.run(
                [str(ROOT / "bin/compact-exec"), "--", "true"],
                cwd=repo, capture_output=True, text=True, check=True,
            )
            dirty_summary = json.loads(dirty.stdout)
            self.assertNotEqual(dirty_summary["tree_sha"], dirty_summary["head_tree_sha"])
            self.assertTrue(dirty_summary["working_tree_dirty"])
            self.assertFalse(dirty_summary["tree_changed_during_command"])
            mutating = subprocess.run(
                [str(ROOT / "bin/compact-exec"), "--", "/bin/sh", "-c",
                 "printf 'later\\n' > value.txt"],
                cwd=repo, capture_output=True, text=True, check=True,
            )
            mutating_summary = json.loads(mutating.stdout)
            self.assertTrue(mutating_summary["tree_changed_during_command"])
            self.assertNotEqual(mutating_summary["tree_sha"], mutating_summary["post_tree_sha"])

    def test_noisy_command_linter_rejects_raw_and_accepts_compact_examples(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills" / "demo" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# Demo\n\n```bash\npytest -q\n```\n")
            rejected = run_script("workflow-noisy-command-check", "--root", str(root))
            self.assertEqual(rejected.returncode, 2)
            self.assertEqual(json.loads(rejected.stdout)["status"], "fail")
            skill.write_text("# Demo\n\n```bash\nbin/compact-exec -- pytest -q\n```\n")
            accepted = run_script("workflow-noisy-command-check", "--root", str(root))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)
            skill.write_text(
                "# Demo\n\n```bash\n"
                "bin/compact-exec -- prefect deploy --pool production\n"
                "```\n"
            )
            unsafe_production = run_script(
                "workflow-noisy-command-check", "--root", str(root)
            )
            self.assertEqual(unsafe_production.returncode, 2)
            self.assertIn(
                "production_mutation_requires_redacted_exec",
                unsafe_production.stdout,
            )
            skill.write_text(
                "# Demo\n\n```bash\n"
                "bin/redacted-exec -- prefect deploy --pool production\n"
                "```\n"
            )
            safe_production = run_script(
                "workflow-noisy-command-check", "--root", str(root)
            )
            self.assertEqual(safe_production.returncode, 0, safe_production.stdout)

    def test_noisy_command_linter_guards_broad_generated_searches(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/demo/SKILL.md"
            skill.parent.mkdir(parents=True)

            unsafe = (
                "grep -R needle .\n",
                'grep -rn "needle\\|other" .\n',
                "rg needle .\n",
                "find . -name '*.json'\n",
            )
            for command in unsafe:
                skill.write_text(f"# Demo\n\n```bash\n{command}```\n")
                result = run_script("workflow-noisy-command-check", "--root", str(root))
                self.assertEqual(result.returncode, 2, (command, result.stdout))
                self.assertIn("broad_search_requires_scope_exclusions", result.stdout)

            skill.write_text(
                "# Demo\n\n```bash\n"
                "rg needle skills/auto-deploy/SKILL.md\n"
                "rg needle .context/staging-port/result.log\n"
                "rg needle . -g '!.context/**' -g '!node_modules/**' "
                "-g '!build/**' --max-count 20\n"
                "find . \\( -path './.context' -o -path './node_modules' "
                "-o -path './build' \\) -prune -o -name '*.md' -print | head -n 20\n"
                "bin/compact-exec -- find . -name '*.json'\n"
                "```\n"
            )
            accepted = run_script("workflow-noisy-command-check", "--root", str(root))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

    def test_auto_deploy_manifest_routes_complete_references(self) -> None:
        deploy = (ROOT / "skills/auto-deploy/SKILL.md").read_text()
        expected = {
            "P1": "references/lifecycle.md",
            "P2": "references/lifecycle.md",
            "P2b": "references/lifecycle.md",
            "P3": "references/provider-project.md",
            "P4": "references/lifecycle.md",
            "P5": "references/lifecycle.md",
            "P6": "references/change-and-execution.md",
            "P6b": "references/change-and-execution.md",
            "P7": "references/lifecycle.md",
            "P8": "references/change-and-execution.md",
            "P8b": "references/back-sync.md",
            "P9": "references/verification-and-status.md",
            "P10": "references/verification-and-status.md",
        }
        self.assertLess(len(deploy.encode()), 16_384)
        for phase, reference in expected.items():
            self.assertRegex(deploy, rf"(?m)^\| {phase} \|.*`{re.escape(reference)}`")
            self.assertTrue((ROOT / "skills/auto-deploy" / reference).is_file(), reference)
        self.assertIn("references/migration-and-runtime-evidence.md", deploy)
        self.assertIn("timeout_ms: 600000", deploy)
        self.assertIn("bin/progress-lease policy", deploy)

        references = ROOT / "skills/auto-deploy/references"
        lifecycle = (references / "lifecycle.md").read_text()
        execution = (references / "change-and-execution.md").read_text()
        migration = (references / "migration-and-runtime-evidence.md").read_text()
        provider = (references / "provider-project.md").read_text()
        back_sync = (references / "back-sync.md").read_text()
        verification = (references / "verification-and-status.md").read_text()
        for anchor in (
            "get_ticket",
            "wait-ci",
            "align-merged-pr-workspace",
            "Phase 2b: Local CI parity before GitHub CI",
            "bin/ci-local --require-receipt",
        ):
            self.assertIn(anchor, lifecycle)
        self.assertLess(
            lifecycle.index("### Phase 2b: Local CI parity before GitHub CI"),
            lifecycle.index("### Phase 4: Check CI"),
        )
        self.assertIn("before every push that\ncreates a new CI generation", lifecycle)
        for anchor in ("Preflight every deploy command", "bin/redacted-exec", "negative inventory"):
            self.assertIn(anchor, execution)
        self.assertIn("runtime evidence producer", migration.lower())
        self.assertIn("A schema change without its required", migration)
        self.assertIn("Thomas-only", provider)
        self.assertIn("project-specific deploy command", provider)
        self.assertIn("content-preserving sync", back_sync)
        self.assertIn("update_ticket", verification)
        self.assertIn("update_epic", verification)
        self.assertIn("terminal-outcomes.md", verification)

        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        self.assertIn("Literal Conductor CI recipe", economy)
        self.assertIn("timeout_ms: 600000", economy)
        self.assertIn("exact `resume_command` unchanged", economy)

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
            self.assertEqual(summary["polls"], 3)
            self.assertEqual(result.stdout.count("\n"), 1)

    def test_shared_waiters_are_portable_from_an_unrelated_consumer_repo(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            installed_bin = root / "installed-bin"
            consumer = root / "consumer-repository"
            installed_bin.mkdir()
            consumer.mkdir()
            for name in ("wait-ci", "wait-prefect-flow"):
                (installed_bin / name).symlink_to(ROOT / "bin" / name)

            fake_gh = root / "gh"
            fake_gh.write_text(
                "#!/bin/sh\n"
                "printf '[{\"name\":\"test\",\"state\":\"IN_PROGRESS\","
                "\"bucket\":\"pending\",\"link\":\"x\"}]'\n"
            )
            fake_gh.chmod(0o755)
            fake_prefect = root / "prefect"
            fake_prefect.write_text(
                "#!/bin/sh\n"
                "printf '{\"state\":{\"type\":\"RUNNING\",\"name\":\"Running\"}}'\n"
            )
            fake_prefect.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{installed_bin}{os.pathsep}{environment['PATH']}"

            ci = subprocess.run(
                [
                    "wait-ci", "12", "--gh", str(fake_gh), "--timeout", "0",
                    "--initial-delay", "0", "--max-delay", "0",
                ],
                cwd=consumer,
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(ci.returncode, 124, ci.stderr)
            ci_summary = json.loads(ci.stdout)
            self.assertEqual(ci_summary["status"], "timeout")
            self.assertEqual(ci_summary["resume_command"], "wait-ci 12 --timeout 120")
            self.assertNotIn("bin/wait-", ci_summary["resume_command"])

            prefect = subprocess.run(
                [
                    "wait-prefect-flow", "run-123",
                    "--command-prefix", str(fake_prefect), "--timeout", "0",
                    "--initial-delay", "0", "--max-delay", "0",
                ],
                cwd=consumer,
                capture_output=True,
                text=True,
                env=environment,
                check=False,
            )
            self.assertEqual(prefect.returncode, 124, prefect.stderr)
            prefect_summary = json.loads(prefect.stdout)
            self.assertEqual(prefect_summary["status"], "timeout")
            self.assertTrue(
                prefect_summary["resume_command"].startswith(
                    "wait-prefect-flow run-123 "
                )
            )
            self.assertNotIn("bin/wait-", prefect_summary["resume_command"])

    def test_active_workflow_guidance_uses_path_resolved_shared_waiters(self) -> None:
        result = run_script("workflow-waiter-portability-check")
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertEqual(json.loads(result.stdout)["violations"], [])

    def test_waiter_portability_check_rejects_repo_relative_guidance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills" / "demo" / "SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text("# Demo\n\n```bash\nbin/wait-ci 42\n```\n")
            result = run_script(
                "workflow-waiter-portability-check", "--root", str(root)
            )
            self.assertEqual(result.returncode, 2)
            violation = json.loads(result.stdout)["violations"][0]
            self.assertEqual(violation["waiter"], "bin/wait-ci")
            self.assertEqual(
                violation["reason"], "shared_waiters_must_resolve_through_PATH"
            )

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

    def test_ticket_deploy_owns_the_complete_staging_repair_chain(self) -> None:
        wrapper = (ROOT / "skills/ticket-deploy/SKILL.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()

        self.assertIn("--no-promote --produce-evidence", wrapper)
        self.assertIn("/ticket-promote <ID>", wrapper)
        self.assertIn("Staging repair/redeploy/reverify loop", wrapper)
        self.assertIn("**one total repair round** for `direct`/`standard`", wrapper)
        self.assertIn("three only for explicit `heavy`", wrapper)
        self.assertIn("before PR creation or the first CI wait", wrapper)
        self.assertIn('fork_turns: "none"', wrapper)
        self.assertIn("returned to active /ticket-deploy staging repair loop", verify)
        self.assertNotIn(
            "do not retry past a failure without a new explicit user instruction", wrapper
        )
        self.assertNotIn("do not retry past a `FAIL`/`BLOCKED` verdict", ticket_flow)
        self.assertIn("final `completed` status", wrapper)
        self.assertIn("ticket-attributed incident cleanup", wrapper)
        self.assertIn("scripts.prefect_ops.delete_ticket_flow_runs", wrapper)
        self.assertIn("stop and ask the user for\nconfirmation", wrapper)
        self.assertIn("wait-prefect-flow", verify)
        self.assertIn("preserve the failed flow-run history", verify)
        self.assertIn("structurally attributes Prefect incident flow runs", verify)
        self.assertIn("/ticket-deploy <ID> staging", ticket_flow)
        self.assertIn("/ticket-deploy <ID> full", ticket_flow)
        self.assertIn("stops after the staging verify leg", ticket_flow)
        self.assertTrue(os.access(ROOT / "bin/wait-prefect-flow", os.X_OK))

    def test_mutation_owners_self_repair_bounded_staging_prerequisites(self) -> None:
        autonomy = (ROOT / "skills/references/staging-autonomy.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        deploy = (ROOT / "skills/ticket-deploy/SKILL.md").read_text()
        ticket_flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        milestone = (ROOT / "skills/milestone-flow/SKILL.md").read_text()
        epic = (ROOT / "skills/epic-flow/SKILL.md").read_text()
        auto_deploy = (ROOT / "skills/auto-deploy/SKILL.md").read_text()
        outcomes = (ROOT / "skills/references/terminal-outcomes.md").read_text()
        normalized_deploy = " ".join(deploy.split())
        normalized_ticket_flow = " ".join(ticket_flow.split())

        for classification in (
            "staging_safe",
            "owner_repair",
            "human_required",
            "external_wait",
        ):
            self.assertIn(classification, autonomy)
        self.assertIn("documented synthetic tenants/users/rows", autonomy)
        self.assertIn("at most three distinct actions", " ".join(autonomy.split()))
        self.assertIn("Two consecutive actions with no source-of-truth progress", autonomy)
        self.assertIn("Do not ask the user to run a command the agent can run", autonomy)
        self.assertIn("machine-readable repair packet", verify)
        self.assertIn("missing synthetic fixture", verify)
        self.assertIn("does not make the verifier a mutation owner", verify)
        self.assertIn("does not count against the product-code repair round", normalized_deploy)
        self.assertIn(
            "agent-resolvable `BLOCKED` is not immediately terminal",
            normalized_ticket_flow,
        )
        self.assertIn("--no-promote --produce-evidence", milestone)
        self.assertIn("consume the verifier's staging-autonomy repair packet", milestone)
        self.assertIn("do not surface a milestone staging `BLOCKED`", epic)
        self.assertIn("staging-autonomy.md", auto_deploy)
        self.assertIn("Staging blocker legitimacy", outcomes)
        self.assertIn("do not print a Next command", outcomes)

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
        self.assertIn("| Closeout check | <READY|NOT READY", outcome)
        self.assertIn("| Not verified |", outcome)
        self.assertIn("## 4. Always end with the exact next command", outcome)
        self.assertIn("### Next", outcome)
        self.assertIn("copy-pasteable invocation", outcome)
        self.assertIn("This section is never omitted", outcome)
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

    def test_ticket_cleanup_contract_supports_large_content_addressed_manifests(self) -> None:
        cleanup = (ROOT / "skills/references/verify-deferred-cleanup.md").read_text()

        self.assertIn("scope_manifest_reference", cleanup)
        self.assertIn("same parent ticket/epic", cleanup)
        self.assertIn("sorted_utf8_lines_v1", cleanup)
        self.assertIn("must equal the resolved manifest exactly", cleanup)
        self.assertIn("Immediately before mutation, re-fetch", cleanup)
        self.assertIn("each internal batch is at", cleanup)
        self.assertIn("most 200 IDs", cleanup)
        self.assertIn("A partial batch resume is allowed only when", cleanup)
        self.assertIn("zero-target dry-run", cleanup)
        self.assertIn("never truncate the inline list", cleanup)

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
                                "--orchestrator-thread-id", "root-rollout",
                                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                                "--telemetry-file", str(root / "telemetry"), env=env)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["key"], "codex")
            sidecar = json.loads(next(usage_dir.glob("*.json")).read_text())
            self.assertTrue(sidecar["usage_available"])
            self.assertEqual(sidecar["usage"]["total_tokens"], 12)
            self.assertEqual(sidecar["model"], "provider_default")
            self.assertEqual(sidecar["repo"], str(ROOT.resolve()))
            self.assertEqual(sidecar["orchestrator_thread_id"], "root-rollout")
            self.assertEqual(sidecar["orchestrator_id_source"], "explicit_cli")
            self.assertRegex(sidecar["started_at"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
            self.assertGreaterEqual(sidecar["duration_ms"], 0)
            self.assertNotIn("all good", json.dumps(sidecar))

    def test_external_review_sidecar_is_attributed_to_root_rollout_report(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_bin = root / "bin"
            fake_bin.mkdir()
            codex = fake_bin / "codex"
            codex.write_text(
                "#!/bin/sh\nout=''\nprev=''\n"
                "for arg in \"$@\"; do [ \"$prev\" = '-o' ] && out=\"$arg\"; prev=\"$arg\"; done\n"
                "cat >/dev/null\n"
                "printf '%s' '{\"reviewer_key\":\"codex\",\"findings\":[],"
                "\"residual_risks\":[],\"testing_gaps\":[]}' > \"$out\"\n"
                "echo '{\"type\":\"turn.completed\",\"usage\":{\"input_tokens\":11,"
                "\"cached_input_tokens\":3,\"output_tokens\":2,\"total_tokens\":13}}'\n"
            )
            codex.chmod(0o755)
            packet = root / "packet"
            packet.write_text("<autodev-memory-task-context>\nx\n</autodev-memory-task-context>")
            usage_dir = root / "usage"
            env = os.environ.copy()
            env["PATH"] = str(fake_bin) + os.pathsep + env["PATH"]
            adapter = run_script(
                "external-agent", "--task", "review", "--provider", "codex",
                "--base", "origin/main", "--repo", str(ROOT),
                "--orchestrator-thread-id", "root-rollout",
                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                "--telemetry-file", str(root / "telemetry"), env=env,
            )
            self.assertEqual(adapter.returncode, 0, adapter.stderr)
            self.write_session(root / "root.jsonl", {"id": "root-rollout"}, [
                {"timestamp": "2026-07-25T20:00:00Z", "type": "event_msg",
                 "payload": {"type": "task_started"}},
            ])
            report_result = run_script(
                "workflow-efficiency-report", str(root / "root.jsonl"),
                "--sessions-root", str(root), "--external-usage-dir", str(usage_dir),
            )
            self.assertEqual(report_result.returncode, 0, report_result.stderr)
            external = json.loads(report_result.stdout)["external_provider_usage"]
            self.assertEqual(external["sidecars"], 1)
            self.assertEqual(external["available_runs"], 1)
            self.assertEqual(external["usage"]["total_tokens"], 13)
            self.assertEqual(external["status"], "complete")

    def test_active_external_dispatches_pass_explicit_orchestrator_identifier(self) -> None:
        paths = (
            "skills/review/SKILL.md",
            "skills/investigate/SKILL.md",
            "skills/research/SKILL.md",
            "skills/ticket-plan/SKILL.md",
            "skills/epic-plan/SKILL.md",
            "agents/external-reviewer.md",
            "agents/external-planner.md",
        )
        for path in paths:
            contract = (ROOT / path).read_text()
            self.assertIn("--orchestrator-thread-id", contract, path)
        external_agent = (ROOT / "bin/external-agent").read_text()
        self.assertIn('"--orchestrator-thread-id", required=True', external_agent)
        self.assertIn('"orchestrator_id_source": "explicit_cli"', external_agent)

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
                                "--orchestrator-thread-id", "root-rollout",
                                "--memory-context-file", str(packet), "--usage-dir", str(usage_dir),
                                "--telemetry-file", str(root / "telemetry"), env=env)
            self.assertEqual(result.returncode, 2)
            sidecar = json.loads(next(usage_dir.glob("*.json")).read_text())
            self.assertFalse(sidecar["usage_available"])
            self.assertEqual(sidecar["adapter_outcome"], "invalid_provider_output")
            self.assertEqual(sidecar["attempt_statuses"], ["exit_7", "exit_7"])
            self.assertEqual(sidecar["orchestrator_thread_id"], "root-rollout")

    def test_external_agent_requires_explicit_orchestrator_identifier(self) -> None:
        result = run_script("external-agent", "--task", "research", "--provider", "codex",
                            "--question", "inspect code", "--repo", str(ROOT),
                            "--memory-context-file", "/missing")
        self.assertEqual(result.returncode, 2)
        self.assertIn("--orchestrator-thread-id", result.stderr)

    def test_e0006_production_only_topology_is_exact_and_fail_closed(self) -> None:
        allowed = run_script(
            "environment-capability",
            "--project", "autodev", "--repo", "autodev-dashboard",
            "--surface", "dashboard", "--production-contract", "--user-authorized",
            "--verifier-mode", "read_only_backdoor_browser",
        )
        self.assertEqual(allowed.returncode, 0, allowed.stdout)
        allowed_result = json.loads(allowed.stdout)
        self.assertEqual(allowed_result["route"], "production_only")
        self.assertFalse(allowed_result["production_visible_surface_allowed"])

        visible_allowed = run_script(
            "environment-capability",
            "--project", "autodev", "--repo", "autodev-dashboard",
            "--surface", "dashboard", "--production-contract", "--user-authorized",
            "--verifier-mode", "read_only_backdoor_browser",
            "--short-expiry-enforced", "--mutation-denied", "--project-scoped",
            "--secret-safe-transport", "--real-browser-available", "--producers-preflighted",
        )
        self.assertTrue(
            json.loads(visible_allowed.stdout)["production_visible_surface_allowed"]
        )

        missing_gate = run_script(
            "environment-capability",
            "--project", "autodev", "--repo", "autodev-dashboard",
            "--surface", "dashboard", "--production-contract",
            "--verifier-mode", "read_only_backdoor_browser",
        )
        self.assertEqual(json.loads(missing_gate.stdout)["route"], "staging_first")

        unknown = run_script(
            "environment-capability",
            "--project", "ordinary", "--repo", "app", "--surface", "web",
            "--production-contract", "--user-authorized",
            "--verifier-mode", "read_only_backdoor_browser",
        )
        self.assertEqual(json.loads(unknown.stdout)["route"], "staging_first")

        epic = (ROOT / "skills/epic-flow/SKILL.md").read_text()
        ticket = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        for contract in (epic, ticket):
            self.assertIn("bin/environment-capability", contract)
            self.assertIn("staging-first", contract)
        self.assertIn("thin coordinator", epic)
        self.assertIn("immutable packet", epic)

    def test_e0006_visible_surface_production_exception_requires_every_gate(self) -> None:
        visible = (ROOT / "skills/references/verify-visible-surfaces.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        for phrase in (
            "server enforces a short expiry",
            "read-only",
            "exact project/surface",
            "secret-safe",
            "real browser",
            "backdoor is authentication only",
        ):
            self.assertIn(phrase, visible)
        self.assertIn("Missing/unknown topology or any failed gate", verify)
        self.assertIn("real-browser screenshot evidence", verify)

    def test_e0006_resolver_is_partitioned_bounded_and_checkpointed(self) -> None:
        resolve = (ROOT / "skills/resolve-review/SKILL.md").read_text()
        for phrase in (
            "coherent subsystem/write-scope chains",
            "Max turns",
            "Max checkpoints",
            "Max elapsed",
            "Max tokens when exposed",
            "bin/phase-contract dispatch",
            "bin/phase-contract result",
            "Checkpoint each finding separately",
            "first observable compaction",
            'fresh `fork_turns: "none"` replacement',
            "orchestrator owns the final validation gate",
        ):
            self.assertIn(phrase, resolve)
        self.assertIn("Never put every gated or", resolve)

    def test_e0006_ticket_context_examples_are_manifest_first_and_linted(self) -> None:
        for path in (
            "skills/create-build-todos/SKILL.md",
            "skills/build/SKILL.md",
            "skills/review/SKILL.md",
        ):
            contract = (ROOT / path).read_text()
            self.assertIn('detail="light"', contract, path)
            self.assertIn("context_version", contract, path)
            self.assertIn("get_artifact", contract, path)
            self.assertIn("immutable packet", contract, path)

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            skill = root / "skills/demo/SKILL.md"
            skill.parent.mkdir(parents=True)
            skill.write_text('get_ticket(project="x", detail="full")\n')
            rejected = run_script("workflow-ticket-context-check", "--root", str(root))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("unfiltered_full_ticket_read", rejected.stdout)
            skill.write_text(
                'get_ticket(project="x", detail="full", artifact_types=["plan"])\n'
            )
            accepted = run_script("workflow-ticket-context-check", "--root", str(root))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

    def test_e0006_progress_policy_rejects_model_polling_and_accepts_waiter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt = Path(directory) / "receipt.json"
            repeated = {
                "observations": [
                    {"actor": "model", "operation": "wait_agent", "condition": "child-1",
                     "lease_expiry_inspection": True},
                    {"actor": "model", "operation": "wait_agent", "condition": "child-1",
                     "lease_expiry_inspection": True},
                ]
            }
            receipt.write_text(json.dumps(repeated))
            rejected = run_script("progress-lease", "policy", str(receipt))
            self.assertEqual(rejected.returncode, 2)
            self.assertFalse(json.loads(rejected.stdout)["execution_economy_compliant"])

            waiter = {
                "observations": [
                    {"actor": "deterministic_waiter", "operation": "github_status",
                     "condition": "pr-12", "lease_expiry_inspection": False},
                    {"actor": "deterministic_waiter", "operation": "github_status",
                     "condition": "pr-12", "lease_expiry_inspection": False},
                    {"actor": "model", "operation": "wait_agent", "condition": "waiter-leaf",
                     "lease_expiry_inspection": True},
                ]
            }
            receipt.write_text(json.dumps(waiter))
            accepted = run_script("progress-lease", "policy", str(receipt))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)
            self.assertTrue(json.loads(accepted.stdout)["execution_economy_compliant"])

    def test_e0006_report_detects_polling_and_attributes_validation_by_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repeated = json.dumps({"target": "child-1"})
            command = "cd /repo && bin/check-agent-workflows"
            receipt_a = json.dumps({
                "tree_sha": "a" * 40, "rerun_command": command,
                "status": "success", "exit_code": 0, "output_file": "/tmp/a",
            })
            receipt_b = json.dumps({
                "tree_sha": "b" * 40, "rerun_command": command,
                "status": "success", "exit_code": 0, "output_file": "/tmp/b",
            })
            repair_command = "cd /repo && pytest -q"
            receipt_failed = json.dumps({
                "tree_sha": "c" * 40, "rerun_command": repair_command,
                "status": "failure", "exit_code": 1, "output_file": "/tmp/c",
            })
            receipt_repaired = json.dumps({
                "tree_sha": "d" * 40, "rerun_command": repair_command,
                "status": "success", "exit_code": 0, "output_file": "/tmp/d",
            })
            self.write_session(root / "root.jsonl", {"id": "root"}, [
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "wait_agent", "call_id": "w1", "arguments": repeated}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "w1", "output": "pending"}},
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "wait_agent", "call_id": "w2", "arguments": repeated}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "w2", "output": "pending"}},
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "exec_command", "call_id": "v1", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "v1", "output": receipt_a}},
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "exec_command", "call_id": "v2", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "v2", "output": receipt_a}},
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "exec_command", "call_id": "v3", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "v3", "output": receipt_b}},
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "exec_command", "call_id": "v4", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "v4", "output": receipt_failed}},
                {"type": "response_item", "payload": {"type": "function_call",
                    "name": "exec_command", "call_id": "v5", "arguments": "{}"}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                    "call_id": "v5", "output": receipt_repaired}},
            ])
            result = run_script(
                "workflow-efficiency-report", str(root / "root.jsonl"),
                "--sessions-root", str(root), "--enforce-execution-economy",
            )
            self.assertEqual(result.returncode, 2)
            report = json.loads(result.stdout)
            self.assertFalse(report["execution_economy"]["compliant"])
            classes = {row["classification"] for row in report["validation_attribution"]}
            self.assertEqual(classes, {
                "exact_tree_duplicate",
                "changed_tree_run",
                "repair_run",
            })

    def test_e0006_build_budget_block_occurs_once(self) -> None:
        build = (ROOT / "skills/build/SKILL.md").read_text()
        self.assertEqual(build.count("| whole implementation owner |"), 1)


if __name__ == "__main__":
    unittest.main()

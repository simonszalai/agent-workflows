from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_script(
    name: str,
    *args: str,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ROOT / "bin" / name), *args],
        cwd=cwd or ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def reference(path: Path) -> dict[str, str]:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class PollAttributionTest(unittest.TestCase):
    def write_session(self, path: Path, records: list[dict]) -> None:
        values = [{"type": "session_meta", "payload": {"id": "root"}}, *records]
        path.write_text("\n".join(json.dumps(value) for value in values) + "\n")

    def call(
        self,
        name: str,
        call_id: str,
        arguments: dict,
        output: str = "pending",
    ) -> list[dict]:
        return [
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call",
                    "name": name,
                    "call_id": call_id,
                    "arguments": json.dumps(arguments),
                },
            },
            {
                "type": "response_item",
                "payload": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": output,
                },
            },
        ]

    def report(self, root: Path, *, enforce: bool = False) -> subprocess.CompletedProcess[str]:
        args = [str(root / "root.jsonl"), "--sessions-root", str(root)]
        if enforce:
            args.append("--enforce-execution-economy")
        return run_script("workflow-efficiency-report", *args)

    def test_preserves_pty_cell_and_active_child_condition_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            records = [
                *self.call("write_stdin", "p1", {"session_id": 12345}),
                *self.call("write_stdin", "p2", {"session_id": 12345}),
                *self.call("write_stdin", "p3", {"session_id": 67890}),
                *self.call("write_stdin", "p4", {"session_id": 67891}),
                *self.call("wait", "c1", {"cell_id": "cell-a"}),
                *self.call("wait", "c2", {"cell_id": "cell-a"}),
                *self.call("wait", "c3", {"cell_id": "cell-b"}),
                *self.call("wait", "c4", {"cell_id": "cell-c"}),
                *self.call(
                    "list_agents",
                    "l1",
                    {},
                    json.dumps({"agents": [{"id": "child-a", "status": "running"}]}),
                ),
                *self.call("wait_agent", "a1", {"timeout_ms": 30000}),
                *self.call(
                    "list_agents",
                    "l1b",
                    {},
                    json.dumps({"agents": [{"id": "child-a", "status": "running"}]}),
                ),
                *self.call("wait_agent", "a2", {"timeout_ms": 30000}),
                *self.call(
                    "list_agents",
                    "l2",
                    {},
                    json.dumps({"agents": [{"id": "child-b", "status": "running"}]}),
                ),
                *self.call("wait_agent", "b1", {"timeout_ms": 30000}),
            ]
            self.write_session(root / "root.jsonl", records)
            result = self.report(root, enforce=True)
            self.assertEqual(result.returncode, 2, result.stdout)
            violations = json.loads(result.stdout)["execution_economy"][
                "model_polling_violations"
            ]
            counts = {(row["tool"], row["count"]) for row in violations}
            self.assertEqual(counts, {("write_stdin", 2), ("wait", 2), ("wait_agent", 2)})

    def test_ambiguous_wait_agent_calls_are_not_asserted_as_repeats(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_session(
                root / "root.jsonl",
                [
                    *self.call("wait_agent", "a1", {"timeout_ms": 30000}),
                    *self.call("wait_agent", "a2", {"timeout_ms": 30000}),
                ],
            )
            result = self.report(root, enforce=True)
            self.assertEqual(result.returncode, 0, result.stdout)
            session = json.loads(result.stdout)["sessions"][0]
            self.assertEqual(session["model_polling"]["violations"], [])
            self.assertEqual(
                session["model_polling"]["conditions"][0]["attribution"], "ambiguous"
            )


class WaitCiTerminalSetTest(unittest.TestCase):
    def fake_gh(self, root: Path, responses: list[list[dict]]) -> Path:
        response_path = root / "responses.json"
        response_path.write_text(json.dumps(responses))
        script = root / "gh"
        script.write_text(
            "#!/usr/bin/env python3\n"
            "import json\n"
            "from pathlib import Path\n"
            f"root = Path({str(root)!r})\n"
            "count_path = root / 'count'\n"
            "count = int(count_path.read_text()) + 1 if count_path.exists() else 1\n"
            "count_path.write_text(str(count))\n"
            "responses = json.loads((root / 'responses.json').read_text())\n"
            "print(json.dumps(responses[min(count - 1, len(responses) - 1)]))\n"
        )
        script.chmod(0o755)
        return script

    @staticmethod
    def check(name: str, bucket: str) -> dict:
        return {
            "name": name,
            "state": bucket.upper(),
            "bucket": bucket,
            "link": f"https://checks/{name}",
        }

    def wait(self, fake: Path, timeout: str = "1") -> subprocess.CompletedProcess[str]:
        return run_script(
            "wait-ci",
            "12",
            "--gh",
            str(fake),
            "--timeout",
            timeout,
            "--initial-delay",
            "0",
            "--max-delay",
            "0",
        )

    def test_mixed_failure_waits_until_every_check_is_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake = self.fake_gh(root, [
                [self.check("failed", "fail"), self.check("tests", "pending")],
                [self.check("failed", "fail"), self.check("tests", "pass")],
            ])
            result = self.wait(fake)
            summary = json.loads(result.stdout)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(summary["polls"], 3)
            self.assertEqual(summary["checks_pending"], 0)
            self.assertEqual(summary["status_counts"], {"fail": 1, "pass": 1})
            self.assertEqual([row["name"] for row in summary["failed_checks"]], ["failed"])

    def test_success_cancellation_skip_timeout_and_check_set_evolution(self) -> None:
        cases = [
            (
                [[self.check("tests", "pass")], [self.check("tests", "pass")]],
                0,
                "success",
            ),
            (
                [
                    [self.check("tests", "cancel"), self.check("docs", "skipping")],
                    [self.check("tests", "cancel"), self.check("docs", "skipping")],
                ],
                1,
                "failure",
            ),
            (
                [
                    [self.check("first", "pass")],
                    [self.check("first", "pass"), self.check("late", "pending")],
                    [self.check("first", "pass"), self.check("late", "pass")],
                ],
                0,
                "success",
            ),
        ]
        for responses, expected_code, expected_status in cases:
            with self.subTest(expected_status=expected_status):
                with tempfile.TemporaryDirectory() as directory:
                    fake = self.fake_gh(Path(directory), responses)
                    result = self.wait(fake)
                    summary = json.loads(result.stdout)
                    self.assertEqual(result.returncode, expected_code, result.stdout)
                    self.assertEqual(summary["status"], expected_status)
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / "gh"
            fake.write_text(
                "#!/bin/sh\n"
                "printf '[{\"name\":\"tests\",\"state\":\"IN_PROGRESS\","
                "\"bucket\":\"pending\",\"link\":\"https://checks/tests\"}]'\n"
            )
            fake.chmod(0o755)
            timed_out = run_script(
                "wait-ci",
                "12",
                "--gh",
                str(fake),
                "--timeout",
                "0.5",
                "--initial-delay",
                "1",
                "--max-delay",
                "1",
            )
            summary = json.loads(timed_out.stdout)
            self.assertEqual(timed_out.returncode, 124)
            self.assertEqual(summary["checks_pending"], 1)
            self.assertIn("resume_command", summary)


class ExecutionEconomyPolicyTest(unittest.TestCase):
    def test_one_terminal_observation_allowed_and_second_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "policy.json"
            one = {
                "observations": [{
                    "actor": "model",
                    "operation": "write_stdin",
                    "condition": "pty-session-123",
                    "lease_expiry_inspection": False,
                }]
            }
            path.write_text(json.dumps(one))
            accepted = run_script("progress-lease", "policy", str(path))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)
            one["observations"].append(dict(one["observations"][0]))
            path.write_text(json.dumps(one))
            rejected = run_script("progress-lease", "policy", str(path))
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("repeated model polling", rejected.stdout)


class InvestigatorOutputContractTest(unittest.TestCase):
    def validate(self, path: Path) -> subprocess.CompletedProcess[str]:
        return run_script(
            "workflow-noisy-command-check", "--investigator-result", str(path)
        )

    def test_compact_receipt_and_failure_tail_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            log = root / "full.log"
            log.write_text("full diagnostic output\n" * 1000)
            row = {
                "command": "pytest -q",
                "status": "failure",
                "summary": "one test failed",
                "output_bytes": log.stat().st_size,
                "output_tail": "AssertionError",
                "compact_receipt": True,
                "log_file": str(log.resolve()),
                "log_sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
            }
            path = root / "result.json"
            path.write_text(json.dumps({"evidence": [row]}))
            accepted = self.validate(path)
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

            unwrapped = {**row, "compact_receipt": False}
            path.write_text(json.dumps({"evidence": [unwrapped]}))
            rejected = self.validate(path)
            self.assertIn("unwrapped_noisy_investigator_command", rejected.stdout)
            self.assertIn("unreferenced_noisy_output", rejected.stdout)

            missing_tail = {**row, "output_tail": ""}
            path.write_text(json.dumps({"evidence": [missing_tail]}))
            rejected = self.validate(path)
            self.assertIn("failure_tail_required", rejected.stdout)

            bad_hash = {**row, "log_sha256": "0" * 64}
            path.write_text(json.dumps({"evidence": [bad_hash]}))
            rejected = self.validate(path)
            self.assertIn("log_sha256_mismatch", rejected.stdout)


class BoundedOwnerDispatchTest(unittest.TestCase):
    def context(
        self,
        root: Path,
        packet: Path,
        context_owner: str,
    ) -> tuple[Path, list[dict]]:
        artifact_refs = [
            {"artifact_id": "source-1", "artifact_type": "source", "sha256": "a" * 64},
            {
                "artifact_id": "guide-1",
                "artifact_type": "deployment_guide",
                "sha256": "b" * 64,
            },
        ]
        receipt = {
            "schema_version": 1,
            "scope": "F0123",
            "context_owner": context_owner,
            "manifest_reads": [{
                "detail": "light",
                "context_version": "v1",
                "known_version": None,
            }],
            "artifact_reads": [
                {
                    "artifact_id": row["artifact_id"],
                    "sha256": row["sha256"],
                    "excerpt_bytes": 128,
                }
                for row in artifact_refs
            ],
            "child_packets": [{
                **reference(packet),
                "artifact_refs": [
                    {"artifact_id": row["artifact_id"], "sha256": row["sha256"]}
                    for row in artifact_refs
                ],
                "excerpt_bytes": 256,
            }],
            "canonical_updates": [],
        }
        path = root / "context.json"
        path.write_text(json.dumps(receipt))
        return path, artifact_refs

    def envelope(self, root: Path, phase: str) -> tuple[Path, dict]:
        packet = root / "packet.txt"
        packet.write_text("bounded immutable packet")
        context_owner = "ticket-deploy" if phase == "deployment" else "investigate"
        context_path, refs = self.context(root, packet, context_owner)
        started = time.time()
        role = "deployment_owner" if phase == "deployment" else "investigator"
        target = "staging"
        envelope = {
            "contract_profile": "bounded-owner",
            "phase_name": phase,
            "rotation_generation": 0,
            "coordinator_generation": 0,
            "fork_mode": "none",
            "compaction_signal": "available",
            "compactions_observed": 0,
            "first_incomplete_unit": phase,
            "started_at_epoch": started,
            "deadline_epoch": started + 1200,
            "budget": {
                "max_turns": 10,
                "max_checkpoints": 4,
                "max_elapsed_seconds": 1200,
                "max_packet_bytes": 16384,
                "token_usage": "unavailable",
                "max_tokens": None,
            },
            "packet": reference(packet),
            "checkpoint": None,
            "context_receipt": reference(context_path),
            "owner_context": {
                "owner_role": role,
                "ticket_id": "F0123",
                "target": target,
                "head_sha": "c" * 40,
                "tree_sha": "d" * 40,
                "context_strategy": "light_manifest_exact_artifacts",
                "dispatch_depth": 0,
                "redispatch_allowed": False,
                "dependencies": [],
                "evidence_gates": ["terminal evidence receipt"],
                "artifact_refs": refs,
            },
        }
        path = root / "dispatch.json"
        path.write_text(json.dumps(envelope))
        return path, envelope

    def test_accepts_fresh_hashed_owner_and_rejects_history_recursion_and_bad_context(
        self,
    ) -> None:
        for phase in ("deployment", "investigation"):
            with self.subTest(phase=phase):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    path, envelope = self.envelope(root, phase)
                    accepted = run_script("phase-contract", "owner-dispatch", str(path))
                    self.assertEqual(accepted.returncode, 0, accepted.stdout)

                    for field, value, expected in (
                        ("fork_mode", "all", "prohibited"),
                        ("fork_mode", "1", "must equal none"),
                    ):
                        changed = copy.deepcopy(envelope)
                        changed[field] = value
                        path.write_text(json.dumps(changed))
                        rejected = run_script(
                            "phase-contract", "owner-dispatch", str(path)
                        )
                        self.assertIn(expected, rejected.stdout)

                    changed = copy.deepcopy(envelope)
                    changed["owner_context"]["dispatch_depth"] = 1
                    path.write_text(json.dumps(changed))
                    rejected = run_script("phase-contract", "owner-dispatch", str(path))
                    self.assertIn("dispatch_depth must equal 0", rejected.stdout)

                    changed = copy.deepcopy(envelope)
                    changed["owner_context"]["artifact_refs"][0]["sha256"] = "e" * 64
                    path.write_text(json.dumps(changed))
                    rejected = run_script("phase-contract", "owner-dispatch", str(path))
                    self.assertIn("exact artifact read", rejected.stdout)

                    changed = copy.deepcopy(envelope)
                    changed["budget"]["max_packet_bytes"] = 16385
                    path.write_text(json.dumps(changed))
                    rejected = run_script("phase-contract", "owner-dispatch", str(path))
                    self.assertIn("exceeds 16384", rejected.stdout)

    def test_rejects_non_light_manifest_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, envelope = self.envelope(root, "deployment")
            context_path = Path(envelope["context_receipt"]["path"])
            context = json.loads(context_path.read_text())
            context["manifest_reads"][0]["detail"] = "full"
            context_path.write_text(json.dumps(context))
            envelope["context_receipt"] = reference(context_path)
            path.write_text(json.dumps(envelope))
            rejected = run_script("phase-contract", "owner-dispatch", str(path))
            self.assertIn("detail must equal light", rejected.stdout)


class DeployReceiptPersistenceTest(unittest.TestCase):
    def manifest(self, root: Path, *, fails: bool = False) -> dict:
        revision = "a" * 40
        return {
            "schema_version": 2,
            "run_id": "run-1",
            "revision": revision,
            "contract_status": "FINALIZED",
            "predicate_receipts": {
                "deploy": "deploy receipt",
                "authorization": "authorization receipt",
                "exact_transport": "transport receipt",
                "safety": "safety receipt",
                "evidence": "guide receipt",
            },
            "environment": "staging",
            "activation_key": "activation",
            "contract_version": "v1",
            "working_directory": str(root),
            "staging_revision": 1,
            "prior_staging_revisions": [],
            "state_path": str(root / "state.json"),
            "log_dir": str(root / "logs"),
            "overall_timeout_seconds": 10,
            "runtime_identity": {
                "command": [sys.executable, "-c", f"print({revision!r})"],
                "expected": revision,
                "poll_interval_seconds": 0.01,
                "wait_timeout_seconds": 2,
                "command_timeout_seconds": 1,
            },
            "rows": [{
                "id": "gate",
                "gate_class": "causal_ship_gate",
                "acceptance_source": {
                    "kind": "source_criterion",
                    "reference": "criterion 1",
                },
                "surface": "command",
                "command": [
                    sys.executable,
                    "-c",
                    "raise SystemExit(1)" if fails else "print('ok')",
                ],
                "expected_exit_code": 0,
                "timeout_seconds": 2,
                "resume_safe": True,
                "sample_size": 1,
                "minimum_sufficient_evidence": "one exact-path result",
                "causal_failure_meaning": "the shipped behavior is absent",
                "evidence_timing": {
                    "source": "immediate",
                    "maturity_delay_seconds": 0,
                    "acquisition_time_seconds": 1,
                    "verification_deadline_seconds": 10,
                },
                "exact_path_canary": False,
                "canary_row_id": None,
                "distinguishes_defect": "behavior absent",
                "failure_class_on_failure": "code_defect",
            }],
        }

    def assert_receipt(self, manifest: dict, output: dict) -> None:
        receipt_path = Path(output["receipt_path"])
        state = json.loads(Path(manifest["state_path"]).read_text())
        persisted = json.loads(receipt_path.read_text())
        self.assertEqual(state["terminal_receipt"], persisted)
        self.assertEqual(
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            output["receipt_sha256"],
        )
        self.assertEqual(state["receipt_sha256"], output["receipt_sha256"])
        self.assertFalse(Path(str(receipt_path) + ".tmp").exists())

    def test_default_explicit_success_failure_and_idempotency(self) -> None:
        for fails in (False, True):
            with self.subTest(fails=fails):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    manifest = self.manifest(root, fails=fails)
                    if fails:
                        manifest["receipt_path"] = str(root / "explicit-receipt.json")
                    path = root / "manifest.json"
                    path.write_text(json.dumps(manifest))
                    first = run_script("deploy-verify-controller", str(path))
                    self.assertEqual(first.returncode, 3 if fails else 0, first.stdout)
                    receipt = json.loads(first.stdout)
                    expected_path = (
                        root / "explicit-receipt.json"
                        if fails
                        else Path(str(root / "state.json") + ".receipt.json")
                    )
                    self.assertEqual(Path(receipt["receipt_path"]), expected_path)
                    self.assert_receipt(manifest, receipt)
                    repeated = run_script("deploy-verify-controller", str(path))
                    self.assertEqual(json.loads(repeated.stdout), receipt)

    def test_nonterminal_timeout_resumes_to_one_persisted_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "identity.txt"
            marker.write_text("not-live")
            manifest = self.manifest(root)
            revision = manifest["revision"]
            manifest["runtime_identity"]["command"] = [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    f"print(Path({str(marker)!r}).read_text())"
                ),
            ]
            manifest["runtime_identity"]["wait_timeout_seconds"] = 1
            path = root / "manifest.json"
            path.write_text(json.dumps(manifest))
            timed_out = run_script("deploy-verify-controller", str(path))
            self.assertEqual(timed_out.returncode, 4, timed_out.stdout)
            timeout_receipt = json.loads(timed_out.stdout)
            self.assertEqual(timeout_receipt["status"], "timeout")
            receipt_path = Path(str(root / "state.json") + ".receipt.json")
            self.assertFalse(receipt_path.exists())

            marker.write_text(revision)
            resumed = run_script(
                "deploy-verify-controller", "--resume", str(path)
            )
            self.assertEqual(resumed.returncode, 0, resumed.stdout)
            self.assert_receipt(manifest, json.loads(resumed.stdout))


class DeploymentGuideContractTest(unittest.TestCase):
    @staticmethod
    def complete() -> dict:
        row = {
            "id": "row-1",
            "exact_command": "read-only check",
            "expected_result": "one matching row",
            "bad_interpretation": "feature output is absent",
            "gate_class": "causal_ship_gate",
            "acceptance_source": {
                "kind": "source_criterion",
                "reference": "ticket acceptance criterion 1",
            },
            "sample_size": 1,
            "minimum_sufficient_evidence": "one exact-path result",
            "distinguishes_defect": "feature output is absent",
            "causal_failure_meaning": "the shipped feature output is absent",
            "failure_class_on_failure": "code_defect",
            "exact_path_canary": False,
            "canary_row_id": None,
            "evidence_timing": {
                "source": "immediate",
                "maturity_delay_seconds": 0,
                "acquisition_time_seconds": 60,
                "verification_deadline_seconds": 3600,
            },
            "bounded_producer": {
                "status": "N/A",
                "justification": "read-only evidence",
            },
            "cleanup": {
                "status": "N/A",
                "justification": "no temporary state",
            },
        }
        return {
            "schema_version": 2,
            "status": "FINALIZED",
            "activation_boundary": "origin/staging commit abc",
            "environments": {
                "staging": {"rows": [copy.deepcopy(row)]},
                "production": {"rows": [{**copy.deepcopy(row), "id": "row-2"}]},
            },
        }

    def validate(self, root: Path, value: dict) -> subprocess.CompletedProcess[str]:
        path = root / "guide.json"
        path.write_text(json.dumps(value))
        return run_script("deployment-guide-contract", str(path))

    def test_complete_missing_fields_and_justified_na(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            accepted = self.validate(root, self.complete())
            self.assertEqual(accepted.returncode, 0, accepted.stdout)
            summary = json.loads(accepted.stdout)
            self.assertEqual(
                summary["environment_row_counts"], {"production": 1, "staging": 1}
            )

            justified = self.complete()
            justified["environments"]["production"] = {
                "status": "N/A",
                "justification": "staging-only delivery",
            }
            accepted = self.validate(root, justified)
            self.assertEqual(accepted.returncode, 0, accepted.stdout)
            contract_path = root / "guide.json"
            production_rejected = run_script(
                "deployment-guide-contract",
                "--environment",
                "production",
                str(contract_path),
            )
            self.assertEqual(production_rejected.returncode, 2)
            self.assertIn("required environment rows", production_rejected.stdout)

            unjustified = copy.deepcopy(justified)
            unjustified["environments"]["production"]["justification"] = ""
            rejected = self.validate(root, unjustified)
            self.assertIn("justification", rejected.stdout)

            for field in (
                "id",
                "exact_command",
                "expected_result",
                "bad_interpretation",
                "gate_class",
                "acceptance_source",
                "sample_size",
                "minimum_sufficient_evidence",
                "distinguishes_defect",
                "causal_failure_meaning",
                "failure_class_on_failure",
                "exact_path_canary",
                "evidence_timing",
                "bounded_producer",
                "cleanup",
            ):
                changed = self.complete()
                changed["environments"]["staging"]["rows"][0].pop(field)
                rejected = self.validate(root, changed)
                self.assertEqual(rejected.returncode, 2, field)
                self.assertIn(field, rejected.stdout)

            for field in (
                "schema_version",
                "status",
                "activation_boundary",
                "environments",
            ):
                changed = self.complete()
                changed.pop(field)
                rejected = self.validate(root, changed)
                self.assertEqual(rejected.returncode, 2, field)
                self.assertIn(field, rejected.stdout)
            for environment in ("staging", "production"):
                changed = self.complete()
                changed["environments"].pop(environment)
                rejected = self.validate(root, changed)
                self.assertEqual(rejected.returncode, 2, environment)
                self.assertIn("environments", rejected.stdout)

    def test_r0059_style_natural_cohort_cannot_be_a_causal_release_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            value = self.complete()
            canary = value["environments"]["staging"]["rows"][0]
            canary["id"] = "exact-path-canary"
            canary["exact_path_canary"] = True
            canary["distinguishes_defect"] = "price-reaction leakage"
            cohort = copy.deepcopy(canary)
            cohort.update({
                "id": "matured-natural-cohort",
                "sample_size": 20,
                "exact_path_canary": False,
                "canary_row_id": "exact-path-canary",
                "statistical_threshold": {
                    "baseline": "24.5% of matured rows qualify",
                    "sample_size_rationale": "20 qualifying rows compare two cohorts",
                    "resource_budget": "natural traffic only",
                    "distinguishes_defect": "price-reaction leakage",
                },
                "evidence_timing": {
                    "source": "natural_traffic",
                    "maturity_delay_seconds": 86400,
                    "acquisition_time_seconds": 705307,
                    "verification_deadline_seconds": 172800,
                    "conservative_eligible_units_per_day": 2.45,
                },
            })
            value["environments"]["staging"]["rows"].append(cohort)
            rejected = self.validate(root, value)
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("infeasible for a causal_ship_gate", rejected.stdout)

            cohort["gate_class"] = "observation"
            cohort.pop("causal_failure_meaning")
            accepted = self.validate(root, value)
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

    def test_contract_skills_guard_the_three_overspecification_classes(self) -> None:
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        self.assertIn("Provider success is not evidence of non-empty business yield", guide)
        self.assertIn("orphan/stranded-record metric", guide)
        self.assertIn("bounded replay are insufficient", guide)
        self.assertIn("BLOCKED: invalid_evidence", verify)
        self.assertIn("evidence_eligible_at", verify)
        self.assertIn("never product FAIL", verify)

    def test_workflows_validate_before_finalization_and_mutation(self) -> None:
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()
        deploy = (ROOT / "skills/ticket-deploy/SKILL.md").read_text()
        self.assertLess(
            guide.index("deployment-guide-contract"),
            guide.index("mcp__autodev-memory__update_artifact"),
        )
        self.assertLess(
            deploy.index("deployment-guide-contract"),
            deploy.index("Run `/auto-deploy"),
        )


class CiLocalReceiptTest(unittest.TestCase):
    def git(self, root: Path, *args: str) -> None:
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_receipt_schema_current_tree_stale_tree_partial_and_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            workflow = repo / ".github" / "workflows" / "ci.yml"
            workflow.parent.mkdir(parents=True)
            workflow.write_text(
                "name: CI\n"
                "on: [pull_request]\n"
                "jobs:\n"
                "  quick:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo ok\n"
                "  skipped:\n"
                "    runs-on: ubuntu-latest\n"
                "    services: {db: {image: postgres:16}}\n"
                "    steps:\n"
                "      - run: echo db\n"
            )
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "test@example.com")
            self.git(repo, "config", "user.name", "Test")
            self.git(repo, "add", ".")
            self.git(repo, "commit", "-qm", "initial")
            receipt_path = repo / "receipt.json"
            result = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--run",
                "--receipt",
                str(receipt_path),
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            receipt = json.loads(receipt_path.read_text())
            self.assertEqual(receipt["schema_version"], 1)
            self.assertEqual(receipt["overall_status"], "passed_with_skips")
            self.assertEqual(receipt["executed_jobs"], ["quick"])
            self.assertEqual(receipt["jobs"][1]["result"], "skipped")
            self.assertTrue(receipt["started_at"])
            self.assertTrue(receipt["completed_at"])
            self.assertFalse(Path(str(receipt_path) + ".tmp").exists())

            malformed = dict(receipt)
            malformed.pop("jobs")
            receipt_path.write_text(json.dumps(malformed))
            invalid = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--require-receipt",
                str(receipt_path),
            )
            self.assertEqual(invalid.returncode, 2, invalid.stdout)
            incomplete = json.loads(json.dumps(receipt))
            incomplete["jobs"][0].pop("steps")
            receipt_path.write_text(json.dumps(incomplete))
            invalid_inventory = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--require-receipt",
                str(receipt_path),
            )
            self.assertEqual(invalid_inventory.returncode, 2, invalid_inventory.stdout)
            self.assertIn("exhaustive steps", invalid_inventory.stdout)
            receipt_path.write_text(json.dumps(receipt))

            current = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--require-receipt",
                str(receipt_path),
            )
            self.assertEqual(current.returncode, 0, current.stdout)
            workflow.write_text(workflow.read_text() + "# changed\n")
            stale = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--require-receipt",
                str(receipt_path),
            )
            self.assertEqual(stale.returncode, 3, stale.stdout)
            self.assertEqual(json.loads(stale.stdout)["status"], "stale")

            workflow.write_text(
                "name: CI\n"
                "on: [pull_request]\n"
                "jobs:\n"
                "  failing:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - {name: first, run: 'exit 1'}\n"
                "      - {name: second, run: 'exit 2'}\n"
                "      - {name: after, run: 'echo continued'}\n"
            )
            failed_path = repo / "failed.json"
            failed = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--run",
                "--receipt",
                str(failed_path),
            )
            self.assertEqual(failed.returncode, 1)
            failed_receipt = json.loads(failed_path.read_text())
            self.assertEqual(failed_receipt["overall_status"], "failed")
            self.assertEqual(failed_receipt["jobs"][0]["failed_steps"], ["first", "second"])
            self.assertEqual(
                [row["result"] for row in failed_receipt["jobs"][0]["steps"]],
                ["failed", "failed", "passed"],
            )

            workflow.write_text(
                "name: CI\n"
                "on: [pull_request]\n"
                "jobs:\n"
                "  expr:\n"
                "    runs-on: ubuntu-latest\n"
                "    steps:\n"
                "      - run: echo '${{ github.base_ref }}'\n"
            )
            partial_path = repo / "partial.json"
            partial = run_script(
                "ci-local",
                "--repo",
                str(repo),
                "--run",
                "--job",
                "expr",
                "--receipt",
                str(partial_path),
            )
            self.assertEqual(partial.returncode, 0, partial.stdout)
            partial_receipt = json.loads(partial_path.read_text())
            self.assertEqual(partial_receipt["jobs"][0]["result"], "partial")
            self.assertEqual(partial_receipt["overall_status"], "passed_with_skips")


class WorkflowSurfaceContractTest(unittest.TestCase):
    def test_fresh_owner_and_bounded_output_guidance_is_wired(self) -> None:
        deploy = (ROOT / "skills/ticket-deploy/SKILL.md").read_text()
        investigate = (ROOT / "skills/investigate/SKILL.md").read_text()
        investigator = (ROOT / "agents/investigator.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()
        ci = (ROOT / "skills/references/ci-self-heal.md").read_text()
        for contract in (deploy, investigate):
            self.assertIn("bin/phase-contract owner-dispatch", contract)
            self.assertNotIn('fork_turns="all"', contract)
            self.assertIn("light_manifest_exact_artifacts", contract)
        self.assertIn('fork_turns="none"', deploy)
        self.assertIn('fork_turns: "none"', investigate)
        self.assertIn("mode: deployment_owner", deploy)
        self.assertIn("redispatch_allowed: false", deploy)
        self.assertIn("bin/compact-exec", investigator)
        self.assertIn("--investigator-result", investigator)
        self.assertIn("exactly one blocking", economy)
        self.assertIn("full remaining deadline", economy)
        self.assertIn("--receipt <absolute-receipt-path>", ci)
        self.assertIn("--require-receipt <absolute-receipt-path>", ci)
        self.assertTrue(os.access(ROOT / "bin" / "deployment-guide-contract", os.X_OK))


if __name__ == "__main__":
    unittest.main()

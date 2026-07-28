from __future__ import annotations

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
) -> subprocess.CompletedProcess:
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


class DeployVerifyControllerTest(unittest.TestCase):
    def manifest(self, root: Path) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        revision = "a" * 40
        return {
            "schema_version": 1,
            "run_id": "ticket-rev-1",
            "revision": revision,
            "contract_status": "FINALIZED",
            "predicate_receipts": {
                "deploy": "deploy receipt 1",
                "authorization": "user authorization 1",
                "exact_transport": "transport canary contract 1",
                "safety": "safety preflight 1",
                "evidence": "deployment guide v1",
            },
            "environment": "staging",
            "activation_key": "ticket-activation",
            "contract_version": "guide-v1",
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
            "rows": [
                {
                    "id": "causal",
                    "gate_class": "causal_ship_gate",
                    "acceptance_source": {
                        "kind": "source_criterion",
                        "reference": "F1 acceptance #1",
                    },
                    "surface": "command",
                    "command": [sys.executable, "-c", "print('ok')"],
                    "expected_exit_code": 0,
                    "timeout_seconds": 2,
                    "resume_safe": True,
                    "sample_size": 1,
                    "exact_path_canary": False,
                    "canary_row_id": None,
                    "distinguishes_defect": "causal behavior is absent",
                    "failure_class_on_failure": "code_defect",
                },
                {
                    "id": "telemetry",
                    "gate_class": "observation",
                    "acceptance_source": {
                        "kind": "invariant",
                        "reference": "operational telemetry invariant",
                    },
                    "surface": "command",
                    "command": [sys.executable, "-c", "raise SystemExit(1)"],
                    "expected_exit_code": 0,
                    "timeout_seconds": 2,
                    "resume_safe": True,
                    "sample_size": 1,
                    "exact_path_canary": False,
                    "canary_row_id": None,
                    "distinguishes_defect": "telemetry unavailable",
                    "failure_class_on_failure": "external_observation",
                },
            ],
        }

    def test_observation_failure_does_not_fail_causal_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(self.manifest(root)))
            completed = run_script("deploy-verify-controller", str(manifest_path))
            self.assertEqual(completed.returncode, 0, completed.stdout)
            receipt = json.loads(completed.stdout)
            self.assertEqual(receipt["verdict"], "PASS")
            self.assertTrue(receipt["ship_gate_passed"])
            self.assertEqual(receipt["observation_failures"], 1)
            telemetry = next(row for row in receipt["rows"] if row["id"] == "telemetry")
            self.assertEqual(telemetry["next_owner"], "observation_owner")
            self.assertTrue(Path(telemetry["log_file"]).is_file())
            self.assertEqual(len(telemetry["log_sha256"]), 64)
            self.assertIn("output_tail", telemetry)

            repeated = run_script("deploy-verify-controller", str(manifest_path))
            self.assertEqual(repeated.returncode, 0, repeated.stdout)
            self.assertEqual(json.loads(repeated.stdout), receipt)

            changed_manifest = self.manifest(root)
            changed_manifest["run_id"] = "changed-after-state"
            manifest_path.write_text(json.dumps(changed_manifest))
            rejected = run_script("deploy-verify-controller", str(manifest_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("manifest changed", rejected.stdout)

    def test_manifest_fails_closed_for_statistics_stabilization_and_surfaces(self) -> None:
        mutations = []
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for label, mutate, expected in (
                (
                    "statistics",
                    lambda value: value["rows"][0].update({"sample_size": 20}),
                    "statistical_threshold",
                ),
                (
                    "stabilization",
                    lambda value: value.update({
                        "staging_revision": 3,
                        "prior_staging_revisions": ["b" * 40, "c" * 40],
                    }),
                    "stabilization",
                ),
                (
                    "surface",
                    lambda value: value["rows"][0].update({"surface": "render"}),
                    "unsupported",
                ),
            ):
                value = self.manifest(root / label)
                mutate(value)
                manifest_path = root / f"{label}.json"
                manifest_path.write_text(json.dumps(value))
                completed = run_script("deploy-verify-controller", str(manifest_path))
                self.assertEqual(completed.returncode, 2)
                self.assertIn(expected, completed.stdout)
                mutations.append(label)
        self.assertEqual(len(mutations), 3)

    def test_failed_canary_stops_high_n_and_unknown_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "high-n-ran"
            manifest = self.manifest(root)
            manifest["rows"] = [
                {
                    **manifest["rows"][0],
                    "id": "canary",
                    "command": [sys.executable, "-c", "raise SystemExit(1)"],
                    "exact_path_canary": True,
                    "distinguishes_defect": "transport framing breaks",
                    "failure_class_on_failure": "unknown",
                },
                {
                    **manifest["rows"][0],
                    "id": "high-n",
                    "command": [
                        sys.executable,
                        "-c",
                        f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
                    ],
                    "sample_size": 50,
                    "canary_row_id": "canary",
                    "distinguishes_defect": "transport framing breaks",
                    "statistical_threshold": {
                        "baseline": "production baseline 1/100 failures",
                        "sample_size_rationale": "50 separates a 10% defect from baseline",
                        "resource_budget": "50 units, 2 minutes, $1",
                        "distinguishes_defect": "transport framing breaks",
                    },
                },
            ]
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            completed = run_script("deploy-verify-controller", str(manifest_path))
            self.assertEqual(completed.returncode, 3, completed.stdout)
            receipt = json.loads(completed.stdout)
            self.assertEqual(receipt["verdict"], "FAIL_CLOSED")
            self.assertFalse(marker.exists())
            high_n = next(row for row in receipt["rows"] if row["id"] == "high-n")
            self.assertEqual(high_n["status"], "skipped_canary_failed")

    def test_failure_classes_route_to_bounded_owners(self) -> None:
        expected_owners = {
            "code_defect": "product_build_review",
            "verifier_defect": "verifier_owner",
            "environment_capacity": "environment_owner",
            "external_observation": "observation_owner",
            "invalid_evidence": "evidence_contract_owner",
            "unknown": "stop_fail_closed",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for index, (failure_class, owner) in enumerate(expected_owners.items()):
                manifest = self.manifest(root / str(index))
                manifest["rows"][1]["failure_class_on_failure"] = failure_class
                manifest_path = root / f"manifest-{index}.json"
                manifest_path.write_text(json.dumps(manifest))
                completed = run_script("deploy-verify-controller", str(manifest_path))
                expected_exit = 3 if failure_class == "unknown" else 0
                self.assertEqual(completed.returncode, expected_exit, completed.stdout)
                receipt = json.loads(completed.stdout)
                telemetry = next(
                    row for row in receipt["rows"] if row["id"] == "telemetry"
                )
                self.assertEqual(telemetry["next_owner"], owner)
                self.assertTrue(receipt["ship_gate_passed"])
                self.assertEqual(
                    receipt["promotion_allowed"], failure_class != "unknown"
                )


class TicketRuntimeContractTest(unittest.TestCase):
    def context_receipt(self, root: Path) -> tuple[Path, dict]:
        packet = root / "child-packet.md"
        packet.write_text("bounded excerpt")
        artifact_hash = "a" * 64
        receipt = {
            "schema_version": 1,
            "scope": "F1",
            "context_owner": "ticket-flow",
            "manifest_reads": [
                {
                    "detail": "light",
                    "context_version": "v1",
                    "known_version": None,
                }
            ],
            "artifact_reads": [
                {
                    "artifact_id": "artifact-1",
                    "sha256": artifact_hash,
                    "excerpt_bytes": 128,
                }
            ],
            "child_packets": [
                {
                    **reference(packet),
                    "artifact_refs": [
                        {"artifact_id": "artifact-1", "sha256": artifact_hash}
                    ],
                    "excerpt_bytes": 128,
                }
            ],
            "canonical_updates": [
                {
                    "artifact_id": "plan-1",
                    "artifact_type": "plan",
                    "update_mode": "replace",
                    "body_bytes": 4096,
                }
            ],
        }
        path = root / "context.json"
        path.write_text(json.dumps(receipt))
        return path, receipt

    def fanout(self, revision_path: str = "first_revision") -> dict:
        if revision_path == "same_risk_delta":
            counts = {
                "investigator": 0,
                "builder_chain": 0,
                "review_wave": 0,
                "verifier": 1,
                "delta_builder": 1,
                "delta_reviewer": 1,
                "specialist_reviewer": 0,
            }
        else:
            counts = {
                "investigator": 1,
                "builder_chain": 1,
                "review_wave": 1,
                "verifier": 1,
                "delta_builder": 0,
                "delta_reviewer": 0,
                "specialist_reviewer": 0,
            }
        return {
            "activation_key": "F1-activation",
            "contract_version": "guide-v1",
            "staging_revision": 1,
            "prior_staging_revisions": [],
            "revision_path": revision_path,
            "role_counts": counts,
            "escalations": [],
            "risk_boundaries": [],
            "heavy_review": False,
        }

    def dispatch(self, root: Path, context_path: Path) -> dict:
        packet = root / "phase-packet.md"
        packet.write_text("phase packet")
        started = time.time()
        return {
            "contract_profile": "ticket-flow",
            "phase_name": "deploy_verify",
            "rotation_generation": 0,
            "coordinator_generation": 0,
            "fork_mode": "none",
            "compaction_signal": "available",
            "compactions_observed": 0,
            "first_incomplete_unit": "deploy",
            "started_at_epoch": started,
            "deadline_epoch": started + 2700,
            "budget": {
                "max_turns": 20,
                "max_checkpoints": 8,
                "max_elapsed_seconds": 2700,
                "max_packet_bytes": 16384,
                "token_usage": "unavailable",
                "max_tokens": None,
            },
            "packet": reference(packet),
            "checkpoint": None,
            "context_receipt": reference(context_path),
            "fanout_budget": self.fanout(),
        }

    def test_context_receipt_rejects_repeat_and_append(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path, receipt = self.context_receipt(root)
            accepted = run_script("workflow-ticket-context-check", "receipt", str(path))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

            receipt["manifest_reads"].append({
                "detail": "light",
                "context_version": "v1",
                "known_version": "v1",
            })
            path.write_text(json.dumps(receipt))
            repeated = run_script("workflow-ticket-context-check", "receipt", str(path))
            self.assertEqual(repeated.returncode, 2)
            self.assertIn("repeats same context_version", repeated.stdout)

            receipt["manifest_reads"] = receipt["manifest_reads"][:1]
            receipt["canonical_updates"][0]["update_mode"] = "append"
            path.write_text(json.dumps(receipt))
            appended = run_script("workflow-ticket-context-check", "receipt", str(path))
            self.assertEqual(appended.returncode, 2)
            self.assertIn("must equal replace", appended.stdout)

    def test_r1_runtime_policy_rejects_repeated_prefect_status_reads(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            receipt_path = Path(directory) / "policy.json"
            receipt_path.write_text(json.dumps({
                "observations": [
                    {
                        "actor": "model",
                        "operation": "prefect_status",
                        "condition": "flow-run-1",
                        "lease_expiry_inspection": False,
                    },
                    {
                        "actor": "model",
                        "operation": "prefect_status",
                        "condition": "flow-run-1",
                        "lease_expiry_inspection": False,
                    },
                ]
            }))
            rejected = run_script("progress-lease", "policy", str(receipt_path))
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("repeated model polling", rejected.stdout)

    def test_ticket_dispatch_enforces_budget_fanout_and_context(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            dispatch = self.dispatch(root, context_path)
            dispatch_path = root / "dispatch.json"
            dispatch_path.write_text(json.dumps(dispatch))
            accepted = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

            dispatch["fork_mode"] = "all"
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("prohibited", rejected.stdout)

            dispatch["fork_mode"] = "none"
            dispatch["budget"]["max_turns"] = 21
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("exceeds 20", rejected.stdout)

            dispatch["budget"]["max_turns"] = 20
            dispatch["fanout_budget"] = self.fanout("same_risk_delta")
            dispatch["fanout_budget"]["role_counts"]["builder_chain"] = 1
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("delta builder", rejected.stdout)

            dispatch["fanout_budget"] = self.fanout("same_risk_delta")
            dispatch["fanout_budget"].update({
                "staging_revision": 3,
                "prior_staging_revisions": ["rev-1", "rev-2"],
            })
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("stabilization", rejected.stdout)

    def test_new_risk_boundary_requires_heavy_specialist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            dispatch = self.dispatch(root, context_path)
            dispatch["fanout_budget"] = self.fanout()
            dispatch["fanout_budget"].update({
                "revision_path": "new_risk_boundary",
                "risk_boundaries": ["auth"],
                "heavy_review": True,
            })
            dispatch_path = root / "dispatch.json"
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("specialist_reviewer", rejected.stdout)

            dispatch["fanout_budget"]["role_counts"]["specialist_reviewer"] = 1
            dispatch["fanout_budget"]["escalations"] = [{
                "role": "specialist_reviewer",
                "trigger": "auth boundary crossed",
            }]
            dispatch_path.write_text(json.dumps(dispatch))
            accepted = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)


class ValidationReceiptTest(unittest.TestCase):
    def git(self, root: Path, *args: str) -> None:
        completed = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, check=False
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_exact_tree_reuse_changed_tree_repair_and_owner(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            registry = root / "registry"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "test@example.com")
            self.git(repo, "config", "user.name", "Test")
            (repo / "data.txt").write_text("one")
            self.git(repo, "add", "data.txt")
            self.git(repo, "commit", "-qm", "initial")

            success_command = [sys.executable, "-c", "print('ok')"]
            first = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *success_command,
                cwd=repo,
            )
            self.assertEqual(first.returncode, 0, first.stdout)
            first_receipt = json.loads(first.stdout)
            self.assertEqual(first_receipt["classification"], "initial_run")
            normalized = json.loads(first_receipt["normalized_exact_command"])
            self.assertEqual(normalized["cwd"], str(repo.resolve()))
            self.assertEqual(normalized["argv"], success_command)

            reused = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *success_command,
                cwd=repo,
            )
            self.assertEqual(reused.returncode, 0, reused.stdout)
            reused_receipt = json.loads(reused.stdout)
            self.assertEqual(reused_receipt["classification"], "exact_tree_duplicate")
            self.assertFalse(reused_receipt["executed"])

            (repo / "data.txt").write_text("two")
            changed = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *success_command,
                cwd=repo,
            )
            self.assertEqual(changed.returncode, 0, changed.stdout)
            self.assertEqual(json.loads(changed.stdout)["classification"], "changed_tree_run")

            gate = repo / "gate.txt"
            gate.write_text("fail")
            failure_command = [
                sys.executable,
                "-c",
                "from pathlib import Path; raise SystemExit(Path('gate.txt').read_text() != 'pass')",
            ]
            failed = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *failure_command,
                cwd=repo,
            )
            self.assertEqual(failed.returncode, 1, failed.stdout)
            repeated_failure = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *failure_command,
                cwd=repo,
            )
            self.assertEqual(repeated_failure.returncode, 2)
            self.assertIn("unchanged tree", repeated_failure.stdout)

            gate.write_text("pass")
            repaired = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *failure_command,
                cwd=repo,
            )
            self.assertEqual(repaired.returncode, 0, repaired.stdout)
            self.assertEqual(json.loads(repaired.stdout)["classification"], "repair_run")

            second_gate = repo / "second-gate.txt"
            second_gate.write_text("fail")
            second_failure_command = [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "raise SystemExit(Path('second-gate.txt').read_text() != 'pass')"
                ),
            ]
            first_failure = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *second_failure_command,
                cwd=repo,
            )
            self.assertEqual(first_failure.returncode, 1, first_failure.stdout)
            second_gate.write_text("still-failing")
            failed_repair = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *second_failure_command,
                cwd=repo,
            )
            self.assertEqual(failed_repair.returncode, 1, failed_repair.stdout)
            self.assertEqual(
                json.loads(failed_repair.stdout)["classification"], "repair_run"
            )
            second_gate.write_text("pass")
            exhausted = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *second_failure_command,
                cwd=repo,
            )
            self.assertEqual(exhausted.returncode, 2, exhausted.stdout)
            self.assertIn("budget is exhausted", exhausted.stdout)

            forbidden = run_script(
                "validation-receipt",
                "--owner",
                "builder",
                "--registry",
                str(registry),
                "--",
                *success_command,
                cwd=repo,
            )
            self.assertEqual(forbidden.returncode, 2)
            self.assertIn("cannot own", forbidden.stdout)


class ContractDocumentationTest(unittest.TestCase):
    def test_accepted_recommendations_are_wired_to_runtime_contracts(self) -> None:
        guide = (ROOT / "skills/create-deployment-guide/SKILL.md").read_text()
        verify = (ROOT / "skills/ticket-verify/SKILL.md").read_text()
        deploy = (ROOT / "skills/ticket-deploy/SKILL.md").read_text()
        investigate = (ROOT / "skills/investigate/SKILL.md").read_text()
        flow = (ROOT / "skills/ticket-flow/SKILL.md").read_text()
        review = (ROOT / "skills/review/SKILL.md").read_text()
        build = (ROOT / "skills/build/SKILL.md").read_text()
        economy = (ROOT / "skills/references/execution-economy.md").read_text()

        for contract in (guide, verify):
            self.assertIn("causal_ship_gate", contract)
            self.assertIn("observation", contract)
            self.assertIn("acceptance source", contract.lower())
            self.assertIn("sample-size rationale", contract)
            self.assertIn("exact-path canary", contract)
        for contract in (verify, deploy):
            self.assertIn("deploy-verify-controller", contract)
            self.assertIn("exact", contract)
        for classification in (
            "code_defect",
            "verifier_defect",
            "environment_capacity",
            "external_observation",
            "invalid_evidence",
            "unknown",
        ):
            self.assertIn(classification, investigate)
        self.assertIn("phase-contract ticket-dispatch", flow)
        self.assertIn("delta builder", flow)
        self.assertIn("delta reviewer", review)
        self.assertIn("workflow-ticket-context-check receipt", flow)
        self.assertIn("validation-receipt --owner orchestrator", build)
        for classification in (
            "initial_run",
            "exact_tree_duplicate",
            "changed_tree_run",
            "repair_run",
        ):
            self.assertIn(classification, economy)
        for binary in (
            "deploy-verify-controller",
            "validation-receipt",
            "phase-contract",
            "workflow-ticket-context-check",
        ):
            self.assertTrue(os.access(ROOT / "bin" / binary, os.X_OK), binary)


if __name__ == "__main__":
    unittest.main()

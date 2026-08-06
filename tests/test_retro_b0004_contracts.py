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


def deterministic_run_id(contract_version: str, scope_id: str, activation_key: str) -> str:
    material = f"{contract_version}:{scope_id}:{activation_key}".encode()
    return hashlib.sha256(material).hexdigest()


def initialize_git_worktree(root: Path) -> tuple[Path, str]:
    repo = root / "repo"
    if not repo.exists():
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", str(repo)], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.email", "test@example.com"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(repo), "config", "user.name", "Contract Test"],
            check=True,
        )
        (repo / "source.txt").write_text("revision-bound source\n")
        subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
        subprocess.run(
            ["git", "-C", str(repo), "commit", "-qm", "fixture"], check=True
        )
    revision = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return repo, revision


class DeployVerifyControllerTest(unittest.TestCase):
    def manifest(self, root: Path) -> dict:
        root.mkdir(parents=True, exist_ok=True)
        working_directory, revision = initialize_git_worktree(root)
        return {
            "schema_version": 2,
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
            "working_directory": str(working_directory),
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
                    "minimum_sufficient_evidence": "one telemetry read",
                    "evidence_timing": {
                        "source": "immediate",
                        "maturity_delay_seconds": 0,
                        "acquisition_time_seconds": 1,
                        "verification_deadline_seconds": 10,
                    },
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
            manifest = self.manifest(root)
            manifest_path.write_text(json.dumps(manifest))
            completed = run_script("deploy-verify-controller", str(manifest_path))
            self.assertEqual(completed.returncode, 0, completed.stdout)
            receipt = json.loads(completed.stdout)
            self.assertEqual(receipt["verdict"], "PASS")
            self.assertTrue(receipt["ship_gate_passed"])
            self.assertEqual(receipt["observation_failures"], 1)
            self.assertEqual(receipt["source_identity"]["head"], manifest["revision"])
            self.assertTrue(receipt["source_identity"]["clean"])
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

    def test_source_revision_mismatch_fails_before_any_command_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "row-ran"
            manifest = self.manifest(root)
            mismatched_revision = "b" * 40
            manifest["revision"] = mismatched_revision
            manifest["runtime_identity"]["expected"] = mismatched_revision
            manifest["runtime_identity"]["command"] = [
                sys.executable,
                "-c",
                f"print({mismatched_revision!r})",
            ]
            manifest["rows"][0]["command"] = [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ]
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            completed = run_script("deploy-verify-controller", str(manifest_path))

            self.assertEqual(completed.returncode, 2, completed.stdout)
            self.assertIn("HEAD does not equal", completed.stdout)
            self.assertFalse(marker.exists())

    def test_dirty_source_tree_fails_even_when_head_matches_revision(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "row-ran"
            manifest = self.manifest(root)
            Path(manifest["working_directory"], "source.txt").write_text("changed\n")
            manifest["rows"][0]["command"] = [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ]
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))

            completed = run_script("deploy-verify-controller", str(manifest_path))

            self.assertEqual(completed.returncode, 2, completed.stdout)
            self.assertIn("source-tree changes", completed.stdout)
            self.assertFalse(marker.exists())

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
                self.assertEqual(completed.returncode, 0, completed.stdout)
                receipt = json.loads(completed.stdout)
                telemetry = next(
                    row for row in receipt["rows"] if row["id"] == "telemetry"
                )
                self.assertEqual(telemetry["next_owner"], owner)
                self.assertTrue(receipt["ship_gate_passed"])
                self.assertTrue(receipt["promotion_allowed"])

    def test_rejects_infeasible_natural_traffic_causal_gate_before_execution(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            marker = root / "executed"
            manifest = self.manifest(root)
            causal = manifest["rows"][0]
            causal["command"] = [
                sys.executable,
                "-c",
                f"from pathlib import Path; Path({str(marker)!r}).write_text('ran')",
            ]
            causal["evidence_timing"] = {
                "source": "natural_traffic",
                "maturity_delay_seconds": 86400,
                "acquisition_time_seconds": 345600,
                "verification_deadline_seconds": 172800,
                "conservative_eligible_units_per_day": 0.25,
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest))
            completed = run_script("deploy-verify-controller", str(manifest_path))
            self.assertEqual(completed.returncode, 2, completed.stdout)
            self.assertIn("infeasible for a causal_ship_gate", completed.stdout)
            self.assertFalse(marker.exists())


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
                "delivery_owner": 0,
                "builder_chain": 0,
                "review_wave": 0,
                "verifier": 1,
                "repair_owner": 1,
                "specialist_reviewer": 0,
            }
        else:
            counts = {
                "investigator": 0,
                "delivery_owner": 1,
                "builder_chain": 0,
                "review_wave": 1,
                "verifier": 1,
                "repair_owner": 0,
                "specialist_reviewer": 0,
            }
        return {
            "activation_key": "F1-activation",
            "contract_version": "guide-v1",
            "staging_revision": 2 if revision_path == "same_risk_delta" else 1,
            "prior_staging_revisions": (
                ["rev-1"] if revision_path == "same_risk_delta" else []
            ),
            "revision_path": revision_path,
            "intensity": "standard",
            "investigation_required": False,
            "environment_verification_required": True,
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
            "run_budget": {
                "contract_version": "ticket-run-budget-v1",
                "ticket_id": "F1",
                "run_id": deterministic_run_id(
                    "ticket-run-budget-v1", "F1", "F1-activation"
                ),
                "activation_key": "F1-activation",
                "intensity": "standard",
                "budget_scope": "environment",
                "session_id": "deploy-owner-1",
                "session_role": "deployment_owner",
                "max_sessions": 6,
                "max_repair_cycles": 1,
                "starts_repair_cycle": False,
                "repair_cycle_id": None,
                "prior_receipt": None,
            },
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

            valid_run_id = dispatch["run_budget"]["run_id"]
            dispatch["run_budget"]["run_id"] = "resume-specific-run-id"
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("deterministic ticket/activation hash", rejected.stdout)
            dispatch["run_budget"]["run_id"] = valid_run_id

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
            dispatch["fanout_budget"]["role_counts"]["delivery_owner"] = 1
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("repair owner", rejected.stdout)

            dispatch["fanout_budget"] = self.fanout("same_risk_delta")
            dispatch["fanout_budget"].update({
                "staging_revision": 3,
                "prior_staging_revisions": ["rev-1", "rev-2"],
            })
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("stabilization", rejected.stdout)

    def test_direct_fanout_does_not_require_investigator_reviewer_or_verifier(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            dispatch = self.dispatch(root, context_path)
            dispatch.update({
                "phase_name": "build_review",
                "first_incomplete_unit": "delivery",
            })
            dispatch["budget"].update({
                "max_turns": 40,
                "max_checkpoints": 12,
                "max_elapsed_seconds": 3600,
            })
            dispatch["deadline_epoch"] = dispatch["started_at_epoch"] + 3600
            dispatch["fanout_budget"].update({
                "intensity": "direct",
                "environment_verification_required": False,
            })
            dispatch["fanout_budget"]["role_counts"].update({
                "review_wave": 0,
                "verifier": 0,
            })
            dispatch["run_budget"].update({
                "intensity": "direct",
                "budget_scope": "delivery",
                "session_id": "direct-delivery-1",
                "session_role": "delivery_owner",
                "max_sessions": 2,
            })
            dispatch_path = root / "dispatch.json"
            dispatch_path.write_text(json.dumps(dispatch))
            accepted = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

            dispatch["fanout_budget"]["role_counts"]["investigator"] = 1
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("investigator count must equal", rejected.stdout)

            dispatch["fanout_budget"]["investigation_required"] = True
            dispatch["fanout_budget"]["escalations"] = [{
                "role": "investigator",
                "trigger": "root cause is not proven",
            }]
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2, rejected.stdout)
            self.assertIn("separate investigator requires heavy", rejected.stdout)

            first_receipt = root / "direct-receipt.json"
            first_receipt.write_text(accepted.stdout)
            dispatch["fanout_budget"].update({
                "intensity": "standard",
                "investigation_required": False,
                "environment_verification_required": False,
                "escalations": [],
            })
            dispatch["fanout_budget"]["role_counts"].update({
                "investigator": 0,
                "review_wave": 1,
            })
            dispatch["run_budget"].update({
                "intensity": "standard",
                "session_id": "standard-review-1",
                "session_role": "reviewer",
                "max_sessions": 3,
                "intensity_escalation_reason": "delivery owner discovered review need",
                "prior_receipt": reference(first_receipt),
            })
            dispatch_path.write_text(json.dumps(dispatch))
            escalated = run_script(
                "phase-contract", "ticket-dispatch", str(dispatch_path)
            )
            self.assertEqual(escalated.returncode, 0, escalated.stdout)
            self.assertEqual(
                json.loads(escalated.stdout)["run_budget_receipt"]["intensity_history"],
                ["direct", "standard"],
            )

    def test_ticket_dispatch_rejects_rotation_generation_beyond_cumulative_cap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            checkpoint = root / "checkpoint.json"
            checkpoint.write_text('{"completed":["deploy"]}')
            dispatch = self.dispatch(root, context_path)
            dispatch["checkpoint"] = reference(checkpoint)

            dispatch["rotation_generation"] = 3
            dispatch_path = root / "dispatch.json"
            dispatch_path.write_text(json.dumps(dispatch))
            accepted = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(accepted.returncode, 0, accepted.stdout)

            dispatch["rotation_generation"] = 4
            dispatch_path.write_text(json.dumps(dispatch))
            rejected = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(rejected.returncode, 2)
            self.assertIn("cumulative cap", rejected.stdout)

    def test_ticket_dispatch_chains_run_budget_and_fails_closed_on_exhaustion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            dispatch = self.dispatch(root, context_path)
            dispatch.update({
                "phase_name": "build_review",
                "first_incomplete_unit": "delivery",
            })
            dispatch["budget"].update({
                "max_turns": 40,
                "max_checkpoints": 12,
                "max_elapsed_seconds": 3600,
            })
            dispatch["deadline_epoch"] = dispatch["started_at_epoch"] + 3600
            dispatch["run_budget"].update({
                "budget_scope": "delivery",
                "session_id": "delivery-1",
                "session_role": "delivery_owner",
                "max_sessions": 3,
            })
            dispatch_path = root / "dispatch.json"

            def reserve() -> subprocess.CompletedProcess:
                dispatch_path.write_text(json.dumps(dispatch))
                completed = run_script(
                    "phase-contract", "ticket-dispatch", str(dispatch_path)
                )
                if completed.returncode == 0:
                    dispatch["run_budget"]["prior_receipt"] = json.loads(
                        completed.stdout
                    )["run_budget_receipt"]
                return completed

            first = reserve()
            self.assertEqual(first.returncode, 0, first.stdout)
            dispatch["run_budget"].update({
                "session_id": "review-1",
                "session_role": "reviewer",
            })
            second = reserve()
            self.assertEqual(second.returncode, 0, second.stdout)
            dispatch["run_budget"].update({
                "session_id": "repair-1",
                "session_role": "repair_owner",
                "starts_repair_cycle": True,
                "repair_cycle_id": "repair-cycle-1",
            })
            third = reserve()
            self.assertEqual(third.returncode, 0, third.stdout)

            dispatch["run_budget"].update({
                "session_id": "review-2",
                "session_role": "reviewer",
                "starts_repair_cycle": False,
                "repair_cycle_id": None,
            })
            exhausted = reserve()
            self.assertEqual(exhausted.returncode, 3, exhausted.stdout)
            self.assertEqual(json.loads(exhausted.stdout)["status"], "BUDGET_EXHAUSTED")

            dispatch = self.dispatch(root, context_path)
            dispatch.update({
                "phase_name": "build_review",
                "first_incomplete_unit": "delivery",
            })
            dispatch["budget"].update({
                "max_turns": 40,
                "max_checkpoints": 12,
                "max_elapsed_seconds": 3600,
            })
            dispatch["deadline_epoch"] = dispatch["started_at_epoch"] + 3600
            dispatch["run_budget"].update({
                "run_id": deterministic_run_id(
                    "ticket-run-budget-v1", "F1", "F1-activation-2"
                ),
                "activation_key": "F1-activation-2",
                "budget_scope": "delivery",
                "session_id": "delivery-a",
                "session_role": "delivery_owner",
                "max_sessions": 3,
            })
            dispatch["fanout_budget"]["activation_key"] = "F1-activation-2"
            first = reserve()
            self.assertEqual(first.returncode, 0, first.stdout)
            dispatch["run_budget"].update({
                "session_id": "repair-a",
                "session_role": "repair_owner",
                "starts_repair_cycle": True,
                "repair_cycle_id": "repair-cycle-a",
            })
            first_repair = reserve()
            self.assertEqual(first_repair.returncode, 0, first_repair.stdout)
            dispatch["run_budget"].update({
                "session_id": "repair-b",
                "repair_cycle_id": "repair-cycle-b",
            })
            repair_exhausted = reserve()
            self.assertEqual(repair_exhausted.returncode, 3, repair_exhausted.stdout)
            self.assertIn("repair-cycle budget exhausted", repair_exhausted.stdout)

    def test_environment_repair_owner_consumes_shared_repair_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            dispatch = self.dispatch(root, context_path)
            dispatch_path = root / "dispatch.json"
            dispatch_path.write_text(json.dumps(dispatch))
            first = run_script("phase-contract", "ticket-dispatch", str(dispatch_path))
            self.assertEqual(first.returncode, 0, first.stdout)

            dispatch["fanout_budget"] = self.fanout("same_risk_delta")
            dispatch["run_budget"].update({
                "session_id": "environment-repair-1",
                "session_role": "repair_owner",
                "starts_repair_cycle": True,
                "repair_cycle_id": "environment-repair-cycle-1",
                "prior_receipt": json.loads(first.stdout)["run_budget_receipt"],
            })
            dispatch_path.write_text(json.dumps(dispatch))
            repaired = run_script(
                "phase-contract", "ticket-dispatch", str(dispatch_path)
            )
            self.assertEqual(repaired.returncode, 0, repaired.stdout)
            receipt = json.loads(repaired.stdout)["run_budget_receipt"]
            self.assertEqual(receipt["repair_cycle_ids"], ["environment-repair-cycle-1"])

    def test_new_risk_boundary_requires_heavy_specialist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            context_path, _ = self.context_receipt(root)
            dispatch = self.dispatch(root, context_path)
            dispatch["fanout_budget"] = self.fanout()
            dispatch["fanout_budget"].update({
                "revision_path": "new_risk_boundary",
                "staging_revision": 2,
                "prior_staging_revisions": ["rev-1"],
                "intensity": "heavy",
                "risk_boundaries": ["auth"],
                "heavy_review": True,
            })
            dispatch["fanout_budget"]["role_counts"].update({
                "delivery_owner": 0,
                "builder_chain": 1,
            })
            dispatch["run_budget"].update({
                "intensity": "heavy",
                "max_sessions": 12,
                "max_repair_cycles": 3,
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

    def test_epic_budget_derives_ceiling_rolls_up_ticket_usage_and_caps_repair(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            epic_budget = {
                "contract_version": "epic-run-budget-v1",
                "epic_id": "E1",
                "run_id": deterministic_run_id(
                    "epic-run-budget-v1", "E1", "E1-plan-v1"
                ),
                "activation_key": "E1-plan-v1",
                "step_intensities": {"F1": "standard"},
                "step_activation_keys": {"F1": "F1-activation"},
                "step_addition_reasons": {"F1": "planned milestone step"},
                "step_intensity_escalation_reasons": {},
                "milestone_ids": ["M1", "M2"],
                "production_authorized": False,
                "production_authorization_reason": None,
                "max_sessions": 15,
                "ticket_run_receipts": [],
                "reservation": {
                    "session_id": "milestone-owner-1",
                    "session_role": "milestone_owner",
                    "milestone_id": "M1",
                    "starts_repair_cycle": False,
                    "repair_cycle_id": None,
                },
                "prior_receipt": None,
            }
            epic_path = root / "epic-budget.json"
            epic_path.write_text(json.dumps(epic_budget))
            first = run_script("phase-contract", "epic-budget", str(epic_path))
            self.assertEqual(first.returncode, 0, first.stdout)
            first_receipt = json.loads(first.stdout)["epic_budget_receipt"]
            self.assertEqual(first_receipt["limits"]["total"], 15)

            context_path, _ = self.context_receipt(root)
            ticket_dispatch = self.dispatch(root, context_path)
            ticket_dispatch.update({
                "phase_name": "build_review",
                "first_incomplete_unit": "delivery",
            })
            ticket_dispatch["budget"].update({
                "max_turns": 40,
                "max_checkpoints": 12,
                "max_elapsed_seconds": 3600,
            })
            ticket_dispatch["deadline_epoch"] = (
                ticket_dispatch["started_at_epoch"] + 3600
            )
            ticket_dispatch["run_budget"].update({
                "budget_scope": "delivery",
                "session_id": "ticket-delivery-1",
                "session_role": "delivery_owner",
                "max_sessions": 3,
            })
            ticket_path = root / "ticket-dispatch.json"
            ticket_path.write_text(json.dumps(ticket_dispatch))
            ticket = run_script("phase-contract", "ticket-dispatch", str(ticket_path))
            self.assertEqual(ticket.returncode, 0, ticket.stdout)

            epic_budget.update({
                "step_addition_reasons": {},
                "ticket_run_receipts": [json.loads(ticket.stdout)["run_budget_receipt"]],
                "reservation": None,
                "prior_receipt": first_receipt,
            })
            epic_path.write_text(json.dumps(epic_budget))
            rolled_up = run_script("phase-contract", "epic-budget", str(epic_path))
            self.assertEqual(rolled_up.returncode, 0, rolled_up.stdout)
            rolled_up_receipt = json.loads(rolled_up.stdout)["epic_budget_receipt"]
            self.assertEqual(rolled_up_receipt["used_sessions"], 2)

            epic_budget.update({
                "step_intensities": {"F1": "heavy"},
                "step_intensity_escalation_reasons": {
                    "F1": "auth boundary discovered"
                },
                "max_sessions": 24,
                "ticket_run_receipts": [],
                "reservation": {
                    "session_id": "milestone-verifier-1",
                    "session_role": "milestone_verifier",
                    "milestone_id": "M1",
                    "starts_repair_cycle": False,
                    "repair_cycle_id": None,
                },
                "prior_receipt": rolled_up_receipt,
            })
            epic_path.write_text(json.dumps(epic_budget))
            escalated = run_script("phase-contract", "epic-budget", str(epic_path))
            self.assertEqual(escalated.returncode, 0, escalated.stdout)
            escalated_receipt = json.loads(escalated.stdout)["epic_budget_receipt"]
            self.assertEqual(
                escalated_receipt["step_intensity_histories"]["F1"],
                ["standard", "heavy"],
            )

            epic_budget.update({
                "step_intensity_escalation_reasons": {},
                "reservation": {
                    "session_id": "milestone-repair-1",
                    "session_role": "milestone_repair_owner",
                    "milestone_id": "M1",
                    "starts_repair_cycle": True,
                    "repair_cycle_id": "M1-repair-1",
                },
                "prior_receipt": escalated_receipt,
            })
            epic_path.write_text(json.dumps(epic_budget))
            repair = run_script("phase-contract", "epic-budget", str(epic_path))
            self.assertEqual(repair.returncode, 0, repair.stdout)

            epic_budget["reservation"].update({
                "session_id": "milestone-repair-2",
                "repair_cycle_id": "M1-repair-2",
            })
            epic_budget["prior_receipt"] = json.loads(repair.stdout)[
                "epic_budget_receipt"
            ]
            epic_path.write_text(json.dumps(epic_budget))
            exhausted = run_script("phase-contract", "epic-budget", str(epic_path))
            self.assertEqual(exhausted.returncode, 3, exhausted.stdout)
            self.assertIn("repair-cycle budget exhausted", exhausted.stdout)


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
            self.assertEqual(json.loads(repaired.stdout)["repair_run_number"], 1)

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
            self.assertEqual(json.loads(failed_repair.stdout)["repair_run_number"], 1)
            second_gate.write_text("still-failing-again")
            second_failed_repair = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *second_failure_command,
                cwd=repo,
            )
            self.assertEqual(second_failed_repair.returncode, 1, second_failed_repair.stdout)
            self.assertEqual(json.loads(second_failed_repair.stdout)["repair_run_number"], 2)
            second_gate.write_text("still-failing-third-time")
            third_failed_repair = run_script(
                "validation-receipt",
                "--owner",
                "orchestrator",
                "--registry",
                str(registry),
                "--",
                *second_failure_command,
                cwd=repo,
            )
            self.assertEqual(third_failed_repair.returncode, 1, third_failed_repair.stdout)
            self.assertEqual(json.loads(third_failed_repair.stdout)["repair_run_number"], 3)
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
            exhausted_receipt = json.loads(exhausted.stdout)
            self.assertIn("budget is exhausted", exhausted_receipt["error"])
            self.assertEqual(exhausted_receipt["repair_runs"], 3)

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

    def test_validation_receipt_accepts_one_round_cap_for_ordinary_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            registry = root / "registry"
            repo.mkdir()
            self.git(repo, "init", "-q")
            self.git(repo, "config", "user.email", "test@example.com")
            self.git(repo, "config", "user.name", "Test")
            gate = repo / "gate.txt"
            gate.write_text("initial")
            self.git(repo, "add", "gate.txt")
            self.git(repo, "commit", "-qm", "initial")
            command = [sys.executable, "-c", "raise SystemExit(1)"]

            def run_gate() -> subprocess.CompletedProcess:
                return run_script(
                    "validation-receipt",
                    "--owner",
                    "orchestrator",
                    "--max-repair-runs",
                    "1",
                    "--registry",
                    str(registry),
                    "--",
                    *command,
                    cwd=repo,
                )

            initial = run_gate()
            self.assertEqual(initial.returncode, 1, initial.stdout)
            gate.write_text("repair-1")
            repair = run_gate()
            self.assertEqual(repair.returncode, 1, repair.stdout)
            self.assertEqual(json.loads(repair.stdout)["repair_run_number"], 1)
            gate.write_text("repair-2")
            exhausted = run_gate()
            self.assertEqual(exhausted.returncode, 2, exhausted.stdout)
            self.assertEqual(json.loads(exhausted.stdout)["max_repair_runs"], 1)


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
        self.assertIn("same-risk repair uses one repair", flow)
        self.assertIn("does not dispatch a reviewer solely to re-confirm", review)
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

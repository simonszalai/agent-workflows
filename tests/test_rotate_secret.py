"""End-to-end coverage for bin/rotate-secret against fake op + fake sync."""

from __future__ import annotations

import json
import stat
import unittest

import yaml

from secrets_common import ROOT, SecretsSandbox, run

ROTATE = str(ROOT / "bin" / "rotate-secret")
# Contract-shaped provider doubles (provider_auto_ready / PROVIDER_FINALIZE_JSON /
# provider_finalize <json> / PROVIDER_ACCEPTS_COMPLETE). The real handlers are
# covered by test_rotate_providers.py; these tests exercise the engine stages.
FIXTURE_PROVIDERS = str(ROOT / "tests" / "fixtures" / "providers")
REAL_PROVIDERS = str(ROOT / "secrets" / "providers")

# sync-secrets double that can record a triggered deploy id the way the render
# writer does (`dest<TAB>deployId` appended to $SYNC_DEPLOYS_FILE).
FAKE_SYNC_DEPLOYS = r"""#!/usr/bin/env bash
printf 'SYNC %s\n' "$*" >> "$FAKE_LOG"
if [[ -n "${FAKE_SYNC_DEPLOY:-}" && -n "${SYNC_DEPLOYS_FILE:-}" && "$*" != *"--no-deploy"* ]]; then
  printf '%s\t%s\n' "${FAKE_SYNC_DEPLOY%%:*}" "${FAKE_SYNC_DEPLOY#*:}" >> "$SYNC_DEPLOYS_FILE"
fi
exit "${FAKE_SYNC_EXIT:-0}"
"""

SELF_MINTED_REF = "op://TESTVAULT/API_HMAC_SECRET/value"
MANUAL_REF = "op://TESTVAULT/EXTERNAL_API_KEY/value"
PG_REF = "op://TESTVAULT-sensitive/PROD_POSTGRES_URL_APP/value"
DISABLED_REF = "op://TESTVAULT/COUPLED_DATABASE/value"


class RotateSecretTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        routes = "\n".join([
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself",
            f"render\tsrv-b\tHMAC\t{SELF_MINTED_REF}\tself",
            f"render\tsrv-a\tEXTERNAL_API_KEY\t{MANUAL_REF}\tself",
            f"render\tsrv-pg\tDATABASE_URL\t{PG_REF}\tself",
            f"render\tsrv-coupled\tDATABASE_URL\t{DISABLED_REF}\tself",
            "",
        ])
        rotation = {
            "test-hmac": {
                "ref": SELF_MINTED_REF,
                "provider": "self_minted",
                "mode": "SELF_MINTED",
                "generate": {"format": "hex", "bytes": 16},
                "owner_repo": "repo",
            },
            "test-manual": {
                "ref": MANUAL_REF,
                "provider": "manual",
                "mode": "MANUAL",
                "owner_repo": "repo",
                "playbook": "1. Mint a new key in the provider dashboard.\n2. Revoke the old key after fan-out.",
            },
            "test-postgres": {
                "ref": PG_REF,
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
            },
            "test-disabled": {
                "ref": DISABLED_REF,
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
                "disabled_reason": "activation spans unsupported channels",
            },
        }
        self.sb.write_manifest(routes, rotation=rotation)

    def env(self, **extra: str) -> dict[str, str]:
        base = {
            "SYNC_SECRETS_BIN": str(self.sb.fakebin / "sync-secrets-fake"),
            "SECRETS_PROVIDERS_DIR": FIXTURE_PROVIDERS,
            "ROTATE_STATE_DIR": str(self.sb.root / "rotate-state"),
        }
        base.update(extra)
        return self.sb.env(**base)

    def rotate(self, *args: str, env: dict[str, str] | None = None, stdin: str | None = None):
        return run([ROTATE, "--repo", str(self.sb.repo), *args],
                   env if env is not None else self.env(), stdin=stdin)

    def sync_calls(self) -> list[str]:
        return [l for l in self.sb.log_lines() if l.startswith("SYNC ")]

    def finalize_calls(self) -> list[str]:
        return [l for l in self.sb.log_lines() if l.startswith("FINALIZE ")]

    def verify_calls(self) -> list[str]:
        return [l for l in self.sb.log_lines() if l.startswith("VERIFY ")]

    def state_file(self, entry_id: str):
        return self.sb.root / "rotate-state" / "testproj" / f"{entry_id}.json"

    def stored_value(self, ref: str) -> str:
        rest = ref.removeprefix("op://")
        vault, item, field = rest.split("/")
        return (self.sb.state / f"{vault}__{item}__{field}").read_text(encoding="utf-8")

    # --- registry gate --------------------------------------------------------

    def test_unknown_item_exits_2_and_lists_known_entries(self) -> None:
        proc = self.rotate("--ref", "op://TESTVAULT/NOT_REGISTERED/value", "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no rotation entry", proc.stderr)
        self.assertIn("test-hmac", proc.stderr)
        self.assertIn("test-manual", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_project_item_field_triple_resolves_the_same_entry(self) -> None:
        proc = self.rotate(
            "--project", "testproj", "--item", "API_HMAC_SECRET", "--field", "value",
            "--dry-run",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("test-hmac", proc.stdout)

    def test_disabled_entry_refuses_before_plan_or_mutation(self) -> None:
        proc = self.rotate("--ref", DISABLED_REF, "--dry-run")

        self.assertEqual(proc.returncode, 3)
        self.assertIn("test-disabled", proc.stderr)
        self.assertIn("unsupported channels", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    # --- dry-run ----------------------------------------------------------------

    def test_dry_run_prints_handler_and_full_fanout_and_mutates_nothing(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("provider: self_minted", proc.stdout)
        self.assertIn("rotation: automatic", proc.stdout)
        self.assertIn(str(self.sb.repo), proc.stdout)
        self.assertIn("render[srv-a]", proc.stdout)
        self.assertIn("render[srv-b]", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])  # no op, no sync

    # --- live refusals ------------------------------------------------------------

    def test_live_rotation_requires_reason(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--reason", proc.stderr)

    def test_live_rotation_refuses_agent_shell(self) -> None:
        proc = self.rotate(
            "--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
            env=self.env(CLAUDECODE="1"),
        )
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.sb.log_lines(), [])

    def test_non_interactive_live_rotation_requires_yes(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--yes", proc.stderr)

    # --- self_minted ---------------------------------------------------------------

    def test_self_minted_writes_vault_and_fans_out_to_every_consumer(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "rotate hmac", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        value = self.stored_value(SELF_MINTED_REF)
        self.assertEqual(len(value), 32)  # 16 bytes hex
        # the minted value never reaches stdout/stderr or the argv log
        combined = proc.stdout + proc.stderr + "\n".join(self.sb.log_lines())
        self.assertNotIn(value, combined)
        calls = self.sync_calls()
        # ONE project-wide sync covers every consumer repo via the config routes
        self.assertEqual(len(calls), 1)
        self.assertIn(f"--repo {self.sb.repo}", calls[0])
        self.assertIn(f"--changed {SELF_MINTED_REF}", calls[0])
        # finalize ran AFTER the fan-out with the persisted payload; no state left
        log = self.sb.log_lines()
        self.assertLess(log.index(calls[0]), log.index(self.finalize_calls()[0]))
        self.assertIn('{"predecessor":"prev-test-hmac"}', self.finalize_calls()[0])
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_self_minted_rerun_replaces_the_item_in_place(self) -> None:
        first = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        v1 = self.stored_value(SELF_MINTED_REF)
        second = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        v2 = self.stored_value(SELF_MINTED_REF)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertNotEqual(v1, v2)

    def test_failed_fanout_after_mint_exits_5_with_recovery(self) -> None:
        proc = self.rotate(
            "--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
            env=self.env(FAKE_SYNC_EXIT="1"),
        )
        self.assertEqual(proc.returncode, 5)
        self.assertIn("vault now holds the NEW value", proc.stderr)
        self.assertIn("--resume", proc.stderr)
        # the vault write still happened (safe documented state); predecessor
        # untouched, state kept for --resume
        self.assertTrue(len(self.stored_value(SELF_MINTED_REF)) > 0)
        self.assertEqual(self.finalize_calls(), [])
        self.assertTrue(self.state_file("test-hmac").exists())

    # --- two-stage: --no-finalize / --finalize / --resume / refusal ---------------

    def test_no_finalize_stops_after_fanout_and_keeps_state(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--no-finalize")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(len(self.sync_calls()), 1)
        self.assertEqual(self.finalize_calls(), [])
        state = json.loads(self.state_file("test-hmac").read_text(encoding="utf-8"))
        self.assertEqual(state["stateVersion"], 1)
        self.assertEqual(state["id"], "test-hmac")
        self.assertEqual(state["finalize"], {"predecessor": "prev-test-hmac"})
        self.assertFalse(state["proven"])
        self.assertTrue(state["fannedOut"])
        self.assertEqual(stat.S_IMODE(self.state_file("test-hmac").stat().st_mode), 0o600)
        value = self.stored_value(SELF_MINTED_REF)
        self.assertNotIn(value, self.state_file("test-hmac").read_text(encoding="utf-8"))

    def test_normal_run_refuses_when_unfinished_state_exists(self) -> None:
        self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--no-finalize")
        v1 = self.stored_value(SELF_MINTED_REF)
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 2, proc.stderr + proc.stdout)
        self.assertIn("unfinished rotation for test-hmac", proc.stderr)
        self.assertIn("--resume", proc.stderr)
        self.assertEqual(self.stored_value(SELF_MINTED_REF), v1)  # no double mint

    def test_finalize_runs_only_finalize_and_is_idempotent(self) -> None:
        self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--no-finalize")
        v1 = self.stored_value(SELF_MINTED_REF)
        n_sync = len(self.sync_calls())
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--finalize")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.stored_value(SELF_MINTED_REF), v1)
        self.assertEqual(len(self.sync_calls()), n_sync)  # no fan-out in --finalize
        self.assertEqual(self.finalize_calls(),
                         ['FINALIZE test-hmac {"predecessor":"prev-test-hmac"}'])
        self.assertFalse(self.state_file("test-hmac").exists())
        again = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--finalize")
        self.assertEqual(again.returncode, 0, again.stderr + again.stdout)
        self.assertIn("nothing to finalize", again.stdout)
        self.assertEqual(len(self.finalize_calls()), 1)

    def test_finalize_is_refused_until_the_fanout_completed(self) -> None:
        # Minted, fan-out failed: the state exists but fannedOut is false, so a
        # bare --finalize would retire the predecessor while consumers still
        # hold it. Only --resume (which completes the fan-out) unlocks it.
        first = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
                            env=self.env(FAKE_SYNC_EXIT="1"))
        self.assertEqual(first.returncode, 5, first.stderr + first.stdout)
        self.assertNotIn("then --finalize", first.stderr)
        state = json.loads(self.state_file("test-hmac").read_text(encoding="utf-8"))
        self.assertFalse(state["fannedOut"])
        fin = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--finalize")
        self.assertEqual(fin.returncode, 5, fin.stderr + fin.stdout)
        self.assertIn("fan-out never completed", fin.stderr)
        self.assertIn("--resume", fin.stderr)
        self.assertEqual(self.finalize_calls(), [])
        self.assertTrue(self.state_file("test-hmac").exists())
        resumed = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--resume", "--no-finalize")
        self.assertEqual(resumed.returncode, 0, resumed.stderr + resumed.stdout)
        self.assertTrue(json.loads(self.state_file("test-hmac").read_text(encoding="utf-8"))["fannedOut"])
        fin2 = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--finalize")
        self.assertEqual(fin2.returncode, 0, fin2.stderr + fin2.stdout)
        self.assertEqual(len(self.finalize_calls()), 1)
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_verify_failure_keeps_state_and_resume_reverifies_without_reminting(self) -> None:
        first = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
                            env=self.env(FAKE_VERIFY_EXIT="1"))
        self.assertEqual(first.returncode, 4, first.stderr + first.stdout)
        self.assertIn("--resume", first.stderr)
        v1 = self.stored_value(SELF_MINTED_REF)
        self.assertTrue(self.state_file("test-hmac").exists())
        self.assertEqual(self.sync_calls(), [])
        self.assertEqual(len(self.verify_calls()), 1)
        # a plain rerun refuses (no double mint); --resume re-verifies first
        plain = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(plain.returncode, 2, plain.stderr)
        still = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--resume",
                            env=self.env(FAKE_VERIFY_EXIT="1"))
        self.assertEqual(still.returncode, 4, still.stderr + still.stdout)
        self.assertEqual(self.sync_calls(), [])
        self.assertEqual(len(self.verify_calls()), 2)
        ok = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--resume")
        self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
        self.assertEqual(self.stored_value(SELF_MINTED_REF), v1)
        self.assertEqual(len(self.verify_calls()), 3)
        self.assertEqual(len(self.sync_calls()), 1)
        self.assertEqual(len(self.finalize_calls()), 1)
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_resume_redoes_fanout_and_finalizes_without_reminting(self) -> None:
        self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--no-finalize")
        v1 = self.stored_value(SELF_MINTED_REF)
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--resume")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("not re-minting", proc.stdout)
        self.assertEqual(self.stored_value(SELF_MINTED_REF), v1)
        self.assertEqual(len(self.sync_calls()), 2)
        self.assertEqual(len(self.finalize_calls()), 1)
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_resume_without_state_is_a_normal_run(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--resume")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(len(self.sync_calls()), 1)
        self.assertEqual(len(self.finalize_calls()), 1)

    def test_finalize_failure_exits_6_and_keeps_state_for_retry(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
                           env=self.env(FAKE_FINALIZE_EXIT="1"))
        self.assertEqual(proc.returncode, 6, proc.stderr + proc.stdout)
        self.assertIn("--finalize", proc.stderr)
        self.assertTrue(self.state_file("test-hmac").exists())
        retry = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--finalize")
        self.assertEqual(retry.returncode, 0, retry.stderr + retry.stdout)
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_recorded_deploys_are_waited_on_before_finalize(self) -> None:
        sync = self.sb.fakebin / "sync-secrets-deploys"
        sync.write_text(FAKE_SYNC_DEPLOYS, encoding="utf-8")
        sync.chmod(0o755)
        env = self.env(
            SYNC_SECRETS_BIN=str(sync), FAKE_SYNC_DEPLOY="srv-a:dep-1",
            RENDER_API_KEY="fake-render-key", SECRETS_RENDER_KEY_REF="env:RENDER_API_KEY",
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        log = self.sb.log_lines()
        polls = [l for l in log if l.startswith("CURL ") and "/services/srv-a/deploys/dep-1" in l]
        self.assertTrue(polls, log)
        self.assertLess(log.index(polls[0]), log.index(self.finalize_calls()[0]))

        # a deploy that never goes live blocks finalize (exit 5, state kept)
        self.sb.log_path.write_text("", encoding="utf-8")
        env2 = self.env(
            SYNC_SECRETS_BIN=str(sync), FAKE_SYNC_DEPLOY="srv-a:dep-1",
            RENDER_API_KEY="fake-render-key", SECRETS_RENDER_KEY_REF="env:RENDER_API_KEY",
            FAKE_DEPLOY_STATUS="build_failed",
        )
        proc2 = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", env=env2)
        self.assertEqual(proc2.returncode, 5, proc2.stderr + proc2.stdout)
        self.assertEqual(self.finalize_calls(), [])
        self.assertTrue(self.state_file("test-hmac").exists())
        state = json.loads(self.state_file("test-hmac").read_text(encoding="utf-8"))
        self.assertEqual(state["deploys"], [{"dest": "srv-a", "deployId": "dep-1"}])

    def test_resume_after_deploy_trigger_failure_redeploys_and_records_all_ids(self) -> None:
        # First fan-out: srv-a's deploy is triggered (id recorded) and then the
        # leg fails. --resume must re-run the leg, which redeploys EVERY
        # service (values already saved, so a diff-based deploy would skip
        # them) and records the new ids; prove_live waits on all of them.
        sync = self.sb.fakebin / "sync-secrets-partial"
        sync.write_text(r"""#!/usr/bin/env bash
printf 'SYNC %s\n' "$*" >> "$FAKE_LOG"
n="$(cat "$FAKE_OP_STATE/sync-calls" 2>/dev/null || echo 0)"; n=$((n + 1)); echo "$n" > "$FAKE_OP_STATE/sync-calls"
if [[ "$n" -eq 1 ]]; then
  printf 'srv-a\tdep-1\n' >> "$SYNC_DEPLOYS_FILE"
  echo "ERROR: a Render deploy trigger failed" >&2; exit 1
fi
printf 'srv-a\tdep-2\nsrv-b\tdep-3\n' >> "$SYNC_DEPLOYS_FILE"
""", encoding="utf-8")
        sync.chmod(0o755)
        env = self.env(SYNC_SECRETS_BIN=str(sync), RENDER_API_KEY="fake-render-key",
                       SECRETS_RENDER_KEY_REF="env:RENDER_API_KEY")
        first = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", env=env)
        self.assertEqual(first.returncode, 5, first.stderr + first.stdout)
        state = json.loads(self.state_file("test-hmac").read_text(encoding="utf-8"))
        self.assertEqual(state["deploys"], [{"dest": "srv-a", "deployId": "dep-1"}])
        self.assertEqual(self.finalize_calls(), [])
        second = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", "--resume", env=env)
        self.assertEqual(second.returncode, 0, second.stderr + second.stdout)
        log = self.sb.log_lines()
        for dep in ("srv-a/deploys/dep-1", "srv-a/deploys/dep-2", "srv-b/deploys/dep-3"):
            self.assertTrue(any(l.startswith("CURL ") and dep in l for l in log), (dep, log))
        self.assertEqual(len(self.finalize_calls()), 1)
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_rotate_rc7_runs_reconcile_then_finishes_without_minting(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
                           env=self.env(FAKE_ROTATE_RC="7"))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("reconciling", proc.stdout)
        self.assertFalse((self.sb.state / "TESTVAULT__API_HMAC_SECRET__value").exists())  # nothing minted
        log = self.sb.log_lines()
        self.assertTrue(any(l.startswith("RECONCILE test-hmac") for l in log), log)
        self.assertEqual(len(self.sync_calls()), 1)
        self.assertIn('{"reconciled":true}', self.finalize_calls()[0])
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_reconcile_rc3_exits_3_and_changes_nothing(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
                           env=self.env(FAKE_ROTATE_RC="7", FAKE_RECONCILE_RC="3"))
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertEqual(self.sync_calls(), [])
        self.assertEqual(self.finalize_calls(), [])
        self.assertFalse(self.state_file("test-hmac").exists())

    def test_removed_flags_are_rejected(self) -> None:
        for flag in ("--keep-old", "--accept-brief-outage"):
            proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes", flag)
            self.assertEqual(proc.returncode, 2, flag)
            self.assertIn("unknown argument", proc.stderr)

    # --- manual ------------------------------------------------------------------

    def test_manual_provider_prints_playbook_exits_3_changes_nothing(self) -> None:
        proc = self.rotate("--ref", MANUAL_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("provider dashboard", proc.stdout)
        self.assertIn("--complete", proc.stdout)
        self.assertEqual(self.sync_calls(), [])
        self.assertFalse((self.sb.state / "TESTVAULT__EXTERNAL_API_KEY__value").exists())

    def test_complete_reads_stdin_once_writes_vault_and_fans_out(self) -> None:
        proc = self.rotate(
            "--ref", MANUAL_REF, "--reason", "t", "--complete",
            stdin="externally-minted-value-123",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.stored_value(MANUAL_REF), "externally-minted-value-123")
        self.assertNotIn("externally-minted-value-123", proc.stdout + proc.stderr)
        self.assertEqual(len(self.sync_calls()), 1)

    def test_complete_with_empty_stdin_refuses_and_leaves_vault_untouched(self) -> None:
        proc = self.rotate("--ref", MANUAL_REF, "--reason", "t", "--complete", stdin="")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.sb.state / "TESTVAULT__EXTERNAL_API_KEY__value").exists())

    def test_complete_is_refused_for_providers_that_mint_themselves(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--complete",
                           stdin="externally-minted-value-123")
        self.assertEqual(proc.returncode, 2, proc.stderr + proc.stdout)
        self.assertIn("--complete is only for providers", proc.stderr)
        self.assertFalse((self.sb.state / "TESTVAULT__API_HMAC_SECRET__value").exists())
        self.assertEqual(self.sync_calls(), [])

    def test_dry_run_classifies_manual_provider(self) -> None:
        proc = self.rotate("--ref", MANUAL_REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("rotation: manual", proc.stdout)

    # --- postgres (central rotator) ---------------------------------------------

    def test_postgres_refuses_project_missing_from_db_roles_config(self) -> None:
        # 'testproj' is not in config/db-roles.json: the rotator must refuse
        # (precondition, nothing changed) instead of improvising tier constants.
        proc = self.rotate("--ref", PG_REF, "--reason", "t", "--yes",
                           env=self.env(SECRETS_ALLOW_AGENT="1",
                                        SECRETS_PROVIDERS_DIR=REAL_PROVIDERS))
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("is not in", proc.stderr)
        self.assertEqual(self.sync_calls(), [])


class VaultEditConflictTest(unittest.TestCase):
    """1Password returns 409 Conflict for concurrent item edits. Same-item
    concurrency is prevented upstream (orchestrator wave partitioning + the
    per-item lock), so a conflict means an EXTERNAL editor raced the rotation:
    the vault replace fails loudly on the first conflict, item untouched."""

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation={
                "test-hmac": {
                    "ref": SELF_MINTED_REF,
                    "provider": "self_minted",
                    "mode": "SELF_MINTED",
                    "generate": {"format": "hex", "bytes": 16},
                    "owner_repo": "repo",
                },
            },
        )

    def rotate(self, conflicts: str):
        env = self.sb.env(
            SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
            SECRETS_PROVIDERS_DIR=FIXTURE_PROVIDERS,
            ROTATE_STATE_DIR=str(self.sb.root / "rotate-state"),
            FAKE_OP_EDIT_CONFLICTS=conflicts,
        )
        return run([ROTATE, "--repo", str(self.sb.repo), "--ref", SELF_MINTED_REF,
                    "--reason", "t", "--yes"], env)

    def test_conflict_fails_loudly_first_time_without_retrying(self) -> None:
        # seed so the replace (edit) path runs rather than create
        rest = SELF_MINTED_REF.removeprefix("op://")
        vault, item, field = rest.split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text("old", encoding="utf-8")
        proc = self.rotate("1")
        self.assertEqual(proc.returncode, 4, proc.stderr + proc.stdout)
        self.assertIn("concurrent external edit", proc.stderr)
        self.assertNotIn("retrying", proc.stderr)
        self.assertEqual(
            (self.sb.state / f"{vault}__{item}__{field}").read_text(encoding="utf-8"), "old")

    def test_no_conflict_replaces_once(self) -> None:
        rest = SELF_MINTED_REF.removeprefix("op://")
        vault, item, field = rest.split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text("old", encoding="utf-8")
        proc = self.rotate("0")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)


class RotateHookTest(unittest.TestCase):
    """Optional repo hook: declared-but-missing refuses; post-sync runs after
    fan-out; hook: full delegates the whole rotation and skips the provider."""

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.hook_log = self.sb.root / "hook.log"
        routes = "\n".join([
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself",
            f"prefect\tstaging\tHMAC\t{SELF_MINTED_REF}\tself",
            "",
        ])
        self.rotation = {
            "test-hmac": {
                "ref": SELF_MINTED_REF,
                "provider": "self_minted",
                "mode": "SELF_MINTED",
                "generate": {"format": "hex", "bytes": 16},
                "owner_repo": "repo",
            },
        }
        self.sb.write_manifest(routes, rotation=self.rotation)

    def write_hook(self) -> None:
        hook_dir = self.sb.repo / "scripts" / "secrets"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook = hook_dir / "rotate-hook"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "HOOK $1 $ROTATE_ID" >> "{self.hook_log}"\n'
            'exit 0\n',
            encoding="utf-8",
        )
        hook.chmod(0o755)

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(
            SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
            SECRETS_PROVIDERS_DIR=FIXTURE_PROVIDERS,
            ROTATE_STATE_DIR=str(self.sb.root / "rotate-state"),
            **extra,
        )

    def rotate(self, *args: str):
        return run([ROTATE, "--repo", str(self.sb.repo), *args], self.env())

    def hook_calls(self) -> list[str]:
        if not self.hook_log.exists():
            return []
        return self.hook_log.read_text(encoding="utf-8").splitlines()

    def test_declared_hook_missing_refuses_before_any_action(self) -> None:
        self.rotation["test-hmac"]["hook"] = "activate"
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation=self.rotation,
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("REFUSED", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_post_sync_hook_runs_after_fanout(self) -> None:
        self.write_hook()
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.hook_calls(), ["HOOK post-sync test-hmac"])

    def test_hook_full_delegates_and_skips_the_provider(self) -> None:
        self.write_hook()
        self.rotation["test-hmac"]["hook"] = "full"
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n"
            f"prefect\tstaging\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation=self.rotation,
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # hook owned the rotation; the self_minted provider never wrote the vault
        self.assertIn("HOOK rotate test-hmac", self.hook_calls())
        self.assertNotIn("OP item edit", "\n".join(self.sb.log_lines()))
        # fan-out still ran; no provider finalize (the hook owns the credential)
        self.assertTrue(any(l.startswith("SYNC ") for l in self.sb.log_lines()))
        self.assertFalse(any(l.startswith("FINALIZE ") for l in self.sb.log_lines()))

    def test_hook_is_looked_up_in_the_owner_repo_not_cwd(self) -> None:
        # The hook lives in the owner repo (resolved through `repos:`), even when
        # rotate-secret is pointed at a sibling repo of the same project.
        self.write_hook()
        other = self.sb.root / "otherrepo"
        other.mkdir()
        (other / "secrets.yaml").write_text("extends: ../repo/secrets.yaml\n", encoding="utf-8")
        proc = run([ROTATE, "--repo", str(other), "--ref", SELF_MINTED_REF,
                    "--reason", "t", "--yes"], self.env())
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.hook_calls(), ["HOOK post-sync test-hmac"])

    def test_dry_run_prints_hook_plan_and_mutates_nothing(self) -> None:
        self.write_hook()
        self.rotation["test-hmac"]["hook"] = "full"
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation=self.rotation,
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hook: scripts/secrets/rotate-hook (full) @", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])


class ExcludeDestsDerivationTest(unittest.TestCase):
    """The Prefect-server topology invariant, now enforced structurally:
    exclude_dests removes a route from the ACTIVATION surface (consumers)
    while the route itself remains visible."""

    def test_exclude_dests_removes_activation_target_but_keeps_route(self) -> None:
        sb = SecretsSandbox()
        self.addCleanup(sb.close)
        ref = "op://TESTVAULT-sensitive/PG/value"
        sb.write_manifest(
            f"render\tsrv-app\tDATABASE_URL\t{ref}\tself\n"
            f"render\tsrv-server\tPREFECT_API_DATABASE_CONNECTION_URL\t{ref}\tself\n",
            rotation={
                "db": {
                    "ref": ref,
                    "provider": "postgres",
                    "mode": "DUAL_KEY",
                    "owner_repo": "repo",
                    "exclude_dests": ["srv-server"],
                }
            },
        )
        lib = ROOT / "secrets" / "lib" / "config.sh"
        env = sb.env(_SECRETS_CONFIG=str(sb.repo))
        proc = run(
            ["bash", "-c", f'source "{lib}"; reg="$(config_registry)" && cat "$reg"'],
            env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        reg = json.loads(proc.stdout)
        entry = reg["secrets"][0]
        dests = [c["dest"] for c in entry["consumers"]]
        self.assertEqual(dests, ["srv-app"])
        route_dests = [r["dest"] for r in entry["routes"]]
        self.assertIn("srv-server", route_dests)


class CrossProjectFanOutTest(unittest.TestCase):
    """A credential routed by a SECOND project must have that project's manifest
    swept too. Before sync_repos the fan-out only ever reached the owning
    project, so the other project's destinations silently kept the retired
    value (the TS read-only prod DB credential that autodev's schema-drift gate
    consumes was exactly this)."""

    REF = "op://TESTVAULT/SHARED_TOKEN/value"

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        # A sibling project alongside the sandbox repo, routing the same ref.
        self.other = self.sb.root / "otherrepo"
        self.other.mkdir()
        (self.other / "secrets.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": "otherproj",
                    "repos": ["otherrepo"],
                    "health": {},
                    "rotation": {},
                    "routes": [{
                        "repo": "otherrepo", "kind": "github", "dest": "otherorg/otherrepo",
                        "env": "SHARED_TOKEN", "ref": self.REF, "transform": "self",
                    }],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.sb.write_manifest(
            f"render\tsrv-a\tSHARED_TOKEN\t{self.REF}\tself\n",
            rotation={
                "shared": {
                    "ref": self.REF,
                    "provider": "self_minted",
                    "mode": "SELF_MINTED",
                    "generate": {"format": "hex", "bytes": 16},
                    "owner_repo": "repo",
                    "sync_repos": ["../otherrepo"],
                }
            },
        )

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
                           SECRETS_PROVIDERS_DIR=FIXTURE_PROVIDERS,
                           ROTATE_STATE_DIR=str(self.sb.root / "rotate-state"), **extra)

    def rotate(self, *args: str, **kw: str):
        return run([ROTATE, "--repo", str(self.sb.repo), *args], self.env(**kw))

    def test_dry_run_lists_both_legs_and_the_cross_project_consumer(self) -> None:
        proc = self.rotate("--ref", self.REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"sync-secrets --repo {self.sb.repo} --changed {self.REF}", proc.stdout)
        self.assertIn(f"sync-secrets --repo {self.other} --changed {self.REF}", proc.stdout)
        self.assertIn("cross-project consumer:", proc.stdout)
        self.assertIn("otherorg/otherrepo", proc.stdout)

    def test_live_rotation_syncs_the_other_project_too(self) -> None:
        proc = self.rotate("--ref", self.REF, "--reason", "rotate shared", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        calls = [l for l in self.sb.log_lines() if l.startswith("SYNC ")]
        repos = sorted(l.split("--repo ")[1].split(" ")[0] for l in calls)
        self.assertEqual(repos, sorted([str(self.sb.repo), str(self.other)]))

    def test_failed_cross_project_leg_names_that_repo_in_the_recovery(self) -> None:
        proc = self.rotate("--ref", self.REF, "--reason", "t", "--yes", FAKE_SYNC_EXIT="1")
        self.assertEqual(proc.returncode, 5)
        self.assertIn(f"sync-secrets --repo {self.other} --changed {self.REF}", proc.stderr)

    def test_postgres_entry_declares_the_sibling_render_dests_to_the_rotator(self) -> None:
        """The rotator's finalize inventory scan only accepts DECLARED consumers;
        a sibling project's Render routes for the ref must reach it as
        ROTATE_EXTRA_CONSUMER_DESTS (sid/ENV), github rows are not dests."""
        pg_ref = "op://TESTVAULT-sensitive/Postgres prod/ro"
        (self.other / "secrets.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": "otherproj",
                    "repos": ["otherrepo"],
                    "health": {},
                    "rotation": {},
                    "routes": [
                        {"repo": "otherrepo", "kind": "render", "dest": "srv-other",
                         "env": "TS_DB_RO_URL", "ref": pg_ref, "transform": "self"},
                        {"repo": "otherrepo", "kind": "github", "dest": "otherorg/otherrepo",
                         "env": "TS_DB_RO_URL", "ref": pg_ref, "transform": "self"},
                    ],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.sb.write_manifest(
            f"dev\tprofile\tDB_RO\t{pg_ref}\tself\n",
            rotation={
                "shared-db": {
                    "ref": pg_ref,
                    "provider": "postgres",
                    "mode": "DUAL_KEY",
                    "owner_repo": "repo",
                    "sync_repos": ["../otherrepo"],
                }
            },
        )
        proc = self.rotate("--ref", pg_ref, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("EXTRA=srv-other/TS_DB_RO_URL\n", proc.stdout)


if __name__ == "__main__":
    unittest.main()

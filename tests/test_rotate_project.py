"""rotate-project orchestrator: plan/selection, phases, canary, checkpoint
resume, batched deploy + finalize ordering, pending-finalize handling."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from secrets_common import FAKE_CURL

HERE = Path(__file__).resolve().parent
BIN = str(HERE.parent / "bin" / "rotate-project")
FIXTURE_PROVIDERS = str(HERE / "fixtures" / "providers")
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CODEX_THREAD_ID", "CODEX_CI", "CODEX_WORKING_DIR")

PG_STAGING = "op://P/Postgres staging/web"
PG_PROD = "op://P-sensitive/Postgres prod/web"
TOKEN = "op://P/API/token"
HMAC = "op://P/HMAC/key"


def registry(tmp: Path) -> Path:
    """Write the sandbox project repo (secrets.yaml) and return its path."""
    doc = {
        "project": "p",
        "repos": ["repo"],
        "health": {"srv-web": "http://127.0.0.1:1/health"},
        "rotation": {
            "p-db-prod": {"ref": PG_PROD, "provider": "postgres", "mode": "DUAL_KEY", "owner_repo": "repo"},
            "p-token": {"ref": TOKEN, "provider": "self_minted", "mode": "SELF_MINTED", "owner_repo": "repo"},
            "p-hmac": {"ref": HMAC, "provider": "self_minted", "mode": "SELF_MINTED", "owner_repo": "repo"},
            "p-db-staging": {"ref": PG_STAGING, "provider": "postgres", "mode": "DUAL_KEY", "owner_repo": "repo"},
            "p-vendor": {"ref": "op://P/Vendor/key", "provider": "manual", "mode": "MANUAL", "owner_repo": "repo"},
            "p-vendor2": {"ref": "op://P/Vendor2/key", "provider": "manual", "mode": "MANUAL", "owner_repo": "repo"},
        },
        "routes": [
            {"repo": "repo", "kind": "render", "dest": "srv-web",
             "env": "DATABASE_URL", "ref": PG_PROD, "transform": "self"},
            {"repo": "repo", "kind": "dev", "dest": "profile", "env": "TOKEN",
             "ref": TOKEN, "transform": "self"},
            {"repo": "repo", "kind": "render", "dest": "srv-x", "env": "HMAC",
             "ref": HMAC, "transform": "self"},
            {"repo": "repo", "kind": "dev", "dest": "profile", "env": "DB_STAGING",
             "ref": PG_STAGING, "transform": "self"},
            {"repo": "repo", "kind": "dev", "dest": "profile", "env": "VENDOR_KEY",
             "ref": "op://P/Vendor/key", "transform": "self"},
            {"repo": "repo", "kind": "render", "dest": "srv-x", "env": "K",
             "ref": "op://P/Vendor2/key", "transform": "self"},
        ],
    }
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "secrets.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return repo


def write_exec(path: Path, body: str) -> Path:
    path.write_text("#!/usr/bin/env bash\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


# rotate-secret double: logs argv to $LOG; FAIL_SUBSTR makes matching calls exit 1
# (FAIL_ONCE=1: only the first time); FINALIZE_EXIT is returned by --finalize calls
# matching FINALIZE_SUBSTR (FINALIZE_ONCE=1: only the first time).
FAKE_ROTATE = r"""
echo "$@${ROTATE_NO_DEPLOY:+ [no-deploy]}" >> "$LOG"
[[ -n "${ROTATE_SWEEP_ID:-}" && "${ROTATE_INVENTORY_CACHE_DIR:-}" == *"/$ROTATE_SWEEP_ID/"* ]] || { echo "fake rotate-secret: sweep id/cache dir not exported" >&2; exit 99; }
args="$*"
if [[ -n "${FAIL_SUBSTR:-}" && "$args" == *"$FAIL_SUBSTR"* && "$args" != *"--finalize"* ]]; then
  if [[ "${FAIL_ONCE:-0}" == 1 && -e "$LOG.failed-once" ]]; then :; else touch "$LOG.failed-once"; exit 1; fi
fi
if [[ "$args" == *"--finalize"* && -n "${FINALIZE_SUBSTR:-}" && "$args" == *"$FINALIZE_SUBSTR"* ]]; then
  if [[ "${FINALIZE_ONCE:-0}" == 1 && -e "$LOG.finalize-once" ]]; then exit 0; fi
  touch "$LOG.finalize-once"; exit "${FINALIZE_EXIT:-0}"
fi
exit 0
"""

# postgres-rotate double: only --print-lock-key; FAKE_LOCK_KEYS maps ref -> key.
FAKE_PG_ROTATOR = r"""
[[ "${1:-}" == "--print-lock-key" ]] || { echo "fake rotator: unexpected $*" >&2; exit 2; }
[[ "${FAKE_LOCK_KEY_FAIL:-0}" == 1 ]] && { echo "fake rotator: no db-roles" >&2; exit 1; }
[[ -n "${SECRET_ROTATION_CONFIG:-}" && -f "$SECRET_ROTATION_CONFIG" ]] || { echo "no registry" >&2; exit 2; }
key=""
[[ -n "${FAKE_LOCK_KEYS:-}" ]] && key="$(jq -r --arg r "$ROTATE_REF" '.[$r] // empty' <<< "$FAKE_LOCK_KEYS")"
if [[ -z "$key" ]]; then tier=prod; [[ "$ROTATE_REF" == *staging* ]] && tier=staging; key="p/$tier"; fi
printf '%s\n' "$key"
"""

class Sandbox:
    def __init__(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = registry(self.tmp)
        self.bin = self.tmp / "fakebin"
        self.bin.mkdir()
        self.log = self.tmp / "calls.log"
        write_exec(self.bin / "rotate-secret", FAKE_ROTATE)
        write_exec(self.bin / "sync-secrets", 'echo "SYNC $*" >> "$LOG"\nexit "${SYNC_EXIT:-0}"\n')
        write_exec(self.bin / "postgres-rotate", FAKE_PG_ROTATOR)
        (self.bin / "curl").write_text(FAKE_CURL, encoding="utf-8")
        (self.bin / "curl").chmod(0o755)

    def env(self, **extra: str) -> dict:
        env = dict(os.environ)
        for m in AGENT_MARKERS:
            env.pop(m, None)
        env.update({
            "ROTATE_PREFLIGHT": "0",  # sandbox refs aren't real vault items
            "ROTATE_PROJECT_STATE_DIR": str(self.tmp / "sweep-state"),
            "ROTATE_SECRET": str(self.bin / "rotate-secret"),
            "SYNC_SECRETS": str(self.bin / "sync-secrets"),
            "POSTGRES_ROTATE_BIN": str(self.bin / "postgres-rotate"),
            "SECRETS_PROVIDERS_DIR": FIXTURE_PROVIDERS,
            "PATH": f"{self.bin}:{env['PATH']}",
            "LOG": str(self.log),
            "FAKE_LOG": str(self.log),
            "RENDER_API_KEY": "fake-render-key",
            "SECRETS_RENDER_KEY_REF": "env:RENDER_API_KEY",
        })
        env.update(extra)
        return env

    def run(self, *args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run([BIN, "--repo", str(self.repo), "p", *args],
                              capture_output=True, text=True, env=self.env(**extra),
                              stdin=subprocess.DEVNULL)

    def calls(self) -> list[str]:
        if not self.log.exists():
            return []
        return [l for l in self.log.read_text(encoding="utf-8").splitlines() if l]

    def reset_log(self) -> None:
        self.log.write_text("", encoding="utf-8")
        for p in (self.tmp / "calls.log.failed-once", self.tmp / "calls.log.finalize-once"):
            p.unlink(missing_ok=True)

    def state(self) -> dict | None:
        p = self.tmp / "sweep-state" / "p.state"
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


class RotateProjectPlanTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = Sandbox()

    def test_dry_run_plan_sections_and_canary(self) -> None:
        proc = self.sb.run("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("ROTATE", out)
        self.assertIn("SYNC", out)
        ids = [l.strip().split(" ")[0] for l in out.splitlines()
               if l.strip().startswith(("p-db", "p-token", "p-hmac", "p-vendor"))]
        # ROTATE (auto) entries in phase order, then SYNC entries
        self.assertEqual(ids, ["p-db-staging", "p-token", "p-hmac", "p-db-prod", "p-vendor", "p-vendor2"])
        self.assertIn("rollback (canary)", out)
        self.assertIn("phase 1 · wave 1/1", out)
        self.assertIn("phase 2b · wave 1/1 · parallel x4", out)
        self.assertIn("phase 3 · wave 1/1", out)
        self.assertIn("render:127.0.0.1:1", out)
        self.assertIn("DATABASE_URL", out)
        self.assertIn("no secret values were read", out)
        self.assertEqual(self.sb.calls(), [])  # plan is read-free (lock keys aside)

    def test_provider_entries_sync_current_vault_value(self) -> None:
        proc = self.sb.run("--dry-run")
        self.assertIn("current 1Password value", proc.stdout)
        self.assertIn("p-vendor", proc.stdout)

    def test_only_filter_narrows_to_one_entry(self) -> None:
        proc = self.sb.run("--dry-run", "--only", "p-vendor")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("p-vendor", proc.stdout)
        self.assertNotIn("p-token", proc.stdout)

    def test_tier_staging_skips_prod_entries(self) -> None:
        proc = self.sb.run("--dry-run", "--tier", "staging")
        self.assertIn("p-db-staging", proc.stdout)
        self.assertNotIn("p-db-prod", proc.stdout)

    def test_unknown_only_or_skip_id_exits_2(self) -> None:
        proc = self.sb.run("--dry-run", "--only", "p-nope")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown rotation id(s): p-nope", proc.stderr)
        self.assertIn("Known ids:", proc.stderr)
        proc = self.sb.run("--dry-run", "--skip", "p-token,typo")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("typo", proc.stderr)

    def test_empty_selection_exits_2(self) -> None:
        proc = self.sb.run("--dry-run", "--tier", "staging", "--only", "p-db-prod")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("matches no entries", proc.stderr)

    def test_lock_key_derivation_failure_is_fatal(self) -> None:
        proc = self.sb.run("--dry-run", FAKE_LOCK_KEY_FAIL="1")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("lock key", proc.stderr)
        live = self.sb.run("--reason", "x", FAKE_LOCK_KEY_FAIL="1")
        self.assertEqual(live.returncode, 2)
        self.assertEqual(self.sb.calls(), [])

    def test_live_sweep_refuses_agent_shell(self) -> None:
        proc = self.sb.run("--reason", "x", CLAUDECODE="1")
        self.assertEqual(proc.returncode, 3, proc.stdout + proc.stderr)
        self.assertEqual(self.sb.calls(), [])


class RotateProjectLiveTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = Sandbox()

    def test_live_sweep_passes_reason_and_stops_on_failure(self) -> None:
        proc = self.sb.run("--reason", "sweep test", "--skip", "p-db-prod,p-vendor2,p-hmac",
                           FAIL_SUBSTR="API/token")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        calls = self.sb.calls()
        staging = [c for c in calls if "Postgres staging/web" in c]
        self.assertEqual(len(staging), 1)
        self.assertIn("sweep test [p-db-staging]", staging[0])
        self.assertIn("--no-finalize", staging[0])
        self.assertIn("--resume", staging[0])
        self.assertNotIn("[no-deploy]", staging[0])  # postgres deploys inside the rotator
        # the canary's predecessor is kept: no --finalize for it when the sweep stops
        self.assertFalse(any("--finalize" in c for c in calls))
        self.assertIn("p-token", proc.stdout)
        self.assertIn("failed", proc.stdout)
        self.assertIn("stopped after a failure", proc.stdout)
        self.assertIn("canary", proc.stdout)

    def test_sync_entry_failure_stops_the_sweep(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-vendor2", SYNC_EXIT="1")
        self.assertEqual(proc.returncode, 1)
        self.assertNotIn("CURL POST", "\n".join(self.sb.calls()))  # nothing deployed

    def test_sync_only_entries_are_not_reported_as_rotated(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-vendor")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("credential NOT rotated", proc.stdout)
        self.assertIn("1 synced only", proc.stdout)
        self.assertIn("0 rotated+verified", proc.stdout)
        self.assertFalse(any("--finalize" in c for c in self.sb.calls()))  # nothing to finalize for SYNC

    def test_rotated_entries_are_still_reported_as_rotated(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-token")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("1 rotated+verified", proc.stdout)
        self.assertNotIn("credential NOT rotated", proc.stdout)
        self.assertNotIn("synced only", proc.stdout)
        self.assertIsNone(self.sb.state())

    def test_sync_entry_deploys_once_and_completes(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-vendor2")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("command not found", proc.stderr)
        self.assertIn("deploy triggered (dep-srv-x)", proc.stdout)
        calls = self.sb.calls()
        self.assertEqual([c for c in calls if c.startswith("SYNC ")],
                         [f"SYNC --repo {self.sb.repo} --changed op://P/Vendor2/key --reason x [p-vendor2] --no-deploy"])
        self.assertEqual(len([c for c in calls if "CURL POST" in c and "/services/srv-x/deploys" in c]), 1)
        self.assertTrue(any("CURL GET" in c and "/services/srv-x/deploys/dep-srv-x" in c for c in calls))

    def test_deploy_finalization_carries_a_reason_for_the_sensitive_render_key(self) -> None:
        """The Render API key lives in <PROJECT>-sensitive and this orchestrator
        resolves it ITSELF; without the reason in the environment the shim
        refuses (exit 3) after every value is already saved."""
        fake_op = write_exec(self.sb.tmp / "fake-op",
            'for a in "$@"; do case "$a" in op://*-sensitive/*)\n'
            '  if [[ -z "${SENSITIVE_ACCESS_REASON:-}${OP_ACCESS_REASON:-}" ]]; then\n'
            '    echo "ERROR: sensitive vault access requires a reason." >&2; exit 3\n'
            '  fi ;; esac; done\n'
            'printf fake-render-key\n')
        env = self.sb.env(OP_BIN=str(fake_op), SECRETS_RENDER_KEY_REF="op://P-sensitive/Render/api_key",
                          SECRETS_ALLOW_AGENT="1")
        for k in ("RENDER_API_KEY", "SENSITIVE_ACCESS_REASON", "OP_ACCESS_REASON"):
            env.pop(k, None)
        proc = subprocess.run([BIN, "--repo", str(self.sb.repo), "p", "--reason", "sweep repair",
                               "--only", "p-vendor2"],
                              capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("requires a reason", proc.stderr)
        self.assertIn("deploy triggered", proc.stdout)

    def test_batched_provider_entry_finalizes_only_after_its_deploy_is_live(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-hmac")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = self.sb.calls()
        i_rotate = next(i for i, c in enumerate(calls) if HMAC in c and "--no-finalize" in c)
        i_deploy = next(i for i, c in enumerate(calls) if "CURL POST" in c and "/services/srv-x/deploys" in c)
        i_live = next(i for i, c in enumerate(calls) if "CURL GET" in c and "/deploys/dep-srv-x" in c)
        i_fin = next(i for i, c in enumerate(calls) if HMAC in c and "--finalize" in c)
        self.assertLess(i_rotate, i_deploy)
        self.assertLess(i_deploy, i_live)
        self.assertLess(i_live, i_fin)
        self.assertIn("[no-deploy]", calls[i_rotate])  # save-only: the deploy is the orchestrator's
        self.assertNotIn("[no-deploy]", calls[i_fin])
        self.assertEqual(len([c for c in calls if "CURL POST" in c]), 1)
        self.assertIsNone(self.sb.state())

    def test_deploy_not_live_blocks_finalize_and_keeps_dests_pending(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-hmac", FAKE_DEPLOY_STATUS="build_failed")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertFalse(any("--finalize" in c for c in self.sb.calls()))
        st = self.sb.state()
        self.assertEqual(st["pendingDests"], ["srv-x"])
        self.assertEqual(st["minted"], ["p-hmac"])

    def test_phase2_partial_wave_failure_then_rerun_deploys_and_finalizes(self) -> None:
        # p-hmac succeeds (minted, srv-x deferred) while p-token fails in the same wave.
        first = self.sb.run("--reason", "x", "--only", "p-hmac,p-token", FAIL_SUBSTR="API/token")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        st = self.sb.state()
        self.assertEqual(st["minted"], ["p-hmac"])
        self.assertEqual(st["pendingDests"], ["srv-x"])
        self.assertEqual(st["selection"], {"tier": "all", "only": "p-hmac,p-token", "skip": ""})
        self.assertFalse(any("CURL POST" in c for c in self.sb.calls()))  # wave failed: no deploy yet
        self.sb.reset_log()
        second = self.sb.run("--reason", "x", "--only", "p-hmac,p-token")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("resuming", second.stdout)
        calls = self.sb.calls()
        self.assertFalse(any(HMAC in c and "--no-finalize" in c for c in calls))  # not reminted
        i_deploy = next(i for i, c in enumerate(calls) if "CURL POST" in c and "/services/srv-x/deploys" in c)
        i_fin = next(i for i, c in enumerate(calls) if HMAC in c and "--finalize" in c)
        i_token = next(i for i, c in enumerate(calls) if TOKEN in c and "--no-finalize" in c)
        self.assertLess(i_deploy, i_fin)
        self.assertLess(i_fin, i_token)
        self.assertIsNone(self.sb.state())

    def test_rerun_does_not_remint_completed_entries(self) -> None:
        first = self.sb.run("--reason", "x", "--skip", "p-vendor2,p-hmac", FAIL_SUBSTR="P-sensitive")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        mints = [c for c in self.sb.calls() if TOKEN in c and "--no-finalize" in c]
        self.assertEqual(len(mints), 1)
        self.sb.reset_log()
        second = self.sb.run("--reason", "x", "--skip", "p-vendor2,p-hmac", FAIL_SUBSTR="P-sensitive")
        self.assertEqual(second.returncode, 1, second.stdout + second.stderr)
        self.assertIn("not reminting", second.stdout)
        calls = "\n".join(self.sb.calls())
        self.assertNotIn(TOKEN, calls)
        self.assertIn("Postgres prod/web", calls)

    def test_canary_is_finalized_at_the_end_of_a_resumed_sweep(self) -> None:
        first = self.sb.run("--reason", "x", "--only", "p-db-staging,p-db-prod",
                            FAIL_SUBSTR="P-sensitive", FAIL_ONCE="1")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        self.assertFalse(any("--finalize" in c for c in self.sb.calls()))
        self.assertEqual(self.sb.state()["canaryRef"], PG_STAGING)
        self.sb.log.write_text("", encoding="utf-8")  # keep the failed-once marker
        second = self.sb.run("--reason", "x", "--only", "p-db-staging,p-db-prod",
                             FAIL_SUBSTR="P-sensitive", FAIL_ONCE="1")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        calls = self.sb.calls()
        self.assertFalse(any(PG_STAGING in c and "--no-finalize" in c for c in calls))  # not reminted
        fin = [i for i, c in enumerate(calls) if PG_STAGING in c and "--finalize" in c]
        self.assertEqual(len(fin), 1)
        prod_fin = next(i for i, c in enumerate(calls) if PG_PROD in c and "--finalize" in c)
        self.assertLess(prod_fin, fin[0])
        self.assertIn("canary predecessor retired", second.stdout)
        self.assertIsNone(self.sb.state())

    def test_prod_postgres_is_finalized_right_after_its_health_gate(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-db-prod")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        calls = self.sb.calls()
        self.assertTrue(any(PG_PROD in c and "--no-finalize" in c for c in calls))
        self.assertTrue(any(PG_PROD in c and "--finalize" in c for c in calls))

    def test_mismatched_selection_resume_is_refused_unless_fresh(self) -> None:
        first = self.sb.run("--reason", "x", "--skip", "p-vendor2,p-hmac", FAIL_SUBSTR="P-sensitive")
        self.assertEqual(first.returncode, 1)
        proc = self.sb.run("--reason", "x", "--skip", "p-vendor,p-hmac")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("different selection", proc.stderr)
        self.sb.reset_log()
        fresh = self.sb.run("--reason", "x", "--skip", "p-vendor,p-hmac", "--fresh", FAIL_SUBSTR="P-sensitive")
        self.assertEqual(fresh.returncode, 1, fresh.stdout + fresh.stderr)
        self.assertIn("discarded unfinished sweep checkpoint", fresh.stdout)
        self.assertIn(TOKEN, "\n".join(self.sb.calls()))  # reminted after --fresh

    def test_fresh_refuses_while_deploys_or_finalizes_are_pending(self) -> None:
        first = self.sb.run("--reason", "x", "--only", "p-hmac,p-token", FAIL_SUBSTR="API/token")
        self.assertEqual(first.returncode, 1)
        proc = self.sb.run("--reason", "x", "--only", "p-hmac,p-token", "--fresh")
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("--fresh refused", proc.stderr)
        self.assertIn("1 deferred deploy(s)", proc.stderr)
        self.assertIsNotNone(self.sb.state())

    def test_crash_between_deploy_and_finalize_is_finalized_on_rerun(self) -> None:
        # deploy_pending succeeded (dests cleared) but finalize failed hard:
        # the checkpoint holds minted=[p-hmac] with no pending dests. The
        # rerun must finalize it, never report "sweep already complete".
        first = self.sb.run("--reason", "x", "--only", "p-hmac",
                            FINALIZE_SUBSTR="HMAC", FINALIZE_EXIT="1", FINALIZE_ONCE="1")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        st = self.sb.state()
        self.assertEqual(st["minted"], ["p-hmac"])
        self.assertEqual(st["pendingDests"], [])
        self.sb.reset_log()
        second = self.sb.run("--reason", "x", "--only", "p-hmac")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertLess(second.stdout.index("finalized (predecessor retired)"),
                        second.stdout.index("sweep already complete"))
        calls = self.sb.calls()
        self.assertFalse(any(HMAC in c and "--no-finalize" in c for c in calls))  # not reminted
        self.assertFalse(any("CURL POST" in c for c in calls))  # deploys were already live
        self.assertEqual(len([c for c in calls if HMAC in c and "--finalize" in c]), 1)
        self.assertIsNone(self.sb.state())

    def test_finalize_rc6_is_non_fatal_and_retried_on_rerun(self) -> None:
        first = self.sb.run("--reason", "x", "--only", "p-hmac,p-token",
                            FINALIZE_SUBSTR=HMAC, FINALIZE_EXIT="6")
        self.assertEqual(first.returncode, 1, first.stdout + first.stderr)
        self.assertIn("predecessor cleanup pending", first.stdout)
        self.assertIn("p-hmac", first.stdout)
        self.assertNotIn("stopped after a failure", first.stdout)
        st = self.sb.state()
        self.assertEqual(st["pendingFinalize"], ["p-hmac"])
        self.assertEqual(sorted(st["completed"]), ["p-hmac", "p-token"])
        # p-token still got its finalize and both rotations ran
        self.assertTrue(any(TOKEN in c and "--finalize" in c for c in self.sb.calls()))
        self.sb.reset_log()
        second = self.sb.run("--reason", "x", "--only", "p-hmac,p-token")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        calls = self.sb.calls()
        self.assertEqual(calls, [c for c in calls if "--finalize" in c])  # only the retry, nothing reminted
        self.assertEqual(len(calls), 1)
        self.assertIn(HMAC, calls[0])
        self.assertIsNone(self.sb.state())

    def test_logs_persist_under_the_state_dir(self) -> None:
        proc = self.sb.run("--reason", "x", "--only", "p-token")
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        logs = list((self.sb.tmp / "sweep-state" / "p" / "logs").glob("*/p-token.log"))
        self.assertEqual(len(logs), 1)
        self.assertIn("logs:", proc.stdout)


def packing_registry(tmp: Path, *, shared_dest: bool = False, shared_item: bool = False) -> Path:
    dest_a, dest_b = "srv-aaaa", ("srv-aaaa" if shared_dest else "srv-bbbb")
    ref_a = "op://P-sensitive/Postgres prod/web_a"
    ref_b = "op://P-sensitive/Postgres prod/web_b" if shared_item else "op://P-sensitive/Postgres prod B/web_b"
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    doc = {
        "project": "p",
        "repos": ["repo"],
        "health": {},
        "rotation": {
            "p-db-a": {"ref": ref_a, "provider": "postgres", "mode": "DUAL_KEY", "owner_repo": "repo"},
            "p-db-b": {"ref": ref_b, "provider": "postgres", "mode": "DUAL_KEY", "owner_repo": "repo"},
        },
        "routes": [
            {"repo": "repo", "kind": "render", "dest": dest_a, "env": "DATABASE_URL_A",
             "ref": ref_a, "transform": "self"},
            {"repo": "repo", "kind": "render", "dest": dest_b, "env": "DATABASE_URL_B",
             "ref": ref_b, "transform": "self"},
        ],
    }
    (repo / "secrets.yaml").write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return repo, ref_a, ref_b


class PostgresWavePackingTest(unittest.TestCase):
    """Dest-disjoint + lock-disjoint + item-disjoint postgres entries share a
    wave; the rest stay sequential. Lock keys come from postgres-rotate
    --print-lock-key."""

    def setUp(self) -> None:
        self.sb = Sandbox()

    def _run(self, repo: Path, keys: dict, *args: str) -> subprocess.CompletedProcess:
        self.sb.repo = repo
        return self.sb.run(*args, FAKE_LOCK_KEYS=json.dumps(keys))

    def test_disjoint_dest_lock_and_item_share_a_wave(self) -> None:
        repo, a, b = packing_registry(self.sb.tmp)
        keys = {a: "box_a/prod", b: "box_b/prod"}
        proc = self._run(repo, keys, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("wave 1/1 · parallel x2", proc.stdout)
        live = self._run(repo, keys, "--reason", "x")
        self.assertEqual(live.returncode, 0, live.stderr + live.stdout)
        self.assertIn("phase 3, parallel x2", live.stdout)

    def test_shared_dest_stays_sequential(self) -> None:
        repo, a, b = packing_registry(self.sb.tmp, shared_dest=True)
        proc = self._run(repo, {a: "box_a/prod", b: "box_b/prod"}, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("wave 1/2", proc.stdout)
        self.assertIn("wave 2/2", proc.stdout)
        self.assertNotIn("parallel x2", proc.stdout)

    def test_shared_lock_stays_sequential(self) -> None:
        repo, a, b = packing_registry(self.sb.tmp)
        proc = self._run(repo, {a: "box_a/prod", b: "box_a/prod"}, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("wave 1/2", proc.stdout)
        self.assertIn("wave 2/2", proc.stdout)
        self.assertNotIn("parallel x2", proc.stdout)

    def test_same_1password_item_stays_sequential(self) -> None:
        repo, a, b = packing_registry(self.sb.tmp, shared_item=True)
        proc = self._run(repo, {a: "box_a/prod", b: "box_b/prod"}, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("wave 1/2", proc.stdout)
        self.assertIn("wave 2/2", proc.stdout)
        self.assertNotIn("parallel x2", proc.stdout)


class DryRunPreflightTest(unittest.TestCase):
    """Dry-run verifies field EXISTENCE from item metadata and fails when a
    required field is absent — the sweep must not pass a dry run it would
    fail live (2026-08-08: Postgres staging/root)."""

    def setUp(self) -> None:
        self.sb = Sandbox()

    def dry_run(self, fields_by_item: dict) -> subprocess.CompletedProcess:
        spec = self.sb.tmp / "op-items.json"
        spec.write_text(json.dumps(fields_by_item), encoding="utf-8")
        op = write_exec(self.sb.tmp / "fake-op",
            'exec python3 - "$3" <<PY\n'
            "import json, sys\n"
            f'spec = json.load(open("{spec}"))\n'
            "title = sys.argv[1]\n"
            "if title not in spec: sys.exit(1)\n"
            'print(json.dumps({"fields": [{"label": f} for f in spec[title]]}))\n'
            "PY\n")
        return self.sb.run("--dry-run", ROTATE_PREFLIGHT="1", DB_ROLES_CONFIG="/nonexistent", OP_BIN=str(op))

    FIELDS = {
        "Postgres prod": ["web"],
        "API": ["token"],
        "HMAC": ["key"],
        "Postgres staging": ["web"],
        "Vendor": ["key"],
        "Vendor2": ["key"],
    }

    def test_all_fields_present_passes(self) -> None:
        proc = self.dry_run(self.FIELDS)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("preflight:", proc.stdout)
        self.assertIn("verified by field name", proc.stdout)

    def test_missing_field_fails_the_dry_run(self) -> None:
        fields = dict(self.FIELDS)
        fields["Vendor2"] = ["something-else"]
        proc = self.dry_run(fields)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("has no field 'key'", proc.stderr)
        self.assertIn("PREFLIGHT FAIL", proc.stderr)

    def test_missing_item_fails_the_dry_run(self) -> None:
        fields = {k: v for k, v in self.FIELDS.items() if k != "Vendor"}
        proc = self.dry_run(fields)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("missing or unreadable", proc.stderr)

    def test_sensitive_vault_is_reported_unchecked_not_prompted(self) -> None:
        fields = {k: v for k, v in self.FIELDS.items() if k != "Postgres prod"}
        proc = self.dry_run(fields)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("unchecked (Touch ID vault", proc.stdout)


if __name__ == "__main__":
    unittest.main()

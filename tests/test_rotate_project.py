"""rotate-project orchestrator: selection, ordering, canary flag, stop-on-failure."""

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
BIN = str(HERE.parent / "bin" / "rotate-project")


def registry(tmp: Path) -> Path:
    """Write the sandbox project repo (secrets.yaml) and return its path."""
    doc = {
        "project": "p",
        "repos": ["repo"],
        "health": {"srv-web": "http://127.0.0.1:1/health"},
        "rotation": {
            "p-db-prod": {"ref": "op://P-sensitive/Postgres prod/web",
                          "provider": "postgres", "mode": "DUAL_KEY"},
            "p-token": {"ref": "op://P/API/token",
                        "provider": "self_minted", "mode": "SELF_MINTED"},
            "p-db-staging": {"ref": "op://P/Postgres staging/web",
                             "provider": "postgres", "mode": "DUAL_KEY"},
            "p-vendor": {"ref": "op://P/Vendor/key",
                         "provider": "vendor", "mode": "DUAL_KEY"},
            "p-vendor2": {"ref": "op://P/Vendor2/key",
                          "provider": "vendor", "mode": "DUAL_KEY"},
        },
        "routes": [
            {"repo": "repo", "kind": "render", "dest": "srv-web",
             "env": "DATABASE_URL", "ref": "op://P-sensitive/Postgres prod/web",
             "transform": "self"},
            {"repo": "repo", "kind": "dev", "dest": "profile", "env": "TOKEN",
             "ref": "op://P/API/token", "transform": "self"},
            {"repo": "repo", "kind": "dev", "dest": "profile", "env": "DB_STAGING",
             "ref": "op://P/Postgres staging/web", "transform": "self"},
            {"repo": "repo", "kind": "dev", "dest": "profile", "env": "VENDOR_KEY",
             "ref": "op://P/Vendor/key", "transform": "self"},
            {"repo": "repo", "kind": "render", "dest": "srv-x", "env": "K",
             "ref": "op://P/Vendor2/key", "transform": "self"},
        ],
    }
    repo = tmp / "repo"
    repo.mkdir(exist_ok=True)
    (repo / "secrets.yaml").write_text(yaml.safe_dump(doc, sort_keys=False),
                                       encoding="utf-8")
    return repo


def fake_rotate(tmp: Path, script: str) -> Path:
    p = tmp / "rotate-secret"
    p.write_text("#!/usr/bin/env bash\n" + script, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def run(tmp: Path, rotate_body: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["ROTATE_PREFLIGHT"] = "0"  # sandbox refs aren't real vault items
    env["ROTATE_SECRET"] = str(fake_rotate(tmp, rotate_body))
    return subprocess.run([BIN, "--repo", str(registry(tmp)), *args],
                          capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


class RotateProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_dry_run_plan_sections_and_canary(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = proc.stdout
        self.assertIn("ROTATE", out)
        self.assertIn("SYNC", out)
        ids = [l.strip().split(" ")[0] for l in out.splitlines()
               if l.strip().startswith(("p-db", "p-token", "p-vendor"))]
        self.assertEqual(ids, ["p-db-staging", "p-token", "p-db-prod", "p-vendor", "p-vendor2"])
        self.assertIn("rollback (canary)", out)
        self.assertIn("render:127.0.0.1:1", out)
        self.assertIn("DATABASE_URL", out)
        self.assertIn("no secret values were read", out)

    def test_live_sweep_passes_reason_and_stops_on_failure(self) -> None:
        body = (
            'echo "$@" >> "$LOG"\n'
            'for a in "$@"; do [[ "$a" == *API/token* ]] && exit 1; done\nexit 0\n'
        )
        env_log = self.tmp / "calls.log"
        env = dict(os.environ)
        env["ROTATE_PREFLIGHT"] = "0"
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, body))
        env["LOG"] = str(env_log)
        proc = subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p",
             "--reason", "sweep test", "--skip", "p-db-prod,p-vendor2"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        calls = env_log.read_text(encoding="utf-8")
        self.assertIn("sweep test [p-db-staging]", calls)
        self.assertIn("--keep-old", calls)
        self.assertIn("p-token", proc.stdout)
        self.assertIn("failed", proc.stdout)
        self.assertIn("stopped after a failure", proc.stdout)

    def test_sync_entry_failure_stops_the_sweep(self) -> None:
        env = dict(os.environ)
        env["ROTATE_PREFLIGHT"] = "0"
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, "exit 0"))
        sync = self.tmp / "sync-secrets"
        sync.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        sync.chmod(sync.stat().st_mode | stat.S_IEXEC)
        env["SYNC_SECRETS"] = str(sync)
        proc = subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p", "--reason", "x", "--only", "p-vendor2"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 1)

    def test_provider_entries_sync_current_vault_value(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run")
        self.assertIn("current 1Password value", proc.stdout)
        self.assertIn("p-vendor", proc.stdout)

    def test_sync_only_entries_are_not_reported_as_rotated(self) -> None:
        """`p-vendor` has an unimplemented provider, so the sweep only pushes the
        value the vault already holds. Reporting that identically to a real mint
        is how a rotation that never happened reads as done."""
        env = dict(os.environ)
        env["ROTATE_PREFLIGHT"] = "0"
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, "exit 0"))
        env["SYNC_SECRETS"] = str(fake_rotate(self.tmp, "exit 0"))
        proc = subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p", "--reason", "x",
             "--only", "p-vendor"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("credential NOT rotated", proc.stdout)
        self.assertIn("1 synced only", proc.stdout)
        self.assertIn("0 rotated+verified", proc.stdout)

    def test_rotated_entries_are_still_reported_as_rotated(self) -> None:
        env = dict(os.environ)
        env["ROTATE_PREFLIGHT"] = "0"
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, "exit 0"))
        proc = subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p", "--reason", "x",
             "--only", "p-token"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("1 rotated+verified", proc.stdout)
        self.assertNotIn("credential NOT rotated", proc.stdout)
        self.assertNotIn("synced only", proc.stdout)

    def test_sweep_reaches_the_deploy_finalization_and_completes(self) -> None:
        """Deploy finalization only runs when EVERY entry succeeded, so it was
        never exercised: it called op_vault_read, which lives in vault.sh — a lib
        finalize_pending_deploys does not source. Every sweep that got that far
        died on `op_vault_read: command not found` after the values were already
        saved, leaving the services un-redeployed."""
        fakebin = self.tmp / "fakebin"
        fakebin.mkdir(exist_ok=True)
        curl = fakebin / "curl"
        curl.write_text(
            '#!/usr/bin/env bash\n'
            'url=""; prev=""\n'
            'for a in "$@"; do [[ "$prev" == "--url" ]] && url="$a"; prev="$a"; done\n'
            'cat >/dev/null 2>&1\n'
            'case "$url" in\n'
            '  *"/deploys"*) printf \'[{"deploy":{"id":"dep-1","status":"live"}}]\' ;;\n'
            '  *) printf \'{"id":"dep-1","status":"live"}\' ;;\n'
            'esac\n',
            encoding="utf-8",
        )
        curl.chmod(0o755)

        env = dict(os.environ)
        env["ROTATE_PREFLIGHT"] = "0"
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, "exit 0"))
        env["SYNC_SECRETS"] = str(fake_rotate(self.tmp, "exit 0"))
        env["PATH"] = f"{fakebin}:{env['PATH']}"
        # Render key via the env sentinel: render_key_ref_for -> env:RENDER_API_KEY,
        # which only render_key_resolve understands (op_vault_read would have tried
        # to read the sentinel as an op:// ref even once it was in scope).
        env["RENDER_API_KEY"] = "fake-render-key"
        env["SECRETS_RENDER_KEY_REF"] = "env:RENDER_API_KEY"

        proc = subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p", "--reason", "x",
             "--only", "p-vendor2"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("command not found", proc.stderr)
        self.assertNotIn("could not resolve Render key", proc.stderr)
        self.assertIn("deploy triggered", proc.stdout)
        self.assertNotIn("stopped after a failure", proc.stdout)

    def test_deploy_finalization_carries_a_reason_for_the_sensitive_render_key(self) -> None:
        """The Render API key lives in <PROJECT>-sensitive, and this orchestrator
        resolves it ITSELF — the child rotate-secret/sync-secrets processes that
        export their own reason are not involved. With no reason in the
        environment the shim refuses (exit 3) after every value is already saved,
        so the sweep dies with the deploys untriggered.

        Unlike the sentinel path, this drives the real op read."""
        fakebin = self.tmp / "fakebin2"
        fakebin.mkdir(exist_ok=True)
        curl = fakebin / "curl"
        curl.write_text(
            '#!/usr/bin/env bash\n'
            'url=""; prev=""\n'
            'for a in "$@"; do [[ "$prev" == "--url" ]] && url="$a"; prev="$a"; done\n'
            'cat >/dev/null 2>&1\n'
            'case "$url" in\n'
            '  *"/deploys"*) printf \'[{"deploy":{"id":"dep-1","status":"live"}}]\' ;;\n'
            '  *) printf \'{"id":"dep-1","status":"live"}\' ;;\n'
            'esac\n',
            encoding="utf-8",
        )
        curl.chmod(0o755)
        # Stands in for the canonical shim's sensitive gate.
        fake_op = self.tmp / "fake-op"
        fake_op.write_text(
            '#!/usr/bin/env bash\n'
            'for a in "$@"; do case "$a" in op://*-sensitive/*)\n'
            '  if [[ -z "${SENSITIVE_ACCESS_REASON:-}${OP_ACCESS_REASON:-}" ]]; then\n'
            '    echo "ERROR: sensitive vault access requires a reason." >&2; exit 3\n'
            '  fi ;; esac; done\n'
            'printf fake-render-key\n',
            encoding="utf-8",
        )
        fake_op.chmod(0o755)

        env = dict(os.environ)
        env["ROTATE_PREFLIGHT"] = "0"
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, "exit 0"))
        env["SYNC_SECRETS"] = str(fake_rotate(self.tmp, "exit 0"))
        env["PATH"] = f"{fakebin}:{env['PATH']}"
        env["OP_BIN"] = str(fake_op)
        env["SECRETS_RENDER_KEY_REF"] = "op://P-sensitive/Render/api_key"
        env["SECRETS_ALLOW_AGENT"] = "1"  # the guard is not what's under test
        env.pop("RENDER_API_KEY", None)
        env.pop("SENSITIVE_ACCESS_REASON", None)
        env.pop("OP_ACCESS_REASON", None)

        proc = subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p", "--reason", "sweep repair",
             "--only", "p-vendor2"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertNotIn("requires a reason", proc.stderr)
        self.assertNotIn("could not resolve Render key", proc.stderr)
        self.assertIn("deploy triggered", proc.stdout)

    def test_only_filter_narrows_to_one_entry(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--only", "p-vendor")
        self.assertIn("p-vendor", proc.stdout)
        self.assertNotIn("p-token", proc.stdout)

    def test_tier_staging_skips_prod_entries(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--tier", "staging")
        self.assertIn("p-db-staging", proc.stdout)
        self.assertNotIn("p-db-prod", proc.stdout)


class DryRunPreflightTest(unittest.TestCase):
    """Dry-run verifies field EXISTENCE from item metadata and fails when a
    required field is absent — the sweep must not pass a dry run it would
    fail live (2026-08-08: Postgres staging/root)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def dry_run(self, fields_by_item: dict) -> subprocess.CompletedProcess:
        import json as _json
        spec = self.tmp / "op-items.json"
        spec.write_text(_json.dumps(fields_by_item), encoding="utf-8")
        op = self.tmp / "fake-op"
        op.write_text(
            "#!/usr/bin/env bash\n"
            'exec python3 - "$3" <<PY\n'
            "import json, sys\n"
            f'spec = json.load(open("{spec}"))\n'
            "title = sys.argv[1]\n"
            "if title not in spec: sys.exit(1)\n"
            'print(json.dumps({"fields": [{"label": f} for f in spec[title]]}))\n'
            "PY\n",
            encoding="utf-8",
        )
        op.chmod(0o755)
        env = dict(os.environ)
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, "exit 0"))
        env["DB_ROLES_CONFIG"] = "/nonexistent"
        env["OP_BIN"] = str(op)
        return subprocess.run(
            [BIN, "--repo", str(registry(self.tmp)), "p", "--dry-run"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )

    FIELDS = {
        "Postgres prod": ["web"],
        "API": ["token"],
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
        # P-sensitive/Postgres prod must be skipped (Touch ID), not failed.
        proc = self.dry_run(fields)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertIn("unchecked (Touch ID vault", proc.stdout)


if __name__ == "__main__":
    unittest.main()

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
        self.assertIn("nothing was read", out)

    def test_live_sweep_passes_reason_and_stops_on_failure(self) -> None:
        body = (
            'echo "$@" >> "$LOG"\n'
            'for a in "$@"; do [[ "$a" == *API/token* ]] && exit 1; done\nexit 0\n'
        )
        env_log = self.tmp / "calls.log"
        env = dict(os.environ)
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

    def test_only_filter_narrows_to_one_entry(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--only", "p-vendor")
        self.assertIn("p-vendor", proc.stdout)
        self.assertNotIn("p-token", proc.stdout)

    def test_tier_staging_skips_prod_entries(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--tier", "staging")
        self.assertIn("p-db-staging", proc.stdout)
        self.assertNotIn("p-db-prod", proc.stdout)


if __name__ == "__main__":
    unittest.main()

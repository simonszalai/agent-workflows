"""rotate-project orchestrator: selection, ordering, canary flag, stop-on-failure."""

import json
import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
BIN = str(HERE.parent / "bin" / "rotate-project")


def registry(tmp: Path) -> Path:
    data = {
        "schema_version": 1,
        "health_urls": {"srv-web": "http://127.0.0.1:1/health"},
        "secrets": [
            {"id": "p-db-prod", "project": "p", "ref": "op://P-sensitive/Postgres prod/web",
             "provider": "postgres", "mode": "DUAL_KEY", "consumers": [{"dest": "srv-web", "env": "DATABASE_URL"}]},
            {"id": "p-token", "project": "p", "ref": "op://P/API/token",
             "provider": "self_minted", "mode": "SELF_MINTED", "consumers": []},
            {"id": "p-db-staging", "project": "p", "ref": "op://P/Postgres staging/web",
             "provider": "postgres", "mode": "DUAL_KEY", "consumers": []},
            {"id": "p-vendor", "project": "p", "ref": "op://P/Vendor/key",
             "provider": "vendor", "mode": "DUAL_KEY", "consumers": []},
            {"id": "other", "project": "q", "ref": "op://Q/API/token",
             "provider": "self_minted", "mode": "SELF_MINTED", "consumers": []},
        ],
    }
    p = tmp / "registry.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def fake_rotate(tmp: Path, script: str) -> Path:
    p = tmp / "rotate-secret"
    p.write_text("#!/usr/bin/env bash\n" + script, encoding="utf-8")
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return p


def run(tmp: Path, rotate_body: str, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["ROTATION_REGISTRY"] = str(registry(tmp))
    env["ROTATE_SECRET"] = str(fake_rotate(tmp, rotate_body))
    return subprocess.run([BIN, *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)


class RotateProjectTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())

    def test_dry_run_orders_phases_and_flags_canary(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [l for l in proc.stdout.splitlines() if "would rotate" in l]
        ids = [l.split("): ")[1].split(" ")[0] for l in lines]
        self.assertEqual(ids, ["p-db-staging", "p-token", "p-vendor", "p-db-prod"])
        self.assertIn("--keep-old", lines[0])
        self.assertIn("(sequential)", lines[0])
        self.assertIn("(parallel", lines[1])
        self.assertNotIn("--keep-old", lines[3])
        self.assertNotIn("other", proc.stdout)

    def test_live_sweep_passes_reason_and_stops_on_failure(self) -> None:
        body = (
            'echo "$@" >> "$LOG"\n'
            'for a in "$@"; do [[ "$a" == *Vendor* ]] && exit 1; done\nexit 0\n'
        )
        env_log = self.tmp / "calls.log"
        env = dict(os.environ)
        env["ROTATION_REGISTRY"] = str(registry(self.tmp))
        env["ROTATE_SECRET"] = str(fake_rotate(self.tmp, body))
        env["LOG"] = str(env_log)
        proc = subprocess.run(
            [BIN, "p", "--reason", "sweep test", "--all", "--skip", "p-db-prod"],
            capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL,
        )
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        calls = env_log.read_text(encoding="utf-8")
        self.assertIn("sweep test [p-db-staging]", calls)
        self.assertIn("--keep-old", calls)
        self.assertIn("p-vendor", proc.stdout)
        self.assertIn("failed", proc.stdout)
        self.assertIn("stopped after a failure", proc.stdout)

    def test_manual_provider_requires_tty(self) -> None:
        proc = run(self.tmp, "exit 3", "p", "--reason", "x", "--manual", "--only", "p-vendor")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("no controlling terminal", proc.stderr)

    def test_default_scope_excludes_manual_providers(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run")
        self.assertNotIn("would rotate (parallel x1): p-vendor", proc.stdout)
        self.assertIn("NOT included (run with --manual): p-vendor", proc.stdout)

    def test_manual_scope_runs_only_manual_providers(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--manual")
        lines = [l for l in proc.stdout.splitlines() if "would rotate" in l]
        self.assertEqual(len(lines), 1)
        self.assertIn("p-vendor", lines[0])

    def test_tier_staging_skips_prod_entries(self) -> None:
        proc = run(self.tmp, "exit 0", "p", "--dry-run", "--tier", "staging")
        self.assertIn("p-db-staging", proc.stdout)
        self.assertNotIn("would rotate: p-db-prod", proc.stdout)


if __name__ == "__main__":
    unittest.main()

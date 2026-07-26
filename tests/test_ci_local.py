from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CI_LOCAL = ROOT / "bin" / "ci-local"

FIXTURE_WORKFLOW = """\
name: CI
on:
  pull_request:
env:
  TOP: topval
jobs:
  quick:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
      - name: env check
        env: {STEPVAR: stepval}
        run: test "$TOP" = topval && test "$STEPVAR" = stepval
      - run: echo quick-ok
  failing:
    runs-on: ubuntu-latest
    steps:
      - run: exit 3
  svc:
    runs-on: ubuntu-latest
    services:
      postgres: {image: postgres:16}
    steps:
      - run: echo needs-db
  expr:
    runs-on: ubuntu-latest
    steps:
      - run: echo "${{ github.base_ref }}"
  opaque:
    runs-on: ubuntu-latest
    steps:
      - uses: some-org/custom-action@v1
      - run: echo after-action
"""

DISPATCH_ONLY_WORKFLOW = """\
name: Manual
on:
  workflow_dispatch:
jobs:
  manual:
    runs-on: ubuntu-latest
    steps:
      - run: echo never-ci
"""


class CiLocalTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.repo = Path(self._tmp.name)
        workflows = self.repo / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(FIXTURE_WORKFLOW, encoding="utf-8")
        (workflows / "manual.yml").write_text(DISPATCH_ONLY_WORKFLOW, encoding="utf-8")

    def run_ci_local(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(CI_LOCAL), "--repo", str(self.repo), *args],
            capture_output=True, text=True,
        )

    def test_plan_classifies_jobs_and_ignores_dispatch_only_workflows(self) -> None:
        result = self.run_ci_local()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[RUN] quick", result.stdout)
        self.assertIn("[SKIP] svc", result.stdout)
        self.assertIn("needs services: postgres", result.stdout)
        self.assertIn("[SKIP] expr", result.stdout)
        self.assertIn("[SKIP] opaque", result.stdout)
        self.assertIn("some-org/custom-action@v1", result.stdout)
        self.assertNotIn("manual", result.stdout)
        self.assertNotIn("never-ci", result.stdout)

    def test_run_executes_with_merged_env_skips_and_reports_failures(self) -> None:
        result = self.run_ci_local("--run")
        self.assertEqual(result.returncode, 1)
        self.assertIn("PASS quick", result.stdout)
        self.assertIn("quick-ok", result.stdout)
        self.assertIn("FAIL failing", result.stdout)
        self.assertIn("SKIP  svc", result.stdout)
        self.assertNotIn("needs-db", result.stdout)

    def test_job_filter_forces_skip_classified_jobs(self) -> None:
        result = self.run_ci_local("--run", "--job", "svc")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("needs-db", result.stdout)
        self.assertIn("PASS svc", result.stdout)

    def test_unknown_job_is_an_error(self) -> None:
        result = self.run_ci_local("--run", "--job", "nope")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown job", result.stderr)

    def test_repo_override_is_delegated_to(self) -> None:
        override = self.repo / "bin" / "ci-local"
        override.parent.mkdir()
        override.write_text("#!/bin/sh\necho override-ran\nexit 0\n", encoding="utf-8")
        override.chmod(override.stat().st_mode | stat.S_IXUSR)
        env = {k: v for k, v in os.environ.items() if k != "CI_LOCAL_OVERRIDE"}
        result = subprocess.run(
            [str(CI_LOCAL), "--repo", str(self.repo), "--run"],
            capture_output=True, text=True, env=env,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("override-ran", result.stdout)
        self.assertIn("delegating to repo override", result.stdout)

    def test_no_override_flag_ignores_repo_script(self) -> None:
        override = self.repo / "bin" / "ci-local"
        override.parent.mkdir()
        override.write_text("#!/bin/sh\necho override-ran\nexit 1\n", encoding="utf-8")
        override.chmod(override.stat().st_mode | stat.S_IXUSR)
        result = self.run_ci_local("--no-override")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("override-ran", result.stdout)
        self.assertIn("[RUN] quick", result.stdout)


if __name__ == "__main__":
    unittest.main()

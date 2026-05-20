#!/usr/bin/env python3
"""Run safe local automated encryption verification for ts-prefect."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REQUIRED_PATHS = [
    "docs/encryption/encryption-testing-automated.md",
    "docs/encryption/encryption-testing-manual.md",
    "docs/encryption/plaintext_fields.md",
    "scripts/check_plaintext_fields.py",
    "src/encryption/plaintext_fields.py",
    "src/encryption/types.py",
]

FOCUSED_TESTS = [
    "tests/unit/test_encryption_types.py",
    "tests/unit/test_plaintext_fields.py",
    "tests/unit/test_check_plaintext_fields.py",
    "tests/unit/test_pipeline_contracts.py",
    "tests/unit/test_response_schemas.py",
]

STALE_DOC_PATTERNS = [
    "allow-list signature",
    "Allow-List Change Drill",
    "EncryptedStr",
    "check_encryption_schema.py",
    "delete `PRIVATE_KEY_B64`",
    "Destroy active key material",
]


@dataclass
class Result:
    name: str
    status: str
    detail: str


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{cwd}{os.pathsep}" + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return proc.returncode, proc.stdout


def add(results: list[Result], name: str, status: str, detail: str) -> None:
    results.append(Result(name=name, status=status, detail=detail.strip()))


def tail(text: str, max_lines: int = 80) -> str:
    lines = text.rstrip().splitlines()
    if len(lines) <= max_lines:
        return text.rstrip()
    return "... output truncated ...\n" + "\n".join(lines[-max_lines:])


def print_report(results: list[Result]) -> None:
    print("# Encryption automated verification")
    for result in results:
        print(f"\n## {result.status}: {result.name}")
        if result.detail:
            print(result.detail)
    counts = {status: sum(1 for r in results if r.status == status) for status in ["PASS", "WARN", "FAIL"]}
    print(f"\nSummary: {counts['PASS']} PASS, {counts['WARN']} WARN, {counts['FAIL']} FAIL")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="ts-prefect repo path")
    parser.add_argument("--full-tests", action="store_true", help="run full pytest tests/ instead of focused tests")
    args = parser.parse_args()

    repo = args.repo.resolve()
    results: list[Result] = []

    if not (repo / "pyproject.toml").exists() or not (repo / "docs/encryption").exists():
        add(results, "repo", "FAIL", f"{repo} does not look like ts-prefect")
        print_report(results)
        return 2

    missing = [p for p in REQUIRED_PATHS if not (repo / p).exists()]
    add(
        results,
        "required files",
        "FAIL" if missing else "PASS",
        "missing: " + ", ".join(missing) if missing else "all expected encryption docs/scripts exist",
    )

    code, out = run(["uv", "run", "python", "scripts/check_plaintext_fields.py", "--verbose"], repo)
    add(results, "PLAINTEXT_FIELDS CI", "PASS" if code == 0 else "FAIL", tail(out))

    test_cmd = ["uv", "run", "pytest"] + (["tests", "-v"] if args.full_tests else [*FOCUSED_TESTS, "-q"])
    code, out = run(test_cmd, repo)
    add(results, "pytest", "PASS" if code == 0 else "FAIL", "$ " + " ".join(test_cmd) + "\n" + tail(out))

    docs = "\n".join((repo / p).read_text(errors="ignore") for p in [
        "docs/encryption/encryption-testing-automated.md",
        "docs/encryption/encryption-testing-manual.md",
    ])
    stale = [pat for pat in STALE_DOC_PATTERNS if pat in docs]
    add(
        results,
        "stale doc instructions",
        "FAIL" if stale else "PASS",
        "found stale patterns: " + ", ".join(stale) if stale else "no stale signed-allow-list / destructive-key-test instructions found",
    )

    guard_exists = (repo / "src/utils/ciphertext_guard.py").exists()
    _, grep_out = run([
        "bash",
        "-lc",
        "rg -n '_is_proxy_configured|guard_ciphertext|ciphertext_guard' src/blocks src/utils tests/unit/test_ciphertext_guard.py 2>/dev/null || true",
    ], repo)
    if guard_exists or grep_out.strip():
        add(
            results,
            "target-state proxy-only cleanup",
            "WARN",
            "ciphertext guard / dual-mode fallback still present; acceptable only if recorded as pending follow-up and staging blocks are proxy-configured",
        )
    else:
        add(results, "target-state proxy-only cleanup", "PASS", "guard removed and dual-mode grep clean")

    add(
        results,
        "manual staging follow-ups",
        "WARN",
        "still requires live staging checks: proxy health/auth/Tailscale, Render env vars, DB spot checks, dashboard extension UX, recovery drill",
    )

    print_report(results)
    return 2 if any(r.status == "FAIL" for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())

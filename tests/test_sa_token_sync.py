from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SYNC = ROOT / "bin/sync-sa-tokens"
KEYCHAIN_PUT = ROOT / "bin/keychain-put"
REGISTRY = ROOT / "config/project-tools.json"

EXPECTED_TOKEN_REFS = {
    "amaru": "op://OP SA/j3nzwa3qi3xkbjpoyj3i6cdp64/credential",
    "autodev": "op://OP SA/guvq7or3ibagshd6hmily5oo6u/credential",
    "ts": "op://OP SA/ntotyjj6l2yukkd3xts5swtmhy/credential",
    "workflow-pro": "op://OP SA/754s5xoosamdvseo6wd2z26pta/credential",
}


def run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, capture_output=True, text=True, timeout=30, **kwargs
    )  # type: ignore[arg-type]


class SaTokenSyncTest(unittest.TestCase):
    def test_dry_run_lists_every_registered_project_without_reading_secrets(self) -> None:
        result = run([str(SYNC), "--dry-run"])

        self.assertEqual(result.returncode, 0, result.stderr)
        for project, ref in EXPECTED_TOKEN_REFS.items():
            self.assertIn(project, result.stdout)
            self.assertIn(ref, result.stdout)

    def test_dry_run_and_verify_only_are_mutually_exclusive(self) -> None:
        result = run([str(SYNC), "--dry-run", "--verify-only"])

        self.assertEqual(result.returncode, 2)
        self.assertIn("mutually exclusive", result.stderr)

    def test_unknown_project_is_rejected(self) -> None:
        result = run([str(SYNC), "--project", "not-a-project", "--dry-run"])

        self.assertEqual(result.returncode, 2)
        self.assertIn("not-a-project", result.stderr)

    def test_unknown_option_is_rejected(self) -> None:
        result = run([str(SYNC), "--wat"])

        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown option", result.stderr)

    def test_keychain_put_requires_service_and_account(self) -> None:
        result = run([str(KEYCHAIN_PUT), "only-one-argument"], input="value")

        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stderr)

    def test_keychain_put_refuses_an_empty_value(self) -> None:
        result = run([str(KEYCHAIN_PUT), "claude-test-unused", "nobody"], input="")

        self.assertEqual(result.returncode, 2)
        self.assertIn("refusing to store an empty value", result.stderr)

    def test_secrets_never_travel_through_argv(self) -> None:
        # `security -w`/-X would place the token in argv, where any local process
        # can read it via ps. bin/keychain-put exists precisely to avoid that.
        source = SYNC.read_text(encoding="utf-8")
        self.assertNotIn("add-generic-password", source)
        self.assertIn('"$KEYCHAIN_PUT"', source)

    def test_full_sync_resolves_every_token_in_one_op_process(self) -> None:
        # Outside Conductor the shim caches nothing, so one op invocation per
        # token would mean one Touch ID prompt per token.
        source = SYNC.read_text(encoding="utf-8")
        self.assertIn('"$OP" inject', source)
        self.assertNotIn('"$OP" read', source)

    def test_registry_token_refs_match_the_op_sa_vault(self) -> None:
        import json

        projects = json.loads(REGISTRY.read_text(encoding="utf-8"))["projects"]
        for project, ref in EXPECTED_TOKEN_REFS.items():
            self.assertEqual(projects[project]["service_account"]["token_ref"], ref)
            self.assertFalse(
                ref.startswith("op://OP SA/Service Account"),
                "token_ref must use the item ID: op rejects the colon in the title",
            )


if __name__ == "__main__":
    unittest.main()

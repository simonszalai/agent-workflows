"""End-to-end coverage for bin/dev-env against fake op + real openssl cache."""

from __future__ import annotations

import stat
import unittest

from secrets_common import ROOT, SecretsSandbox, run

DEV_ENV = str(ROOT / "bin" / "dev-env")

DEV_MANIFEST = "\n".join(
    [
        "dev\tmyprofile\tPLAIN_A\top://TESTVAULT/ITEM/value\tself",
        "dev\tmyprofile\tPLAIN_B\top://TESTVAULT/ITEM2/value\tself",
        "dev\tmyprofile\tLIT_C\tliteral:committed-config\tself",
        "dev\totherprofile\tOTHER\top://TESTVAULT/OTHER/value\tself",
        "",
    ]
)

SENSITIVE_DEV_MANIFEST = "\n".join(
    [
        "dev\tmixed\tPLAIN_A\top://TESTVAULT/ITEM/value\tself",
        "dev\tmixed\tSECRET_S\top://TESTVAULT-sensitive/SECRETX/value\tself",
        "",
    ]
)


class DevEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.sb.write_manifest(DEV_MANIFEST)
        self.cache_dir = self.sb.root / "devenv-cache"

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(DEV_ENV_CACHE_DIR=str(self.cache_dir), **extra)

    def dev(self, *args: str, env: dict[str, str] | None = None):
        return run(
            [DEV_ENV, "--repo", str(self.sb.repo), *args],
            env if env is not None else self.env(),
        )

    def op_calls(self) -> list[str]:
        return [l for l in self.sb.log_lines() if l.startswith("OP ")]

    # --- inventory modes -------------------------------------------------------

    def test_keys_lists_envnames_with_zero_op_invocations(self) -> None:
        proc = self.dev("myprofile", "--keys")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.split(), ["PLAIN_A", "PLAIN_B", "LIT_C"])
        self.assertEqual(self.sb.log_lines(), [])

    def test_profiles_lists_dev_dests_with_zero_op_invocations(self) -> None:
        proc = self.dev("--profiles")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(proc.stdout.split()), ["myprofile", "otherprofile"])
        self.assertEqual(self.sb.log_lines(), [])

    def test_unknown_profile_is_usage_error(self) -> None:
        proc = self.dev("nope", "--", "true")
        self.assertEqual(proc.returncode, 2)

    # --- resolution ----------------------------------------------------------------

    def test_batched_inject_is_exactly_one_op_call_and_child_sees_values(self) -> None:
        proc = self.dev(
            "myprofile", "--",
            "bash", "-c", 'printf "%s|%s|%s" "$PLAIN_A" "$PLAIN_B" "$LIT_C"',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value|val-ITEM2-value|committed-config")
        self.assertEqual(self.op_calls(), ["OP inject"])

    def test_child_exit_code_is_propagated(self) -> None:
        proc = self.dev("myprofile", "--", "bash", "-c", "exit 7")
        self.assertEqual(proc.returncode, 7)

    def test_empty_resolved_value_exports_nothing_and_exits_1(self) -> None:
        self.sb.write_manifest(
            "dev\tmyprofile\tGOOD\top://TESTVAULT/ITEM/value\tself\n"
            "dev\tmyprofile\tBAD\top://TESTVAULT/EMPTY_ITEM/value\tself\n"
        )
        proc = self.dev("myprofile", "--", "bash", "-c", 'printf "%s" "${GOOD:-unset}"')
        self.assertEqual(proc.returncode, 1)
        self.assertIn("nothing exported", proc.stderr)
        self.assertNotIn("val-ITEM-value", proc.stdout)

    # --- encrypted cache --------------------------------------------------------------

    def test_second_run_hits_the_cache_with_zero_op_calls(self) -> None:
        first = self.dev("myprofile", "--", "bash", "-c", 'printf "%s" "$PLAIN_A"')
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(self.op_calls(), ["OP inject"])
        self.sb.log_path.unlink()
        second = self.dev("myprofile", "--", "bash", "-c", 'printf "%s" "$PLAIN_A"')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout, "val-ITEM-value")
        self.assertEqual(self.op_calls(), [])

    def test_cache_file_is_mode_600_and_encrypted(self) -> None:
        self.dev("myprofile", "--", "true")
        cache_file = self.cache_dir / "testproj" / "myprofile.enc"
        self.assertTrue(cache_file.exists())
        self.assertEqual(stat.S_IMODE(cache_file.stat().st_mode), 0o600)
        raw = cache_file.read_bytes()
        self.assertNotIn(b"val-ITEM-value", raw)  # never plaintext on disk

    def test_refresh_bypasses_the_cache(self) -> None:
        self.dev("myprofile", "--", "true")
        self.sb.log_path.unlink()
        proc = self.dev("myprofile", "--refresh", "--", "true")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.op_calls(), ["OP inject"])

    def test_row_hash_change_invalidates_the_cache(self) -> None:
        self.dev("myprofile", "--", "true")
        self.sb.log_path.unlink()
        self.sb.write_manifest(DEV_MANIFEST.replace("committed-config", "changed-config"))
        proc = self.dev("myprofile", "--", "bash", "-c", 'printf "%s" "$LIT_C"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "changed-config")
        self.assertEqual(self.op_calls(), ["OP inject"])

    def test_without_sa_token_cache_is_silently_skipped_but_run_fails_closed(self) -> None:
        # No token: plain reads themselves fail closed (rc 1, nothing exported),
        # and no cache file is created.
        proc = self.dev("myprofile", "--", "true", env=self.env(sa_token=False))
        self.assertEqual(proc.returncode, 1)
        self.assertFalse((self.cache_dir / "testproj").exists())

    # --- sensitive rows ------------------------------------------------------------------

    def test_sensitive_profile_without_reason_exits_3_before_any_read(self) -> None:
        self.sb.write_manifest(SENSITIVE_DEV_MANIFEST)
        proc = self.dev("mixed", "--", "true")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("reason is required", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_sensitive_profile_refuses_agent_shell(self) -> None:
        self.sb.write_manifest(SENSITIVE_DEV_MANIFEST)
        proc = self.dev("mixed", "--reason", "t", "--", "true", env=self.env(CLAUDECODE="1"))
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.sb.log_lines(), [])

    def test_sensitive_rows_resolve_individually_through_the_shim(self) -> None:
        self.sb.write_manifest(SENSITIVE_DEV_MANIFEST)
        proc = self.dev(
            "mixed", "--reason", "local debugging", "--",
            "bash", "-c", 'printf "%s|%s" "$PLAIN_A" "$SECRET_S"',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value|val-SECRETX-value")
        calls = self.op_calls()
        self.assertEqual(len([c for c in calls if c == "OP inject"]), 1)
        self.assertEqual(
            [c for c in calls if c.startswith("OP read")],
            ["OP read --no-newline op://TESTVAULT-sensitive/SECRETX/value"],
        )

    def test_no_sensitive_skips_sensitive_rows_entirely(self) -> None:
        self.sb.write_manifest(SENSITIVE_DEV_MANIFEST)
        proc = self.dev(
            "mixed", "--no-sensitive", "--",
            "bash", "-c", 'printf "%s|%s" "$PLAIN_A" "${SECRET_S:-unset}"',
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value|unset")
        self.assertFalse(any("sensitive" in c for c in self.op_calls()))
        # nosens cache variant is kept separate from the full profile cache
        self.assertTrue((self.cache_dir / "testproj" / "mixed.nosens.enc").exists())


if __name__ == "__main__":
    unittest.main()

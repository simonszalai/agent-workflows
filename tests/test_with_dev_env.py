"""bin/with-dev-env: profile selection + agent-shell defaulting over the real
bin/dev-env (fake op)."""

from __future__ import annotations

import unittest

from secrets_common import ROOT, SecretsSandbox, run

BIN = str(ROOT / "bin" / "with-dev-env")

ONE_PROFILE = "\n".join([
    "dev\tmain\tPLAIN_A\top://TESTVAULT/ITEM/value\tself",
    "dev\tmain\tLIT_C\tliteral:committed-config\tself",
    "",
])
TWO_PROFILES = ONE_PROFILE + "dev\tother\tOTHER\top://TESTVAULT/OTHER/value\tself\n"
MIXED = "\n".join([
    "dev\tmain\tPLAIN_A\top://TESTVAULT/ITEM/value\tself",
    "dev\tmain\tSECRET_S\top://TESTVAULT-sensitive/SECRETX/value\tself",
    "",
])


class WithDevEnvTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.cache_dir = self.sb.root / "devenv-cache"

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(DEV_ENV_CACHE_DIR=str(self.cache_dir), **extra)

    def wde(self, *args: str, **extra: str):
        return run([BIN, "--repo", str(self.sb.repo), *args], self.env(**extra))

    def test_single_profile_is_selected_automatically_and_child_sees_values(self) -> None:
        self.sb.write_manifest(ONE_PROFILE)
        proc = self.wde("bash", "-c", 'printf "%s|%s" "$PLAIN_A" "$LIT_C"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value|committed-config")

    def test_child_exit_status_and_argv_pass_through(self) -> None:
        self.sb.write_manifest(ONE_PROFILE)
        proc = self.wde("bash", "-c", 'test "$1" = "a b" && exit 7', "_", "a b")
        self.assertEqual(proc.returncode, 7, proc.stderr)

    def test_several_profiles_need_profile_flag_or_env(self) -> None:
        self.sb.write_manifest(TWO_PROFILES)
        proc = self.wde("true")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--profile", proc.stderr)
        proc = self.wde("--profile", "other", "bash", "-c", 'printf "%s" "$OTHER"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-OTHER-value")
        proc = self.wde("bash", "-c", 'printf "%s" "$OTHER"', WITH_DEV_ENV_PROFILE="other")
        self.assertEqual(proc.stdout, "val-OTHER-value")

    def test_no_command_is_usage(self) -> None:
        self.sb.write_manifest(ONE_PROFILE)
        self.assertEqual(self.wde().returncode, 2)
        self.assertEqual(self.wde("--bogus", "true").returncode, 2)

    def test_agent_shell_defaults_to_no_sensitive(self) -> None:
        self.sb.write_manifest(MIXED)
        proc = self.wde("bash", "-c", 'printf "%s|%s" "$PLAIN_A" "${SECRET_S:-unset}"', CLAUDECODE="1")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value|unset")
        self.assertFalse(any("sensitive" in l for l in self.sb.log_lines()))

    def test_explicit_flags_disable_the_agent_default(self) -> None:
        self.sb.write_manifest(MIXED)
        # --refresh given explicitly: sensitive rows stay in; no reason -> dev-env refuses (3).
        proc = self.wde("--refresh", "true", CLAUDECODE="1")
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertIn("reason is required", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])


if __name__ == "__main__":
    unittest.main()

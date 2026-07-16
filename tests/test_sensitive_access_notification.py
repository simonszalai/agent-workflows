from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SensitiveAccessNotificationTest(unittest.TestCase):
    def _run_shim(
        self,
        *,
        reason: str | None,
        use_env_file: bool = False,
        notification_sent: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fake_op = root / "op"
            fake_op.write_text("#!/bin/sh\nprintf 'real-op-called\\n'\n")
            fake_op.chmod(0o755)
            shim = (ROOT / "bin" / "op").read_text().replace(
                'REAL_OP="/opt/homebrew/bin/op"', f'REAL_OP="{fake_op}"'
            )
            test_shim = root / "op-shim"
            test_shim.write_text(shim)
            test_shim.chmod(0o755)
            (root / "sensitive-access-notify").write_text(
                "#!/bin/sh\nprintf 'notified:%s:%s:%s\\n' \"$1\" \"$2\" \"$3\"\n"
            )
            (root / "sensitive-access-notify").chmod(0o755)
            shutil.copy2(ROOT / "bin" / "sensitive-session-cache", root)
            env = os.environ.copy()
            env["XDG_STATE_HOME"] = str(root / "state")
            env["OP_SERVICE_ACCOUNT_TOKEN"] = "test-token"
            env.pop("CONDUCTOR_SESSION_ID", None)
            if notification_sent:
                env["OP_SENSITIVE_NOTIFICATION_SENT"] = "1"
            else:
                env.pop("OP_SENSITIVE_NOTIFICATION_SENT", None)
            if reason is not None:
                env["SENSITIVE_ACCESS_REASON"] = reason
            else:
                env.pop("SENSITIVE_ACCESS_REASON", None)
                env.pop("OP_ACCESS_REASON", None)
            args = ["read", "op://TS-sensitive/PROD_POSTGRES_URL/value"]
            if use_env_file:
                env_file = root / "refs.env"
                env_file.write_text("DATABASE_URL=op://TS-sensitive/PROD_POSTGRES_URL/value\n")
                args = ["run", f"--env-file={env_file}", "--", "true"]
            return subprocess.run(
                [str(test_shim), *args],
                env=env,
                capture_output=True,
                text=True,
            )

    def test_sensitive_access_fails_before_op_without_reason(self) -> None:
        result = self._run_shim(reason=None)
        self.assertEqual(result.returncode, 3)
        self.assertIn("requires a reason", result.stderr)
        self.assertNotIn("real-op-called", result.stdout)

    def test_sensitive_access_notifies_with_reason_then_calls_op(self) -> None:
        result = self._run_shim(reason="Verify F0123 production schema")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(
            "notified:TS-sensitive:PROD_POSTGRES_URL:Verify F0123 production schema",
            result.stdout,
        )
        self.assertIn("real-op-called", result.stdout)

    def test_sensitive_env_file_requires_reason_before_op(self) -> None:
        result = self._run_shim(reason=None, use_env_file=True)
        self.assertEqual(result.returncode, 3)
        self.assertIn("requires a reason", result.stderr)
        self.assertNotIn("real-op-called", result.stdout)

    def test_sensitive_read_reuses_memory_cache_for_conductor_session(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            calls = root / "calls"
            fake_op = root / "real-op"
            fake_op.write_text(
                f"#!/bin/sh\necho called >> '{calls}'\nprintf 'resolved-value'\n"
            )
            fake_op.chmod(0o755)
            shim = (ROOT / "bin" / "op").read_text().replace(
                'REAL_OP="/opt/homebrew/bin/op"', f'REAL_OP="{fake_op}"'
            )
            test_shim = root / "op-shim"
            test_shim.write_text(shim)
            test_shim.chmod(0o755)
            notify_log = root / "notifications"
            (root / "sensitive-access-notify").write_text(
                f"#!/bin/sh\necho notified >> '{notify_log}'\n"
            )
            (root / "sensitive-access-notify").chmod(0o755)
            shutil.copy2(ROOT / "bin" / "sensitive-session-cache", root)

            env = os.environ.copy()
            env.update(
                {
                    "CONDUCTOR_SESSION_ID": "test-session-reuse",
                    "SENSITIVE_ACCESS_REASON": "Deploy E0003 staging config",
                    "OP_SERVICE_ACCOUNT_TOKEN": "test-token",
                    "TMPDIR": str(root),
                    "XDG_STATE_HOME": str(root / "state"),
                }
            )
            # read.sh/op_human places the global --account flag before `read`.
            args = [
                str(test_shim),
                "--account",
                "test-account",
                "read",
                "--no-newline",
                "op://AMARU-sensitive/RENDER/value",
            ]
            first = subprocess.run(args, env=env, capture_output=True, text=True)
            second = subprocess.run(args, env=env, capture_output=True, text=True)
            subprocess.run(
                [str(root / "sensitive-session-cache"), "stop", "unused"],
                env=env,
                capture_output=True,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first.stdout, "resolved-value")
            self.assertEqual(second.stdout, "resolved-value")
            self.assertEqual(calls.read_text().splitlines(), ["called"])
            self.assertEqual(notify_log.read_text().splitlines(), ["notified"])

    def test_notification_bypass_flag_is_ignored_on_cache_miss(self) -> None:
        result = self._run_shim(
            reason="Deploy E0003 staging config", notification_sent=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("notified:", result.stdout)


if __name__ == "__main__":
    unittest.main()

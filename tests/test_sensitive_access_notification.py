from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SensitiveAccessNotificationTest(unittest.TestCase):
    def _run_shim(
        self, *, reason: str | None, use_env_file: bool = False
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
            env = os.environ.copy()
            env["XDG_STATE_HOME"] = str(root / "state")
            env["OP_SERVICE_ACCOUNT_TOKEN"] = "test-token"
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


if __name__ == "__main__":
    unittest.main()

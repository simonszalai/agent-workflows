from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CANONICAL_ACCOUNT = "SVKNULWI3VCHVHQ77S27TZQLAY"
CREDENTIALS = {
    "OP_SERVICE_ACCOUNT_TOKEN": "SENTINEL_SERVICE_ACCOUNT_7f6d",
    "OP_CONNECT_HOST": "SENTINEL_CONNECT_HOST_8a2c",
    "OP_CONNECT_TOKEN": "SENTINEL_CONNECT_TOKEN_091b",
    "OP_SESSION_primary": "SENTINEL_SESSION_PRIMARY_31ce",
    "OP_SESSION_SECONDARY_9": "SENTINEL_SESSION_SECONDARY_d8a4",
}
KEYCHAIN_SENTINEL = "SENTINEL_KEYCHAIN_TOKEN_b662"
SECRET_SENTINELS = (*CREDENTIALS.values(), KEYCHAIN_SENTINEL)


class SensitiveAccessFixture:
    """Private fake-only installation of op, op-env, notifier, and security."""

    def __init__(self) -> None:
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self._temporary_directory.name)
        self.bin_dir = self.root / "bin"
        self.fake_path = self.root / "fake-path"
        self.state_dir = self.root / "state"
        self.home = self.root / "home"
        self.events_path = self.root / "events"
        self.auth_calls_path = self.root / "auth-calls.jsonl"
        self.child_calls_path = self.root / "child-calls.jsonl"
        self.notify_calls_path = self.root / "notify-calls.jsonl"
        self.cache_calls_path = self.root / "cache-calls.jsonl"
        self.security_calls_path = self.root / "security-calls.jsonl"
        self.helper_calls_path = self.root / "helper-calls.jsonl"
        self.audit_path = self.state_dir / "op-audit.log"
        self.account_config = self.bin_dir / "op-human-account"
        self.real_op = self.root / "real-op"
        self.op = self.bin_dir / "op"
        self.op_env = self.bin_dir / "op-env"

        self.bin_dir.mkdir()
        self.fake_path.mkdir()
        self.home.mkdir()
        self.write_account_config(CANONICAL_ACCOUNT + "\n")
        self._write_fake_real_op()
        self._write_fake_notifier()
        self._write_fake_security()
        self._write_fake_helpers()
        self._copy_scripts()

        self.base_env = os.environ.copy()
        self.base_env.update(
            {
                "HOME": str(self.home),
                "TMPDIR": str(self.root),
                "XDG_STATE_HOME": str(self.state_dir),
                "PATH": f"{self.fake_path}:{self.base_env.get('PATH', '')}",
                "FAKE_EVENTS": str(self.events_path),
                "FAKE_AUTH_CALLS": str(self.auth_calls_path),
                "FAKE_CHILD_CALLS": str(self.child_calls_path),
                "FAKE_NOTIFY_CALLS": str(self.notify_calls_path),
                "FAKE_CACHE_CALLS": str(self.cache_calls_path),
                "FAKE_SECURITY_CALLS": str(self.security_calls_path),
                "FAKE_HELPER_CALLS": str(self.helper_calls_path),
                "FAKE_SECURITY_VALUE": KEYCHAIN_SENTINEL,
                "FAKE_SIGNIN_DELAY": "0.75",
            }
        )
        for name in tuple(self.base_env):
            if name in {
                "SENSITIVE_ACCESS_REASON",
                "OP_ACCESS_REASON",
                "OP_DESKTOP",
                "OP_SENSITIVE_NOTIFICATION_SENT",
                "OP_HUMAN_ACCOUNT",
                "OP_BIN",
                "OP_REAL_BIN",
                "CONDUCTOR_SESSION_ID",
            } or name in CREDENTIALS or name.startswith("OP_SESSION_"):
                self.base_env.pop(name, None)
        self.base_env["OP_REAL_BIN"] = str(self.real_op)

    def close(self) -> None:
        self._temporary_directory.cleanup()

    def __enter__(self) -> SensitiveAccessFixture:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _copy_scripts(self) -> None:
        # The silent service-account fallback resolves the owning project's
        # Keychain item from the canonical registry next to bin/.
        config_dir = self.root / "config"
        config_dir.mkdir(exist_ok=True)
        shutil.copy2(
            ROOT / "config" / "project-tools.json", config_dir / "project-tools.json"
        )
        shutil.copy2(ROOT / "bin" / "op", self.op)
        self.op.chmod(0o755)
        shutil.copy2(ROOT / "bin" / "op-env", self.op_env)
        self.op_env.chmod(0o755)
        real_cache = self.bin_dir / "sensitive-session-cache-real"
        shutil.copy2(ROOT / "bin" / "sensitive-session-cache", real_cache)
        cache = self.bin_dir / "sensitive-session-cache"
        cache.write_text(
            textwrap.dedent(
                f"""\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                credential_names = sorted(
                    name
                    for name in os.environ
                    if name in {{
                        "OP_SERVICE_ACCOUNT_TOKEN",
                        "OP_CONNECT_HOST",
                        "OP_CONNECT_TOKEN",
                    }}
                    or name.startswith("OP_SESSION_")
                )
                with open(os.environ["FAKE_CACHE_CALLS"], "a") as ledger:
                    ledger.write(
                        json.dumps(
                            {{"argv": sys.argv[1:], "env_present": credential_names}},
                            sort_keys=True,
                        )
                        + "\\n"
                    )
                os.execv({str(real_cache)!r}, [{str(real_cache)!r}, *sys.argv[1:]])
                """
            )
        )
        cache.chmod(0o755)

    def _write_fake_real_op(self) -> None:
        self.real_op.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys
                import time

                credential_names = sorted(
                    name
                    for name in os.environ
                    if name in {
                        "OP_SERVICE_ACCOUNT_TOKEN",
                        "OP_CONNECT_HOST",
                        "OP_CONNECT_TOKEN",
                        "OP_DESKTOP",
                    }
                    or name.startswith("OP_SESSION_")
                )
                record = {
                    "argv": sys.argv[1:],
                    "env_present": credential_names,
                }
                if len(sys.argv) > 1 and sys.argv[1] == "signin":
                    with open(os.environ["FAKE_EVENTS"], "a") as ledger:
                        ledger.write("auth\\n")
                    with open(os.environ["FAKE_AUTH_CALLS"], "a") as ledger:
                        ledger.write(json.dumps(record, sort_keys=True) + "\\n")
                    time.sleep(float(os.environ.get("FAKE_SIGNIN_DELAY", "0")))
                    raise SystemExit(int(os.environ.get("FAKE_SIGNIN_EXIT", "0")))

                with open(os.environ["FAKE_EVENTS"], "a") as ledger:
                    ledger.write("real\\n")
                with open(os.environ["FAKE_CHILD_CALLS"], "a") as ledger:
                    ledger.write(json.dumps(record, sort_keys=True) + "\\n")
                sys.stdout.write("resolved-value")
                """
            )
        )
        self.real_op.chmod(0o755)

    def _write_fake_notifier(self) -> None:
        notifier = self.bin_dir / "sensitive-access-notify"
        notifier.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                with open(os.environ["FAKE_EVENTS"], "a") as ledger:
                    ledger.write("notify\\n")
                credential_names = sorted(
                    name
                    for name in os.environ
                    if name in {
                        "OP_SERVICE_ACCOUNT_TOKEN",
                        "OP_CONNECT_HOST",
                        "OP_CONNECT_TOKEN",
                    }
                    or name.startswith("OP_SESSION_")
                )
                with open(os.environ["FAKE_NOTIFY_CALLS"], "a") as ledger:
                    ledger.write(
                        json.dumps(
                            {"argv": sys.argv[1:], "env_present": credential_names},
                            sort_keys=True,
                        )
                        + "\\n"
                    )
                raise SystemExit(int(os.environ.get("FAKE_NOTIFIER_EXIT", "0")))
                """
            )
        )
        notifier.chmod(0o755)

    def _write_fake_security(self) -> None:
        security = self.fake_path / "security"
        security.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                import sys

                with open(os.environ["FAKE_EVENTS"], "a") as ledger:
                    ledger.write("security\\n")
                with open(os.environ["FAKE_SECURITY_CALLS"], "a") as ledger:
                    ledger.write(json.dumps({"argv": sys.argv[1:]}, sort_keys=True) + "\\n")
                sys.stdout.write(os.environ["FAKE_SECURITY_VALUE"])
                """
            )
        )
        security.chmod(0o755)

    def _write_fake_helpers(self) -> None:
        helper_source = textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import sys

            helper = os.path.basename(sys.argv[0])
            credential_names = sorted(
                name
                for name in os.environ
                if name in {
                    "OP_SERVICE_ACCOUNT_TOKEN",
                    "OP_CONNECT_HOST",
                    "OP_CONNECT_TOKEN",
                }
                or name.startswith("OP_SESSION_")
            )
            with open(os.environ["FAKE_HELPER_CALLS"], "a") as ledger:
                ledger.write(
                    json.dumps(
                        {"helper": helper, "env_present": credential_names},
                        sort_keys=True,
                    )
                    + "\\n"
                )
            if helper == "mkdir":
                os.execv("/bin/mkdir", ["/bin/mkdir", *sys.argv[1:]])
            raise SystemExit(99)
            """
        )
        for helper in ("grep", "mkdir"):
            path = self.fake_path / helper
            path.write_text(helper_source)
            path.chmod(0o755)

    def write_account_config(self, content: str, mode: int = 0o644) -> None:
        self.account_config.write_text(content)
        self.account_config.chmod(mode)

    def remove_account_config(self) -> None:
        self.account_config.unlink(missing_ok=True)

    def set_notifier(self, state: str) -> None:
        notifier = self.bin_dir / "sensitive-access-notify"
        if state == "missing":
            notifier.unlink(missing_ok=True)
        elif state == "non-executable":
            notifier.chmod(stat.S_IRUSR | stat.S_IWUSR)
        elif state == "non-regular":
            notifier.unlink()
            notifier.mkdir()
        elif state == "symlink-to-true":
            notifier.unlink()
            notifier.symlink_to("/usr/bin/true")
        elif state == "group-writable":
            notifier.chmod(0o775)
        elif state == "other-writable":
            notifier.chmod(0o757)
        elif state != "executable":
            raise ValueError(f"unknown notifier state: {state}")

    def env(
        self,
        *,
        reason: str | None = "Apply the reviewed sensitive fixture",
        credentials: bool = False,
        **updates: str,
    ) -> dict[str, str]:
        env = self.base_env.copy()
        if reason is not None:
            env["SENSITIVE_ACCESS_REASON"] = reason
        if credentials:
            env.update(CREDENTIALS)
        env.update(updates)
        return env

    def run_op(
        self,
        args: list[str],
        *,
        reason: str | None = "Apply the reviewed sensitive fixture",
        credentials: bool = False,
        env_updates: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        env = self.env(reason=reason, credentials=credentials, **(env_updates or {}))
        return subprocess.run(
            [str(self.op), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def run_op_env(
        self,
        env_file: Path,
        *,
        reason: str | None = "Apply the reviewed sensitive fixture",
        credentials: bool = False,
        env_updates: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        updates = {
            "OP_BIN": str(self.op),
            "ENV_FILE": str(env_file),
            **(env_updates or {}),
        }
        env = self.env(reason=reason, credentials=credentials, **updates)
        return subprocess.run(
            [str(self.op_env), "fixture-command", "--fixture-argument"],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def make_env_file(self, *, sensitive: bool) -> Path:
        path = self.root / ("sensitive.env" if sensitive else "ordinary.env")
        vault = "AUTODEV-sensitive" if sensitive else "TS"
        path.write_text(f'DATABASE_URL="op://{vault}/DATABASE_URL/value"\n')
        return path

    def stop_cache(self, env: dict[str, str]) -> None:
        env = env.copy()
        for name in tuple(env):
            if name in CREDENTIALS or name.startswith("OP_SESSION_"):
                env.pop(name, None)
        subprocess.run(
            [str(self.bin_dir / "sensitive-session-cache"), "stop", "unused"],
            env=env,
            capture_output=True,
            timeout=10,
        )

    @staticmethod
    def _json_lines(path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    @property
    def events(self) -> list[str]:
        if not self.events_path.exists():
            return []
        return self.events_path.read_text().splitlines()

    @property
    def child_calls(self) -> list[dict[str, object]]:
        return self._json_lines(self.child_calls_path)

    @property
    def auth_calls(self) -> list[dict[str, object]]:
        return self._json_lines(self.auth_calls_path)

    @property
    def notify_calls(self) -> list[dict[str, object]]:
        return self._json_lines(self.notify_calls_path)

    @property
    def cache_calls(self) -> list[dict[str, object]]:
        return self._json_lines(self.cache_calls_path)

    @property
    def security_calls(self) -> list[dict[str, object]]:
        return self._json_lines(self.security_calls_path)

    @property
    def helper_calls(self) -> list[dict[str, object]]:
        return self._json_lines(self.helper_calls_path)

    @property
    def audit(self) -> str:
        return self.audit_path.read_text() if self.audit_path.exists() else ""

    def persisted_observables(self) -> str:
        paths = (
            self.events_path,
            self.auth_calls_path,
            self.child_calls_path,
            self.notify_calls_path,
            self.cache_calls_path,
            self.security_calls_path,
            self.helper_calls_path,
            self.audit_path,
        )
        return "\n".join(path.read_text() for path in paths if path.exists())


class SensitiveAccessNotificationTest(unittest.TestCase):
    def test_no_other_binary_owns_sensitive_access_notifications(self) -> None:
        canonical_owners = {"op", "sensitive-access-notify"}
        forbidden_markers = (
            "SENSITIVE_NOTIFY_BIN",
            "notify_sensitive_access",
            "OP_SENSITIVE_NOTIFICATION_SENT",
            "osascript",
            "display notification",
        )

        for path in sorted((ROOT / "bin").iterdir()):
            if not path.is_file() or path.name in canonical_owners:
                continue
            contents = path.read_text(errors="ignore")
            for marker in forbidden_markers:
                self.assertNotIn(marker, contents, f"{path.name} duplicates {marker}")

    def assert_no_secret_sentinels(
        self,
        fixture: SensitiveAccessFixture,
        *results: subprocess.CompletedProcess[str],
    ) -> None:
        observable = fixture.persisted_observables()
        for result in results:
            observable += result.stdout + result.stderr
        for sentinel in SECRET_SENTINELS:
            self.assertNotIn(sentinel, observable)

    def test_checked_in_account_config_is_exact_data_only_non_secret_input(self) -> None:
        account_config = ROOT / "bin" / "op-human-account"

        self.assertTrue(account_config.is_file())
        self.assertFalse(account_config.is_symlink())
        self.assertEqual(account_config.read_bytes(), (CANONICAL_ACCOUNT + "\n").encode())
        self.assertEqual(stat.S_IMODE(account_config.stat().st_mode), 0o644)

    def test_op_resolves_first_path_binary_after_skipping_itself(self) -> None:
        with SensitiveAccessFixture() as fixture:
            path_op = fixture.fake_path / "op"
            shutil.copy2(fixture.real_op, path_op)
            result = fixture.run_op(
                ["item", "list"],
                credentials=True,
                env_updates={
                    "OP_REAL_BIN": "",
                    "PATH": (
                        f"{fixture.bin_dir}:{fixture.fake_path}:"
                        f"{fixture.base_env.get('PATH', '')}"
                    ),
                },
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.events, ["real"])
            self.assertEqual(fixture.child_calls[0]["argv"], ["item", "list"])

    def test_op_rejects_override_that_points_back_to_shim(self) -> None:
        with SensitiveAccessFixture() as fixture:
            result = fixture.run_op(
                ["item", "list"],
                credentials=True,
                env_updates={"OP_REAL_BIN": str(fixture.op)},
            )

            self.assertEqual(result.returncode, 127)
            self.assertIn("not the op audit shim", result.stderr)
            self.assertEqual(fixture.events, [])
            self.assertEqual(fixture.child_calls, [])

    def assert_sensitive_child(
        self,
        fixture: SensitiveAccessFixture,
        result: subprocess.CompletedProcess[str],
        expected_argv: list[str],
    ) -> None:
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(fixture.events, ["auth", "notify", "real"])
        if expected_argv[0] == "--account":
            expected_account = expected_argv[1]
        else:
            expected_account = expected_argv[0].removeprefix("--account=")
        self.assertEqual(
            fixture.auth_calls,
            [
                {
                    "argv": ["signin", "--account", expected_account],
                    "env_present": [],
                }
            ],
        )
        self.assertEqual(len(fixture.notify_calls), 1)
        self.assertEqual(fixture.notify_calls[0]["env_present"], [])
        self.assertEqual(
            fixture.child_calls,
            [{"argv": expected_argv, "env_present": []}],
        )
        self.assertEqual(fixture.security_calls, [])
        self.assert_no_secret_sentinels(fixture, result)

    def test_every_sensitive_detection_form_uses_the_fake_desktop_contract(self) -> None:
        cases: list[tuple[str, list[str], bool]] = [
            (
                "direct-ref",
                ["read", "op://AUTODEV-sensitive/DATABASE_URL/value"],
                False,
            ),
            (
                "vault-space",
                ["vault", "get", "--vault", "AUTODEV-sensitive"],
                False,
            ),
            (
                "vault-equals",
                ["vault", "get", "--vault=AUTODEV-sensitive"],
                False,
            ),
            ("env-file-space", ["run", "--env-file", "{env}", "--", "true"], True),
            ("env-file-equals", ["run", "--env-file={env}", "--", "true"], True),
            (
                "item-list",
                ["item", "list", "--vault", "AUTODEV-sensitive"],
                False,
            ),
            (
                "item-create",
                ["item", "create", "fixture", "--vault=AUTODEV-sensitive"],
                False,
            ),
            (
                "positional-over-detection",
                ["item", "list", "unrelated-sensitive"],
                False,
            ),
        ]
        for name, template, needs_env_file in cases:
            with self.subTest(name=name), SensitiveAccessFixture() as fixture:
                env_file = fixture.make_env_file(sensitive=True)
                args = [
                    part.replace("{env}", str(env_file)) if needs_env_file else part
                    for part in template
                ]
                result = fixture.run_op(args, credentials=True)
                self.assert_sensitive_child(
                    fixture,
                    result,
                    ["--account", CANONICAL_ACCOUNT, *args],
                )

    def test_value_free_hint_routes_stdin_only_command_through_sensitive_gate(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["inject"]
            result = fixture.run_op(
                args,
                credentials=True,
                env_updates={
                    "OP_SENSITIVE_VAULT_HINT": "AUTODEV-sensitive",
                    "OP_SENSITIVE_ITEM_HINT": "template-inject",
                },
            )

            self.assert_sensitive_child(
                fixture,
                result,
                ["--account", CANONICAL_ACCOUNT, *args],
            )
            self.assertEqual(
                fixture.notify_calls[0]["argv"][:2],
                ["AUTODEV-sensitive", "template-inject"],
            )

    def test_invalid_value_free_hint_blocks_before_auth_notification_and_child(self) -> None:
        with SensitiveAccessFixture() as fixture:
            result = fixture.run_op(
                ["inject"],
                credentials=True,
                env_updates={"OP_SENSITIVE_VAULT_HINT": "AUTODEV"},
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("invalid OP_SENSITIVE_VAULT_HINT", result.stderr)
            self.assertEqual(fixture.events, [])
            self.assertEqual(fixture.notify_calls, [])
            self.assertEqual(fixture.child_calls, [])

    def test_ordinary_reference_keeps_the_inherited_service_account_path(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["read", "op://TS/DATABASE_URL/value"]
            result = fixture.run_op(args, reason=None, credentials=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.events, ["real"])
            self.assertEqual(fixture.notify_calls, [])
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(
                fixture.child_calls,
                [{"argv": args, "env_present": sorted(CREDENTIALS)}],
            )
            self.assert_no_secret_sentinels(fixture, result)

    def test_regular_vault_read_uses_the_owning_project_keychain_item(self) -> None:
        expected_items = {
            "AMARU": "op-amaru-token",
            "AUTODEV": "op-autodev-token",
            "TS": "op-ts-token",
            "WORKFLOW_PRO": "op-workflow-pro-token",
        }
        for vault, keychain_item in expected_items.items():
            with self.subTest(vault=vault), SensitiveAccessFixture() as fixture:
                args = ["read", f"op://{vault}/Postgres staging/owner"]
                result = fixture.run_op(args, reason=None, credentials=False)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(fixture.events, ["security", "real"])
                self.assertEqual(
                    fixture.security_calls,
                    [{"argv": ["find-generic-password", "-s", keychain_item, "-a", "simon", "-w"]}],
                )
                self.assertEqual(
                    fixture.child_calls,
                    [{"argv": args, "env_present": ["OP_SERVICE_ACCOUNT_TOKEN"]}],
                )
                self.assertNotIn("BIOMETRIC-PROMPT", fixture.audit)
                self.assertIn("service-account(keychain)", fixture.audit)
                self.assert_no_secret_sentinels(fixture, result)

    def test_vault_operation_flag_resolves_the_same_owning_project_token(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["item", "list", "--vault", "WORKFLOW_PRO"]
            result = fixture.run_op(args, reason=None, credentials=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                fixture.security_calls,
                [
                    {
                        "argv": [
                            "find-generic-password",
                            "-s",
                            "op-workflow-pro-token",
                            "-a",
                            "simon",
                            "-w",
                        ]
                    }
                ],
            )
            self.assert_no_secret_sentinels(fixture, result)

    def test_unregistered_vault_fails_closed_before_any_credential_or_prompt(
        self,
    ) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["read", "op://UNREGISTERED/Item/value"]
            result = fixture.run_op(args, reason=None, credentials=False)

            self.assertEqual(result.returncode, 5)
            self.assertIn("has no project in config/project-tools.json", result.stderr)
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(fixture.events, [])
            self.assertEqual(fixture.child_calls, [])
            self.assertIn("status=BLOCKED unregistered-vault", fixture.audit)
            self.assert_no_secret_sentinels(fixture, result)

    def test_registered_vault_without_stored_token_fails_closed(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["read", "op://AUTODEV/Postgres prod RO/canonical"]
            result = fixture.run_op(
                args,
                reason=None,
                credentials=False,
                env_updates={"FAKE_SECURITY_VALUE": ""},
            )

            self.assertEqual(result.returncode, 6)
            self.assertIn("no service-account token", result.stderr)
            self.assertIn("op-autodev-token", result.stderr)
            self.assertEqual(fixture.child_calls, [])
            self.assertIn("status=BLOCKED missing-service-account-token", fixture.audit)
            self.assert_no_secret_sentinels(fixture, result)

    def test_op_env_unregistered_vault_fails_closed_without_reading_via_helpers(
        self,
    ) -> None:
        with SensitiveAccessFixture() as fixture:
            env_file = fixture.root / "unregistered.env"
            env_file.write_text('DATABASE_URL="op://UNREGISTERED/DATABASE_URL/value"\n')
            result = fixture.run_op_env(env_file, credentials=False)

            self.assertEqual(result.returncode, 5)
            self.assertIn("no single registered owner", result.stderr)
            self.assertIn("UNREGISTERED", result.stderr)
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(fixture.child_calls, [])
            self.assertEqual(fixture.helper_calls, [])
            self.assert_no_secret_sentinels(fixture, result)

    def test_command_without_a_vault_keeps_its_existing_behavior(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["--version"]
            result = fixture.run_op(args, reason=None, credentials=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(fixture.child_calls, [{"argv": args, "env_present": []}])
            self.assert_no_secret_sentinels(fixture, result)

    def test_regular_vault_can_request_canonical_human_without_notification(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["item", "list", "--vault", "TS"]
            result = fixture.run_op(
                args,
                reason=None,
                credentials=True,
                env_updates={"OP_USE_CANONICAL_HUMAN_ACCOUNT": "1"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.events, ["real"])
            self.assertEqual(fixture.notify_calls, [])
            self.assertEqual(fixture.auth_calls, [])
            self.assertEqual(
                fixture.child_calls,
                [
                    {
                        "argv": ["--account", CANONICAL_ACCOUNT, *args],
                        "env_present": [],
                    }
                ],
            )

    def test_regular_vault_canonical_human_request_fails_closed(self) -> None:
        cases = (
            ("invalid-flag", "unexpected", 2),
            ("missing-account-config", "1", 4),
        )
        for name, flag, expected_status in cases:
            with self.subTest(name=name), SensitiveAccessFixture() as fixture:
                if name == "missing-account-config":
                    fixture.remove_account_config()
                result = fixture.run_op(
                    ["item", "list", "--vault", "TS"],
                    reason=None,
                    credentials=True,
                    env_updates={"OP_USE_CANONICAL_HUMAN_ACCOUNT": flag},
                )

                self.assertEqual(result.returncode, expected_status)
                self.assertEqual(fixture.events, [])
                self.assertEqual(fixture.notify_calls, [])
                self.assertEqual(fixture.child_calls, [])

    def test_missing_reason_blocks_before_notification_auth_and_child(self) -> None:
        with SensitiveAccessFixture() as fixture:
            result = fixture.run_op(
                ["read", "op://AUTODEV-sensitive/ITEM/value"],
                reason=None,
                credentials=True,
            )

            self.assertEqual(result.returncode, 3)
            self.assertIn("requires a reason", result.stderr)
            self.assertIn("status=BLOCKED", fixture.audit)
            self.assertEqual(fixture.events, [])
            self.assertEqual(fixture.notify_calls, [])
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(fixture.child_calls, [])
            self.assert_no_secret_sentinels(fixture, result)

    def test_whitespace_only_reason_forms_block_before_notification_and_child(self) -> None:
        cases = (
            ("primary", " \t\n", {}),
            ("fallback", None, {"OP_ACCESS_REASON": "\r\n\t"}),
        )
        for name, reason, env_updates in cases:
            with self.subTest(name=name), SensitiveAccessFixture() as fixture:
                result = fixture.run_op(
                    ["read", "op://AUTODEV-sensitive/ITEM/value"],
                    reason=reason,
                    credentials=True,
                    env_updates=env_updates,
                )

                self.assertEqual(result.returncode, 3)
                self.assertIn("requires a reason", result.stderr)
                self.assertEqual(fixture.events, [])
                self.assertEqual(fixture.notify_calls, [])
                self.assertEqual(fixture.security_calls, [])
                self.assertEqual(fixture.child_calls, [])
                self.assert_no_secret_sentinels(fixture, result)

    def test_every_notifier_failure_blocks_before_sensitive_child(self) -> None:
        cases = (
            ("missing", None),
            ("non-executable", None),
            ("non-regular", None),
            ("symlink-to-true", None),
            ("group-writable", None),
            ("other-writable", None),
            ("executable", 1),
            ("executable", 126),
            ("executable", 127),
        )
        for notifier_state, exit_code in cases:
            with (
                self.subTest(state=notifier_state, exit_code=exit_code),
                SensitiveAccessFixture() as fixture,
            ):
                fixture.set_notifier(notifier_state)
                env_updates = (
                    {"FAKE_NOTIFIER_EXIT": str(exit_code)}
                    if exit_code is not None
                    else None
                )
                result = fixture.run_op(
                    ["read", "op://AUTODEV-sensitive/ITEM/value"],
                    credentials=True,
                    env_updates=env_updates,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("status=BLOCKED", fixture.audit)
                expected_events = ["auth", "notify"] if exit_code is not None else []
                self.assertEqual(fixture.events, expected_events)
                if exit_code is not None:
                    self.assertEqual(fixture.notify_calls[0]["env_present"], [])
                self.assertEqual(fixture.security_calls, [])
                self.assertEqual(fixture.child_calls, [])
                self.assert_no_secret_sentinels(fixture, result)

    def test_child_account_after_delimiter_does_not_select_the_op_account(self) -> None:
        with SensitiveAccessFixture() as fixture:
            env_file = fixture.make_env_file(sensitive=True)
            args = [
                "run",
                f"--env-file={env_file}",
                "--",
                "fixture-command",
                "--account",
                "child-account",
            ]
            result = fixture.run_op(args, credentials=True)

            self.assert_sensitive_child(
                fixture,
                result,
                ["--account", CANONICAL_ACCOUNT, *args],
            )

    def test_child_read_after_delimiter_is_not_a_cacheable_op_read(self) -> None:
        with SensitiveAccessFixture() as fixture:
            env_file = fixture.make_env_file(sensitive=True)
            args = [
                "run",
                f"--env-file={env_file}",
                "--",
                "fixture-command",
                "read",
            ]
            env = fixture.env(
                credentials=True,
                CONDUCTOR_SESSION_ID="fixture-child-read-session",
            )
            command = [str(fixture.op), *args]
            first = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            second = subprocess.run(
                command,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(
                fixture.events,
                ["auth", "notify", "real", "auth", "notify", "real"],
            )
            self.assertEqual(len(fixture.notify_calls), 2)
            self.assertTrue(
                all(call["env_present"] == [] for call in fixture.notify_calls)
            )
            self.assertEqual(
                fixture.child_calls,
                [
                    {
                        "argv": ["--account", CANONICAL_ACCOUNT, *args],
                        "env_present": [],
                    },
                    {
                        "argv": ["--account", CANONICAL_ACCOUNT, *args],
                        "env_present": [],
                    },
                ],
            )
            self.assertEqual(fixture.cache_calls, [])
            self.assert_no_secret_sentinels(fixture, first, second)

    def test_success_notifies_before_child_and_scrubs_every_machine_credential(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["item", "list", "--vault", "AUTODEV-sensitive"]
            result = fixture.run_op(args, credentials=True)

            self.assert_sensitive_child(
                fixture,
                result,
                ["--account", CANONICAL_ACCOUNT, *args],
            )
            self.assertEqual(
                fixture.notify_calls[0]["argv"][:3],
                [
                    "AUTODEV-sensitive",
                    "vault operation",
                    "Apply the reviewed sensitive fixture",
                ],
            )
            self.assertIn("auth=interactive BIOMETRIC-PROMPT", fixture.audit)

    def test_already_authenticated_preflight_suppresses_notification(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["item", "list", "--vault", "AUTODEV-sensitive"]
            result = fixture.run_op(
                args,
                credentials=True,
                env_updates={"FAKE_SIGNIN_DELAY": "0"},
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.events, ["auth", "real"])
            self.assertEqual(fixture.notify_calls, [])
            self.assertEqual(
                fixture.auth_calls,
                [
                    {
                        "argv": ["signin", "--account", CANONICAL_ACCOUNT],
                        "env_present": [],
                    }
                ],
            )
            self.assertEqual(
                fixture.child_calls,
                [
                    {
                        "argv": ["--account", CANONICAL_ACCOUNT, *args],
                        "env_present": [],
                    }
                ],
            )
            self.assertIn("auth=interactive desktop-session(silent)", fixture.audit)
            self.assert_no_secret_sentinels(fixture, result)

    def test_failed_authentication_blocks_sensitive_child(self) -> None:
        with SensitiveAccessFixture() as fixture:
            result = fixture.run_op(
                ["read", "op://AUTODEV-sensitive/ITEM/value"],
                credentials=True,
                env_updates={"FAKE_SIGNIN_EXIT": "17"},
            )

            self.assertEqual(result.returncode, 17)
            self.assertIn("authentication failed", result.stderr)
            self.assertIn("status=BLOCKED", fixture.audit)
            self.assertEqual(fixture.events, ["auth", "notify"])
            self.assertEqual(fixture.child_calls, [])
            self.assertEqual(fixture.security_calls, [])
            self.assert_no_secret_sentinels(fixture, result)

    def test_sensitive_classification_scrubs_before_helpers_and_never_calls_grep(
        self,
    ) -> None:
        for entrypoint in ("op", "op-env"):
            with self.subTest(entrypoint=entrypoint), SensitiveAccessFixture() as fixture:
                env_file = fixture.make_env_file(sensitive=True)
                if entrypoint == "op":
                    result = fixture.run_op(
                        ["run", f"--env-file={env_file}", "--", "fixture-command"],
                        credentials=True,
                    )
                else:
                    result = fixture.run_op_env(env_file, credentials=True)

                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn(
                    "grep",
                    [call["helper"] for call in fixture.helper_calls],
                )
                self.assertIn(
                    "mkdir",
                    [call["helper"] for call in fixture.helper_calls],
                )
                self.assertTrue(
                    all(call["env_present"] == [] for call in fixture.helper_calls)
                )
                self.assert_no_secret_sentinels(fixture, result)

    def test_canonical_account_is_added_once_and_explicit_selectors_are_exact(self) -> None:
        cases = (
            (
                "canonical",
                ["read", "op://AUTODEV-sensitive/ITEM/value"],
                [
                    "--account",
                    CANONICAL_ACCOUNT,
                    "read",
                    "op://AUTODEV-sensitive/ITEM/value",
                ],
            ),
            (
                "explicit-space",
                [
                    "--account",
                    "fixture-explicit-account",
                    "read",
                    "op://AUTODEV-sensitive/ITEM/value",
                ],
                [
                    "--account",
                    "fixture-explicit-account",
                    "read",
                    "op://AUTODEV-sensitive/ITEM/value",
                ],
            ),
            (
                "explicit-equals",
                [
                    "--account=fixture-explicit-account",
                    "read",
                    "op://AUTODEV-sensitive/ITEM/value",
                ],
                [
                    "--account=fixture-explicit-account",
                    "read",
                    "op://AUTODEV-sensitive/ITEM/value",
                ],
            ),
        )
        for name, args, expected in cases:
            with self.subTest(name=name), SensitiveAccessFixture() as fixture:
                result = fixture.run_op(args, credentials=True)
                self.assert_sensitive_child(fixture, result, expected)

    def test_ambient_account_override_cannot_replace_the_checked_in_selector(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["read", "op://AUTODEV-sensitive/ITEM/value"]
            result = fixture.run_op(
                args,
                credentials=True,
                env_updates={"OP_HUMAN_ACCOUNT": "ambient-override"},
            )
            self.assert_sensitive_child(
                fixture,
                result,
                ["--account", CANONICAL_ACCOUNT, *args],
            )

    def test_invalid_shared_account_config_fails_closed_before_notifier_auth_or_child(
        self,
    ) -> None:
        cases: tuple[tuple[str, str | None, int], ...] = (
            ("missing", None, 0o644),
            ("unreadable", CANONICAL_ACCOUNT + "\n", 0o000),
            ("owner-only", CANONICAL_ACCOUNT + "\n", 0o600),
            ("group-writable", CANONICAL_ACCOUNT + "\n", 0o664),
            ("other-writable", CANONICAL_ACCOUNT + "\n", 0o646),
            ("empty", "", 0o644),
            (
                "shell-syntax",
                f"OP_HUMAN_ACCOUNT={CANONICAL_ACCOUNT}\n",
                0o644,
            ),
            ("malformed-identifier", "not-a-valid-account\n", 0o644),
            ("missing-final-newline", CANONICAL_ACCOUNT, 0o644),
        )
        for name, content, mode in cases:
            with self.subTest(name=name), SensitiveAccessFixture() as fixture:
                if content is None:
                    fixture.remove_account_config()
                else:
                    fixture.write_account_config(content, mode)
                result = fixture.run_op(
                    ["read", "op://AUTODEV-sensitive/ITEM/value"],
                    credentials=True,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("account", result.stderr.lower())
                self.assertIn("status=BLOCKED", fixture.audit)
                self.assertEqual(fixture.events, [])
                self.assertEqual(fixture.notify_calls, [])
                self.assertEqual(fixture.security_calls, [])
                self.assertEqual(fixture.child_calls, [])
                self.assert_no_secret_sentinels(fixture, result)

    def test_op_env_sensitive_file_skips_keychain_scrubs_credentials_and_uses_shared_account(
        self,
    ) -> None:
        for credentials in (False, True):
            with (
                self.subTest(inherited_credentials=credentials),
                SensitiveAccessFixture() as fixture,
            ):
                env_file = fixture.make_env_file(sensitive=True)
                result = fixture.run_op_env(
                    env_file,
                    credentials=credentials,
                    env_updates={"OP_HUMAN_ACCOUNT": "ambient-override"},
                )

                self.assert_sensitive_child(
                    fixture,
                    result,
                    [
                        "--account",
                        CANONICAL_ACCOUNT,
                        "run",
                        f"--env-file={env_file}",
                        "--",
                        "fixture-command",
                        "--fixture-argument",
                    ],
                )

    def test_op_env_delegates_selector_validation_to_op_before_notification(
        self,
    ) -> None:
        with SensitiveAccessFixture() as fixture:
            fixture.write_account_config("invalid\n")
            env_file = fixture.make_env_file(sensitive=True)
            result = fixture.run_op_env(env_file, credentials=True)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("account", result.stderr.lower())
            self.assertEqual(fixture.events, [])
            self.assertEqual(fixture.notify_calls, [])
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(fixture.child_calls, [])
            self.assert_no_secret_sentinels(fixture, result)

    def test_op_env_sensitive_file_rejects_path_raw_and_mixed_root_op_bin(self) -> None:
        for case in ("path", "raw", "mixed-root"):
            with self.subTest(case=case), SensitiveAccessFixture() as fixture:
                env_file = fixture.make_env_file(sensitive=True)
                if case == "path":
                    op_bin = "op"
                elif case == "raw":
                    op_bin = str(fixture.real_op)
                else:
                    mixed_op = fixture.root / "other" / "bin" / "op"
                    mixed_op.parent.mkdir(parents=True)
                    mixed_op.write_text("#!/bin/sh\nexit 0\n")
                    mixed_op.chmod(0o755)
                    op_bin = str(mixed_op)

                result = fixture.run_op_env(
                    env_file,
                    credentials=True,
                    env_updates={"OP_BIN": op_bin},
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exact co-located op shim", result.stderr)
                self.assertEqual(fixture.events, [])
                self.assertEqual(fixture.notify_calls, [])
                self.assertEqual(fixture.cache_calls, [])
                self.assertEqual(fixture.security_calls, [])
                self.assertEqual(fixture.child_calls, [])
                self.assert_no_secret_sentinels(fixture, result)

    def test_op_env_sensitive_file_rejects_unsafe_colocated_op_file(self) -> None:
        for state in (
            "non-executable",
            "non-regular",
            "symlink",
            "group-writable",
            "other-writable",
        ):
            with self.subTest(state=state), SensitiveAccessFixture() as fixture:
                env_file = fixture.make_env_file(sensitive=True)
                if state == "non-executable":
                    fixture.op.chmod(0o600)
                elif state == "non-regular":
                    fixture.op.unlink()
                    fixture.op.mkdir()
                elif state == "symlink":
                    fixture.op.unlink()
                    fixture.op.symlink_to(fixture.real_op)
                elif state == "group-writable":
                    fixture.op.chmod(0o775)
                else:
                    fixture.op.chmod(0o757)

                result = fixture.run_op_env(env_file, credentials=True)

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("exact co-located op shim", result.stderr)
                self.assertEqual(fixture.events, [])
                self.assertEqual(fixture.notify_calls, [])
                self.assertEqual(fixture.cache_calls, [])
                self.assertEqual(fixture.security_calls, [])
                self.assertEqual(fixture.child_calls, [])
                self.assert_no_secret_sentinels(fixture, result)

    def test_op_env_non_sensitive_inherited_token_does_not_read_keychain(self) -> None:
        with SensitiveAccessFixture() as fixture:
            env_file = fixture.make_env_file(sensitive=False)
            result = fixture.run_op_env(env_file, credentials=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.events, ["real"])
            self.assertEqual(fixture.security_calls, [])
            self.assertEqual(
                fixture.child_calls,
                [
                    {
                        "argv": [
                            "run",
                            f"--env-file={env_file}",
                            "--",
                            "fixture-command",
                            "--fixture-argument",
                        ],
                        "env_present": sorted(CREDENTIALS),
                    }
                ],
            )
            self.assert_no_secret_sentinels(fixture, result)

    def test_op_env_non_sensitive_missing_token_uses_fake_keychain(self) -> None:
        with SensitiveAccessFixture() as fixture:
            env_file = fixture.make_env_file(sensitive=False)
            result = fixture.run_op_env(env_file, credentials=False)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(fixture.events, ["security", "real"])
            self.assertEqual(len(fixture.security_calls), 1)
            self.assertEqual(
                fixture.child_calls,
                [
                    {
                        "argv": [
                            "run",
                            f"--env-file={env_file}",
                            "--",
                            "fixture-command",
                            "--fixture-argument",
                        ],
                        "env_present": ["OP_SERVICE_ACCOUNT_TOKEN"],
                    }
                ],
            )
            self.assert_no_secret_sentinels(fixture, result)

    def test_sensitive_read_reuses_memory_cache_without_repeating_any_gate(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = [
                "read",
                "--no-newline",
                "op://AUTODEV-sensitive/ITEM/value",
            ]
            first_env = fixture.env(
                credentials=True,
                CONDUCTOR_SESSION_ID="fixture-cache-session",
            )
            command = [str(fixture.op), *args]
            first = subprocess.run(
                command,
                env=first_env,
                capture_output=True,
                text=True,
                timeout=10,
            )

            # A hit must return before reason, notifier, account loading, or auth.
            fixture.set_notifier("missing")
            fixture.remove_account_config()
            second_env = first_env.copy()
            second_env.pop("SENSITIVE_ACCESS_REASON", None)
            for name in CREDENTIALS:
                second_env.pop(name, None)
            second = subprocess.run(
                command,
                env=second_env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            fixture.stop_cache(first_env)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(first.stdout, "resolved-value")
            self.assertEqual(second.stdout, "resolved-value")
            self.assertEqual(fixture.events, ["auth", "notify", "real"])
            self.assertEqual(len(fixture.notify_calls), 1)
            self.assertEqual(len(fixture.child_calls), 1)
            self.assertEqual(
                [call["argv"][0] for call in fixture.cache_calls],
                ["get", "put", "get", "stop"],
            )
            self.assertTrue(
                all(call["env_present"] == [] for call in fixture.cache_calls)
            )
            self.assertEqual(fixture.notify_calls[0]["env_present"], [])
            self.assertEqual(
                fixture.child_calls[0],
                {
                    "argv": ["--account", CANONICAL_ACCOUNT, *args],
                    "env_present": [],
                },
            )
            self.assertEqual(fixture.security_calls, [])
            self.assertIn("auth=session-cache", fixture.audit)
            self.assert_no_secret_sentinels(fixture, first, second)

    def test_notification_bypass_flag_is_ignored_on_cache_miss(self) -> None:
        with SensitiveAccessFixture() as fixture:
            args = ["read", "op://AUTODEV-sensitive/ITEM/value"]
            result = fixture.run_op(
                args,
                credentials=True,
                env_updates={"OP_SENSITIVE_NOTIFICATION_SENT": "1"},
            )
            self.assert_sensitive_child(
                fixture,
                result,
                ["--account", CANONICAL_ACCOUNT, *args],
            )


if __name__ == "__main__":
    unittest.main()

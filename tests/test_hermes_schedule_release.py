from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
HERMES = ROOT / "hermes"


def load_extensionless_module(name: str, path: Path) -> types.ModuleType:
    loader = importlib.machinery.SourceFileLoader(name, str(path))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


def git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return result.stdout.strip()


def seed_schedule_repository(root: Path) -> str:
    git(root, "init", "--initial-branch=main")
    git(root, "config", "user.email", "tests@example.com")
    git(root, "config", "user.name", "Hermes tests")
    schedules = root / "hermes" / "schedules"
    schedules.mkdir(parents=True)
    (schedules / "runner.py").write_text("print('runner')\n")
    (schedules / "schedules.yaml").write_text(
        "deployment_contract_version: 1\nschedules: []\n"
    )
    (schedules / "requirements.txt").write_text(
        "PyYAML==6.0.2 \\\n"
        "  --hash=sha256:80bab7bfc629882493af4aa31a4cfa43a4c57c83813253626916b8c7ada83476\n"
    )
    (schedules / "prompt.md").write_text("prompt\n")
    (schedules / "README.md").write_text("operator docs\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "seed schedules")
    return git(root, "rev-parse", "HEAD")


class HermesScheduleReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.release = load_extensionless_module(
            "hermes_schedule_release",
            HERMES / "bin" / "hermes-schedule-release",
        )
        cls.validator = load_extensionless_module(
            "hermes_schedule_validator",
            HERMES / "bin" / "validate-schedule-release",
        )
        cls.alert = load_extensionless_module(
            "hermes_schedule_alert",
            HERMES / "bin" / "hermes-schedule-alert",
        )
        cls.inputs = load_extensionless_module(
            "hermes_bootstrap_inputs",
            HERMES / "bin" / "validate-bootstrap-inputs",
        )

    def create_valid_release(self, releases: Path, revision: str) -> Path:
        path = releases / revision
        (path / "venv" / "bin").mkdir(parents=True)
        files = {
            "runner.py": b"print('runner')\n",
            "schedules.yaml": b"deployment_contract_version: 1\n",
            "requirements.txt": b"package==1 --hash=sha256:" + b"a" * 64 + b"\n",
        }
        for name, content in files.items():
            (path / name).write_bytes(content)
        (path / "venv" / "bin" / "python").write_text("")
        metadata = {
            "revision": revision,
            "git_tree": "b" * 40,
            "bundle_hash": self.release.hash_files(files),
            "files": {
                name: hashlib.sha256(content).hexdigest()
                for name, content in files.items()
            },
        }
        (path / "release.json").write_text(json.dumps(metadata))
        return path

    def test_checked_in_release_matches_contract_and_timer_inventory(self) -> None:
        self.validator.validate_release(HERMES / "schedules", HERMES / "systemd")
        manifest = yaml.safe_load((HERMES / "schedules" / "schedules.yaml").read_text())
        self.assertEqual(manifest["deployment_contract_version"], 1)

    def test_validator_rejects_contract_bump_until_manual_host_update(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / "release"
            release.mkdir()
            for name in ("runner.py", "requirements.txt", "health-6h.md"):
                source = HERMES / "schedules" / name
                (release / name).write_bytes(source.read_bytes())
            manifest = yaml.safe_load(
                (HERMES / "schedules" / "schedules.yaml").read_text()
            )
            manifest["deployment_contract_version"] = 2
            (release / "schedules.yaml").write_text(yaml.safe_dump(manifest))
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_release(release, HERMES / "systemd")

    def test_archive_exports_runtime_files_and_ignores_readme(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            revision = seed_schedule_repository(repository)
            bundle = self.release.archive_bundle(repository, revision)
        self.assertEqual(bundle.revision, revision)
        self.assertEqual(
            set(bundle.files),
            {"runner.py", "schedules.yaml", "requirements.txt", "prompt.md"},
        )
        self.assertNotIn("README.md", bundle.files)

    def test_archive_rejects_symlinks_and_unhashed_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory)
            seed_schedule_repository(repository)
            schedules = repository / "hermes" / "schedules"
            (schedules / "linked.md").symlink_to("prompt.md")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "add unsafe symlink")
            revision = git(repository, "rev-parse", "HEAD")
            with self.assertRaises(self.release.ReleaseError):
                self.release.archive_bundle(repository, revision)
            (schedules / "linked.md").unlink()
            (schedules / "requirements.txt").write_text("PyYAML==6.0.2\n")
            git(repository, "add", ".")
            git(repository, "commit", "-m", "remove hashes")
            revision = git(repository, "rev-parse", "HEAD")
            with self.assertRaises(self.release.ReleaseError):
                self.release.archive_bundle(repository, revision)

    def test_fetch_refuses_non_fast_forward_main(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            state = root / "state"
            source.mkdir()
            first = seed_schedule_repository(source)
            original_url = self.release.REMOTE_URL
            self.release.REMOTE_URL = str(source)
            try:
                state.mkdir()
                mirror = self.release.ensure_mirror(state)
                self.assertEqual(self.release.fetch_main(mirror), first)
                self.assertEqual(self.release.read_last_seen(mirror), first)
                (source / "note").write_text("descendant\n")
                git(source, "add", "note")
                git(source, "commit", "-m", "descendant")
                second = git(source, "rev-parse", "HEAD")
                self.assertEqual(self.release.fetch_main(mirror), second)
                self.assertEqual(self.release.read_last_seen(mirror), second)
                tree = git(source, "rev-parse", f"{first}^{{tree}}")
                divergent = git(source, "commit-tree", tree, "-m", "divergent")
                git(source, "update-ref", "refs/heads/main", divergent)
                with self.assertRaises(self.release.ReleaseError):
                    self.release.fetch_main(mirror)
            finally:
                self.release.REMOTE_URL = original_url

    def test_activation_preserves_previous_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory).resolve() / "runtime"
            releases = runtime / "releases"
            first = releases / ("a" * 40)
            second = releases / ("b" * 40)
            first.mkdir(parents=True)
            second.mkdir()
            self.release.activate_release(first, runtime)
            self.release.activate_release(second, runtime)
            self.assertEqual((runtime / "current").resolve(), second.resolve())
            self.assertEqual((runtime / "previous").resolve(), first.resolve())

    def test_rollback_quarantines_bad_bundle_before_switching(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            state = root / "state"
            releases = self.release.prepare_directories(runtime, state)
            first = self.create_valid_release(releases, "a" * 40)
            second = self.create_valid_release(releases, "b" * 40)
            self.release.replace_link(runtime / "previous", first)
            self.release.replace_link(runtime / "current", second)
            with (
                mock.patch.object(self.release, "RUNTIME_ROOT", runtime),
                mock.patch.object(self.release, "STATE_ROOT", state),
            ):
                self.release.rollback()
            self.assertEqual((runtime / "current").resolve(), first.resolve())
            self.assertEqual((runtime / "previous").resolve(), second.resolve())
            bad_hash = self.release.read_metadata(second).bundle_hash
            self.assertTrue((state / "quarantine" / bad_hash).is_file())
            with (
                mock.patch.object(self.release, "RUNTIME_ROOT", runtime),
                mock.patch.object(self.release, "STATE_ROOT", state),
                self.assertRaises(self.release.ReleaseError),
            ):
                self.release.rollback()

    def test_reused_release_detects_asset_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            releases = Path(directory)
            release = self.create_valid_release(releases, "a" * 40)
            self.release.verify_release(release)
            (release / "runner.py").write_text("tampered\n")
            with self.assertRaises(self.release.ReleaseError):
                self.release.verify_release(release)

    def test_release_integrity_rejects_wrong_bundle_identity_and_extra_assets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            releases = Path(directory)
            release = self.create_valid_release(releases, "a" * 40)
            metadata_path = release / "release.json"
            metadata = json.loads(metadata_path.read_text())
            metadata["bundle_hash"] = "f" * 64
            metadata_path.write_text(json.dumps(metadata))
            with self.assertRaises(self.release.ReleaseError):
                self.release.verify_release(release)
            metadata["bundle_hash"] = self.release.hash_files(
                {
                    name: (release / name).read_bytes()
                    for name in metadata["files"]
                }
            )
            metadata_path.write_text(json.dumps(metadata))
            (release / "unexpected.txt").write_text("unexpected")
            with self.assertRaises(self.release.ReleaseError):
                self.release.verify_release(release)

    def test_quarantined_bundle_is_not_redeployed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            state = root / "state"
            releases = self.release.prepare_directories(runtime, state)
            healthy = self.create_valid_release(releases, "a" * 40)
            self.release.replace_link(runtime / "current", healthy)
            bundle = self.release.Bundle(
                "b" * 40,
                "d" * 40,
                "e" * 64,
                {
                    "runner.py": b"print('candidate')\n",
                    "schedules.yaml": b"deployment_contract_version: 1\n",
                    "requirements.txt": b"package==1 --hash=sha256:" + b"a" * 64,
                },
            )
            (state / "quarantine" / bundle.bundle_hash).write_text(f"{bundle.revision}\n")
            with mock.patch.object(self.release, "build_release") as build:
                result = self.release.install_bundle(
                    bundle,
                    runtime,
                    state,
                    HERMES / "systemd",
                )
            build.assert_not_called()
            self.assertIn("quarantined schedule bundle unchanged", result)
            self.assertEqual((runtime / "current").resolve(), healthy.resolve())
    def test_sync_failures_are_always_pending_until_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            error = self.release.ReleaseError("fetch", "GitHub unavailable")
            self.release.record_failure(state, error)
            first = json.loads((state / "pending-failure.json").read_text())
            self.release.record_failure(state, error)
            second = json.loads((state / "pending-failure.json").read_text())
            self.assertEqual(first, second)
            self.release.clear_failure(state)
            self.assertFalse((state / "pending-failure.json").exists())

    def test_repeated_sync_failures_always_exit_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            error = self.release.ReleaseError("fetch", "GitHub unavailable")
            with (
                mock.patch.object(self.release, "STATE_ROOT", state),
                mock.patch.object(self.release, "sync", side_effect=error),
                mock.patch.object(self.release, "require_root"),
            ):
                self.assertEqual(self.release.main(["release", "sync"]), 1)
                self.assertEqual(self.release.main(["release", "sync"]), 1)

    def test_sync_alert_marks_dedup_only_after_successful_post(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            pending = {
                "fingerprint": "a" * 64,
                "phase": "fetch",
                "detail": "GitHub unavailable",
            }
            (state / "pending-failure.json").write_text(json.dumps(pending))
            with (
                mock.patch.object(self.alert, "SYNC_STATE", state),
                mock.patch.object(self.alert, "post", side_effect=OSError("offline")),
                self.assertRaises(OSError),
            ):
                self.alert.alert_sync()
            self.assertFalse((state / "last-alerted-failure.json").exists())
            with (
                mock.patch.object(self.alert, "SYNC_STATE", state),
                mock.patch.object(self.alert, "post") as post,
            ):
                self.assertIn("posted", self.alert.alert_sync())
                self.assertIn("deduplicated", self.alert.alert_sync())
            post.assert_called_once()

    def test_sync_alert_reports_unstructured_updater_crash(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            with (
                mock.patch.object(self.alert, "SYNC_STATE", state),
                mock.patch.object(self.alert, "post") as post,
            ):
                self.assertIn("posted", self.alert.alert_sync())
            self.assertIn("before structured sync details", post.call_args.args[0])
            self.assertTrue((state / "last-alerted-failure.json").is_file())

    def test_timer_validation_rejects_comments_extra_calendars_and_dropins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = root / "release"
            timers = root / "timers"
            release.mkdir()
            timers.mkdir()
            (release / "runner.py").write_text("pass\n")
            (release / "requirements.txt").write_text("x==1 --hash=sha256:" + "a" * 64)
            (release / "prompt.md").write_text("prompt\n")
            (release / "schedules.yaml").write_text(
                "deployment_contract_version: 1\n"
                "runner:\n  poll_seconds: 1\n  retention_days_pass: 1\n"
                "  retention_days_fail: 1\n  archive_on_complete: [PASS]\n"
                "slack_channels:\n  '#autodev-incidents': C1\n"
                "production_approval:\n  enabled: true\n"
                "  hermes_slack_user_id: U123\n  authorized_slack_users: [U456]\n"
                "  expires_days: 1\n  max_runtime_minutes: 1\n  max_start_attempts: 1\n"
                "schedules:\n- name: job\n  cron: '0 2 * * *'\n"
                "  prompt: prompt.md\n  slack_channel: '#autodev-incidents'\n"
                "  max_runtime_minutes: 1\n  enabled: true\n"
                "  workspace:\n    repo: r\n    repo_url: u\n    branch: b\n"
                "    agent: a\n    model: m\n"
            )
            timer = timers / "hermes-schedule@job.timer"
            for name in (
                "hermes-schedule-approval.service",
                "hermes-schedule-approval.timer",
            ):
                (timers / name).write_bytes((HERMES / "systemd" / name).read_bytes())
            timer.write_text(
                "[Timer]\n# OnCalendar=*-*-* 02:00:00 America/Vancouver\n"
                "OnCalendar=*-*-* 03:00:00 America/Vancouver\nPersistent=true\n"
            )
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_release(release, timers)
            timer.write_text(
                "[Timer]\nOnCalendar=*-*-* 02:00:00 America/Vancouver\n"
                "OnCalendar=*-*-* 03:00:00 America/Vancouver\nPersistent=true\n"
            )
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_release(release, timers)
            timer.write_text(
                "[Timer]\nOnCalendar=*-*-* 02:00:00 America/Vancouver\nPersistent=true\n"
            )
            (timers / "hermes-schedule@job.timer.d").mkdir()
            with self.assertRaises(self.validator.ValidationError):
                self.validator.validate_release(release, timers)

    def test_bootstrap_input_validation_rejects_placeholders_and_empty_auth(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            environment = root / "gateway.env"
            auth = root / "auth.json"
            environment.write_bytes((HERMES / "config" / "gateway.env.example").read_bytes())
            auth.write_text("{}")
            with self.assertRaises(self.inputs.InputError):
                self.inputs.parse_environment(environment)
            with self.assertRaises(self.inputs.InputError):
                self.inputs.validate_auth(auth)

    def test_bootstrap_input_example_matches_validator_schema(self) -> None:
        text = (HERMES / "config" / "gateway.env.example").read_text()
        replacements = {
            "replace-with-xapp-token": "xapp-test",
            "replace-with-xoxb-token": "xoxb-test",
            "replace-with-channel-allowlist": "C1",
            "replace-with-home-channel-id": "C1",
            "replace-with-home-channel-name": "home",
            "replace-with-user-allowlist": "user",
            "replace-with-home-chat": "chat",
            "replace-with-thread-id": "thread",
            "replace-with-reviewed-mode": "bot",
        }
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / "gateway.env"
            environment.write_text(text)
            values = self.inputs.parse_environment(environment)
        self.assertEqual(set(values), self.inputs.EXPECTED_ENV_KEYS)
        self.assertEqual(values["WHATSAPP_HOME_CHANNEL_THREAD_ID"], "")

    def test_bootstrap_input_validation_only_allows_documented_optional_empty(self) -> None:
        text = (HERMES / "config" / "gateway.env.example").read_text()
        replacements = {
            "replace-with-xapp-token": "xapp-test",
            "replace-with-xoxb-token": "xoxb-test",
            "replace-with-channel-allowlist": "C1",
            "replace-with-home-channel-id": "C1",
            "replace-with-home-channel-name": "home",
            "replace-with-user-allowlist": "user",
            "replace-with-home-chat": "chat",
            "replace-with-reviewed-mode": "bot",
        }
        for placeholder, value in replacements.items():
            text = text.replace(placeholder, value)
        text = text.replace("SLACK_HOME_CHANNEL_NAME=home", "SLACK_HOME_CHANNEL_NAME=")
        with tempfile.TemporaryDirectory() as directory:
            environment = Path(directory) / "gateway.env"
            environment.write_text(text)
            with self.assertRaises(self.inputs.InputError):
                self.inputs.parse_environment(environment)

    def test_concurrent_release_operation_fails_without_waiting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)
            first = self.release.locked(state)
            try:
                with self.assertRaises(self.release.ReleaseError):
                    self.release.locked(state)
            finally:
                first.close()

    def test_launcher_resolves_absolute_release_before_exec(self) -> None:
        launcher = (HERMES / "bin" / "run-schedule-release").read_text()
        self.assertIn('RELEASE="$(readlink -e "$RUNTIME_ROOT/current")"', launcher)
        self.assertIn('exec "$RELEASE/venv/bin/python" "$RELEASE/runner.py"', launcher)
        self.assertNotIn("current/venv/bin/python", launcher)

    def test_launcher_pins_inflight_process_across_switch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runtime = Path(directory).resolve() / "runtime"
            releases = runtime / "releases"
            releases.mkdir(parents=True)
            for revision, prompt in (("a" * 40, "old"), ("b" * 40, "new")):
                release = releases / revision
                (release / "venv" / "bin").mkdir(parents=True)
                (release / "venv" / "bin" / "python").symlink_to("/usr/bin/python3")
                (release / "prompt.md").write_text(prompt)
                (release / "runner.py").write_text(
                    "import pathlib,sys,time\n"
                    "root=pathlib.Path(__file__).resolve().parent\n"
                    "print(root.name, flush=True)\n"
                    "if len(sys.argv)>1: pathlib.Path(sys.argv[1]).write_text('ready')\n"
                    "time.sleep(0.4)\n"
                    "print((root/'prompt.md').read_text(), flush=True)\n"
                )
            self.release.replace_link(runtime / "current", releases / ("a" * 40))
            readlink = Path(directory) / "readlink-e"
            readlink.write_text(
                "#!/usr/bin/env python3\n"
                "import pathlib,sys\n"
                "print(pathlib.Path(sys.argv[1]).resolve(strict=True))\n"
            )
            readlink.chmod(0o755)
            launcher = Path(directory) / "launcher"
            launcher.write_text(
                (HERMES / "bin" / "run-schedule-release")
                .read_text()
                .replace("/opt/hermes-schedules", str(runtime))
                .replace("readlink -e", str(readlink))
            )
            launcher.chmod(0o755)
            ready = Path(directory) / "ready"
            old = subprocess.Popen(
                [str(launcher), str(ready)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            deadline = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not ready.exists():
                _, stderr = old.communicate(timeout=5)
                self.fail(f"old launcher did not start: {stderr}")
            self.release.replace_link(runtime / "current", releases / ("b" * 40))
            new = subprocess.run(
                [str(launcher)],
                check=True,
                capture_output=True,
                text=True,
            )
            old_stdout, old_stderr = old.communicate(timeout=5)
            self.assertEqual(old.returncode, 0, old_stderr)
            self.assertEqual(old_stdout.splitlines(), ["a" * 40, "old"])
            self.assertEqual(new.stdout.splitlines(), ["b" * 40, "new"])

    def test_failed_build_leaves_current_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            runtime = root / "runtime"
            state = root / "state"
            releases = self.release.prepare_directories(runtime, state)
            healthy = self.create_valid_release(releases, "a" * 40)
            self.release.replace_link(runtime / "current", healthy)
            bundle = self.release.Bundle("b" * 40, "c" * 40, "d" * 64, {})
            with (
                mock.patch.object(
                    self.release,
                    "build_release",
                    side_effect=self.release.ReleaseError("validation", "invalid"),
                ),
                self.assertRaises(self.release.ReleaseError),
            ):
                self.release.install_bundle(bundle, runtime, state, HERMES / "systemd")
            self.assertEqual((runtime / "current").resolve(), healthy.resolve())

    def test_build_release_verifies_a_sha_named_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            releases = root / "releases"
            releases.mkdir()
            files = {
                "runner.py": b"print('runner')\n",
                "schedules.yaml": b"deployment_contract_version: 1\n",
                "requirements.txt": b"package==1 --hash=sha256:" + b"a" * 64 + b"\n",
            }
            revision = "a" * 40
            bundle = self.release.Bundle(
                revision,
                "b" * 40,
                self.release.hash_files(files),
                files,
            )

            def fake_build(command: list[str], phase: str) -> None:
                if phase == "venv":
                    venv = Path(command[-1])
                    (venv / "bin").mkdir(parents=True)
                    (venv / "bin" / "python").write_text("")

            with (
                mock.patch.object(self.release, "change_owner") as change_owner,
                mock.patch.object(self.release, "lock_down"),
                mock.patch.object(self.release, "run_as_build_user", side_effect=fake_build),
            ):
                release = self.release.build_release(bundle, releases, root)

            self.assertEqual(release.name, revision)
            owned_staging = change_owner.call_args.args[0]
            self.assertNotEqual(owned_staging.name, revision)
            self.assertEqual((owned_staging / revision).name, release.name)
            self.release.verify_release(release, bundle)

    def test_builder_subprocess_drops_identity_and_cannot_regain_privileges(self) -> None:
        account = types.SimpleNamespace(pw_uid=1234, pw_gid=5678)
        with (
            mock.patch.object(self.release.pwd, "getpwnam", return_value=account),
            mock.patch.object(self.release, "run_text") as run_text,
        ):
            self.release.run_as_build_user(["/usr/bin/id", "-u"], "validation")

        command = run_text.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/setpriv")
        self.assertIn("--reuid=1234", command)
        self.assertIn("--regid=5678", command)
        self.assertIn("--inh-caps=-all", command)
        self.assertIn("--ambient-caps=-all", command)
        self.assertIn("--no-new-privs", command)
        self.assertNotIn("/usr/sbin/runuser", command)

    def test_lock_down_makes_restrictive_umask_venv_readable_by_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            release = Path(directory) / ("a" * 40)
            (release / "venv" / "bin").mkdir(parents=True)
            pyvenv = release / "venv" / "pyvenv.cfg"
            python = release / "venv" / "bin" / "python"
            pyvenv.write_text("home = /usr/bin\n")
            python.write_text("#!/bin/sh\n")
            pyvenv.chmod(0o600)
            python.chmod(0o700)

            with mock.patch.object(self.release.os, "chown"):
                self.release.lock_down(release)

            self.assertEqual(pyvenv.stat().st_mode & 0o777, 0o644)
            self.assertEqual(python.stat().st_mode & 0o777, 0o755)
            self.assertEqual((release / "venv").stat().st_mode & 0o777, 0o755)

    def test_moved_virtual_environment_uses_release_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            staged = root / "staged"
            subprocess.run(["python3", "-m", "venv", str(staged / "venv")], check=True)
            release = root / ("a" * 40)
            staged.rename(release)
            result = subprocess.run(
                [str(release / "venv" / "bin" / "python"), "-c", "import sys; print(sys.prefix)"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(Path(result.stdout.strip()).resolve(), (release / "venv").resolve())

    def test_sync_unit_is_fixed_hardened_root_code(self) -> None:
        service = (HERMES / "systemd" / "hermes-schedule-sync.service").read_text()
        timer = (HERMES / "systemd" / "hermes-schedule-sync.timer").read_text()
        self.assertIn("ExecStart=/opt/hermes-schedules/bin/hermes-schedule-release sync", service)
        self.assertIn("OnFailure=hermes-schedule-sync-alert.service", service)
        self.assertIn("ProtectSystem=strict", service)
        self.assertIn("NoNewPrivileges=true", service)
        self.assertIn("RestrictSUIDSGID=true", service)
        # setpriv must drop to the builder; an explicit User=root together with
        # NoNewPrivileges=true breaks that setuid on systemd 255 (EPERM).
        self.assertNotRegex(service, r"(?m)^User=")
        self.assertNotRegex(service, r"(?m)^Group=")
        self.assertIn("ReadWritePaths=/opt/hermes-schedules", service)
        self.assertIn("TimeoutStartSec=20min", service)
        self.assertIn("OnCalendar=*-*-* *:00/15:00 UTC", timer)
        self.assertIn("RandomizedDelaySec=5min", timer)
        self.assertIn("Persistent=true", timer)
        installer = (HERMES / "install.sh").read_text()
        self.assertNotIn("git pull", installer)
        self.assertNotIn("/opt/hermes-schedules/runner.py", installer)
        self.assertIn("ls-remote --exit-code", installer)
        self.assertIn("status --porcelain --untracked-files=all", installer)
        self.assertIn("archive --format=tar", installer)
        self.assertIn("systemctl disable --now", installer)
        self.assertIn('chmod 0755 "$CONDUCTOR_NEW"', installer)
        self.assertIn('CONDUCTOR_NEW="/opt/hermes-conductor/.venv.failed.$$"', installer)
        release_manager = (HERMES / "bin" / "hermes-schedule-release").read_text()
        self.assertIn('"/usr/bin/setpriv"', release_manager)
        self.assertNotIn('"/usr/sbin/runuser"', release_manager)
        self.assertIn(
            '"$SOURCE_ROOT/hermes/config/config.yaml" "$HERMES_CONFIG"',
            installer,
        )
        self.assertIn(
            '/dev/null "$HERMES_HOME/.no-bundled-skills"',
            installer,
        )
        self.assertNotIn('configure.py" "$HERMES_CONFIG"', installer)

    def test_units_that_switch_users_never_pin_user_root(self) -> None:
        for unit in sorted((HERMES / "systemd").glob("*.service")):
            content = unit.read_text()
            exec_line = next((l for l in content.splitlines() if l.startswith("ExecStart=")), "")
            binary = exec_line.removeprefix("ExecStart=").split()[0] if exec_line else ""
            source = HERMES / "bin" / Path(binary).name
            if not source.exists() or not any(t in source.read_text() for t in ("setpriv", "runuser")):
                continue
            self.assertNotRegex(content, r"(?m)^User=", f"{unit.name} switches user; drop User=")

    def test_managed_install_method_marker_does_not_dirty_agent_checkout(self) -> None:
        bootstrap = (HERMES / "bootstrap.sh").read_text()
        installer = (HERMES / "install.sh").read_text()
        verifier = (HERMES / "verify.sh").read_text()
        for script in (bootstrap, verifier):
            self.assertIn("':(exclude).install_method'", script)
        self.assertIn("chmod 0644 \"$AGENT_DIR/.install_method\"", bootstrap)
        self.assertIn("mv -Tf --", installer)
        self.assertIn('= "hermes:hermes:644"', verifier)

    def test_bootstrap_pins_downloads_and_requires_external_secrets(self) -> None:
        bootstrap = (HERMES / "bootstrap.sh").read_text()
        versions = (HERMES / "versions.env").read_text()
        for name in (
            "HERMES_AGENT_UPSTREAM_COMMIT",
            "HERMES_AGENT_PATCHED_COMMIT",
            "HERMES_UV_SHA256",
            "HERMES_NODE_SHA256",
            "HERMES_PYTHON_VERSION",
            "HERMES_NPM_VERSION",
            "HERMES_SYSTEM_NODE_VERSION",
        ):
            self.assertIn(f"{name}=", versions)
        self.assertIn('check_secret "$INPUT_DIR/gateway.env"', bootstrap)
        self.assertIn('check_secret "$INPUT_DIR/auth.json"', bootstrap)
        self.assertIn("--locked", bootstrap)
        self.assertIn("sha256sum --check", bootstrap)
        self.assertNotIn("curl |", bootstrap)
        self.assertNotIn("curl -s |", bootstrap)
        installer = (HERMES / "install.sh").read_text()
        conductor_lock = (HERMES / "conductor" / "requirements.txt").read_text()
        self.assertIn("--require-hashes", installer)
        self.assertIn("--only-binary=:all:", installer)
        self.assertIn("--hash=sha256:", conductor_lock)


if __name__ == "__main__":
    unittest.main()

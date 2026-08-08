"""End-to-end coverage for bin/rotate-secret against fake op + fake sync."""

from __future__ import annotations

import json
import unittest

import yaml

from secrets_common import ROOT, SecretsSandbox, run

ROTATE = str(ROOT / "bin" / "rotate-secret")

SELF_MINTED_REF = "op://TESTVAULT/API_HMAC_SECRET/value"
MANUAL_REF = "op://TESTVAULT/EXTERNAL_API_KEY/value"
PG_REF = "op://TESTVAULT-sensitive/PROD_POSTGRES_URL_APP/value"
DISABLED_REF = "op://TESTVAULT/COUPLED_DATABASE/value"


class RotateSecretTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        routes = "\n".join([
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself",
            f"render\tsrv-b\tHMAC\t{SELF_MINTED_REF}\tself",
            f"render\tsrv-a\tEXTERNAL_API_KEY\t{MANUAL_REF}\tself",
            f"render\tsrv-pg\tDATABASE_URL\t{PG_REF}\tself",
            f"render\tsrv-coupled\tDATABASE_URL\t{DISABLED_REF}\tself",
            "",
        ])
        rotation = {
            "test-hmac": {
                "ref": SELF_MINTED_REF,
                "provider": "self_minted",
                "mode": "SELF_MINTED",
                "generate": {"format": "hex", "bytes": 16},
                "owner_repo": "repo",
            },
            "test-manual": {
                "ref": MANUAL_REF,
                "provider": "manual",
                "mode": "MANUAL",
                "owner_repo": "repo",
                "playbook": "1. Mint a new key in the provider dashboard.\n2. Revoke the old key after fan-out.",
            },
            "test-postgres": {
                "ref": PG_REF,
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
            },
            "test-disabled": {
                "ref": DISABLED_REF,
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
                "disabled_reason": "activation spans unsupported channels",
            },
        }
        self.sb.write_manifest(routes, rotation=rotation)

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(
            SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
            **extra,
        )

    def rotate(self, *args: str, env: dict[str, str] | None = None, stdin: str | None = None):
        return run([ROTATE, "--repo", str(self.sb.repo), *args],
                   env if env is not None else self.env(), stdin=stdin)

    def sync_calls(self) -> list[str]:
        return [l for l in self.sb.log_lines() if l.startswith("SYNC ")]

    def stored_value(self, ref: str) -> str:
        rest = ref.removeprefix("op://")
        vault, item, field = rest.split("/")
        return (self.sb.state / f"{vault}__{item}__{field}").read_text(encoding="utf-8")

    # --- registry gate --------------------------------------------------------

    def test_unknown_item_exits_2_and_lists_known_entries(self) -> None:
        proc = self.rotate("--ref", "op://TESTVAULT/NOT_REGISTERED/value", "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no rotation entry", proc.stderr)
        self.assertIn("test-hmac", proc.stderr)
        self.assertIn("test-manual", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_project_item_field_triple_resolves_the_same_entry(self) -> None:
        proc = self.rotate(
            "--project", "testproj", "--item", "API_HMAC_SECRET", "--field", "value",
            "--dry-run",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("test-hmac", proc.stdout)

    def test_disabled_entry_refuses_before_plan_or_mutation(self) -> None:
        proc = self.rotate("--ref", DISABLED_REF, "--dry-run")

        self.assertEqual(proc.returncode, 3)
        self.assertIn("test-disabled", proc.stderr)
        self.assertIn("unsupported channels", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    # --- dry-run ----------------------------------------------------------------

    def test_dry_run_prints_handler_and_full_fanout_and_mutates_nothing(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("provider: self_minted", proc.stdout)
        self.assertIn(str(self.sb.repo), proc.stdout)
        self.assertIn("render[srv-a]", proc.stdout)
        self.assertIn("render[srv-b]", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])  # no op, no sync

    # --- live refusals ------------------------------------------------------------

    def test_live_rotation_requires_reason(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--reason", proc.stderr)

    def test_live_rotation_refuses_agent_shell(self) -> None:
        proc = self.rotate(
            "--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
            env=self.env(CLAUDECODE="1"),
        )
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.sb.log_lines(), [])

    def test_non_interactive_live_rotation_requires_yes(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--yes", proc.stderr)

    # --- self_minted ---------------------------------------------------------------

    def test_self_minted_writes_vault_and_fans_out_to_every_consumer(self) -> None:
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "rotate hmac", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        value = self.stored_value(SELF_MINTED_REF)
        self.assertEqual(len(value), 32)  # 16 bytes hex
        # the minted value never reaches stdout/stderr or the argv log
        combined = proc.stdout + proc.stderr + "\n".join(self.sb.log_lines())
        self.assertNotIn(value, combined)
        calls = self.sync_calls()
        # ONE project-wide sync covers every consumer repo via the config routes
        self.assertEqual(len(calls), 1)
        self.assertIn(f"--repo {self.sb.repo}", calls[0])
        self.assertIn(f"--changed {SELF_MINTED_REF}", calls[0])

    def test_self_minted_rerun_replaces_the_item_in_place(self) -> None:
        first = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        v1 = self.stored_value(SELF_MINTED_REF)
        second = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        v2 = self.stored_value(SELF_MINTED_REF)
        self.assertEqual((first.returncode, second.returncode), (0, 0))
        self.assertNotEqual(v1, v2)

    def test_failed_fanout_after_mint_exits_5_with_recovery(self) -> None:
        proc = self.rotate(
            "--ref", SELF_MINTED_REF, "--reason", "t", "--yes",
            env=self.env(FAKE_SYNC_EXIT="1"),
        )
        self.assertEqual(proc.returncode, 5)
        self.assertIn("vault now holds the NEW value", proc.stderr)
        self.assertIn("sync-secrets --repo", proc.stderr)
        # the vault write still happened (safe documented state)
        self.assertTrue(len(self.stored_value(SELF_MINTED_REF)) > 0)

    # --- manual ------------------------------------------------------------------

    def test_manual_provider_prints_playbook_exits_3_changes_nothing(self) -> None:
        proc = self.rotate("--ref", MANUAL_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("provider dashboard", proc.stdout)
        self.assertIn("--complete", proc.stdout)
        self.assertEqual(self.sync_calls(), [])
        self.assertFalse((self.sb.state / "TESTVAULT__EXTERNAL_API_KEY__value").exists())

    def test_complete_reads_stdin_once_writes_vault_and_fans_out(self) -> None:
        proc = self.rotate(
            "--ref", MANUAL_REF, "--reason", "t", "--complete",
            stdin="externally-minted-value-123",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.stored_value(MANUAL_REF), "externally-minted-value-123")
        self.assertNotIn("externally-minted-value-123", proc.stdout + proc.stderr)
        self.assertEqual(len(self.sync_calls()), 1)

    def test_complete_with_empty_stdin_refuses_and_leaves_vault_untouched(self) -> None:
        proc = self.rotate("--ref", MANUAL_REF, "--reason", "t", "--complete", stdin="")
        self.assertEqual(proc.returncode, 2)
        self.assertFalse((self.sb.state / "TESTVAULT__EXTERNAL_API_KEY__value").exists())

    # --- postgres (central rotator) ---------------------------------------------

    def test_postgres_refuses_project_missing_from_db_roles_config(self) -> None:
        # 'testproj' is not in config/db-roles.json: the rotator must refuse
        # (precondition, nothing changed) instead of improvising tier constants.
        proc = self.rotate("--ref", PG_REF, "--reason", "t", "--yes",
                           env=self.env(SECRETS_ALLOW_AGENT="1"))
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("is not in", proc.stderr)
        self.assertEqual(self.sync_calls(), [])


class VaultEditConflictTest(unittest.TestCase):
    """1Password returns 409 Conflict for concurrent item edits. Same-item
    concurrency is prevented upstream (orchestrator wave partitioning + the
    per-item lock), so a conflict means an EXTERNAL editor raced the rotation:
    the vault replace fails loudly on the first conflict, item untouched."""

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation={
                "test-hmac": {
                    "ref": SELF_MINTED_REF,
                    "provider": "self_minted",
                    "mode": "SELF_MINTED",
                    "generate": {"format": "hex", "bytes": 16},
                    "owner_repo": "repo",
                },
            },
        )

    def rotate(self, conflicts: str):
        env = self.sb.env(
            SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
            FAKE_OP_EDIT_CONFLICTS=conflicts,
        )
        return run([ROTATE, "--repo", str(self.sb.repo), "--ref", SELF_MINTED_REF,
                    "--reason", "t", "--yes"], env)

    def test_conflict_fails_loudly_first_time_without_retrying(self) -> None:
        # seed so the replace (edit) path runs rather than create
        rest = SELF_MINTED_REF.removeprefix("op://")
        vault, item, field = rest.split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text("old", encoding="utf-8")
        proc = self.rotate("1")
        self.assertEqual(proc.returncode, 4, proc.stderr + proc.stdout)
        self.assertIn("concurrent external edit", proc.stderr)
        self.assertNotIn("retrying", proc.stderr)
        self.assertEqual(
            (self.sb.state / f"{vault}__{item}__{field}").read_text(encoding="utf-8"), "old")

    def test_no_conflict_replaces_once(self) -> None:
        rest = SELF_MINTED_REF.removeprefix("op://")
        vault, item, field = rest.split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text("old", encoding="utf-8")
        proc = self.rotate("0")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)


class RotateHookTest(unittest.TestCase):
    """Optional repo hook: declared-but-missing refuses; post-sync runs after
    fan-out; hook: full delegates the whole rotation and skips the provider."""

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.hook_log = self.sb.root / "hook.log"
        routes = "\n".join([
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself",
            f"prefect\tstaging\tHMAC\t{SELF_MINTED_REF}\tself",
            "",
        ])
        self.rotation = {
            "test-hmac": {
                "ref": SELF_MINTED_REF,
                "provider": "self_minted",
                "mode": "SELF_MINTED",
                "generate": {"format": "hex", "bytes": 16},
                "owner_repo": "repo",
            },
        }
        self.sb.write_manifest(routes, rotation=self.rotation)

    def write_hook(self) -> None:
        hook_dir = self.sb.repo / "scripts" / "secrets"
        hook_dir.mkdir(parents=True, exist_ok=True)
        hook = hook_dir / "rotate-hook"
        hook.write_text(
            "#!/usr/bin/env bash\n"
            f'echo "HOOK $1 $ROTATE_ID" >> "{self.hook_log}"\n'
            'exit 0\n',
            encoding="utf-8",
        )
        hook.chmod(0o755)

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(
            SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
            **extra,
        )

    def rotate(self, *args: str):
        return run([ROTATE, "--repo", str(self.sb.repo), *args], self.env())

    def hook_calls(self) -> list[str]:
        if not self.hook_log.exists():
            return []
        return self.hook_log.read_text(encoding="utf-8").splitlines()

    def test_declared_hook_missing_refuses_before_any_action(self) -> None:
        self.rotation["test-hmac"]["hook"] = "activate"
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation=self.rotation,
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("REFUSED", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_post_sync_hook_runs_after_fanout(self) -> None:
        self.write_hook()
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.hook_calls(), ["HOOK post-sync test-hmac"])

    def test_hook_full_delegates_and_skips_the_provider(self) -> None:
        self.write_hook()
        self.rotation["test-hmac"]["hook"] = "full"
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n"
            f"prefect\tstaging\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation=self.rotation,
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # hook owned the rotation; the self_minted provider never wrote the vault
        self.assertIn("HOOK rotate test-hmac", self.hook_calls())
        self.assertNotIn("OP item edit", "\n".join(self.sb.log_lines()))
        # fan-out still ran
        self.assertTrue(any(l.startswith("SYNC ") for l in self.sb.log_lines()))

    def test_dry_run_prints_hook_plan_and_mutates_nothing(self) -> None:
        self.write_hook()
        self.rotation["test-hmac"]["hook"] = "full"
        self.sb.write_manifest(
            f"render\tsrv-a\tHMAC\t{SELF_MINTED_REF}\tself\n",
            rotation=self.rotation,
        )
        proc = self.rotate("--ref", SELF_MINTED_REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hook: scripts/secrets/rotate-hook (full)", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])


class ExcludeDestsDerivationTest(unittest.TestCase):
    """The Prefect-server topology invariant, now enforced structurally:
    exclude_dests removes a route from the ACTIVATION surface (consumers)
    while the route itself remains visible."""

    def test_exclude_dests_removes_activation_target_but_keeps_route(self) -> None:
        sb = SecretsSandbox()
        self.addCleanup(sb.close)
        ref = "op://TESTVAULT-sensitive/PG/value"
        sb.write_manifest(
            f"render\tsrv-app\tDATABASE_URL\t{ref}\tself\n"
            f"render\tsrv-server\tPREFECT_API_DATABASE_CONNECTION_URL\t{ref}\tself\n",
            rotation={
                "db": {
                    "ref": ref,
                    "provider": "postgres",
                    "mode": "DUAL_KEY",
                    "owner_repo": "repo",
                    "exclude_dests": ["srv-server"],
                }
            },
        )
        lib = ROOT / "secrets" / "lib" / "config.sh"
        env = sb.env(_SECRETS_CONFIG=str(sb.repo))
        proc = run(
            ["bash", "-c", f'source "{lib}"; reg="$(config_registry)" && cat "$reg"'],
            env,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        reg = json.loads(proc.stdout)
        entry = reg["secrets"][0]
        dests = [c["dest"] for c in entry["consumers"]]
        self.assertEqual(dests, ["srv-app"])
        route_dests = [r["dest"] for r in entry["routes"]]
        self.assertIn("srv-server", route_dests)


class CrossProjectFanOutTest(unittest.TestCase):
    """A credential routed by a SECOND project must have that project's manifest
    swept too. Before sync_repos the fan-out only ever reached the owning
    project, so the other project's destinations silently kept the retired
    value (the TS read-only prod DB credential that autodev's schema-drift gate
    consumes was exactly this)."""

    REF = "op://TESTVAULT/SHARED_TOKEN/value"

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        # A sibling project alongside the sandbox repo, routing the same ref.
        self.other = self.sb.root / "otherrepo"
        self.other.mkdir()
        (self.other / "secrets.yaml").write_text(
            yaml.safe_dump(
                {
                    "project": "otherproj",
                    "repos": ["otherrepo"],
                    "health": {},
                    "rotation": {},
                    "routes": [{
                        "repo": "otherrepo", "kind": "github", "dest": "otherorg/otherrepo",
                        "env": "SHARED_TOKEN", "ref": self.REF, "transform": "self",
                    }],
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        self.sb.write_manifest(
            f"render\tsrv-a\tSHARED_TOKEN\t{self.REF}\tself\n",
            rotation={
                "shared": {
                    "ref": self.REF,
                    "provider": "self_minted",
                    "mode": "SELF_MINTED",
                    "generate": {"format": "hex", "bytes": 16},
                    "owner_repo": "repo",
                    "sync_repos": ["../otherrepo"],
                }
            },
        )

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"), **extra)

    def rotate(self, *args: str, **kw: str):
        return run([ROTATE, "--repo", str(self.sb.repo), *args], self.env(**kw))

    def test_dry_run_lists_both_legs_and_the_cross_project_consumer(self) -> None:
        proc = self.rotate("--ref", self.REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(f"sync-secrets --repo {self.sb.repo} --changed {self.REF}", proc.stdout)
        self.assertIn(f"sync-secrets --repo {self.other} --changed {self.REF}", proc.stdout)
        self.assertIn("cross-project consumer:", proc.stdout)
        self.assertIn("otherorg/otherrepo", proc.stdout)

    def test_live_rotation_syncs_the_other_project_too(self) -> None:
        proc = self.rotate("--ref", self.REF, "--reason", "rotate shared", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        calls = [l for l in self.sb.log_lines() if l.startswith("SYNC ")]
        repos = sorted(l.split("--repo ")[1].split(" ")[0] for l in calls)
        self.assertEqual(repos, sorted([str(self.sb.repo), str(self.other)]))

    def test_failed_cross_project_leg_names_that_repo_in_the_recovery(self) -> None:
        proc = self.rotate("--ref", self.REF, "--reason", "t", "--yes", FAKE_SYNC_EXIT="1")
        self.assertEqual(proc.returncode, 5)
        self.assertIn(f"sync-secrets --repo {self.other} --changed {self.REF}", proc.stderr)


if __name__ == "__main__":
    unittest.main()

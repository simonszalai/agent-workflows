"""End-to-end coverage for bin/sync-secrets against fake op/gh/curl."""

from __future__ import annotations

import unittest

from secrets_common import ROOT, SENSITIVE_MANIFEST, SecretsSandbox, run

SYNC = str(ROOT / "bin" / "sync-secrets")
RENDER_WRITER = str(ROOT / "secrets" / "lib" / "writers" / "render")

# Canonical DB env names are owned by the postgres tooling, never plain sync.
DB_GUARD_MANIFEST = "\n".join(
    [
        "render\tsrv-alpha\tDATABASE_URL\top://TESTVAULT/PG_APP/value\tself",
        "render\tsrv-alpha\tMIGRATE_DATABASE_URL\top://TESTVAULT/PG_OWNER/value\tself",
        "render\tsrv-alpha\tSYSTEM_DATABASE_URL\top://TESTVAULT/PG_OWNER/value\tself",
        "render\tsrv-alpha\tALPHA_ONE\top://TESTVAULT/ITEM/value\tself",
        "render\tsrv-beta\tDATABASE_URL_GLOBAL\top://TESTVAULT/PG_APP/value\tdb=mem_global",
        "github\ttestorg/testrepo\tDATABASE_URL_PROD\top://TESTVAULT/PG_OWNER/value\tself",
        "",
    ]
)


class SyncSecretsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def sync(self, *args: str, env: dict[str, str] | None = None):
        return run(
            [SYNC, "--repo", str(self.sb.repo), *args],
            env if env is not None else self.sb.env(),
        )

    # --- dry-run ------------------------------------------------------------

    def test_dry_run_is_credential_free_and_writes_nothing(self) -> None:
        proc = self.sync("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("gh[testorg/testrepo] GH_TOKEN_A", proc.stdout)
        self.assertIn("render[srv-alpha] ALPHA_ONE", proc.stdout)
        # dry-run: not one fake call — no op, no gh, no curl, no project layer
        self.assertEqual(self.sb.log_lines(), [])

    def test_dry_run_works_from_agent_shells(self) -> None:
        proc = self.sync("--dry-run", env=self.sb.env(CLAUDECODE="1"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_default_sweep_never_includes_prefect(self) -> None:
        proc = self.sync("--dry-run")
        self.assertNotIn("prefect[", proc.stdout)

    # --- usage / manifest gates ----------------------------------------------

    def test_missing_manifest_exits_2_with_clear_message(self) -> None:
        (self.sb.repo / "scripts" / "secrets" / "manifest").unlink()
        proc = self.sync("--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no secrets manifest", proc.stderr)

    def test_malformed_manifest_fails_whole_file_before_any_action(self) -> None:
        self.sb.write_manifest("github\ta/b\tNAME\top://V/I/value\n")
        proc = self.sync()
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.sb.log_lines(), [])

    def test_changed_cannot_combine_with_channel(self) -> None:
        proc = self.sync("--changed", "op://TESTVAULT/ITEM/value", "--channel", "render")
        self.assertEqual(proc.returncode, 2)

    def test_bad_changed_ref_form_is_usage_error(self) -> None:
        proc = self.sync("--changed", "ITEM")
        self.assertEqual(proc.returncode, 2)

    # --- live sweep -----------------------------------------------------------

    def test_full_sweep_pushes_github_and_render_with_deploys_last(self) -> None:
        proc = self.sync("--reason", "test sweep")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        lines = self.sb.log_lines()
        gh_lines = [i for i, l in enumerate(lines) if l.startswith("GH secret set")]
        put_lines = [i for i, l in enumerate(lines) if "CURL PUT" in l]
        deploy_lines = [i for i, l in enumerate(lines) if "CURL POST" in l and "/deploys" in l]
        self.assertEqual(len(gh_lines), 1)
        self.assertEqual(len(put_lines), 4)  # ALPHA_ONE, ALPHA_TWO, BETA_ONE, BETA_LIT
        self.assertEqual(len(deploy_lines), 2)  # one per touched service
        # deploy-last: every PUT strictly precedes the first deploy
        self.assertLess(max(put_lines), min(deploy_lines))
        # no secret value ever hit stdout/stderr
        self.assertNotIn("val-", proc.stdout + proc.stderr)

    def test_no_deploy_flag_pushes_without_triggering_deploys(self) -> None:
        proc = self.sync("--reason", "test", "--no-deploy")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertFalse(any("/deploys" in l for l in self.sb.log_lines()))

    def test_empty_resolve_refuses_write_and_nothing_is_pushed(self) -> None:
        self.sb.write_manifest(
            "render\tsrv-alpha\tGOOD\top://TESTVAULT/ITEM/value\tself\n"
            "render\tsrv-alpha\tBAD\top://TESTVAULT/EMPTY_ITEM/value\tself\n"
        )
        proc = self.sync("--reason", "test")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("EMPTY VALUE", proc.stderr)
        lines = self.sb.log_lines()
        # batch validation: zero PUTs, zero deploys — even for the good row
        self.assertFalse(any("CURL" in l for l in lines))

    def test_failed_put_triggers_zero_deploys(self) -> None:
        proc = self.sync(
            "--reason", "test",
            env=self.sb.env(FAKE_CURL_FAIL_URL_SUBSTR="env-vars/ALPHA_ONE"),
        )
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(any("/deploys" in l for l in self.sb.log_lines()))

    # --- --changed routing ------------------------------------------------------

    def put_envnames(self) -> set[str]:
        return {
            line.rsplit("/", 1)[-1]
            for line in self.sb.log_lines()
            if "CURL PUT" in line
        }

    def test_changed_full_ref_matches_by_exact_equality(self) -> None:
        proc = self.sync("--changed", "op://TESTVAULT/ITEM/value", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.put_envnames(), {"ALPHA_ONE"})
        self.assertTrue(any(l.startswith("GH secret set GH_TOKEN_A") for l in self.sb.log_lines()))

    def test_changed_item_form_matches_prefix_never_bare_substring(self) -> None:
        # op://TESTVAULT/ITEM must match ITEM rows but NOT ITEM2 rows
        proc = self.sync("--changed", "op://TESTVAULT/ITEM", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.put_envnames(), {"ALPHA_ONE"})
        self.assertNotIn("BETA_ONE", proc.stdout)

    def test_changed_with_zero_matches_exits_1(self) -> None:
        proc = self.sync("--changed", "op://TESTVAULT/NOSUCH/value", "--reason", "t")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(self.sb.log_lines(), [])

    # --- DB-credential guard ----------------------------------------------------

    def test_full_sweep_skips_db_credential_rows_but_pushes_everything_else(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync("--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # exact-name rows skipped with the pointer note
        for env in ("DATABASE_URL", "MIGRATE_DATABASE_URL", "SYSTEM_DATABASE_URL"):
            self.assertIn(f"{env}  skipped (db credential", proc.stdout)
        # derived per-database credential and ordinary rows still push
        self.assertEqual(self.put_envnames(), {"ALPHA_ONE", "DATABASE_URL_GLOBAL"})
        # github DATABASE_URL_PROD is NOT in the guarded set (exact match only)
        self.assertTrue(any(l.startswith("GH secret set DATABASE_URL_PROD") for l in self.sb.log_lines()))

    def test_sweep_with_only_db_credential_rows_deploys_nothing(self) -> None:
        self.sb.write_manifest(
            "render\tsrv-alpha\tDATABASE_URL\top://TESTVAULT/PG_APP/value\tself\n"
        )
        proc = self.sync("--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("skipped (db credential", proc.stdout)
        self.assertFalse(any("CURL" in l for l in self.sb.log_lines()))

    def test_dry_run_marks_skipped_db_credential_rows_and_reads_nothing(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DATABASE_URL  skipped (db credential", proc.stdout)
        self.assertIn("render[srv-alpha] ALPHA_ONE", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_changed_selecting_a_db_credential_row_exits_2_before_any_write(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync("--changed", "op://TESTVAULT/PG_APP/value", "--reason", "t")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("DB credential", proc.stderr)
        self.assertIn("rotate-secret", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_changed_item_prefix_form_selecting_db_credentials_also_exits_2(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync("--changed", "op://TESTVAULT/PG_OWNER", "--reason", "t")
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.sb.log_lines(), [])

    def test_render_writer_ref_selection_of_db_credential_exits_2_directly(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        env = self.sb.env(
            _MANIFEST_FILE=str(self.sb.repo / "scripts" / "secrets" / "manifest"),
        )
        proc = run([RENDER_WRITER, "--ref", "op://TESTVAULT/PG_APP/value"], env)
        self.assertEqual(proc.returncode, 2)
        self.assertIn("db-provision-roles", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    # --- --include-db (initial DB cutover override) ------------------------------

    def test_include_db_without_changed_selection_exits_2_and_writes_nothing(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync("--include-db", "--reason", "t")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--include-db needs a targeted --changed selection", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_include_db_without_reason_exits_2_and_writes_nothing(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync("--include-db", "--changed", "op://TESTVAULT/PG_APP/value")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--include-db requires --reason", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_include_db_with_changed_pushes_db_row_and_triggers_deploy(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync(
            "--changed", "op://TESTVAULT/PG_APP/value",
            "--include-db", "--reason", "initial cutover srv-alpha",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # the canonical DB row pushes like a normal row; derived row untouched scope
        self.assertEqual(self.put_envnames(), {"DATABASE_URL", "DATABASE_URL_GLOBAL"})
        self.assertTrue(any("CURL POST" in l and "/deploys" in l for l in self.sb.log_lines()))
        # no secret value ever hit stdout/stderr
        self.assertNotIn("val-", proc.stdout + proc.stderr)

    def test_include_db_cannot_combine_with_skip_db_rows(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        proc = self.sync(
            "--changed", "op://TESTVAULT/PG_APP/value",
            "--include-db", "--skip-db-rows", "--reason", "t",
        )
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.sb.log_lines(), [])

    def test_render_writer_include_db_without_ref_selection_exits_2(self) -> None:
        self.sb.write_manifest(DB_GUARD_MANIFEST)
        env = self.sb.env(
            _MANIFEST_FILE=str(self.sb.repo / "scripts" / "secrets" / "manifest"),
        )
        proc = run([RENDER_WRITER, "--include-db", "--reason", "t"], env)
        self.assertEqual(proc.returncode, 2)
        self.assertEqual(self.sb.log_lines(), [])

    # --- refusals ----------------------------------------------------------------

    def test_sensitive_read_from_agent_shell_refuses_rc3_with_empty_log(self) -> None:
        self.sb.write_manifest(SENSITIVE_MANIFEST)
        proc = self.sync("--reason", "t", env=self.sb.env(CLAUDECODE="1"))
        self.assertEqual(proc.returncode, 3)
        self.assertIn("agent shell", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_live_run_without_any_sa_token_fails_closed(self) -> None:
        env = self.sb.env(sa_token=False)
        proc = self.sync("--reason", "t", env=env)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("no project service-account token", proc.stderr)
        self.assertFalse(any("CURL" in l or l.startswith("GH") for l in self.sb.log_lines()))


if __name__ == "__main__":
    unittest.main()

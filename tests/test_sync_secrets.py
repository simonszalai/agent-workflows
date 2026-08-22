"""End-to-end coverage for bin/sync-secrets against fake op/gh/curl."""

from __future__ import annotations

import unittest

from secrets_common import ROOT, SENSITIVE_MANIFEST, SecretsSandbox, run

SYNC = str(ROOT / "bin" / "sync-secrets")
RENDER_WRITER = str(ROOT / "secrets" / "lib" / "writers" / "render")
GITHUB_WRITER = str(ROOT / "secrets" / "lib" / "writers" / "github")
PREFECT_WRITER = str(ROOT / "secrets" / "lib" / "writers" / "prefect")
HERMES_WRITER = str(ROOT / "secrets" / "lib" / "writers" / "hermes")

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

    def test_default_sweep_includes_both_prefect_tiers(self) -> None:
        proc = self.sync("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("prefect[staging] PF_ONE", proc.stdout)
        self.assertIn("no prefect:prod rows", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_prod_prefect_tier_runs_last_and_needs_confirmation_or_assume_yes(self) -> None:
        self.sb.write_manifest(
            "render\tsrv-alpha\tALPHA_ONE\top://TESTVAULT/ITEM/value\tself\n"
            "prefect\tstaging\tPF_ONE\top://TESTVAULT/ITEM/value\tself\n"
            "prefect\tprod\tPF_PROD\top://TESTVAULT/ITEM/value\tself\n"
        )
        # no tty, no SECRETS_ASSUME_YES: the prod tier aborts (exit 3), staging saved
        proc = run([SYNC, "--repo", str(self.sb.repo), "--reason", "t"], self.sb.env(), stdin="")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("Aborted", proc.stderr)
        self.assertEqual(len([l for l in self.sb.log_lines() if l.startswith("UV ")]), 1)
        self.assertLess(proc.stdout.index("== sync-secrets: render"),
                        proc.stdout.index("== sync-secrets: prefect:prod"))
        # a confirmed rotation (rotate-secret exports SECRETS_ASSUME_YES=1) saves both tiers
        self.sb.log_path.write_text("", encoding="utf-8")
        proc = self.sync("--reason", "t", env=self.sb.env(SECRETS_ASSUME_YES="1"))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(len([l for l in self.sb.log_lines() if l.startswith("UV ")]), 2)
        self.assertIn("save_blocks.py --yes", "\n".join(self.sb.log_lines()))

    def test_hermes_channel_dry_run_is_credential_free(self) -> None:
        self.sb.write_manifest(
            "hermes\t/etc/hermes-mcp/autodev-memory.token\tMEM_TOKEN\top://TESTVAULT/ITEM/value\tself\n"
            "hermes\t/etc/hermes-schedules/op.token\tOP_TOKEN\top://TESTVAULT/ITEM/value\tself\n",
            hermes={"ssh": "testbox"},
        )
        proc = self.sync("--channel", "hermes", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hermes[/etc/hermes-mcp/autodev-memory.token] MEM_TOKEN", proc.stdout)
        self.assertIn("restart hermes-autodev-mcp", proc.stdout)
        # schedule tokens are read per timer run: no restart annotation
        self.assertNotIn("op.token] OP_TOKEN <- op://TESTVAULT/ITEM/value (self) + restart", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_default_sweep_includes_hermes_rows(self) -> None:
        self.sb.write_manifest(
            "github\ttestorg/testrepo\tGH_TOKEN_A\top://TESTVAULT/ITEM/value\tself\n"
            "hermes\t/etc/hermes-schedules/slack.token\tSLACK\top://TESTVAULT/ITEM/value\tself\n",
            hermes={"ssh": "testbox"},
        )
        proc = self.sync("--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("hermes[/etc/hermes-schedules/slack.token] SLACK", proc.stdout)

    # --- usage / manifest gates ----------------------------------------------

    def test_missing_config_exits_2_with_clear_message(self) -> None:
        (self.sb.repo / "secrets.yaml").unlink()
        proc = self.sync("--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no secrets config", proc.stderr)

    def test_changed_ref_with_only_prefect_dev_rows_succeeds(self) -> None:
        # A rotated ref may legitimately route only to prefect/dev — the
        # github+render sweep has nothing to push and must NOT fail the
        # rotation's fan-out leg (2026-08-08: ts-prefect-db-staging).
        self.sb.write_manifest(
            "prefect\tstaging\tDB_URL\top://TESTVAULT/ONLYPF/value\tself\n"
            "dev\tprofile\tDB_URL\top://TESTVAULT/ONLYPF/value\tself\n"
            "render\tsrv-alpha\tOTHER\top://TESTVAULT/ITEM/value\tself\n"
        )
        proc = self.sync("--changed", "op://TESTVAULT/ONLYPF/value", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # prefect is a default channel: the staging tier saved its block
        self.assertEqual(len([l for l in self.sb.log_lines() if l.startswith("UV ")]), 1)
        self.assertFalse(any("CURL PUT" in l for l in self.sb.log_lines()))

    def test_changed_ref_with_only_dev_rows_is_a_fact_not_a_failure(self) -> None:
        self.sb.write_manifest(
            "dev\tprofile\tDB_URL\top://TESTVAULT/ONLYDEV/value\tself\n"
            "render\tsrv-alpha\tOTHER\top://TESTVAULT/ITEM/value\tself\n"
        )
        proc = self.sync("--changed", "op://TESTVAULT/ONLYDEV/value", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("routes only to dev", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_changed_ref_matching_nothing_still_errors(self) -> None:
        proc = self.sync("--changed", "op://TESTVAULT/TYPO/value", "--reason", "t")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("matched no routes at all", proc.stderr)

    def test_malformed_manifest_fails_whole_file_before_any_action(self) -> None:
        self.sb.write_manifest("github\ta/b\tNAME\top://V/I/value\n")
        proc = self.sync()
        self.assertEqual(proc.returncode, 2)
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
        env = self.sb.env(_SECRETS_CONFIG=str(self.sb.repo))
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
        env = self.sb.env(_SECRETS_CONFIG=str(self.sb.repo))
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

    # --- render diff-before-PUT / deploy correlation ----------------------------

    def _env_dir(self, **values: str):
        d = self.sb.root / "render-env"
        d.mkdir(exist_ok=True)
        for name, value in values.items():
            (d / name).write_text(value, encoding="utf-8")
        return str(d)

    def test_unchanged_values_are_not_put_and_untouched_services_do_not_deploy(self) -> None:
        # srv-beta already holds both of its values; srv-alpha differs.
        envd = self._env_dir(BETA_ONE="val-ITEM2-value", BETA_LIT="plain-config")
        proc = self.sync("--reason", "t", env=self.sb.env(FAKE_CURL_ENV_DIR=envd))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.put_envnames(), {"ALPHA_ONE", "ALPHA_TWO"})
        self.assertIn("render[srv-beta] BETA_ONE  unchanged", proc.stdout)
        self.assertIn("render[srv-beta] no changes — deploy skipped", proc.stdout)
        deploys = [l for l in self.sb.log_lines() if "CURL POST" in l and "/deploys" in l]
        self.assertEqual(len(deploys), 1)
        self.assertIn("srv-alpha", deploys[0])

    def test_all_values_unchanged_means_zero_deploys(self) -> None:
        envd = self._env_dir(ALPHA_ONE="val-ITEM-value", ALPHA_TWO="val-OTHER-value",
                             BETA_ONE="val-ITEM2-value", BETA_LIT="plain-config")
        proc = self.sync("--reason", "t", "--channel", "render",
                         env=self.sb.env(FAKE_CURL_ENV_DIR=envd))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.put_envnames(), set())
        self.assertFalse(any("/deploys" in l and "POST" in l for l in self.sb.log_lines()))

    def test_rotation_deploys_every_touched_service_even_when_unchanged(self) -> None:
        # Under a rotation ($SYNC_DEPLOYS_FILE set) a resumed fan-out must
        # redeploy services whose values were already saved by the failed
        # attempt, or prove_live would pass against the OLD instance.
        envd = self._env_dir(ALPHA_ONE="val-ITEM-value", ALPHA_TWO="val-OTHER-value",
                             BETA_ONE="val-ITEM2-value", BETA_LIT="plain-config")
        out = self.sb.root / "deploys.tsv"
        proc = self.sync("--reason", "t", "--channel", "render",
                         env=self.sb.env(FAKE_CURL_ENV_DIR=envd, SYNC_DEPLOYS_FILE=str(out)))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.put_envnames(), set())
        self.assertIn("deploying anyway", proc.stdout)
        rows = sorted(l.split("\t") for l in out.read_text().splitlines())
        self.assertEqual(rows, [["srv-alpha", "dep-srv-alpha"], ["srv-beta", "dep-srv-beta"]])

    def test_deploy_ids_are_recorded_to_sync_deploys_file(self) -> None:
        out = self.sb.root / "deploys.tsv"
        proc = self.sync("--reason", "t", "--channel", "render",
                         env=self.sb.env(SYNC_DEPLOYS_FILE=str(out)))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = sorted(l.split("\t") for l in out.read_text().splitlines())
        self.assertEqual(rows, [["srv-alpha", "dep-srv-alpha"], ["srv-beta", "dep-srv-beta"]])
        self.assertIn("deploy triggered (dep-srv-alpha)", proc.stdout)

    def test_env_only_deploys_use_deploy_only_mode(self) -> None:
        # The deploy POST body travels via stdin; the fake logs only method+url,
        # so prove the mode through the helper itself.
        script = (
            f'source "{ROOT}/secrets/lib/read.sh"; source "{ROOT}/secrets/lib/render-api.sh"; '
            'RENDER_API_KEY=k; curl() { case "$*" in *limit=1*) cat >/dev/null; printf "[]\\n200" ;; '
            '*) cat > "$FAKE_OP_STATE/body"; printf \'{"id":"dep-1"}\\n201\' ;; esac; }; '
            'render_trigger_deploy_id srv-x'
        )
        proc = run(["bash", "-c", script], self.sb.env())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "dep-1")
        self.assertIn('"deployMode":"deploy_only"', (self.sb.state / "body").read_text())

    # --- retries ------------------------------------------------------------------

    def test_transient_curl_rc_is_retried_and_the_put_succeeds(self) -> None:
        env = self.sb.env(FAKE_CURL_RC_URL_SUBSTR="env-vars/ALPHA_ONE", FAKE_CURL_RC="56",
                          FAKE_CURL_RC_TIMES="2", RETRY_BASE_SECONDS="0")
        proc = self.sync("--reason", "t", "--channel", "render", "--only", "ALPHA_ONE", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("ALPHA_ONE  OK", proc.stdout)
        puts = [l for l in self.sb.log_lines() if "CURL PUT" in l]
        # 2 injected failures are spent on the GET+PUT pair; the PUT still lands
        self.assertGreaterEqual(len(puts), 1)

    def test_http_5xx_on_put_is_retried_then_succeeds(self) -> None:
        env = self.sb.env(FAKE_CURL_5XX_URL_SUBSTR="env-vars/ALPHA_ONE", FAKE_CURL_5XX_TIMES="3",
                          RETRY_BASE_SECONDS="0")
        proc = self.sync("--reason", "t", "--channel", "render", "--only", "ALPHA_ONE", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        calls = [l for l in self.sb.log_lines() if "env-vars/ALPHA_ONE" in l]
        self.assertGreaterEqual(len(calls), 4)  # 3 x 503 + the one that landed
        self.assertTrue(any("/deploys" in l for l in self.sb.log_lines()))

    def test_exhausted_5xx_retries_fail_the_row_and_trigger_no_deploy(self) -> None:
        env = self.sb.env(FAKE_CURL_5XX_URL_SUBSTR="env-vars/ALPHA_ONE", FAKE_CURL_5XX_TIMES="99",
                          RETRY_BASE_SECONDS="0", RETRY_MAX="1")
        proc = self.sync("--reason", "t", "--channel", "render", env=env)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("PUT FAILED", proc.stderr)
        self.assertIn("HTTP 503", proc.stderr)
        self.assertNotIn("upstream unavailable\n", proc.stderr.replace("HTTP 503: ", "", 1))
        self.assertFalse(any("/deploys" in l and "POST" in l for l in self.sb.log_lines()))

    def test_gh_transient_http_error_is_retried(self) -> None:
        env = self.sb.env(FAKE_GH_FAIL_TIMES="2", RETRY_BASE_SECONDS="0")
        proc = self.sync("--reason", "t", "--channel", "github", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(len([l for l in self.sb.log_lines() if l.startswith("GH secret set")]), 3)
        self.assertIn("GH_TOKEN_A  OK", proc.stdout)

    def test_github_rows_are_all_attempted_and_failures_collected(self) -> None:
        self.sb.write_manifest(
            "github\ttestorg/testrepo\tA_ONE\top://TESTVAULT/ITEM/value\tself\n"
            "github\ttestorg/testrepo\tA_TWO\top://TESTVAULT/ITEM2/value\tself\n"
            "github\ttestorg/testrepo\tA_THREE\top://TESTVAULT/OTHER/value\tself\n"
        )
        # a non-transient gh failure on the first call only
        gh = self.sb.fakebin / "gh"
        gh.write_text(
            gh.read_text().replace('>> "$FAKE_LOG"\n',
                '>> "$FAKE_LOG"\nif [[ "$*" == *A_ONE* ]]; then echo "permission denied" >&2; exit 1; fi\n', 1),
            encoding="utf-8")
        proc = self.sync("--reason", "t", "--channel", "github", env=self.sb.env(SYNC_PUT_CONCURRENCY="1"))
        self.assertEqual(proc.returncode, 1)
        sets = [l for l in self.sb.log_lines() if l.startswith("GH secret set")]
        self.assertEqual(len(sets), 3)  # every row attempted; no retry of a hard failure
        self.assertIn("A_ONE: SET FAILED", proc.stderr)
        self.assertIn("A_TWO  OK", proc.stdout)

    def test_put_concurrency_is_validated(self) -> None:
        proc = self.sync("--reason", "t", "--channel", "render", env=self.sb.env(SYNC_PUT_CONCURRENCY="lots"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("SYNC_PUT_CONCURRENCY", proc.stderr)
        self.assertFalse(any("CURL" in l for l in self.sb.log_lines()))

    # --- concurrency across channels ------------------------------------------------

    def test_channels_run_concurrently(self) -> None:
        # Each fake blocks until the OTHER channel's fake has started: a
        # sequential github-then-render run deadlocks into the fakes' timeout.
        barrier = self.sb.root / "barrier"
        barrier.mkdir()
        proc = self.sync("--reason", "t", env=self.sb.env(FAKE_BARRIER_DIR=str(barrier)))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("GH_TOKEN_A  OK", proc.stdout)
        self.assertIn("ALPHA_ONE  OK", proc.stdout)
        # output is replayed per channel, in channel order, never interleaved
        self.assertLess(proc.stdout.index("== sync-secrets: github"), proc.stdout.index("== sync-secrets: render"))

    def test_prefect_channel_count_is_tier_scoped_like_its_writer(self) -> None:
        # Only a PROD prefect row exists: the staging tier must report "no
        # rows" rather than launching the writer on zero rows.
        self.sb.write_manifest("prefect\tprod\tPF_PROD\top://TESTVAULT/ITEM/value\tself\n")
        proc = self.sync("--channel", "prefect", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("no prefect:staging rows", proc.stdout)
        self.assertIn("prefect[prod] PF_PROD", proc.stdout)
        proc = self.sync("--channel", "prefect", "--dest", "staging", "--dry-run")
        self.assertIn("no prefect:staging rows", proc.stdout)
        self.assertNotIn("PF_PROD", proc.stdout)
        proc = self.sync("--channel", "prefect", "--dest", "srv-x", "--dry-run")
        self.assertEqual(proc.returncode, 2)

    # --- prefect env-name validation ------------------------------------------------

    def test_prefect_refuses_reserved_or_malformed_env_names(self) -> None:
        for name in ("PATH", "lower", "1BAD", "LD_PRELOAD"):
            with self.subTest(name):
                self.sb.write_manifest(f"prefect\tstaging\t{name}\top://TESTVAULT/ITEM/value\tself\n")
                env = self.sb.env(_SECRETS_CONFIG=str(self.sb.repo))
                proc = run([PREFECT_WRITER, "--repo", str(self.sb.repo), "--dry-run"], env)
                self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
                self.assertEqual(self.sb.log_lines(), [])

    # --- hermes batch over one ssh session ----------------------------------------

    def test_hermes_writes_the_batch_in_one_remote_script(self) -> None:
        self.sb.write_manifest(
            "hermes\t/etc/hermes-mcp/autodev-memory.token\tMEM_TOKEN\top://TESTVAULT/ITEM/value\tself\n"
            "hermes\t/etc/hermes-schedules/op.token\tOP_TOKEN\top://TESTVAULT/ITEM2/value\tself\n",
            hermes={"ssh": "testbox"},
        )
        box = self.sb.root / "box"
        box.mkdir()
        proc = self.sync("--channel", "hermes", "--reason", "t", env=self.sb.env(FAKE_SSH_DIR=str(box)))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        ssh_calls = [l for l in self.sb.log_lines() if l.startswith("SSH ")]
        self.assertEqual(len(ssh_calls), 2)  # reachability probe + ONE batch script
        self.assertIn("mktemp", self.sb.log_path.read_text())
        self.assertEqual((box / "autodev-memory.token").read_text(), "val-ITEM-value")
        self.assertEqual((box / "op.token").read_text(), "val-ITEM2-value")
        self.assertIn("autodev-memory.token] MEM_TOKEN  OK", proc.stdout)
        self.assertIn("restarted hermes-autodev-mcp", proc.stdout)
        self.assertNotIn("val-", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()

"""Unit coverage for the shared secrets engine libraries (secrets/lib/)."""

from __future__ import annotations

import subprocess
import unittest

import yaml

from secrets_common import ROOT, SHELL_FILES, SecretsSandbox, run

LIB = ROOT / "secrets" / "lib"


def bash_lib(snippet: str, env: dict[str, str], *, stdin: str | None = None,
             config: str | None = None) -> subprocess.CompletedProcess[str]:
    if config is not None:
        env = dict(env)
        env["_SECRETS_CONFIG"] = config
    script = f'source "{LIB}/config.sh"; source "{LIB}/read.sh"; source "{LIB}/derive.sh"; {snippet}'
    return run(["bash", "-c", script], env, stdin=stdin)


class ShellSyntaxTest(unittest.TestCase):
    def test_every_engine_shell_file_parses_under_bash_n(self) -> None:
        for rel in SHELL_FILES:
            with self.subTest(rel):
                proc = subprocess.run(
                    ["bash", "-n", str(ROOT / rel)], capture_output=True, text=True
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)


class ManifestValidationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.config = self.sb.repo

    def validate(self, content: str) -> subprocess.CompletedProcess[str]:
        self.sb.write_manifest(content)
        return bash_lib("config_validate", self.sb.env(), config=str(self.config))

    def test_committed_style_config_validates_cleanly(self) -> None:
        proc = bash_lib("config_validate", self.sb.env(), config=str(self.config))
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_wrong_field_count_rejects_the_whole_manifest(self) -> None:
        proc = self.validate("github\ta/b\tNAME\top://V/I/value\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing/empty", proc.stderr)

    def test_empty_field_rejects(self) -> None:
        proc = self.validate("github\t\tNAME\top://V/I/value\tself\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("missing/empty dest", proc.stderr)

    def test_unknown_kind_rejects(self) -> None:
        proc = self.validate("s3\ta/b\tNAME\top://V/I/value\tself\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unknown kind", proc.stderr)

    def test_unknown_transform_rejects(self) -> None:
        proc = self.validate("github\ta/b\tNAME\top://V/I/value\trot13\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("unknown transform", proc.stderr)

    def test_ref_missing_field_segment_rejects(self) -> None:
        proc = self.validate("github\ta/b\tNAME\top://V/I\tself\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("REF needs vault/item/field", proc.stderr)

    def test_arbitrary_field_names_are_accepted_for_product_grouped_items(self) -> None:
        proc = self.validate("render\tsrv-x\tDATABASE_URL\top://V/Postgres prod/app\tself\n")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_duplicate_kind_dest_envname_rejects(self) -> None:
        proc = self.validate(
            "github\ta/b\tNAME\top://V/I/value\tself\n"
            "github\ta/b\tNAME\top://V/J/value\tself\n"
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("duplicate route", proc.stderr)

    # --- sync_repos (cross-project fan-out) -----------------------------------

    def _with_sync_repos(self, value, sibling: dict | None = None) -> subprocess.CompletedProcess[str]:
        """Write a one-route/one-rotation config declaring sync_repos=value, plus
        an optional sibling project config at <root>/other/secrets.yaml."""
        ref = "op://V/I/value"
        if sibling is not None:
            other = self.sb.root / "other"
            other.mkdir(exist_ok=True)
            (other / "secrets.yaml").write_text(
                yaml.safe_dump(sibling, sort_keys=False), encoding="utf-8"
            )
        self.sb.write_manifest(
            f"render\tsrv-x\tE\t{ref}\tself\n",
            rotation={"e1": {
                "ref": ref, "provider": "self_minted", "mode": "SELF_MINTED",
                "owner_repo": "repo", "sync_repos": value,
            }},
        )
        return bash_lib("config_validate", self.sb.env(), config=str(self.config))

    def _sibling(self, project: str, ref: str) -> dict:
        return {
            "project": project, "repos": ["other"], "health": {}, "routes": [
                {"repo": "other", "kind": "github", "dest": "o/o",
                 "env": "E", "ref": ref, "transform": "self"}
            ],
        }

    def test_sync_repos_accepts_a_sibling_project_routing_the_same_ref(self) -> None:
        proc = self._with_sync_repos(
            ["../other"], self._sibling("otherproj", "op://V/I/value")
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_sync_repos_rejects_a_nonexistent_repo(self) -> None:
        proc = self._with_sync_repos(["../nope"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("does not exist", proc.stderr)

    def test_sync_repos_rejects_the_same_project(self) -> None:
        proc = self._with_sync_repos(
            ["../other"], self._sibling("testproj", "op://V/I/value")
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("is the same project", proc.stderr)

    def test_sync_repos_rejects_a_sibling_that_does_not_route_the_ref(self) -> None:
        proc = self._with_sync_repos(
            ["../other"], self._sibling("otherproj", "op://V/UNRELATED/value")
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("routes none of", proc.stderr)

    def test_sync_repos_rejects_a_bare_string(self) -> None:
        proc = self._with_sync_repos("../other", self._sibling("otherproj", "op://V/I/value"))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("must be a list of non-empty strings", proc.stderr)

    def test_missing_manifest_file_returns_2(self) -> None:
        proc = bash_lib(
            "config_validate", self.sb.env(), config=str(self.sb.root / "nope")
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("no secrets config", proc.stderr)

    def test_config_rows_ref_filter_is_exact_equality_not_substring(self) -> None:
        self.sb.write_manifest(
            "render\tsrv-x\tA\top://V/ITEM/value\tself\n"
            "render\tsrv-x\tB\top://V/ITEM2/value\tself\n"
        )
        proc = bash_lib(
            'config_rows render "" "op://V/ITEM/value"',
            self.sb.env(),
            config=str(self.config),
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("\tA\t", proc.stdout)
        self.assertNotIn("ITEM2", proc.stdout)


class DeriveTransformTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def derive(self, transform: str, value: str) -> subprocess.CompletedProcess[str]:
        return bash_lib(f"apply_transform '{transform}'", self.sb.env(), stdin=value)

    URL = "postgresql://user:p%40ss@host.frankfurt-postgres.render.com:5432/maindb?sslmode=require"

    def test_self_passes_through(self) -> None:
        proc = self.derive("self", "plain-value\n")
        self.assertEqual((proc.returncode, proc.stdout), (0, "plain-value"))

    def test_no_query_strips_options(self) -> None:
        proc = self.derive("no-query", self.URL)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(
            proc.stdout,
            "postgresql://user:p%40ss@host.frankfurt-postgres.render.com:5432/maindb",
        )

    def test_conn_id_accepts_kinde_connection_ids_only(self) -> None:
        ok = self.derive("conn-id", "conn_abc123")
        self.assertEqual((ok.returncode, ok.stdout), (0, "conn_abc123"))
        bad = self.derive("conn-id", "not-a-conn-id")
        self.assertEqual(bad.returncode, 3)

    def test_db_swaps_database_and_keeps_query(self) -> None:
        proc = self.derive("db=mem_ts", self.URL)
        self.assertEqual(
            proc.stdout,
            "postgresql://user:p%40ss@host.frankfurt-postgres.render.com:5432/mem_ts?sslmode=require",
        )

    def test_pgbouncer_forces_plain_scheme_and_drops_query(self) -> None:
        proc = self.derive("pgbouncer=bouncer:6432/mydb", self.URL)
        self.assertEqual(proc.stdout, "postgresql://user:p%40ss@bouncer:6432/mydb")

    def test_asyncpg_internal_uses_short_host(self) -> None:
        proc = self.derive("asyncpg-internal=prefect", self.URL)
        self.assertEqual(proc.stdout, "postgresql+asyncpg://user:p%40ss@host:5432/prefect")

    def test_asyncpg_external_keeps_full_host(self) -> None:
        proc = self.derive("asyncpg-external=prefect", self.URL)
        self.assertEqual(
            proc.stdout,
            "postgresql+asyncpg://user:p%40ss@host.frankfurt-postgres.render.com:5432/prefect",
        )

    def test_empty_stdin_exits_2(self) -> None:
        self.assertEqual(self.derive("self", "").returncode, 2)

    def test_unknown_transform_exits_3(self) -> None:
        proc = self.derive("nonsense=1", "x")
        self.assertEqual(proc.returncode, 3)
        self.assertIn("unknown transform", proc.stderr)


class ReadDispatchTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)

    def test_resolve_ref_literal_never_calls_op(self) -> None:
        proc = bash_lib('resolve_ref "literal:hello"', self.sb.env())
        self.assertEqual((proc.returncode, proc.stdout), (0, "hello"))
        self.assertEqual(self.sb.log_lines(), [])

    def test_plain_ref_uses_the_project_service_account_token(self) -> None:
        env = self.sb.env(
            SECRETS_SA_TOKEN_ENV="TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
            SECRETS_SA_KEYCHAIN_ITEM="op-testproj-token",
        )
        proc = bash_lib('resolve_ref "op://TESTVAULT/ITEM/value"', env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "val-ITEM-value")
        self.assertTrue(any(line.startswith("OP read") for line in self.sb.log_lines()))

    def test_plain_ref_without_any_token_fails_closed_no_ambient_fallback(self) -> None:
        env = self.sb.env(
            sa_token=False,
            SECRETS_SA_TOKEN_ENV="TESTPROJ_OP_SERVICE_ACCOUNT_TOKEN",
            SECRETS_SA_KEYCHAIN_ITEM="op-testproj-token",
        )
        proc = bash_lib('resolve_ref "op://TESTVAULT/ITEM/value"', env)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("no project service-account token", proc.stderr)
        self.assertFalse(any(line.startswith("OP read") for line in self.sb.log_lines()))

    def test_sensitive_ref_refuses_agent_shell_before_touching_op(self) -> None:
        env = self.sb.env(CLAUDECODE="1")
        proc = bash_lib('resolve_ref "op://TESTVAULT-sensitive/SECRETX/value"', env)
        self.assertEqual(proc.returncode, 3)
        self.assertIn("agent shell", proc.stderr)
        self.assertEqual(self.sb.log_lines(), [])

    def test_sensitive_ref_escape_hatch_allows_agent_shell(self) -> None:
        env = self.sb.env(CLAUDECODE="1", SECRETS_ALLOW_AGENT="1")
        proc = bash_lib('resolve_ref "op://TESTVAULT-sensitive/SECRETX/value"', env)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_non_op_ref_is_a_usage_error(self) -> None:
        proc = bash_lib('resolve_ref "https://nope"', self.sb.env())
        self.assertEqual(proc.returncode, 2)


if __name__ == "__main__":
    unittest.main()

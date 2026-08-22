"""Coverage for bin/db-provision-roles: committed config shape + --app mode
behavior against fake psql/op/render-cli (never live).

EXPECTED_APPS mirrors config/db-roles.json projects[].apps — any new app entry
requires updating this dict.
"""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path

from secrets_common import SecretsSandbox, run

ROOT = Path(__file__).resolve().parents[1]
BIN = str(ROOT / "bin" / "db-provision-roles")
CONFIG = ROOT / "config" / "db-roles.json"

EXPECTED_APPS = {
    "ts": {
        "ts_prefect": {"roles": {"app": "ts_prefect_app"}, "tiers": ["staging", "prod"]},
        "ts_dashboard": {
            "roles": {"app": "ts_dashboard_app", "ro": "ts_dashboard_ro"},
            "tiers": ["staging", "prod"],
        },
    },
    "amaru": {
        "amaru_web": {"roles": {"app": "amaru_web_app"}, "tiers": ["staging", "prod"]},
        "amaru_mcp": {"roles": {"app": "amaru_mcp_app"}, "tiers": ["prod"]},
    },
    "workflow-pro": {
        "workflow_web": {"roles": {"app": "workflow_web_app"}, "tiers": ["staging", "prod"]},
        "workflow_mcp": {"roles": {"app": "workflow_mcp_app"}, "tiers": ["prod"]},
    },
    "autodev": {
        "autodev_dashboard": {"roles": {"app": "autodev_dashboard_app"}, "tiers": ["prod"]},
        "autodev_memory": {
            "roles": {"app": "autodev_memory_app", "migrator": "autodev_memory_migrator"},
            "tiers": ["prod"],
        },
        "autodev_mem_ts": {
            "roles": {
                "app": "autodev_mem_ts",
                "migrator": "autodev_mem_ts_migrator",
                "ro": "autodev_mem_ts_ro",
            },
            "tiers": ["prod"],
            "instance": {"project": "ts", "tier_map": {"prod": "prod"}},
            "databases": ["mem_ts"],
        },
        "autodev_mem_amaru": {
            "roles": {"app": "autodev_mem_amaru", "migrator": "autodev_mem_amaru_migrator"},
            "tiers": ["prod"],
            "instance": {"project": "amaru", "tier_map": {"prod": "prod"}},
            "databases": ["mem_amaru"],
        },
    },
}

SYNTH_CONFIG = {
    "projects": {
        "alpha": {
            "vault": "ALPHAV",
            "vault_sensitive": "ALPHAV-sensitive",
            "render_key_ref": "op://ALPHAV/ALPHA_RENDER_API_KEY/value",
            "render_project": "alpha-render",
            "slug": "alpha",
            "roles": {"owner": "alpha_owner", "app": "alpha_app", "ro": "alpha_ro"},
            "apps": {
                "web": {
                    "roles": {"app": "web_app", "ro": "web_ro"},
                    "tiers": ["staging", "prod"],
                    "item_prefix": "WEB_",
                },
                "migweb": {
                    "roles": {"app": "migweb_app", "migrator": "migweb_migrator"},
                    "tiers": ["prod"],
                    "item_prefix": "MIGWEB_",
                },
            },
            "tiers": {
                "prod": {
                    "db_id": "dpg-alpha-prod",
                    "table_owner": "alpha_user",
                    "database": "alpha_db",
                },
                "staging": {
                    "db_id": "dpg-alpha-staging",
                    "table_owner": "alpha_staging_user",
                    "database": "alpha_staging",
                },
            },
        },
        "shared": {
            "vault": "SHAREDV",
            "vault_sensitive": "SHAREDV-sensitive",
            "render_key_ref": "op://ALPHAV/ALPHA_RENDER_API_KEY/value",
            "render_project": "alpha-render",
            "slug": "shared",
            "owner_kind": "sql_role",
            "roles": {"owner": "shared_owner", "app": "shared_app", "ro": "shared_ro"},
            "apps": {
                "memsvc": {
                    "roles": {"app": "memsvc_app", "migrator": "memsvc_migrator"},
                    "tiers": ["prod"],
                    "item_prefix": "MEMSVC_",
                },
                "crossapp": {
                    "roles": {"app": "crossapp"},
                    "tiers": ["prod"],
                    "item_prefix": "CROSSAPP_",
                    "instance": {"project": "alpha", "tier_map": {"prod": "prod"}},
                    "databases": ["mem_x"],
                },
            },
            "tiers": {
                "prod": {
                    "db_id": "dpg-shared-prod",
                    "table_owner": "render",
                    "database": "mem_shared",
                    "extra_databases": ["mem_extra"],
                }
            },
        },
    }
}

FAKE_PSQL = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in *pw-*) echo "LEAK: password on psql argv" >&2; exit 90 ;; esac
done
stdin=$(cat || true)
printf 'PSQL user=%s db=%s options=%s sslmode=%s args=%s\n' \
  "${PGUSER:-}" "${PGDATABASE:-}" "${PGOPTIONS:-}" "${PGSSLMODE:-}" "$*" >> "$FAKE_LOG"
case "$*" in
  *_provision_ro_probe*) exit 1 ;;
  *"SELECT current_user"*)
    cu="${PGUSER:-}"
    case "${PGOPTIONS:-}" in *role=*) cu="${PGOPTIONS##*role=}"; cu="${cu%% *}" ;; esac
    printf '%s\n' "$cu"
    exit 0
    ;;
esac
case "$stdin" in
  *pg_has_role*) printf 't\n' ;;
  *"THEN 'rotated' ELSE 'plain'"*) printf '%s\n' "${FAKE_PSQL_ROTATED:-plain}" ;;
esac
case "$*" in
  *"pg_get_userbyid(datdba)"*) printf '%s\n' "${FAKE_PSQL_DATDBA:-render}" ;;
esac
exit 0
"""

FAKE_RENDER_CLI = r"""#!/usr/bin/env bash
set -uo pipefail
printf 'RENDER %s\n' "$*" >> "$FAKE_LOG"
path=""
for a in "$@"; do case "$a" in /v1/*) path="$a" ;; esac; done
case "$path" in
  *dpg-alpha-prod*) u=alpha_owner_login_20260808t204833_ef12ea db=alpha_db ;;
  *dpg-alpha-staging*) u=alpha_staging_owner db=alpha_staging ;;
  *dpg-shared-prod*) u=shared_admin db=mem_shared ;;
  *) echo "fake render-cli: unknown path $path" >&2; exit 1 ;;
esac
echo "context: fake render project"
printf '{"externalConnectionString":"postgresql://%s:pw-%s@ext-host:5432/%s?sslmode=require","internalConnectionString":"postgresql://%s:pw-%s@int-host:5432/%s"}\n' \
  "$u" "$u" "$db" "$u" "$u" "$db"
"""


# The postgres provider no longer falls back to a naming convention for admin
# credentials -- they must be declared. Mirror what config/db-roles.json now
# states explicitly, so these fixtures exercise the same single path.
for _proj in SYNTH_CONFIG["projects"].values():
    _v, _s = _proj.get("vault"), _proj.get("vault_sensitive")
    _proj.setdefault(
        "admin_refs",
        {
            _t: {
                "root": "op://%s/Postgres %s/root" % (_s if _t == "prod" else _v, _t),
                "owner": "op://%s/Postgres %s/owner" % (_s if _t == "prod" else _v, _t),
            }
            for _t in _proj.get("tiers", {})
        },
    )


class DbRolesConfigTest(unittest.TestCase):
    """The committed config's apps mirror EXPECTED_APPS exactly."""

    def setUp(self) -> None:
        self.config = json.loads(CONFIG.read_text(encoding="utf-8"))

    def test_every_project_declares_exactly_the_expected_apps(self) -> None:
        for project, apps in EXPECTED_APPS.items():
            declared = self.config["projects"][project].get("apps", {})
            self.assertEqual(set(declared), set(apps), project)
            for slug, expected in apps.items():
                app = declared[slug]
                self.assertEqual(app["roles"], expected["roles"], f"{project}/{slug}")
                self.assertEqual(app["tiers"], expected["tiers"], f"{project}/{slug}")
                if "instance" in expected:
                    self.assertEqual(app["instance"], expected["instance"], f"{project}/{slug}")
                if "databases" in expected:
                    self.assertEqual(app["databases"], expected["databases"], f"{project}/{slug}")

    def test_item_prefixes_are_upper_slug_with_trailing_underscore(self) -> None:
        for project, apps in EXPECTED_APPS.items():
            for slug in apps:
                prefix = self.config["projects"][project]["apps"][slug]["item_prefix"]
                self.assertEqual(prefix, slug.upper() + "_", f"{project}/{slug}")

    def test_cross_instance_apps_point_at_configured_owning_tiers(self) -> None:
        for project in EXPECTED_APPS:
            for slug, app in self.config["projects"][project].get("apps", {}).items():
                instance = app.get("instance")
                if not isinstance(instance, dict):
                    continue
                owning = self.config["projects"][instance["project"]]
                for consumer_tier, own_tier in instance["tier_map"].items():
                    self.assertIn(consumer_tier, app["tiers"], f"{project}/{slug}")
                    self.assertIn(own_tier, owning["tiers"], f"{project}/{slug}")

    def test_scraper_and_decrypt_proxy_have_no_app_entries(self) -> None:
        ts_apps = self.config["projects"]["ts"].get("apps", {})
        self.assertNotIn("ts_scraper", ts_apps)
        self.assertNotIn("ts_decrypt_proxy", ts_apps)


class DbProvisionRolesAppModeTest(unittest.TestCase):
    """--app behavior against fake psql/op/render-cli."""

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        self.config_path = self.sb.root / "db-roles.json"
        self.config_path.write_text(json.dumps(SYNTH_CONFIG), encoding="utf-8")
        for name, body in (("psql", FAKE_PSQL), ("render-cli", FAKE_RENDER_CLI)):
            path = self.sb.fakebin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def env(self, **extra: str) -> dict[str, str]:
        return self.sb.env(
            sa_token=False,
            DB_ROLES_CONFIG=str(self.config_path),
            RENDER_CLI=str(self.sb.fakebin / "render-cli"),
            **extra,
        )

    def provision(self, *args: str, env: dict[str, str] | None = None):
        return run([BIN, *args], env if env is not None else self.env())

    def stored(self, vault: str, title: str, field: str = "value") -> str:
        return (self.sb.state / f"{vault}__{title}__{field}").read_text(encoding="utf-8")

    def test_bash_syntax_is_valid(self) -> None:
        proc = subprocess.run(["bash", "-n", BIN], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_transfer_flips_inherit_and_does_not_skip_on_member(self) -> None:
        src = Path(BIN).read_text(encoding="utf-8")
        self.assertIn("sql_alter_membership_options", src)
        self.assertIn("WITH INHERIT %s, SET %s", src)
        self.assertNotIn("WITH INHERIT %s, SET %s, ADMIN %s", src)
        alter = src.split("sql_alter_membership_options()", 1)[1].split("sql_has_role_usage", 1)[0]
        self.assertNotIn("pg_has_role", alter)

    def test_ownership_transfer_is_per_relation_with_datdba_guard(self) -> None:
        """C4: REASSIGN OWNED also moves the database, schemas, functions and
        objects in other databases the admin owns. Provisioning transfers the
        table owner's relations of the session database one ALTER at a time
        and proves pg_database.datdba did not move."""
        src = Path(BIN).read_text(encoding="utf-8")
        self.assertNotIn("REASSIGN OWNED BY %I", src)
        body = src.split("sql_transfer_owned_relations_on_db()", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("ALTER %s %I.%I OWNER TO %I", body)
        for kind in ("'SEQUENCE'", "'VIEW'", "'MATERIALIZED VIEW'", "'FOREIGN TABLE'", "'TABLE'"):
            self.assertIn(kind, body)
        self.assertIn("relkind IN ('r','p','S','v','m','f')", body)
        self.assertIn("ALTER TYPE %I.%I OWNER TO %I", body)
        self.assertIn("c.relowner = to_regrole(:'from_role')", body)
        self.assertLess(body.index("datdba_before="), body.index("ALTER %s %I.%I OWNER TO"))
        self.assertIn('[[ "$datdba_before" == "$datdba_after" ]]', body)
        self.assertIn("pg_get_userbyid(datdba)", src)
        # rotation never transfers ownership
        rotator = (ROOT / "secrets" / "providers" / "postgres-rotate").read_text(encoding="utf-8")
        self.assertNotIn("REASSIGN OWNED", rotator)
        self.assertNotIn("OWNER TO", rotator)

    def test_ownership_transfer_refuses_when_database_owner_moves(self) -> None:
        # The guard compares datdba before/after; a fake whose answer flips
        # between the two reads must abort the migrator provisioning.
        fake = (self.sb.fakebin / "psql").read_text(encoding="utf-8").replace(
            'printf \'%s\\n\' "${FAKE_PSQL_DATDBA:-render}"',
            'n="$(cat "$FAKE_LOG.datdba" 2>/dev/null || echo 0)"; echo $((n + 1)) > "$FAKE_LOG.datdba"; printf \'owner%s\\n\' "$n"',
        )
        (self.sb.fakebin / "psql").write_text(fake, encoding="utf-8")
        proc = self.provision("--project", "shared", "--app", "memsvc", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("database owner changed during ownership transfer", proc.stderr)

    def test_provision_refuses_to_re_login_a_rotated_capability(self) -> None:
        # L4: a rotated capability is NOLOGIN with <role>_login_* versions;
        # re-enabling LOGIN with a fresh password would leave a credential no
        # consumer holds and the rotator cannot account for.
        proc = self.provision("--project", "alpha", "--app", "web", "prod", "--reason", "t",
                              env=self.env(FAKE_PSQL_ROTATED="rotated"))
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("rotated capability", proc.stderr)
        self.assertIn("rotate-secret", proc.stderr)
        log = "\n".join(self.sb.log_lines())
        self.assertNotIn("OP item", log)
        # no CREATE/ALTER ROLE batch reached psql (the refusal query is the only stdin batch)
        self.assertNotIn("user=web_app", log)

    def test_psql_sessions_require_tls_and_carry_timeouts(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "web", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        log = "\n".join(self.sb.log_lines())
        self.assertIn("lock_timeout=", log)
        self.assertIn("statement_timeout=", log)
        self.assertIn("sslmode=require", log)

    def test_list_shows_apps_per_project(self) -> None:
        proc = self.provision("--list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("alpha", proc.stdout)
        self.assertIn("  app: web", proc.stdout)
        self.assertIn("  app: crossapp", proc.stdout)

    def test_unknown_app_exits_2_and_lists_known_apps(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "nope", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("unknown app", proc.stderr)
        self.assertIn("web", proc.stderr)

    def test_app_dry_run_prints_plan_and_reads_nothing(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "web", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("web_app", proc.stdout)
        self.assertIn("web_ro", proc.stdout)
        self.assertIn("op://ALPHAV-sensitive/Postgres prod/web", proc.stdout)
        self.assertIn("op://ALPHAV/Postgres prod RO/web", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_app_live_run_requires_reason(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "web", "prod")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--reason", proc.stderr)

    def test_app_live_run_refuses_agent_shell(self) -> None:
        proc = self.provision(
            "--project", "alpha", "--app", "web", "prod", "--reason", "t",
            env=self.env(CLAUDECODE="1"),
        )
        self.assertEqual(proc.returncode, 3)
        self.assertEqual(self.sb.log_lines(), [])

    def test_app_live_provisions_logins_and_upserts_items_without_leaking(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "web", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # app item: internal host, sensitive vault; ro item: external host, regular vault
        app_url = self.stored("ALPHAV-sensitive", "Postgres prod", "web")
        ro_url = self.stored("ALPHAV", "Postgres prod RO", "web")
        self.assertIn("web_app", app_url)
        self.assertIn("@int-host:", app_url)
        self.assertIn("/alpha_db", app_url)
        self.assertIn("web_ro", ro_url)
        self.assertIn("@ext-host:", ro_url)
        # Dual-key owner rotation names the Render default <owner>_login_<tag>.
        self.assertIn("login=alpha_owner_login_", proc.stdout)
        # owner attestation ran as the table owner, grants ran for both roles
        log = "\n".join(self.sb.log_lines())
        self.assertIn("role=alpha_user", log)
        # no fake credential ever hit stdout/stderr
        self.assertNotIn("pw-", proc.stdout + proc.stderr)

    def test_app_staging_skips_when_tier_not_declared(self) -> None:
        proc = self.provision("--project", "shared", "--app", "memsvc", "staging", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("skip staging", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_shared_box_app_grants_span_tier_and_extra_databases(self) -> None:
        proc = self.provision("--project", "shared", "--app", "memsvc", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        log = "\n".join(self.sb.log_lines())
        self.assertIn("db=mem_shared", log)
        self.assertIn("db=mem_extra", log)
        # shared box stores the EXTERNAL host (matches project-mode autodev items)
        url = self.stored("SHAREDV-sensitive", "Postgres prod", "memsvc")
        self.assertIn("memsvc_app", url)
        self.assertIn("@ext-host:", url)
        self.assertIn("/mem_shared", url)

    def test_migrator_default_privs_only_target_same_instance_roles(self) -> None:
        # Cross-instance provision (autodev_mem_ts on the ts box) used to ALTER
        # DEFAULT PRIVILEGES for autodev_app because the project-level role was
        # always included and apps without instance defaulted to $own.
        src = (ROOT / "bin" / "db-provision-roles").read_text()
        self.assertIn("if $own == $p then .projects[$p].roles.app", src)
        self.assertIn("select((.value.instance.project // $p) == $own)", src)
        self.assertNotIn("select((.value.instance.project // $own) == $own)", src)

    def test_migrator_role_is_a_separate_principal_owning_its_own_credential(self) -> None:
        """The app role is revoked from alembic_version by design, so a service that
        migrates at boot needs its own principal. Before this, autodev-memory borrowed
        another PROJECT's owner credential at runtime and went stale the moment that
        credential rotated."""
        proc = self.provision("--project", "shared", "--app", "memsvc", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        log = "\n".join(self.sb.log_lines())
        # sql_role box: SET ROLE the SQL owner, not table_owner (`render`).
        # GRANT render is impossible (no ADMIN OPTION). Grants span every db.
        self.assertIn("USER=MEMSVC_MIGRATOR DB=MEM_SHARED OPTIONS=-C ROLE=SHARED_OWNER", log.upper())
        self.assertIn("DB=MEM_EXTRA", log.upper())
        self.assertIn("transfer ownership of render relations to shared_owner", proc.stdout)
        url = self.stored("SHAREDV-sensitive", "Postgres prod", "memsvc_migrator")
        self.assertIn("memsvc_migrator", url)
        self.assertIn("options=-c%20role%3Dshared_owner", url)
        self.assertNotIn("role%3Drender", url)
        # the app credential is untouched and remains a separate field
        app_url = self.stored("SHAREDV-sensitive", "Postgres prod", "memsvc")
        self.assertIn("memsvc_app", app_url)
        self.assertNotIn("memsvc_migrator", app_url)

    def test_migrator_dry_run_names_the_role_and_its_field(self) -> None:
        proc = self.provision("--project", "shared", "--app", "memsvc", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("memsvc_migrator", proc.stdout)
        self.assertIn("preferred SET ROLE shared_owner", proc.stdout)
        self.assertIn("transfer ownership of render relations to shared_owner", proc.stdout)
        self.assertIn("op://SHAREDV-sensitive/Postgres prod/memsvc_migrator", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_dedicated_box_migrator_sets_role_to_itself(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "migweb", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        url = self.stored("ALPHAV-sensitive", "Postgres prod", "migweb_migrator")
        self.assertIn("migweb_migrator", url)
        self.assertIn("options=-c%20role%3Dmigweb_migrator", url)
        self.assertNotIn("options=-c%20role%3Dalpha_user", url)

    def test_dedicated_box_migrator_dry_run_reassigns_to_migrator(self) -> None:
        proc = self.provision("--project", "alpha", "--app", "migweb", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("preferred SET ROLE migweb_migrator", proc.stdout)
        self.assertIn("transfer ownership of alpha_user relations to migweb_migrator", proc.stdout)
        self.assertNotIn("instance ROOT", proc.stdout)

    def test_cross_instance_app_provisions_on_owning_box_into_consumer_vault(self) -> None:
        proc = self.provision("--project", "shared", "--app", "crossapp", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        log = "\n".join(self.sb.log_lines())
        # role created on the OWNING instance (alpha's box), grants on mem_x only
        self.assertIn("dpg-alpha-prod", log)
        self.assertIn("db=mem_x", log)
        self.assertNotIn("db=mem_shared", log)
        # item lands in the CONSUMER project's sensitive vault, external host
        url = self.stored("SHAREDV-sensitive", "Postgres prod", "crossapp")
        self.assertIn("crossapp", url)
        self.assertIn("@ext-host:", url)
        self.assertIn("/mem_x", url)

    def test_roles_requires_app_mode(self) -> None:
        proc = self.provision("--project", "alpha", "--roles", "app", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--roles is only valid with --app", proc.stderr)

    def test_roles_rejects_unknown_kind(self) -> None:
        proc = self.provision(
            "--project", "shared", "--app", "memsvc", "--roles", "owner", "prod", "--dry-run"
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("app, ro, migrator", proc.stderr)

    def test_roles_migrator_dry_run_skips_the_app_login(self) -> None:
        proc = self.provision(
            "--project", "shared", "--app", "memsvc", "--roles", "migrator", "prod", "--dry-run"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("memsvc_migrator", proc.stdout)
        self.assertIn("op://SHAREDV-sensitive/Postgres prod/memsvc_migrator", proc.stdout)
        self.assertNotIn("memsvc_app", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

    def test_roles_migrator_live_does_not_rotate_the_app_password(self) -> None:
        proc = self.provision(
            "--project", "shared", "--app", "memsvc", "--roles", "migrator", "prod",
            "--reason", "t",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        url = self.stored("SHAREDV-sensitive", "Postgres prod", "memsvc_migrator")
        self.assertIn("memsvc_migrator", url)
        app_path = self.sb.state / "SHAREDV-sensitive__Postgres prod__memsvc"
        self.assertFalse(app_path.exists())

    def test_cross_instance_dry_run_names_owning_instance(self) -> None:
        proc = self.provision("--project", "shared", "--app", "crossapp", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("instance=alpha/prod", proc.stdout)
        self.assertIn("op://SHAREDV-sensitive/Postgres prod/crossapp", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])


if __name__ == "__main__":
    unittest.main()

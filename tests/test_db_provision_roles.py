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
                }
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
printf 'PSQL user=%s db=%s options=%s args=%s\n' \
  "${PGUSER:-}" "${PGDATABASE:-}" "${PGOPTIONS:-}" "$*" >> "$FAKE_LOG"
cat >/dev/null || true
case "$*" in
  *_provision_ro_probe*) exit 1 ;;
  *"SELECT current_user"*)
    cu="${PGUSER:-}"
    case "${PGOPTIONS:-}" in *role=*) cu="${PGOPTIONS##*role=}" ;; esac
    printf '%s\n' "$cu"
    ;;
esac
exit 0
"""

FAKE_RENDER_CLI = r"""#!/usr/bin/env bash
set -uo pipefail
printf 'RENDER %s\n' "$*" >> "$FAKE_LOG"
path=""
for a in "$@"; do case "$a" in /v1/*) path="$a" ;; esac; done
case "$path" in
  *dpg-alpha-prod*) u=alpha_owner db=alpha_db ;;
  *dpg-alpha-staging*) u=alpha_staging_owner db=alpha_staging ;;
  *dpg-shared-prod*) u=shared_admin db=mem_shared ;;
  *) echo "fake render-cli: unknown path $path" >&2; exit 1 ;;
esac
echo "context: fake render project"
printf '{"externalConnectionString":"postgresql://%s:pw-%s@ext-host:5432/%s?sslmode=require","internalConnectionString":"postgresql://%s:pw-%s@int-host:5432/%s"}\n' \
  "$u" "$u" "$db" "$u" "$u" "$db"
"""


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

    def test_migrator_role_is_a_separate_principal_owning_its_own_credential(self) -> None:
        """The app role is revoked from alembic_version by design, so a service that
        migrates at boot needs its own principal. Before this, autodev-memory borrowed
        another PROJECT's owner credential at runtime and went stale the moment that
        credential rotated."""
        proc = self.provision("--project", "shared", "--app", "memsvc", "prod", "--reason", "t")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        log = "\n".join(self.sb.log_lines())
        # the migrator verifies itself with the ownership trick applied, and its
        # grants run on every database the app spans
        self.assertIn("USER=MEMSVC_MIGRATOR DB=MEM_SHARED OPTIONS=-C ROLE=RENDER", log.upper())
        self.assertIn("DB=MEM_EXTRA", log.upper())
        url = self.stored("SHAREDV-sensitive", "Postgres prod", "memsvc_migrator")
        self.assertIn("memsvc_migrator", url)
        # the ownership trick, so new objects stay owned by the table owner
        self.assertIn("options=-c%20role%3Drender", url)
        # the app credential is untouched and remains a separate field
        app_url = self.stored("SHAREDV-sensitive", "Postgres prod", "memsvc")
        self.assertIn("memsvc_app", app_url)
        self.assertNotIn("memsvc_migrator", app_url)

    def test_migrator_dry_run_names_the_role_and_its_field(self) -> None:
        proc = self.provision("--project", "shared", "--app", "memsvc", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("memsvc_migrator", proc.stdout)
        self.assertIn("op://SHAREDV-sensitive/Postgres prod/memsvc_migrator", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])

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

    def test_cross_instance_dry_run_names_owning_instance(self) -> None:
        proc = self.provision("--project", "shared", "--app", "crossapp", "prod", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("instance=alpha/prod", proc.stdout)
        self.assertIn("op://SHAREDV-sensitive/Postgres prod/crossapp", proc.stdout)
        self.assertEqual(self.sb.log_lines(), [])


if __name__ == "__main__":
    unittest.main()

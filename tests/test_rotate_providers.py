"""Slice-4a provider coverage for bin/rotate-secret: postgres (dry-run plan +
refusal paths + lock-contention mapping), resend/aws dual-flow ordering, aws
pair semantics, and playbook exits for unconfigured openai/xai. No live calls:
psql/curl/aws/op are PATH-shadowed fakes that log actions, never values."""

from __future__ import annotations

import json
import unittest

from secrets_common import ROOT, SecretsSandbox, run

ROTATE = str(ROOT / "bin" / "rotate-secret")

PG_APP_REF = "op://TESTVAULT-sensitive/PROD_POSTGRES_URL_APP/value"
PG_OWNER_SQLROLE_REF = "op://TESTVAULT-sensitive/PROD_POSTGRES_URL_OWNER/value"
PG_ROOT_REF = "op://TESTVAULT-sensitive/Postgres prod/root"
RESEND_REF = "op://TESTVAULT/RESEND_API_KEY/value"
AWS_ID_REF = "op://TESTVAULT/AWS_ACCESS_KEY_ID/value"
AWS_SECRET_REF = "op://TESTVAULT/AWS_SECRET_ACCESS_KEY/value"
OPENAI_REF = "op://TESTVAULT/OPENAI_API_KEY/value"
XAI_REF = "op://TESTVAULT/XAI_API_KEY/value"

AWS_OLD_ID = "AKIAOLDKEY2222222"
AWS_NEW_ID = "AKIANEWKEY1111111"

DB_ROLES = {
    "projects": {
        "testproj": {
            "vault": "TESTVAULT",
            "vault_sensitive": "TESTVAULT-sensitive",
            "render_key_ref": "op://TESTVAULT/TEST_RENDER_API_KEY/value",
            "render_project": "testproj",
            "slug": "testproj",
            "roles": {"owner": "testproj_owner", "app": "testproj_app", "ro": "testproj_ro"},
            "tiers": {
                "prod": {
                    "db_id": "dpg-test123-a",
                    "table_owner": "testproj_dbuser",
                    "database": "testdb",
                }
            },
        },
        "sqlproj": {
            "vault": "TESTVAULT",
            "vault_sensitive": "TESTVAULT-sensitive",
            "render_key_ref": "op://TESTVAULT/TEST_RENDER_API_KEY/value",
            "render_project": "testproj",
            "slug": "sqlproj",
            "owner_kind": "sql_role",
            "roles": {"owner": "sqlproj_owner", "app": "sqlproj_app", "ro": "sqlproj_ro"},
            "tiers": {
                "prod": {
                    "db_id": "dpg-test123-a",
                    "table_owner": "shared_admin",
                    "database": "sqldb",
                    "admin_via": {"project": "testproj", "table_owner": "testproj_dbuser"},
                }
            },
        },
    }
}

FAKE_CURL = r"""#!/usr/bin/env bash
set -uo pipefail
method="GET" url="" prev=""
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*|resend-token-NEW*|aws-secret-NEW*) echo "LEAK: secret value on curl argv" >&2; exit 91 ;; esac
  [[ "$prev" == "--request" ]] && method="$a"
  [[ "$prev" == "--url" ]] && url="$a"
  prev="$a"
done
cat >/dev/null
printf 'CURL %s %s\n' "$method" "$url" >> "$FAKE_LOG"
case "$method $url" in
  "GET https://api.render.com/v1/postgres/"*"/connection-info")
    printf '{"internalConnectionString":"postgresql://cur_user:cur_pw@internal-host:5432/testdb","externalConnectionString":"postgresql://cur_user:cur_pw@external-host:5432/testdb"}' ;;
  "GET https://api.resend.com/api-keys")
    printf '{"data":[{"id":"old-key-1","name":"testkey primary"},{"id":"other-key","name":"unrelated"}]}' ;;
  "POST https://api.resend.com/api-keys")
    printf '{"id":"new-key-1","token":"resend-token-NEW"}' ;;
  "DELETE https://api.resend.com/api-keys/"*)
    printf '{}' ;;
  "POST https://api.resend.com/emails")
    printf '{"id":"email-1"}' ;;
  *) printf '{}' ;;
esac
"""

FAKE_PSQL = r"""#!/usr/bin/env bash
set -uo pipefail
printf 'PSQL %s\n' "$*" >> "$FAKE_LOG"
# -c command mode: answer simple probes.
prev=""
for a in "$@"; do
  if [[ "$prev" == "-c" ]]; then
    case "$a" in
      *current_user*) printf '%s\n' "${FAKE_PSQL_CURRENT_USER:-testproj_dbuser}" ;;
      *) printf '0\n' ;;
    esac
    exit 0
  fi
  prev="$a"
done
# FIFO session mode (advisory lock): answer line-by-line.
while IFS= read -r line; do
  case "$line" in
    *pg_try_advisory_lock*) printf '%s|12345\n' "${FAKE_PSQL_LOCK:-t}" ;;
    *pg_locks*) printf 't\n' ;;
    '\q'*) exit 0 ;;
    *) printf '\n' ;;
  esac
done
exit 0
"""

FAKE_AWS = r"""#!/usr/bin/env bash
set -uo pipefail
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*|aws-secret-NEW*) echo "LEAK: secret value on aws argv" >&2; exit 91 ;; esac
done
printf 'AWS %s\n' "$*" >> "$FAKE_LOG"
case "$*" in
  *list-access-keys*)
    if [[ -n "${FAKE_AWS_EXTRA_KEY:-}" ]]; then
      printf '{"AccessKeyMetadata":[{"AccessKeyId":"%s","Status":"Active"},{"AccessKeyId":"%s","Status":"Active"}]}' \
        "${FAKE_AWS_OLD_ID:?}" "$FAKE_AWS_EXTRA_KEY"
    else
      printf '{"AccessKeyMetadata":[{"AccessKeyId":"%s","Status":"Active"}]}' "${FAKE_AWS_OLD_ID:?}"
    fi
    ;;
  *create-access-key*)
    printf '{"AccessKey":{"AccessKeyId":"AKIANEWKEY1111111","SecretAccessKey":"aws-secret-NEW"}}' ;;
  *get-caller-identity*)
    printf '{"Account":"123456789012"}' ;;
  *update-access-key*|*delete-access-key*)
    printf '{}' ;;
  *) printf '{}' ;;
esac
"""


class RotateProvidersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        # Richer fakes for provider flows.
        for name, body in (("curl", FAKE_CURL), ("psql", FAKE_PSQL), ("aws", FAKE_AWS)):
            path = self.sb.fakebin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.db_roles_path = self.sb.root / "db-roles.json"
        self.db_roles_path.write_text(json.dumps(DB_ROLES), encoding="utf-8")
        self.state_dir = self.sb.root / "db-rotation-state"
        self.rotation = {
            "pg-app": {
                "ref": PG_APP_REF,
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
            },
            "pg-app-no-consumers": {
                "ref": PG_APP_REF.replace("_APP", "_RO"),
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
                "sync_refs": [],
            },
            "pg-owner-sqlrole": {
                "ref": PG_OWNER_SQLROLE_REF,
                "project": "sqlproj",
                "provider": "postgres",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
            },
            "test-resend": {
                "ref": RESEND_REF,
                "provider": "resend",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
                "config": {"key_name": "testkey"},
            },
            "test-resend-unconfigured": {
                "ref": RESEND_REF,
                "provider": "resend",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
            },
            "test-aws": {
                "ref": AWS_ID_REF,
                "provider": "aws_iam",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
                "sync_refs": [AWS_ID_REF, AWS_SECRET_REF],
                "config": {
                    "iam_user": "test-iam-user",
                    "secret_ref": AWS_SECRET_REF,
                    "profile": "test-admin",
                },
            },
            "test-openai-unconfigured": {
                "ref": OPENAI_REF,
                "provider": "openai",
                "mode": "DUAL_KEY",
                "owner_repo": "repo",
            },
            "test-xai": {
                "ref": XAI_REF,
                "provider": "xai",
                "mode": "MANUAL",
                "owner_repo": "repo",
            },
        }
        self.write_config()

    def write_config(self) -> None:
        # Every rotation ref must have a route (fail-closed validator). Routes
        # that must NOT be activation targets are dev-kind (consumers derive
        # from render+github only). srv-target's health URL is deliberately
        # ABSENT from health: the fail-closed test needs it.
        pg_ro_ref = PG_APP_REF.replace("_APP", "_RO")
        routes = "\n".join([
            f"render\tsrv-target\tDATABASE_URL\t{PG_APP_REF}\tself",
            f"dev\tprofile\tDATABASE_URL_RO\t{pg_ro_ref}\tself",
            f"dev\tprofile\tOWNER_URL\t{PG_OWNER_SQLROLE_REF}\tself",
            f"render\tsrv-alpha\tRESEND_API_KEY\t{RESEND_REF}\tself",
            f"render\tsrv-alpha\tAWS_ACCESS_KEY_ID\t{AWS_ID_REF}\tself",
            f"render\tsrv-alpha\tAWS_SECRET_ACCESS_KEY\t{AWS_SECRET_REF}\tself",
            f"dev\tprofile\tOPENAI_API_KEY\t{OPENAI_REF}\tself",
            f"dev\tprofile\tXAI_API_KEY\t{XAI_REF}\tself",
            "",
        ])
        self.sb.write_manifest(routes, rotation=self.rotation)

    def env(self, **extra: str) -> dict[str, str]:
        # First registry lookup key doubles as duplicate guard: the two resend
        # entries share a ref, so tests select by --project/--item or unique refs.
        return self.sb.env(
            DB_ROLES_CONFIG=str(self.db_roles_path),
            DB_ROTATION_STATE_DIR=str(self.state_dir),
            SYNC_SECRETS_BIN=str(self.sb.fakebin / "sync-secrets-fake"),
            **extra,
        )

    def rotate(self, *args: str, env: dict[str, str] | None = None, stdin: str = ""):
        # stdin defaults to empty (never inherited) so fake curl/aws drains
        # can't block on the test runner's stdin.
        return run([ROTATE, "--repo", str(self.sb.repo), *args],
                   env if env is not None else self.env(), stdin=stdin)

    def log(self) -> list[str]:
        return self.sb.log_lines()

    def seed_item(self, ref: str, value: str) -> None:
        rest = ref.removeprefix("op://")
        vault, item, field = rest.split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text(value, encoding="utf-8")

    def stored_value(self, ref: str) -> str:
        rest = ref.removeprefix("op://")
        vault, item, field = rest.split("/")
        return (self.sb.state / f"{vault}__{item}__{field}").read_text(encoding="utf-8")

    # --- postgres ---------------------------------------------------------------

    def test_postgres_dry_run_prints_plan_and_reads_nothing(self) -> None:
        proc = self.rotate("--ref", PG_APP_REF, "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("postgres dual-principal rotation plan", proc.stdout)
        self.assertIn("render[srv-target] DATABASE_URL", proc.stdout)
        self.assertIn("advisory lock", proc.stdout)
        self.assertEqual(self.log(), [])  # zero op/curl/psql invocations

    def test_postgres_refuses_unknown_health_url_before_any_mutation(self) -> None:
        proc = self.rotate("--ref", PG_APP_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("no health URL registered for render[srv-target]", proc.stderr)
        self.assertEqual(self.log(), [])  # refused before op/curl/psql ran

    def test_postgres_refuses_sql_role_owner_scope(self) -> None:
        proc = self.rotate("--ref", PG_OWNER_SQLROLE_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("owner_kind 'sql_role'", proc.stderr)
        self.assertIn("Nothing was changed", proc.stderr)
        self.assertEqual(self.log(), [])

    def test_postgres_lock_contention_maps_to_exit_2(self) -> None:
        self.seed_item(
            PG_ROOT_REF,
            "postgresql://rootuser:rootpw@external-host:5432/testdb",
        )
        proc = self.rotate(
            "--project", "testproj", "--item", "PROD_POSTGRES_URL_RO", "--field", "value",
            "--reason", "t", "--yes",
            env=self.env(FAKE_PSQL_LOCK="f"),
        )
        self.assertEqual(proc.returncode, 2, proc.stderr + proc.stdout)
        self.assertIn("holds the advisory lock", proc.stderr)
        # No vault/env mutation happened: no op item edit/create, no PUT.
        joined = "\n".join(self.log())
        self.assertNotIn("OP item edit", joined)
        self.assertNotIn("OP item create", joined)
        self.assertNotIn("CURL PUT", joined)
        self.assertEqual(len([l for l in self.log() if l.startswith("SYNC ")]), 0)

    # --- resend -----------------------------------------------------------------

    def test_resend_duplicate_ref_registry_lookup_is_rejected(self) -> None:
        # Two synthetic entries share RESEND_REF: the lookup must refuse the
        # ambiguity instead of picking one.
        self.seed_item(RESEND_REF, "resend-token-OLD")
        proc = self.rotate("--project", "testproj", "--item", "RESEND_API_KEY",
                           "--field", "value", "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("more than one entry", proc.stderr)

    def test_resend_dual_flow_via_unique_entry(self) -> None:
        # Drop the unconfigured duplicate so the ref resolves uniquely.
        del self.rotation["test-resend-unconfigured"]
        self.write_config()
        self.seed_item(RESEND_REF, "resend-token-OLD")

        proc = self.rotate("--ref", RESEND_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertEqual(self.stored_value(RESEND_REF), "resend-token-NEW")
        log = self.log()
        combined = proc.stdout + proc.stderr + "\n".join(log)
        self.assertNotIn("resend-token-NEW", combined)

        def first(prefix_substr: str) -> int:
            for i, line in enumerate(log):
                if prefix_substr in line:
                    return i
            raise AssertionError(f"missing log line: {prefix_substr}\n{log}")

        i_list = first("CURL GET https://api.resend.com/api-keys")
        i_create = first("CURL POST https://api.resend.com/api-keys")
        i_vault = first("OP item edit")
        i_sync = first("SYNC ")
        i_delete = first("CURL DELETE https://api.resend.com/api-keys/old-key-1")
        self.assertLess(i_list, i_create)
        self.assertLess(i_create, i_vault)
        self.assertLess(i_vault, i_sync)
        self.assertLess(i_sync, i_delete)
        # Only the snapshotted predecessor is deleted, never the unrelated key.
        self.assertNotIn("api-keys/other-key", "\n".join(log))
        self.assertNotIn("api-keys/new-key-1", "\n".join(log))

    def test_resend_never_deletes_old_key_when_verify_fails(self) -> None:
        del self.rotation["test-resend-unconfigured"]
        self.rotation["test-resend"]["verify_command"] = "exit 1"
        self.write_config()
        self.seed_item(RESEND_REF, "resend-token-OLD")

        proc = self.rotate("--ref", RESEND_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 4, proc.stderr + proc.stdout)
        joined = "\n".join(self.log())
        self.assertNotIn("CURL DELETE", joined)
        self.assertEqual(len([l for l in self.log() if l.startswith("SYNC ")]), 0)

    def test_resend_without_key_name_exits_3_and_changes_nothing(self) -> None:
        del self.rotation["test-resend"]
        self.write_config()
        proc = self.rotate("--ref", RESEND_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("config.key_name", proc.stdout)
        self.assertEqual([l for l in self.log() if l.startswith("CURL")], [])

    # --- aws_iam ----------------------------------------------------------------

    def test_aws_pair_flow_updates_both_items_before_sync_and_deletes_old_after(self) -> None:
        self.seed_item(AWS_ID_REF, AWS_OLD_ID)
        self.seed_item(AWS_SECRET_REF, "aws-secret-OLD")
        proc = self.rotate("--ref", AWS_ID_REF, "--reason", "t", "--yes",
                           env=self.env(FAKE_AWS_OLD_ID=AWS_OLD_ID))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        # PAIR: both items hold the new pair.
        self.assertEqual(self.stored_value(AWS_ID_REF), AWS_NEW_ID)
        self.assertEqual(self.stored_value(AWS_SECRET_REF), "aws-secret-NEW")
        combined = proc.stdout + proc.stderr + "\n".join(self.log())
        self.assertNotIn("aws-secret-NEW", combined)

        log = self.log()
        edit_idxs = [i for i, l in enumerate(log) if "OP item edit" in l]
        sync_idxs = [i for i, l in enumerate(log) if l.startswith("SYNC ")]
        inactive_idx = [i for i, l in enumerate(log) if "update-access-key" in l]
        delete_idx = [i for i, l in enumerate(log) if "delete-access-key" in l]
        self.assertEqual(len(edit_idxs), 2)  # id + secret, both written
        # Fan-out covers BOTH refs for every repo leg.
        self.assertTrue(any(AWS_ID_REF in log[i] for i in sync_idxs))
        self.assertTrue(any(AWS_SECRET_REF in log[i] for i in sync_idxs))
        # Pair-atomicity at the engine level: both vault writes precede any sync.
        self.assertLess(max(edit_idxs), min(sync_idxs))
        # Old key deactivated then deleted, strictly after the fan-out.
        self.assertEqual(len(inactive_idx), 1)
        self.assertEqual(len(delete_idx), 1)
        self.assertLess(max(sync_idxs), inactive_idx[0])
        self.assertLess(inactive_idx[0], delete_idx[0])
        self.assertIn(AWS_OLD_ID, log[delete_idx[0]])

    def test_aws_refuses_when_user_has_unknown_second_key(self) -> None:
        self.seed_item(AWS_ID_REF, AWS_OLD_ID)
        self.seed_item(AWS_SECRET_REF, "aws-secret-OLD")
        proc = self.rotate("--ref", AWS_ID_REF, "--reason", "t", "--yes",
                           env=self.env(FAKE_AWS_OLD_ID=AWS_OLD_ID,
                                        FAKE_AWS_EXTRA_KEY="AKIAROGUEKEY00001"))
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        joined = "\n".join(self.log())
        self.assertNotIn("create-access-key", joined)
        self.assertNotIn("delete-access-key", joined)
        # Vault untouched.
        self.assertEqual(self.stored_value(AWS_ID_REF), AWS_OLD_ID)

    def test_aws_never_deletes_old_key_when_verify_fails(self) -> None:
        self.rotation["test-aws"]["verify_command"] = "exit 1"
        self.write_config()
        self.seed_item(AWS_ID_REF, AWS_OLD_ID)
        self.seed_item(AWS_SECRET_REF, "aws-secret-OLD")
        proc = self.rotate("--ref", AWS_ID_REF, "--reason", "t", "--yes",
                           env=self.env(FAKE_AWS_OLD_ID=AWS_OLD_ID))
        self.assertEqual(proc.returncode, 4, proc.stderr + proc.stdout)
        joined = "\n".join(self.log())
        self.assertNotIn("update-access-key", joined)
        self.assertNotIn("delete-access-key", joined)
        self.assertEqual(len([l for l in self.log() if l.startswith("SYNC ")]), 0)

    # --- openai / xai playbooks ---------------------------------------------------

    def test_openai_without_admin_config_exits_3_playbook(self) -> None:
        proc = self.rotate("--ref", OPENAI_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("config.admin_key_ref", proc.stdout)
        self.assertIn("--complete", proc.stdout)
        self.assertEqual([l for l in self.log() if l.startswith("CURL")], [])
        self.assertEqual([l for l in self.log() if l.startswith("SYNC ")], [])

    def test_xai_always_exits_3_with_console_playbook(self) -> None:
        proc = self.rotate("--ref", XAI_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 3, proc.stderr + proc.stdout)
        self.assertIn("console.x.ai", proc.stdout)
        self.assertIn("--complete", proc.stdout)
        self.assertEqual(self.log(), [])


class DrainKeepsAdvisoryLockWarmTest(unittest.TestCase):
    """The advisory-lock session is opened once over the Render EXTERNAL
    endpoint and is otherwise idle for the whole drain (each drain poll opens
    its own connection). That proxy drops idle flows at ~5min, which is shorter
    than the drain's own 600s budget, so a slow drain used to lose the lock and
    abort after the fact. These are source invariants rather than a live drain:
    the failure only reproduces against a real proxy after minutes of idling."""

    SOURCE = (ROOT / "secrets" / "providers" / "postgres-rotate").read_text()

    def _function_body(self, name: str) -> str:
        start = self.SOURCE.index(f"\n{name}() {{\n")
        end = self.SOURCE.index("\n}\n", start)
        return self.SOURCE[start:end]

    def test_every_drain_loop_probes_the_lock_each_poll(self) -> None:
        for name in ("wait_for_predecessor_drain", "wait_for_fenced_sql_drain"):
            with self.subTest(drain=name):
                body = self._function_body(name)
                self.assertIn("while [[", body)
                probe = body.index("assert_rotation_lock_live")
                loop = body.index("while [[")
                # Inside the loop body, not a one-shot check before it.
                self.assertGreater(probe, loop, f"{name} probes outside its poll loop")
                self.assertIn("sleep \"${ROTATION_DRAIN_POLL_SECONDS:-10}\"", body)

    def test_drain_stall_hook_cannot_desync_the_lock_protocol(self) -> None:
        body = self._function_body("wait_for_predecessor_drain")
        hook_line = next(l for l in body.splitlines() if '"$ROTATE_HOOK" drain-stall' in l)
        # The lock is a strict one-write/one-read exchange on fds 8/7; a hook
        # that touched either would silently desync every later probe.
        self.assertIn("8>&-", hook_line)
        self.assertIn("7<&-", hook_line)

    def test_lock_connection_sets_socket_keepalives(self) -> None:
        body = self._function_body("acquire_rotation_lock")
        self.assertIn("PGKEEPALIVESIDLE=30", body)
        self.assertIn("PGKEEPALIVESINTERVAL=10", body)
        self.assertIn("PGKEEPALIVESCOUNT=6", body)


if __name__ == "__main__":
    unittest.main()

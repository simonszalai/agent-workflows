"""Provider coverage: postgres through bin/rotate-secret (dry-run plan +
refusal paths + lock-contention mapping) and the §1 provider contract for
resend/openai/aws_iam/self_minted/manual driven directly (provider_auto_ready,
provider_rotate -> PROVIDER_FINALIZE_JSON, provider_verify, provider_finalize
<json>, aws provider_reconcile). No live calls: psql/curl/aws/op are
PATH-shadowed fakes that log actions, never values."""

from __future__ import annotations

import json
import unittest

from secrets_common import ROOT, SecretsSandbox, run

ROTATE = str(ROOT / "bin" / "rotate-secret")

PG_APP_REF = "op://TESTVAULT-sensitive/Postgres prod/app"
PG_RO_REF = "op://TESTVAULT/Postgres prod RO/canonical"
PG_OWNER_SQLROLE_REF = "op://TESTVAULT-sensitive/Postgres prod/owner"
PG_ROOT_REF = "op://TESTVAULT-sensitive/Postgres prod/root"
PG_ADMIN_OWNER_REF = "op://TESTVAULT-sensitive/Postgres prod/owner"
ROTATOR = str(ROOT / "secrets" / "providers" / "postgres-rotate")
RESEND_REF = "op://TESTVAULT/RESEND_API_KEY/value"
RESEND2_REF = "op://TESTVAULT/RESEND_API_KEY_2/value"
AWS_ID_REF = "op://TESTVAULT/AWS/access_key_id"
AWS_SECRET_REF = "op://TESTVAULT/AWS/secret_access_key"
OPENAI_REF = "op://TESTVAULT/OPENAI_API_KEY/value"
MANUAL_REF = "op://TESTVAULT/XAI_API_KEY/value"

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
method="GET" url="" prev="" cfg="" out="" wout=""
for a in "$@"; do
  case "$a" in val-*|SENTINEL_*|resend-token-NEW*|aws-secret-NEW*|sk-proj-NEW*) echo "LEAK: secret value on curl argv" >&2; exit 91 ;; esac
  [[ "$prev" == "--request" ]] && method="$a"
  [[ "$prev" == "--url" ]] && url="$a"
  [[ "$prev" == "--config" ]] && cfg="$a"
  [[ "$prev" == "--output" ]] && out="$a"
  [[ "$prev" == "--write-out" ]] && wout="$a"
  [[ "$a" == http* ]] && url="$a"
  prev="$a"
done
# Classify the bearer key (never log it): NEW when it is a freshly minted value.
auth="none"
if [[ -n "$cfg" ]]; then
  hdr="$(cat "$cfg")"
  case "$hdr" in *resend-token-NEW*|*sk-proj-NEW*) auth="new" ;; *resend-token-OLD*|*sk-admin*|*val-*) auth="old" ;; esac
fi
cat >/dev/null
printf 'CURL %s %s auth=%s\n' "$method" "$url" "$auth" >> "$FAKE_LOG"
status=200
body() {
if [[ -n "${FAKE_CURL_404_URL_SUBSTR:-}" && "$url" == *"${FAKE_CURL_404_URL_SUBSTR}"* ]]; then
  status=404; printf '{"message":"not found"}'; return
elif [[ -n "${FAKE_CURL_500_URL_SUBSTR:-}" && "$url" == *"${FAKE_CURL_500_URL_SUBSTR}"* ]]; then
  status=500; printf '{"message":"boom"}'; return
fi
case "$method $url" in
  "GET https://api.render.com/v1/postgres/"*"/connection-info")
    printf '{"internalConnectionString":"postgresql://cur_user:cur_pw@internal-host:5432/testdb","externalConnectionString":"postgresql://cur_user:cur_pw@external-host:5432/testdb"}' ;;
  "GET https://api.render.com/v1/services?limit=100"*|"GET https://api.render.com/v1/env-groups?limit=100")
    printf '[]' ;;
  "GET https://api.render.com/v1/services/"*"/env-vars/"*)
    # Declared-target env read: the value comes from a file the test seeds
    # (never a literal in this script); absent file = env var unset.
    if [[ -n "${FAKE_RENDER_ENV_FILE:-}" && -f "${FAKE_RENDER_ENV_FILE:-}" ]]; then
      jq -Rs '{value: .}' < "$FAKE_RENDER_ENV_FILE"
    else
      printf '{}'
    fi ;;
  "GET https://health.test/ok")
    printf '{"status":"ok","databaseRoleSafe":true}' ;;
  "GET "*"/api-keys")
    printf '{"data":[{"id":"old-key-1","name":"testkey 20260101T000000Z"},{"id":"old-key-2","name":"testkey 20260301T120000Z"},{"id":"prefix-key","name":"testkey primary"},{"id":"longer-name-key","name":"testkeyfoo 20260101T000000Z"},{"id":"other-key","name":"unrelated"}]}' ;;
  "POST "*"/api-keys")
    printf '{"id":"new-key-1","token":"resend-token-NEW"}' ;;
  "DELETE "*"/api-keys/"*)
    printf '{}' ;;
  "POST "*"/emails")
    printf '{"id":"email-1"}' ;;
  "GET "*"/service_accounts?limit=100&after=sa-page1-last")
    printf '{"object":"list","data":[{"id":"sa-old-3","name":"rotate-test-openai-20260301T000000Z"},{"id":"sa-other","name":"dashboard"}],"has_more":false}' ;;
  "GET "*"/service_accounts?limit=100")
    printf '{"object":"list","data":[{"id":"sa-old-1","name":"rotate-test-openai-20260101T000000Z"},{"id":"sa-page1-last","name":"rotate-test-openai-extra"}],"has_more":true,"last_id":"sa-page1-last"}' ;;
  "POST "*"/service_accounts")
    printf '{"id":"sa-new","name":"rotate-test-openai-now","api_key":{"value":"sk-proj-NEW"}}' ;;
  "DELETE "*"/service_accounts/"*)
    printf '{"deleted":true}' ;;
  "GET "*"/v1/models")
    printf '{"data":[]}' ;;
  *) printf '{}' ;;
esac
}
if [[ -n "$out" ]]; then body > "$out"; else body; fi
if [[ -n "$wout" ]]; then wout="${wout//\\n/$'\n'}"; printf '%s' "${wout//%\{http_code\}/$status}"; fi
exit 0
"""

# Fake psql for the rotator: role = PGOPTIONS `-c role=` (else PGUSER); the
# unified attestation query answers from the session env; stdin SQL lines are
# logged as `SQL ...` (psql variables travel on argv, passwords never do).
FAKE_PSQL = r"""#!/usr/bin/env bash
set -uo pipefail
printf 'PSQL %s\n' "$*" >> "$FAKE_LOG"
role="${PGUSER:-}"
if [[ "${PGOPTIONS:-}" == *role=* ]]; then role="${PGOPTIONS##*role=}"; role="${role%% *}"; fi
prev=""
for a in "$@"; do
  if [[ "$prev" == "-c" ]]; then
    case "$a" in
      *"session_user, current_user, l.rolsuper"*)
        ro=off; [[ "$role" == *_ro ]] && ro=on
        printf '%s|%s|f|f|f|f|t|%s|t|t|%s\n' "${PGUSER:-}" "$role" "${FAKE_PSQL_OWNS_ANY:-f}" "$ro" ;;
      *_rotation_ro_probe*) exit 1 ;;
      *current_user*) printf '%s\n' "${FAKE_PSQL_CURRENT_USER:-$role}" ;;
      *) printf '0\n' ;;
    esac
    exit 0
  fi
  prev="$a"
done
# stdin: the FIFO advisory-lock session (one statement, one answer line) or a
# heredoc SQL batch.
while IFS= read -r line; do
  printf 'SQL %s\n' "$line" >> "$FAKE_LOG"
  case "$line" in
    *pg_try_advisory_lock*) printf '%s|12345\n' "${FAKE_PSQL_LOCK:-t}" ;;
    *pg_locks*) printf 't\n' ;;
    '\q'*) exit 0 ;;
    *"count(*)"*) printf '0\n' ;;
    *rolcanlogin*) printf 'f\n' ;;
    *"DROP ROLE"*) [[ -z "${FAKE_PSQL_DROP_FAIL:-}" ]] || { echo "ERROR:  role cannot be dropped (fake)" >&2; exit 1; } ;;
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
      printf '{"AccessKeyMetadata":[{"AccessKeyId":"%s","Status":"Active","CreateDate":"2026-01-01T00:00:00Z"},{"AccessKeyId":"%s","Status":"Active","CreateDate":"%s"}]}' \
        "${FAKE_AWS_OLD_ID:?}" "$FAKE_AWS_EXTRA_KEY" "${FAKE_AWS_EXTRA_DATE:-2026-02-01T00:00:00Z}"
    elif [[ -n "${FAKE_AWS_OLD_ID:-}" ]]; then
      printf '{"AccessKeyMetadata":[{"AccessKeyId":"%s","Status":"Active","CreateDate":"2026-01-01T00:00:00Z"}]}' "$FAKE_AWS_OLD_ID"
    else
      printf '{"AccessKeyMetadata":[]}'
    fi
    ;;
  *create-access-key*)
    printf '{"AccessKey":{"AccessKeyId":"AKIANEWKEY1111111","SecretAccessKey":"aws-secret-NEW"}}' ;;
  *get-caller-identity*)
    [[ "${FAKE_AWS_STS_FAIL:-0}" == "1" ]] && { echo "InvalidClientTokenId" >&2; exit 254; }
    printf '{"Account":"123456789012"}' ;;
  *update-access-key*)
    [[ "${FAKE_AWS_UPDATE_FAIL:-0}" == "1" ]] && { echo "AccessDenied" >&2; exit 254; }
    printf '{}' ;;
  *delete-access-key*)
    printf '{}' ;;
  *) printf '{}' ;;
esac
"""


# The postgres provider no longer falls back to a naming convention for admin
# credentials -- they must be declared. Mirror what config/db-roles.json now
# states explicitly, so these fixtures exercise the same single path.
for _proj in DB_ROLES["projects"].values():
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
                "ref": PG_RO_REF,
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
                "ref": RESEND2_REF,
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
            "test-manual": {
                "ref": MANUAL_REF,
                "provider": "manual",
                "mode": "MANUAL",
                "owner_repo": "repo",
                "playbook": "console.x.ai -> API keys: create a new key.",
            },
        }
        self.write_config()

    def write_config(self) -> None:
        # Every rotation ref must have a route (fail-closed validator). Routes
        # that must NOT be activation targets are dev-kind (consumers derive
        # from render+github only). srv-target's health URL is deliberately
        # ABSENT from health: the fail-closed test needs it.
        routes = "\n".join([
            f"render\tsrv-target\tDATABASE_URL\t{PG_APP_REF}\tself",
            f"dev\tprofile\tDATABASE_URL_RO\t{PG_RO_REF}\tself",
            f"dev\tprofile\tOWNER_URL\t{PG_OWNER_SQLROLE_REF}\tself",
            f"render\tsrv-alpha\tRESEND_API_KEY\t{RESEND_REF}\tself",
            f"render\tsrv-alpha\tRESEND_API_KEY_2\t{RESEND2_REF}\tself",
            f"render\tsrv-alpha\tAWS_ACCESS_KEY_ID\t{AWS_ID_REF}\tself",
            f"render\tsrv-alpha\tAWS_SECRET_ACCESS_KEY\t{AWS_SECRET_REF}\tself",
            f"dev\tprofile\tOPENAI_API_KEY\t{OPENAI_REF}\tself",
            f"dev\tprofile\tXAI_API_KEY\t{MANUAL_REF}\tself",
            "",
        ])
        self.sb.write_manifest(routes, rotation=self.rotation)

    def env(self, **extra: str) -> dict[str, str]:
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

    # --- config --------------------------------------------------------------------

    def test_two_entries_sharing_a_ref_are_rejected_by_the_config(self) -> None:
        self.rotation["test-resend-unconfigured"]["ref"] = RESEND_REF
        self.write_config()
        proc = self.rotate("--ref", RESEND_REF, "--reason", "t", "--yes")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("is already rotated by", proc.stderr)
        self.assertEqual(self.log(), [])

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
            "--project", "testproj", "--item", "Postgres prod RO", "--field", "canonical",
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



# Drive a provider file directly, the way bin/rotate-secret does after sourcing
# it: ROTATE_* env describes the entry; commands run in one bash process.
# vault_replace_fields (owned by vault.sh) is shimmed when the lib lacks it.
DRIVER = """
set -uo pipefail
source "$LIB/read.sh"; source "$LIB/vault.sh"
declare -F vault_replace_fields >/dev/null || vault_replace_fields() {
  local a; for a in "$@"; do VAULT_VALUE="${a#*=}" vault_write_value "${a%%=*}" || return 1; done; }
source "$PROVIDERS/$ROTATE_PROVIDER.sh"
"""


class ProviderContractTest(unittest.TestCase):
    """§1 provider contract for the non-postgres providers."""

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        for name, body in (("curl", FAKE_CURL), ("aws", FAKE_AWS)):
            path = self.sb.fakebin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)

    def seed_item(self, ref: str, value: str) -> None:
        vault, item, field = ref.removeprefix("op://").split("/")
        (self.sb.state / f"{vault}__{item}__{field}").write_text(value, encoding="utf-8")

    def stored_value(self, ref: str) -> str:
        vault, item, field = ref.removeprefix("op://").split("/")
        return (self.sb.state / f"{vault}__{item}__{field}").read_text(encoding="utf-8")

    def log(self) -> list[str]:
        return self.sb.log_lines()

    def drive(self, provider: str, entry: dict, script: str, *, ref: str | None = None,
              rid: str = "e1", env_extra: dict | None = None, stdin: str = ""):
        entry = {"id": rid, "project": "testproj", "provider": provider,
                 "mode": "DUAL_KEY", "owner_repo": "repo", **entry}
        env = self.sb.env(
            LIB=str(ROOT / "secrets" / "lib"),
            PROVIDERS=str(ROOT / "secrets" / "providers"),
            ROTATE_ENTRY_JSON=json.dumps(entry),
            ROTATE_ID=rid, ROTATE_PROJECT="testproj",
            ROTATE_REF=ref or entry["ref"], ROTATE_PROVIDER=provider,
            **(env_extra or {}),
        )
        return run(["bash", "-c", DRIVER + script], env, stdin=stdin)

    # --- resend --------------------------------------------------------------

    RESEND_ENTRY = {"ref": RESEND_REF, "config": {"key_name": "testkey"}}
    ROTATE_THEN_FINALIZE = (
        'provider_rotate; echo "RC=$?"; echo "FIN=$PROVIDER_FINALIZE_JSON"; '
        'provider_verify; echo "VRC=$?"; '
        'provider_finalize "$PROVIDER_FINALIZE_JSON"; echo "FRC=$?"'
    )

    def test_resend_auto_ready_iff_key_name(self) -> None:
        ok = self.drive("resend", self.RESEND_ENTRY, 'provider_auto_ready; echo "RC=$? ACCEPTS=$PROVIDER_ACCEPTS_COMPLETE"')
        self.assertIn("RC=0 ACCEPTS=0", ok.stdout)
        no = self.drive("resend", {"ref": RESEND_REF}, 'provider_auto_ready; echo "RC=$? ACCEPTS=$PROVIDER_ACCEPTS_COMPLETE"')
        self.assertIn("RC=1 ACCEPTS=1", no.stdout)
        self.assertEqual(self.log(), [])  # read-free

    def test_resend_unconfigured_rotate_prints_playbook_exit_3_no_calls(self) -> None:
        proc = self.drive("resend", {"ref": RESEND_REF}, 'provider_rotate; echo "RC=$?"')
        self.assertIn("RC=3", proc.stdout)
        self.assertIn("config.key_name", proc.stdout)
        self.assertIn("--complete", proc.stdout)
        self.assertEqual(self.log(), [])

    def test_resend_exact_name_predecessors_and_finalize_with_new_key(self) -> None:
        self.seed_item(RESEND_REF, "resend-token-OLD")
        proc = self.drive("resend", self.RESEND_ENTRY, self.ROTATE_THEN_FINALIZE)
        self.assertIn("RC=0", proc.stdout, proc.stderr)
        self.assertIn("VRC=0", proc.stdout)
        self.assertIn("FRC=0", proc.stdout, proc.stderr)
        self.assertEqual(self.stored_value(RESEND_REF), "resend-token-NEW")
        fin = json.loads(proc.stdout.split("FIN=")[1].splitlines()[0])
        # Exact "<key_name> <ts>" matches only: not "testkey primary", not "testkeyfoo ...".
        self.assertEqual(fin, {"delete_ids": ["old-key-1", "old-key-2"]})
        log = self.log()
        combined = proc.stdout + proc.stderr + "\n".join(log)
        self.assertNotIn("resend-token-NEW", combined)
        listing = [l for l in log if "GET https://api.resend.com/api-keys" in l]
        deletes = [l for l in log if "DELETE https://api.resend.com/api-keys/" in l]
        self.assertTrue(listing[0].endswith("auth=old"))
        self.assertEqual(len(deletes), 2)
        self.assertTrue(all(l.endswith("auth=new") for l in deletes), deletes)
        self.assertNotIn("api-keys/prefix-key", combined)
        self.assertNotIn("api-keys/longer-name-key", combined)
        self.assertNotIn("api-keys/new-key-1", combined)
        # Ordering: list < create < vault write < delete.
        i_list = next(i for i, l in enumerate(log) if "GET https://api.resend.com/api-keys" in l)
        i_create = next(i for i, l in enumerate(log) if "POST https://api.resend.com/api-keys" in l)
        i_vault = next(i for i, l in enumerate(log) if "OP item edit" in l)
        i_del = next(i for i, l in enumerate(log) if "DELETE" in l)
        self.assertLess(i_list, i_create)
        self.assertLess(i_create, i_vault)
        self.assertLess(i_vault, i_del)

    def test_resend_finalize_tolerates_already_deleted_ids_and_reports_real_failures(self) -> None:
        self.seed_item(RESEND_REF, "resend-token-NEW")
        fin = json.dumps({"delete_ids": ["gone-key", "old-key-1"]})
        ok = self.drive("resend", self.RESEND_ENTRY, f"provider_finalize '{fin}'; echo \"FRC=$?\"",
                        env_extra={"FAKE_CURL_404_URL_SUBSTR": "api-keys/gone-key"})
        self.assertIn("FRC=0", ok.stdout, ok.stderr)
        bad = self.drive("resend", self.RESEND_ENTRY, f"provider_finalize '{fin}'; echo \"FRC=$?\"",
                         env_extra={"FAKE_CURL_500_URL_SUBSTR": "api-keys/gone-key"})
        self.assertIn("FRC=1", bad.stdout)
        self.assertIn("could not be deleted", bad.stderr)
        empty = self.drive("resend", self.RESEND_ENTRY, 'provider_finalize ""; echo "FRC=$?"')
        self.assertIn("FRC=2", empty.stdout)
        none = self.drive("resend", self.RESEND_ENTRY, 'provider_finalize "{}"; echo "FRC=$?"')
        self.assertIn("FRC=0", none.stdout)

    def test_resend_vault_write_failure_retires_the_unused_new_key(self) -> None:
        self.seed_item(RESEND_REF, "resend-token-OLD")
        proc = self.drive("resend", self.RESEND_ENTRY, 'provider_rotate; echo "RC=$?"',
                          env_extra={"FAKE_OP_EDIT_CONFLICTS": "1"})
        self.assertIn("RC=4", proc.stdout, proc.stderr)
        self.assertEqual(self.stored_value(RESEND_REF), "resend-token-OLD")
        self.assertTrue(any("DELETE https://api.resend.com/api-keys/new-key-1" in l for l in self.log()))
        self.assertFalse(any("api-keys/old-key" in l for l in self.log()))

    def test_resend_verify_command_sees_new_value_in_child_env_only(self) -> None:
        self.seed_item(RESEND_REF, "resend-token-OLD")
        entry = dict(self.RESEND_ENTRY, verify_command='[ "$ROTATE_NEW_VALUE" = resend-token-NEW ]')
        proc = self.drive("resend", entry, 'provider_rotate; provider_verify; echo "VRC=$? PARENT=${ROTATE_NEW_VALUE:-unset}"')
        self.assertIn("VRC=0 PARENT=unset", proc.stdout, proc.stderr)
        failing = dict(self.RESEND_ENTRY, verify_command="exit 1")
        proc = self.drive("resend", failing, 'provider_rotate; provider_verify; echo "VRC=$?"')
        self.assertIn("VRC=1", proc.stdout)

    def test_api_base_override_needs_test_mode(self) -> None:
        self.seed_item(RESEND_REF, "resend-token-OLD")
        proc = self.drive("resend", self.RESEND_ENTRY, "provider_rotate >/dev/null",
                          env_extra={"RESEND_API_BASE": "https://evil.example"})
        self.assertTrue(all("api.resend.com" in l for l in self.log() if l.startswith("CURL")))
        self.sb.log_path.unlink()
        self.drive("resend", self.RESEND_ENTRY, "provider_rotate >/dev/null 2>&1",
                   env_extra={"RESEND_API_BASE": "https://evil.example", "SECRETS_TEST_MODE": "1"})
        self.assertTrue(any("evil.example" in l for l in self.log()))

    # --- openai --------------------------------------------------------------

    OPENAI_ENTRY = {"ref": OPENAI_REF, "config": {
        "admin_key_ref": "op://TESTVAULT/OPENAI_ADMIN/value", "project_id": "proj_123"}}

    def test_openai_auto_ready_and_unconfigured_playbook(self) -> None:
        ok = self.drive("openai", self.OPENAI_ENTRY, 'provider_auto_ready; echo "RC=$? ACCEPTS=$PROVIDER_ACCEPTS_COMPLETE"')
        self.assertIn("RC=0 ACCEPTS=0", ok.stdout)
        no = self.drive("openai", {"ref": OPENAI_REF}, 'provider_auto_ready; echo "RC=$? ACCEPTS=$PROVIDER_ACCEPTS_COMPLETE"; provider_rotate; echo "RRC=$?"')
        self.assertIn("RC=1 ACCEPTS=1", no.stdout)
        self.assertIn("RRC=3", no.stdout)
        self.assertIn("config.admin_key_ref", no.stdout)
        self.assertEqual([l for l in self.log() if l.startswith("CURL")], [])

    def test_openai_paginates_predecessors_and_finalizes_all_pages(self) -> None:
        self.seed_item(OPENAI_REF, "sk-proj-OLD")
        self.seed_item("op://TESTVAULT/OPENAI_ADMIN/value", "sk-admin-x")
        proc = self.drive("openai", self.OPENAI_ENTRY, self.ROTATE_THEN_FINALIZE, rid="test-openai")
        self.assertIn("RC=0", proc.stdout, proc.stderr)
        self.assertIn("VRC=0", proc.stdout)
        self.assertIn("FRC=0", proc.stdout, proc.stderr)
        fin = json.loads(proc.stdout.split("FIN=")[1].splitlines()[0])
        self.assertEqual(fin, {"delete_ids": ["sa-old-1", "sa-old-3"]})  # both pages, exact names only
        self.assertEqual(self.stored_value(OPENAI_REF), "sk-proj-NEW")
        log = self.log()
        self.assertTrue(any("after=sa-page1-last" in l for l in log))
        self.assertTrue(any("DELETE" in l and "sa-old-3" in l for l in log))
        self.assertFalse(any("sa-page1-last" in l and "DELETE" in l for l in log))
        self.assertTrue(any("GET https://api.openai.com/v1/models auth=new" in l for l in log))
        self.assertNotIn("sk-proj-NEW", proc.stdout + proc.stderr + "\n".join(log))

    # --- aws_iam -------------------------------------------------------------

    AWS_ENTRY = {"ref": AWS_ID_REF, "sync_refs": [AWS_ID_REF, AWS_SECRET_REF], "config": {
        "iam_user": "test-iam-user", "secret_ref": AWS_SECRET_REF, "profile": "test-admin"}}

    def _seed_aws(self) -> None:
        self.seed_item(AWS_ID_REF, AWS_OLD_ID)
        self.seed_item(AWS_SECRET_REF, "aws-secret-OLD")

    def test_aws_auto_ready_needs_user_secret_ref_and_admin(self) -> None:
        for cfg, want in (
            ({"iam_user": "u", "secret_ref": AWS_SECRET_REF, "profile": "p"}, 0),
            ({"iam_user": "u", "secret_ref": AWS_SECRET_REF,
              "admin_key_id_ref": "op://V/A/id", "admin_secret_ref": "op://V/A/secret"}, 0),
            ({"iam_user": "u", "secret_ref": AWS_SECRET_REF}, 1),
            ({"iam_user": "u", "profile": "p"}, 1),
            ({}, 1),
        ):
            with self.subTest(cfg=cfg):
                proc = self.drive("aws_iam", {"ref": AWS_ID_REF, "config": cfg}, 'provider_auto_ready; echo "RC=$?"')
                self.assertIn(f"RC={want}", proc.stdout)
        self.assertEqual(self.log(), [])

    def test_aws_pair_flow_mints_writes_pair_verifies_and_finalizes(self) -> None:
        self._seed_aws()
        proc = self.drive("aws_iam", self.AWS_ENTRY, self.ROTATE_THEN_FINALIZE,
                          env_extra={"FAKE_AWS_OLD_ID": AWS_OLD_ID})
        self.assertIn("RC=0", proc.stdout, proc.stderr)
        self.assertIn("VRC=0", proc.stdout)
        self.assertIn("FRC=0", proc.stdout, proc.stderr)
        self.assertEqual(self.stored_value(AWS_ID_REF), AWS_NEW_ID)
        self.assertEqual(self.stored_value(AWS_SECRET_REF), "aws-secret-NEW")
        fin = json.loads(proc.stdout.split("FIN=")[1].splitlines()[0])
        self.assertEqual(fin, {"old_key_id": AWS_OLD_ID})
        log = self.log()
        self.assertNotIn("aws-secret-NEW", proc.stdout + proc.stderr + "\n".join(log))
        edits = [i for i, l in enumerate(log) if "OP item edit" in l]
        inactive = [i for i, l in enumerate(log) if "update-access-key" in l]
        delete = [i for i, l in enumerate(log) if "delete-access-key" in l]
        sts = [i for i, l in enumerate(log) if "get-caller-identity" in l]
        self.assertEqual(len(edits), 1)  # the pair is ONE locked item edit
        self.assertEqual((len(inactive), len(delete)), (1, 1))
        self.assertLess(max(edits), sts[0])
        self.assertLess(sts[0], inactive[0])
        self.assertLess(inactive[0], delete[0])
        self.assertIn(AWS_OLD_ID, log[delete[0]])

    def test_aws_verify_command_gets_pair_in_child_env(self) -> None:
        self._seed_aws()
        entry = dict(self.AWS_ENTRY, verify_command=(
            '[ "$ROTATE_NEW_VALUE" = AKIANEWKEY1111111 ] && [ "$ROTATE_NEW_SECRET_VALUE" = aws-secret-NEW ]'))
        proc = self.drive("aws_iam", entry, 'provider_rotate >/dev/null; provider_verify; echo "VRC=$? P=${ROTATE_NEW_VALUE:-unset}"',
                          env_extra={"FAKE_AWS_OLD_ID": AWS_OLD_ID})
        self.assertIn("VRC=0 P=unset", proc.stdout, proc.stderr)
        self.assertFalse(any("get-caller-identity" in l for l in self.log()))

    def test_aws_second_key_returns_7_and_reconcile_completes_when_vault_pair_authenticates(self) -> None:
        self._seed_aws()
        env = {"FAKE_AWS_OLD_ID": AWS_OLD_ID, "FAKE_AWS_EXTRA_KEY": "AKIAORPHANKEY0001"}
        proc = self.drive("aws_iam", self.AWS_ENTRY,
                          'provider_rotate; echo "RC=$?"; provider_reconcile; echo "RRC=$? FIN=$PROVIDER_FINALIZE_JSON"',
                          env_extra=env)
        self.assertIn("RC=7", proc.stdout, proc.stderr)
        self.assertIn("RRC=0", proc.stdout, proc.stderr)
        fin = json.loads(proc.stdout.split("FIN=")[1].splitlines()[0])
        self.assertEqual(fin, {"old_key_id": "AKIAORPHANKEY0001"})
        self.assertIn("orphan", proc.stdout)  # extra key is newer than the vault key
        self.assertFalse(any("create-access-key" in l for l in self.log()))
        self.assertFalse(any("delete-access-key" in l for l in self.log()))
        self.assertEqual(self.stored_value(AWS_ID_REF), AWS_OLD_ID)

    def test_aws_reconcile_older_other_key_is_an_unfinished_rotation(self) -> None:
        self._seed_aws()
        env = {"FAKE_AWS_OLD_ID": AWS_OLD_ID, "FAKE_AWS_EXTRA_KEY": "AKIAPREDECESSOR01",
               "FAKE_AWS_EXTRA_DATE": "2025-12-01T00:00:00Z"}
        proc = self.drive("aws_iam", self.AWS_ENTRY, 'provider_reconcile; echo "RRC=$?"', env_extra=env)
        self.assertIn("RRC=0", proc.stdout, proc.stderr)
        self.assertIn("unfinished rotation", proc.stdout)

    def test_aws_reconcile_refuses_when_vault_pair_fails_sts(self) -> None:
        self._seed_aws()
        env = {"FAKE_AWS_OLD_ID": AWS_OLD_ID, "FAKE_AWS_EXTRA_KEY": "AKIAOTHERKEY00001", "FAKE_AWS_STS_FAIL": "1"}
        proc = self.drive("aws_iam", self.AWS_ENTRY, 'provider_reconcile; echo "RRC=$? FIN=$PROVIDER_FINALIZE_JSON"', env_extra=env)
        self.assertIn("RRC=3 FIN=", proc.stdout)
        self.assertIn("does not authenticate", proc.stderr)
        self.assertFalse(any("delete-access-key" in l for l in self.log()))

    def test_aws_rotate_refuses_when_vault_id_is_not_on_the_user(self) -> None:
        self._seed_aws()
        # Listing without the vault's id at all (two foreign keys) -> refuse, no create.
        env = {"FAKE_AWS_OLD_ID": "AKIAFOREIGNKEY001", "FAKE_AWS_EXTRA_KEY": "AKIAFOREIGNKEY002"}
        proc = self.drive("aws_iam", self.AWS_ENTRY, 'provider_rotate; echo "RC=$?"', env_extra=env)
        self.assertIn("RC=3", proc.stdout)
        self.assertFalse(any("create-access-key" in l for l in self.log()))

    def test_aws_finalize_is_idempotent_and_reports_revoke_failure(self) -> None:
        self._seed_aws()
        fin = json.dumps({"old_key_id": AWS_OLD_ID})
        gone = self.drive("aws_iam", self.AWS_ENTRY, f"provider_finalize '{fin}'; echo \"FRC=$?\"",
                          env_extra={"FAKE_AWS_OLD_ID": "AKIASOMEOTHERKEY1"})
        self.assertIn("FRC=0", gone.stdout, gone.stderr)
        self.assertIn("already gone", gone.stdout)
        self.assertFalse(any("update-access-key" in l or "delete-access-key" in l for l in self.log()))
        failed = self.drive("aws_iam", self.AWS_ENTRY, f"provider_finalize '{fin}'; echo \"FRC=$?\"",
                            env_extra={"FAKE_AWS_OLD_ID": AWS_OLD_ID, "FAKE_AWS_UPDATE_FAIL": "1"})
        self.assertIn("FRC=1", failed.stdout)
        self.assertIn("could not deactivate", failed.stderr)
        self.assertFalse(any("delete-access-key" in l for l in self.log()))

    def test_aws_unconfigured_prints_playbook_exit_3(self) -> None:
        proc = self.drive("aws_iam", {"ref": AWS_ID_REF, "config": {"iam_user": "u"}}, 'provider_rotate; echo "RC=$?"')
        self.assertIn("RC=3", proc.stdout)
        self.assertIn("config.iam_user", proc.stdout)
        self.assertEqual(self.log(), [])

    # --- self_minted / manual ------------------------------------------------

    def test_self_minted_is_auto_ready_and_writes_vault(self) -> None:
        ref = "op://TESTVAULT/HMAC/value"
        proc = self.drive("self_minted", {"ref": ref, "mode": "SELF_MINTED", "generate": {"format": "hex", "bytes": 8}},
                          'provider_auto_ready; echo "AR=$? ACCEPTS=$PROVIDER_ACCEPTS_COMPLETE"; provider_rotate; echo "RC=$?"; '
                          'provider_verify; echo "VRC=$?"; provider_finalize ""; echo "FRC=$?"')
        self.assertIn("AR=0 ACCEPTS=0", proc.stdout)
        self.assertIn("RC=0", proc.stdout, proc.stderr)
        self.assertIn("VRC=0", proc.stdout)
        self.assertIn("FRC=0", proc.stdout)  # nothing to finalize; never refuses
        self.assertRegex(self.stored_value(ref), r"^[0-9a-f]{16}$")

    def test_manual_accepts_complete_and_never_auto(self) -> None:
        proc = self.drive("manual", {"ref": MANUAL_REF, "mode": "MANUAL", "playbook": "console.x.ai -> API keys"},
                          'echo "ACCEPTS=$PROVIDER_ACCEPTS_COMPLETE"; provider_auto_ready; echo "AR=$?"; provider_rotate; echo "RC=$?"')
        self.assertIn("ACCEPTS=1", proc.stdout)
        self.assertIn("AR=1", proc.stdout)
        self.assertIn("RC=3", proc.stdout)
        self.assertIn("console.x.ai", proc.stdout)
        self.assertIn("--complete", proc.stdout)
        self.assertEqual(self.log(), [])

    def test_xai_provider_is_gone(self) -> None:
        self.assertFalse((ROOT / "secrets" / "providers" / "xai.sh").exists())


class PostgresRotatorSourceTest(unittest.TestCase):
    """Source invariants of secrets/providers/postgres-rotate that only
    reproduce against live Render/Postgres (idle-proxy drops, cross-workspace
    403s, membership semantics)."""

    SOURCE = (ROOT / "secrets" / "providers" / "postgres-rotate").read_text()

    def _function_body(self, name: str) -> str:
        start = self.SOURCE.index(f"\n{name}() {{")
        end = self.SOURCE.index("\n}\n", start)
        return self.SOURCE[start:end]

    def test_every_drain_loop_probes_the_lock_each_poll(self) -> None:
        # The lock session idles over the Render external proxy (~5min idle
        # drop) for the whole 600s drain budget; each poll must probe it.
        for name in ("wait_for_predecessor_drain", "wait_for_fenced_sql_drain"):
            with self.subTest(drain=name):
                body = self._function_body(name)
                probe = body.index("assert_rotation_lock_live")
                loop = body.index("while [[")
                self.assertGreater(probe, loop, f"{name} probes outside its poll loop")
                self.assertIn("sleep \"${ROTATION_DRAIN_POLL_SECONDS:-10}\"", body)
        self.assertNotIn("start_rotation_lock_watchdog", self.SOURCE)

    def test_hooks_cannot_desync_the_lock_protocol(self) -> None:
        # The lock is a strict one-write/one-read exchange on fds 8/7.
        for hook in ('"$ROTATE_HOOK" drain-stall', '"$ROTATE_HOOK" activate'):
            line = next(l for l in self.SOURCE.splitlines() if hook in l)
            self.assertIn("8>&-", line, hook)
            self.assertIn("7<&-", line, hook)

    def test_admin_refs_have_no_convention_fallback(self) -> None:
        self.assertNotIn("admin_vault_for_tier", self.SOURCE)
        for field in ("root", "owner"):
            self.assertIn(f"no admin_refs.$INSTANCE_TIER.{field}", self.SOURCE)

    def test_every_configured_tier_declares_grouped_admin_refs(self) -> None:
        cfg = json.loads((ROOT / "config" / "db-roles.json").read_text())
        for name, proj in cfg["projects"].items():
            for tier in (proj.get("tiers") or {}):
                via = ((proj["tiers"][tier].get("admin_via") or {}).get("project"))
                admin = cfg["projects"][via] if via else proj
                admin_tier = tier if not via else "prod"
                refs = (admin.get("admin_refs") or {}).get(admin_tier) or {}
                with self.subTest(project=name, tier=tier):
                    for field in ("root", "owner"):
                        ref = refs.get(field)
                        self.assertTrue(ref, f"{name}/{tier}: no admin {field} ref")
                        self.assertRegex(ref, rf"^op://[^/]+/Postgres {admin_tier}/{field}$")
                        self.assertNotIn("POSTGRES_URL", ref)

    def test_lock_key_is_the_single_source_for_lock_hash_and_print(self) -> None:
        self.assertIn('LOCK_KEY="${ADMIN_PROJECT}/${INSTANCE_TIER}"', self.SOURCE)
        body = self._function_body("acquire_rotation_lock")
        self.assertIn('"${LOCK_KEY%/*}" "${LOCK_KEY#*/}"', body)
        self.assertIn("-credential-rotation:", body)
        self.assertIn("PGKEEPALIVESIDLE=30", body)
        self.assertIn("PGKEEPALIVESINTERVAL=10", body)
        self.assertIn("PGKEEPALIVESCOUNT=6", body)
        # root URL: rehost first, then strip SET ROLE options (ts_root holds
        # ADMIN OPTION on ts_user; SET ROLE ts_user does not).
        self.assertLess(body.index("db_rehost_url"), body.index("db_url_without_role_option"))

    def test_candidate_mutation_guard_compares_transformed_live_values(self) -> None:
        body = self._function_body("_verify_candidate_target")
        self.assertIn("apply_transform", body)
        self.assertIn("ROTATION_TRANSFORMS[$1]", body)

    def test_service_env_reads_use_the_consumer_workspace_key(self) -> None:
        # Autodev services live in the autodev Render workspace; the shared
        # box's admin key is workflow-pro (HTTP 403 for /services/<sid>).
        for name in ("target_live_value", "rotation_get_env", "rotation_put_env",
                     "rotation_trigger_deploy", "rotation_wait_deploy"):
            with self.subTest(fn=name):
                self.assertIn("with_sid_render_key", self._function_body(name))
        # every live-target consumer goes through the one iterator
        for name in ("capture_predecessors", "observe_candidate_value",
                     "verify_sql_candidate_before_mutation", "verify_declared_targets_current"):
            with self.subTest(fn=name):
                self.assertIn("for_each_live_target", self._function_body(name))

    def test_scope_mapping_uses_grouped_fields_only(self) -> None:
        self.assertNotIn("POSTGRES_URL_", self.SOURCE)
        self.assertIn('"${slug}_migrator") SCOPE_KIND="migrator"', self.SOURCE)
        self.assertIn('"${slug}_ro") SCOPE_KIND="ro"', self.SOURCE)
        self.assertIn('SET_ROLE_TARGET="$CAPABILITY"', self.SOURCE)

    def test_rotation_never_reassigns_ownership(self) -> None:
        # C4: ownership transfer is a provisioning step (per relation, datdba
        # guarded); rotation only creates/grants versioned logins.
        self.assertNotIn("REASSIGN OWNED", self.SOURCE)
        body = self._function_body("create_candidate_login")
        self.assertIn("CREATE ROLE", body)
        self.assertIn("WITH INHERIT TRUE, SET TRUE, ADMIN FALSE", body)
        self.assertNotIn("GRANT ts_user", body)
        self.assertEqual(self.SOURCE.count("SELECT format('CREATE ROLE %I NOINHERIT LOGIN"), 1)

    def test_protected_principals_are_never_retired(self) -> None:
        body = self._function_body("protected_login")
        for var in ("ADMIN_TABLE_OWNER", "TABLE_OWNER", "ROOT_LOGIN"):
            self.assertIn(var, body)
        for fn in ("record_predecessor", "retire_sql_predecessors", "retire_owner_predecessors"):
            self.assertIn("protected_login", self._function_body(fn), fn)
        self.assertNotIn("2>&1 <<'SQL'", self._function_body("retire_owner_predecessor_sql"))
        # the final capability NOLOGIN is guarded like every other retirement site
        self.assertIn('protected_login "$CAPABILITY"', self._function_body("retire_sql_predecessors"))

    def test_inventory_scans_every_consumer_workspace_with_markers(self) -> None:
        body = self._function_body("run_inventory_scan")
        self.assertIn("inventory_render_key_refs", body)
        self.assertIn("render_inventory_clean_cached", body)
        self.assertIn('ROTATION_INSTANCE_MARKERS="${DB_ID%-a} ', self.SOURCE)
        self.assertIn('startswith("pgbouncer=")', self.SOURCE)
        lib = (ROOT / "secrets" / "lib" / "db-rotation.sh").read_text()
        self.assertIn("ROTATE_INVENTORY_CACHE_DIR", lib)
        self.assertIn("ROTATE_SWEEP_ID", lib)
        self.assertIn("ROTATION_DECLARED_DESTS", lib)
        self.assertIn("declared consumer render[", lib)
        self.assertNotIn("all_old_logins", lib + self.SOURCE)

    def test_autodev_dashboard_repo_maps_to_the_autodev_render_key(self) -> None:
        import subprocess

        tools = ROOT / "config" / "project-tools.json"
        script = r"""
jq -r --arg repo "autodev-dashboard" '
  [.projects | to_entries[]
   | select(any(.value.repo_remotes[]?;
       (split("/")[-1] == $repo) or (split("/")[-1] == ($repo + ".git"))))
   | .key] | unique | .[]
' """
        project = subprocess.check_output(
            ["bash", "-lc", script + str(tools)], text=True
        ).strip()
        self.assertEqual(project, "autodev")
        key = json.loads(tools.read_text())["projects"][project]["render"]["api_key_ref"]
        self.assertEqual(key, "op://AUTODEV-sensitive/Render/api_key")
        admin = json.loads((ROOT / "config" / "db-roles.json").read_text())["projects"][
            "autodev"
        ]["render_key_ref"]
        self.assertEqual(admin, "op://WORKFLOW_PRO/Render/api_key")
        self.assertNotEqual(key, admin)


class PostgresRotatorStagesTest(unittest.TestCase):
    """Drives secrets/providers/postgres-rotate directly (the rotate-secret
    entry contract in env) against fake op/psql/curl: rotate stops at
    `promoted`, finalize retires, resume never re-activates."""

    ROOT_URL = "postgresql://rootuser:rootpw@external-host:5432/testdb"
    ADMIN_OWNER_URL = (
        "postgresql://testproj_owner_login_20260801t000000_aa11bb:ownerpw@internal-host:5432/testdb"
        "?options=-c%20role%3Dtestproj_dbuser"
    )

    def setUp(self) -> None:
        self.sb = SecretsSandbox()
        self.addCleanup(self.sb.close)
        for name, body in (("curl", FAKE_CURL), ("psql", FAKE_PSQL)):
            path = self.sb.fakebin / name
            path.write_text(body, encoding="utf-8")
            path.chmod(0o755)
        self.db_roles_path = self.sb.root / "db-roles.json"
        self.db_roles_path.write_text(json.dumps(DB_ROLES), encoding="utf-8")
        self.state_dir = self.sb.root / "db-rotation-state"
        self.registry_path = self.sb.root / "registry.json"
        self.seed_item(PG_ROOT_REF, self.ROOT_URL)
        self.seed_item(PG_ADMIN_OWNER_REF, self.ADMIN_OWNER_URL)

    # -- helpers -----------------------------------------------------------------
    def item_path(self, ref: str):
        vault, item, field = ref.removeprefix("op://").split("/")
        return self.sb.state / f"{vault}__{item}__{field}"

    def seed_item(self, ref: str, value: str) -> None:
        self.item_path(ref).write_text(value, encoding="utf-8")

    def stored_value(self, ref: str) -> str:
        return self.item_path(ref).read_text(encoding="utf-8")

    def entry(self, entry_id: str, ref: str, *, project: str = "testproj",
              targets: list[tuple[str, str]] | None = None) -> dict:
        routes = [
            {"repo": "testrepo", "kind": "render", "dest": d, "env": e, "ref": ref, "transform": "self"}
            for d, e in (targets or [])
        ]
        return {
            "id": entry_id, "project": project, "ref": ref, "provider": "postgres",
            "mode": "DUAL_KEY", "owner_repo": "testrepo",
            "consumers": [{"repo": r["repo"], "dest": r["dest"], "env": r["env"]} for r in routes],
            "routes": routes,
        }

    def rotator(self, entry: dict, *args: str, resume: bool = False, finalize: bool = False,
                **extra: str):
        self.registry_path.write_text(json.dumps({
            "schema_version": 1,
            "health_urls": {"srv-target": "https://health.test/ok"},
            "secrets": [entry],
        }), encoding="utf-8")
        env = self.sb.env(
            DB_ROLES_CONFIG=str(self.db_roles_path),
            DB_ROTATION_STATE_DIR=str(self.state_dir),
            SECRET_ROTATION_CONFIG=str(self.registry_path),
            ROTATE_ENTRY_JSON=json.dumps(entry),
            ROTATE_REASON="t",
            ROTATE_RESUME="1" if resume else "0",
            ROTATE_FINALIZE="1" if finalize else "0",
            ROTATION_DRAIN_POLL_SECONDS="0",
            ROTATION_DRAIN_STABLE_POLLS="1",
            **extra,
        )
        return run([ROTATOR, *args], env, stdin="")

    def log(self) -> list[str]:
        return self.sb.log_lines()

    def sql_log(self) -> str:
        return "\n".join(l for l in self.log() if l.startswith("SQL ") or l.startswith("PSQL "))

    def state(self, name: str) -> dict:
        return json.loads((self.state_dir / name).read_text(encoding="utf-8"))

    # -- tests -------------------------------------------------------------------
    def test_print_lock_key_is_read_free(self) -> None:
        for entry, key in (
            (self.entry("pg-app", PG_APP_REF), "testproj/prod"),
            (self.entry("pg-owner-sqlrole", PG_OWNER_SQLROLE_REF, project="sqlproj"), "testproj/prod"),
            (self.entry("pg-canonical", "op://TESTVAULT-sensitive/Postgres prod/canonical"), "testproj/prod"),
        ):
            with self.subTest(entry=entry["id"]):
                env = self.sb.env(DB_ROLES_CONFIG=str(self.db_roles_path), ROTATE_ENTRY_JSON=json.dumps(entry))
                proc = run([ROTATOR, "--print-lock-key"], env, stdin="")
                self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                self.assertEqual(proc.stdout, key + "\n")
        self.assertEqual(self.log(), [])

    def test_rotate_stops_at_promoted_and_finalize_retires(self) -> None:
        self.seed_item(PG_RO_REF, "postgresql://testproj_ro:oldpw@external-host:5432/testdb")
        entry = self.entry("pg-ro", PG_RO_REF)

        proc = self.rotator(entry)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("Rotation promoted", proc.stdout)
        state = self.state("testproj-prod-ro.state")
        self.assertEqual(state["phase"], "promoted")
        self.assertEqual(state["oldLogins"], "testproj_ro")
        self.assertTrue(state["login"].startswith("testproj_ro_login_"))
        # canonical now holds the candidate; predecessor untouched
        self.assertIn(state["login"], self.stored_value(PG_RO_REF))
        sql = self.sql_log()
        self.assertIn("CREATE ROLE", sql)
        self.assertNotIn("NOLOGIN", sql)
        self.assertNotIn("DROP ROLE", sql)
        self.assertNotIn("oldpw", proc.stdout + proc.stderr + "\n".join(self.log()))
        # a second plain run refuses the unfinished state instead of re-minting
        proc2 = self.rotator(entry)
        self.assertEqual(proc2.returncode, 2, proc2.stderr)
        self.assertIn("unfinished", proc2.stderr)

        self.sb.log_path.write_text("", encoding="utf-8")
        proc3 = self.rotator(entry, resume=True, finalize=True)
        self.assertEqual(proc3.returncode, 0, proc3.stderr + proc3.stdout)
        self.assertIn("Credential rotation complete", proc3.stdout)
        self.assertFalse((self.state_dir / "testproj-prod-ro.state").exists())
        sql = self.sql_log()
        self.assertIn("-v old=testproj_ro", sql)
        self.assertIn("ALTER ROLE %I NOLOGIN PASSWORD NULL", sql)
        # the capability itself is fenced + NOLOGIN'd, never dropped
        self.assertNotIn("DROP ROLE", sql)
        self.assertIn("SELECT rolcanlogin FROM pg_roles", sql)
        # inventory scanned and candidate item removed
        joined = "\n".join(self.log())
        self.assertIn("CURL GET https://api.render.com/v1/services?limit=100", joined)
        self.assertIn("OP item delete", joined)
        self.assertFalse(self.item_path(state["candidateRef"]).exists())

    def test_resume_without_state_is_a_fresh_rotation(self) -> None:
        # rotate-project always passes --resume (ROTATE_RESUME=1): with no
        # rotator state that must be a normal fresh run, not "no resumable state".
        self.seed_item(PG_RO_REF, "postgresql://testproj_ro:oldpw@external-host:5432/testdb")
        entry = self.entry("pg-ro", PG_RO_REF)
        proc = self.rotator(entry, resume=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("starting a fresh rotation", proc.stdout)
        self.assertIn("Rotation promoted", proc.stdout)
        state = self.state("testproj-prod-ro.state")
        self.assertEqual(state["phase"], "promoted")
        self.assertIn(state["login"], self.stored_value(PG_RO_REF))
        # a plain run still refuses the unfinished state
        proc2 = self.rotator(entry)
        self.assertEqual(proc2.returncode, 2, proc2.stderr)
        self.assertIn("unfinished", proc2.stderr)

    def test_finalize_without_state_is_a_noop(self) -> None:
        proc = self.rotator(self.entry("pg-ro", PG_RO_REF), resume=True, finalize=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("nothing to finalize", proc.stdout)
        self.assertEqual(self.log(), [])

    def test_drop_role_failure_is_best_effort(self) -> None:
        # Versioned predecessor (the capability itself is only ever NOLOGIN'd).
        old = "testproj_ro_login_20260101t000000_aaaaaa"
        self.seed_item(PG_RO_REF, f"postgresql://{old}:oldpw@external-host:5432/testdb")
        entry = self.entry("pg-ro", PG_RO_REF)
        self.assertEqual(self.rotator(entry).returncode, 0)
        proc = self.rotator(entry, resume=True, finalize=True, FAKE_PSQL_DROP_FAIL="1")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn(f"WARN: DROP ROLE {old} failed", proc.stderr)
        self.assertIn(f"-v old={old}", self.sql_log())
        self.assertIn("Credential rotation complete", proc.stdout)
        self.assertIn("ALTER ROLE %I NOLOGIN PASSWORD NULL", self.sql_log())

    def test_table_owner_predecessor_is_protected_never_retired(self) -> None:
        # canonical RO field still holds the instance table owner (pre-cutover)
        self.seed_item(PG_RO_REF, "postgresql://testproj_dbuser:oldpw@external-host:5432/testdb")
        entry = self.entry("pg-ro", PG_RO_REF)
        proc = self.rotator(entry)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("protected principal", proc.stdout)
        self.assertEqual(self.state("testproj-prod-ro.state")["oldLogins"], "")
        proc = self.rotator(entry, resume=True, finalize=True)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertNotIn("-v old=testproj_dbuser", self.sql_log())
        self.assertNotIn("DROP ROLE", self.sql_log())

    def test_activated_resume_verifies_targets_without_reactivating(self) -> None:
        tag = "20260822t000000_abc123"
        login = f"testproj_app_login_{tag}"
        candidate_ref = f"op://TESTVAULT-sensitive/Postgres prod_CANDIDATE_app_{tag}/value"
        candidate = f"postgresql://{login}:candpw@internal-host:5432/testdb?options=-c%20role%3Dtestproj_app"
        self.seed_item(candidate_ref, candidate)
        self.seed_item(PG_APP_REF, "postgresql://testproj_app:oldpw@internal-host:5432/testdb?options=-c%20role%3Dtestproj_app")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "testproj-prod-app.state").write_text(json.dumps({
            "stateVersion": 1, "entryId": "pg-app", "project": "testproj", "tier": "prod",
            "scope": "app", "phase": "activated", "versionTag": tag, "login": login,
            "candidateRef": candidate_ref, "oldLogins": "testproj_app",
        }), encoding="utf-8")
        entry = self.entry("pg-app", PG_APP_REF, targets=[("srv-target", "DATABASE_URL")])
        proc = self.rotator(entry, resume=True, FAKE_RENDER_ENV_FILE=str(self.item_path(candidate_ref)))
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("no re-activation", proc.stdout)
        joined = "\n".join(self.log())
        self.assertNotIn("CURL PUT", joined)
        self.assertNotIn("/deploys", joined)
        self.assertIn("CURL GET https://health.test/ok", joined)
        self.assertIn("CURL GET https://api.render.com/v1/services/srv-target/env-vars/DATABASE_URL", joined)
        self.assertEqual(self.state("testproj-prod-app.state")["phase"], "promoted")
        self.assertEqual(self.stored_value(PG_APP_REF), candidate)

    def test_lock_connection_failure_exits_2(self) -> None:
        self.seed_item(PG_RO_REF, "postgresql://testproj_ro:oldpw@external-host:5432/testdb")
        proc = self.rotator(self.entry("pg-ro", PG_RO_REF), FAKE_PSQL_LOCK="garbage")
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("advisory-lock response was invalid", proc.stderr)
        self.assertFalse((self.state_dir / "testproj-prod-ro.state").exists())
        self.assertNotIn("OP item create", "\n".join(self.log()))


if __name__ == "__main__":
    unittest.main()

# shellcheck shell=bash
# providers/postgres.sh — dual-principal zero-downtime Postgres rotation.
#
# The state machine lives in the co-located `postgres-rotate` executable; this
# glue derives the plan (read-free, for --dry-run), runs the rotator for the
# rotate stage (stops at phase `promoted`, predecessor valid) and again with
# ROTATE_FINALIZE=1 for the finalize stage (drain, inventory, retire).
# Rotator exit codes map 1:1 onto the rotate-secret contract (0/2/3/4/5);
# 75 (advisory-lock session lost) is reported as 4 (state is safe, --resume).
#
# Sourced by bin/rotate-secret after read.sh + vault.sh. Interface:
#   provider_plan / provider_auto_ready / provider_rotate / provider_verify /
#   provider_finalize <json> / provider_playbook

_PG_PROVIDER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PG_ROTATOR="${POSTGRES_ROTATE_BIN:-$_PG_PROVIDER_DIR/postgres-rotate}"

provider_plan() { # read-free rotation plan for rotate-secret --dry-run
  local title consumers
  title="$(printf '%s' "$ROTATE_REF" | sed 's|^op://[^/]*/||')"
  echo "  postgres dual-principal rotation plan for $title:"
  echo "    1. acquire the instance advisory lock using the zero-consumer root login"
  echo "    2. create a uniquely versioned candidate login; predecessor stays valid"
  consumers="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '(.consumers // [])[] | "    3. stage candidate -> render[\(.dest)] \(.env)"')"
  if [[ -n "$consumers" ]]; then
    printf '%s\n' "$consumers"
    echo "    4. trigger all services, poll each exact deploy to live, probe registered health URLs"
  else
    echo "    3. no Render service consumes this item; verify the candidate directly"
  fi
  echo "    5. promote the candidate to the canonical item (immutable id, verified) and STOP (phase promoted)"
  echo "    6. rotate-secret fans out to every other destination, waits for deploys and health"
  echo "    7. finalize: drain predecessor sessions, scan ALL Render env/group/secret-file values,"
  echo "       fence and retire the predecessor only if every proof passes (else exit 6, finalize again)"
  echo "  guarantee boundary: no rotation-induced interruption for registry-declared"
  echo "  Render consumers while Render and Postgres remain available."
}

provider_auto_ready() { return 0; }

_pg_run_rotator() { # VAR=value... — rc passthrough; 75 -> 4
  local rc=0
  [[ -x "$_PG_ROTATOR" ]] || { echo "ERROR: postgres rotator not found: $_PG_ROTATOR" >&2; return 4; }
  env "$@" "$_PG_ROTATOR" || rc=$?
  if [[ "$rc" -eq 75 ]]; then
    echo "ERROR: the advisory-lock session was lost mid-rotation; state is safe. Re-run with --resume." >&2
    return 4
  fi
  [[ "$rc" -le 5 ]] || return 4
  return "$rc"
}

provider_rotate() {
  _pg_run_rotator ROTATE_FINALIZE=0 || return $?
  PROVIDER_FINALIZE_JSON="$(jq -nc --arg id "${ROTATE_ID:-}" \
    --arg d "${DB_ROTATION_STATE_DIR:-$HOME/.local/state/agent-workflows/db-rotation}" \
    '{rotator:"postgres-rotate", entryId:$id, stateDir:$d}')"
}

provider_verify() {
  # The rotator proved candidate, deploys, health and canonical equality before
  # returning 0. Nothing further to verify here.
  return 0
}

provider_finalize() { # <json> (informational; the rotator finds its own state file)
  # Idempotent: no rotation state -> "nothing to finalize", rc 0.
  _pg_run_rotator ROTATE_FINALIZE=1 ROTATE_RESUME=1
}

provider_playbook() {
  cat <<EOF
postgres rotation for $ROTATE_REF (dual-principal, zero-downtime):
  rotate:   candidate login -> batch PUT to every registry consumer -> exact deploys ->
            health probes -> canonical vault promotion (phase promoted; predecessor valid)
  finalize: drain + full Render inventory -> reversible fence -> retirement
  State: \${DB_ROTATION_STATE_DIR:-~/.local/state/agent-workflows/db-rotation}/<project>-<tier>-<scope>[-<app>].state
  Resume an interrupted rotation:  rotate-secret --ref '$ROTATE_REF' --reason ... --resume
  Retire the predecessor:          rotate-secret --ref '$ROTATE_REF' --reason ... --finalize
EOF
}

# shellcheck shell=bash
# providers/postgres.sh — dual-principal zero-downtime Postgres rotation
# (central port of amaru-web scripts/db/rotate-credentials).
#
# The state machine lives in the co-located `postgres-rotate` executable; this
# glue derives the plan (read-free, for --dry-run), runs the rotator, and maps
# its exit codes onto the rotate-secret contract:
#   rotator 0  -> 0 (rotate-secret then fans out sync-secrets --skip-db-rows)
#   rotator 2  -> 2 usage / state mismatch / lock contention (nothing changed)
#   rotator 3  -> 3 precondition refused, nothing changed (playbook printed)
#   rotator 4  -> 4 activation failed; paused before promotion, both logins valid
#   rotator 5  -> 5 promoted but retirement unproven; predecessor remains valid
#   rotator 75 -> 4 advisory-lock session lost; safe state, --resume later
#
# Sourced by bin/rotate-secret after read.sh + vault.sh. Interface:
#   provider_plan / provider_rotate / provider_verify / provider_playbook

_PG_PROVIDER_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_PG_ROTATOR="${POSTGRES_ROTATE_BIN:-$_PG_PROVIDER_DIR/postgres-rotate}"

provider_plan() { # read-free rotation plan for rotate-secret --dry-run
  local title consumers
  title="$(printf '%s' "$ROTATE_REF" | sed 's|^op://[^/]*/||; s|/[^/]*$||')"
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
  echo "    5. promote the candidate to the canonical item (immutable id, verified)"
  echo "    6. wait for predecessor drain and scan ALL Render env/group/secret-file values"
  echo "    7. retire the predecessor only if every proof passes (else exit 5, --resume)"
  echo "  guarantee boundary: no rotation-induced interruption for registry-declared"
  echo "  Render consumers while Render and Postgres remain available."
}

provider_rotate() {
  local rc=0
  [[ -x "$_PG_ROTATOR" ]] || { echo "ERROR: postgres rotator not found: $_PG_ROTATOR" >&2; return 4; }
  "$_PG_ROTATOR" || rc=$?
  case "$rc" in
    0) return 0 ;;
    2) return 2 ;;
    3) return 3 ;;
    4) return 4 ;;
    5) return 5 ;;
    75)
      echo "ERROR: the advisory-lock session was lost mid-rotation; state is safe. Re-run with --resume." >&2
      return 4
      ;;
    *) return 4 ;;
  esac
}

provider_verify() {
  # The rotator's own state machine proved deploys, health, canonical equality,
  # drain, and inventory before returning 0. Nothing further to verify here.
  return 0
}

provider_playbook() {
  cat <<EOF
postgres rotation for $ROTATE_REF (dual-principal, zero-downtime):
  candidate login -> batch PUT to every registry consumer -> exact deploys ->
  health probes -> canonical vault promotion -> drain + full Render inventory ->
  reversible fence -> retirement. State: \${DB_ROTATION_STATE_DIR:-~/.local/state/agent-workflows/db-rotation}/<project>-<tier>.state
  Resume an interrupted rotation with: rotate-secret --ref '$ROTATE_REF' --reason ... --resume
  Keep the predecessor valid after promotion with --keep-old.
EOF
}

# shellcheck shell=bash
# providers/postgres.sh — Postgres credential rotation. SLICE-1 STUB.
#
# The full dual-principal zero-downtime rotator (advisory lock, candidate
# logins, activation/promotion/drain/retirement state machine) is the amaru
# `scripts/db/rotate-credentials` design; its central port lands in slice 3/4.
# Until then:
#   * project == amaru  -> bridge: exec amaru-web's own rotator.
#   * anything else     -> rc 4 with a pointer; nothing is changed.
#
# Sourced by bin/rotate-secret after read.sh + vault.sh. Interface:
#   provider_rotate / provider_verify / provider_playbook

provider_rotate() {
  if [[ "$ROTATE_PROJECT" == "amaru" ]]; then
    local bridge="$ROTATE_OWNER_REPO/scripts/db/rotate-credentials"
    [[ -x "$bridge" ]] || { echo "ERROR: bridge rotator not found: $bridge" >&2; return 4; }
    local args=()
    while IFS= read -r a; do [[ -n "$a" ]] && args+=("$a"); done \
      < <(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.bridge_args // [] | .[]')
    echo "  bridging to $bridge (central postgres port pending, slice 3/4)"
    exec "$bridge" ${args[@]+"${args[@]}"} --reason "$ROTATE_REASON"
  fi
  echo "ERROR: central postgres rotation is not implemented yet (port of amaru" >&2
  echo "rotate-credentials pending, slice 3/4). Nothing was changed." >&2
  return 4
}

provider_verify() {
  return 0
}

provider_playbook() {
  cat <<EOF
postgres rotation for $ROTATE_REF:
  amaru: bridged to amaru-web scripts/db/rotate-credentials (dual-principal,
  zero-downtime). Other projects: pending the central port (slice 3/4) — use
  bin/db-provision-roles for app/ro password rotation in the meantime.
EOF
}

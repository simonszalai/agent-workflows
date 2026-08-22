# shellcheck shell=bash
# providers/self_minted.sh — rotate a secret WE mint ourselves (HMAC keys,
# session/bypass secrets, dashboard tokens). New value = `openssl rand`; the
# vault item is replaced in place by immutable id (create-if-absent), verified
# by re-read. No predecessor exists: the old value dies as consumers redeploy,
# so finalize is the no-op default.
#
# Registry knobs (entry "generate" object, validated by config.sh):
#   format: hex | base64   (default hex)
#   bytes:  N              (default 32)
# shellcheck source=../lib/provider-common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/provider-common.sh"

provider_auto_ready() { return 0; }

provider_rotate() {
  local format bytes new_value
  format="$(entry_field '.generate.format')"
  bytes="$(entry_field '.generate.bytes')"
  [[ -n "$format" ]] || format="hex"
  [[ -n "$bytes" ]] || bytes=32
  case "$format" in
    hex) new_value="$(openssl rand -hex "$bytes")" ;;
    base64) new_value="$(openssl rand -base64 "$bytes" | tr -d '\n')" ;;
    *) echo "ERROR: unknown self_minted generate.format: $format" >&2; return 4 ;;
  esac
  [[ -n "$new_value" ]] || { echo "ERROR: openssl produced an empty value — vault untouched" >&2; return 4; }
  VAULT_VALUE="$new_value" vault_write_value "$ROTATE_REF" || { new_value=""; return 4; }
  new_value=""
  echo "  minted new $format value for $ROTATE_REF ($bytes bytes)"
}

provider_verify() {
  # vault_write_value already re-read and byte-compared the stored value.
  local v
  verify_command_configured || return 0
  v="$(op_vault_read "$ROTATE_REF")" || return 1
  run_verify_command "$v"
}

provider_playbook() {
  cat <<EOF
self_minted rotation for $ROTATE_REF:
  1. Mint a fresh random value (openssl rand).
  2. Replace the vault item in place (immutable id, verified by re-read).
  3. rotate-secret fans out sync-secrets to the owner repo and every
     registered consumer repo (deploy-last per service).
No external provider is involved; the old value stops working as soon as every
consumer has redeployed (nothing to finalize).
EOF
}

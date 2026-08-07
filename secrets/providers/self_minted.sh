# shellcheck shell=bash
# providers/self_minted.sh — rotate a secret WE mint ourselves (HMAC keys,
# session/bypass secrets, dashboard tokens). New value = `openssl rand`; the
# vault item is replaced in place by immutable id (create-if-absent), verified
# by re-read; the caller (rotate-secret) then fans sync-secrets out to every
# registered consumer repo.
#
# Registry knobs (optional, in the entry's "generate" object):
#   format: hex | base64   (default hex)
#   bytes:  N              (default 32)
#
# Sourced by bin/rotate-secret after read.sh + vault.sh. Interface:
#   provider_rotate     mint + vault write; rc 0 = vault now holds the new value
#   provider_verify     vault write already verified by re-read; rc 0
#   provider_playbook   human description of what a rotation does

provider_rotate() {
  local format bytes new_value
  format="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.generate.format // "hex"')"
  bytes="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.generate.bytes // 32')"
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
  return 0
}

provider_playbook() {
  cat <<EOF
self_minted rotation for $ROTATE_REF:
  1. Mint a fresh random value (openssl rand).
  2. Replace the vault item in place (immutable id, verified by re-read).
  3. Fan out: sync-secrets --changed $ROTATE_REF in the owner repo and every
     registered consumer repo (deploy-last per service).
No external provider is involved; the old value stops working as soon as every
consumer has redeployed.
EOF
}

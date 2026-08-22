# shellcheck shell=bash
# providers/resend.sh — dual create/delete rotation for Resend API keys.
#
# rotate:   list keys -> predecessors = exact-name matches "<key_name> <UTC ts>"
#           -> POST /api-keys "<key_name> <now>" -> vault-replace by immutable id.
#           PROVIDER_FINALIZE_JSON = {"delete_ids":[...]} (value-free).
# verify:   entry verify_command (ROTATE_NEW_VALUE), else config.canary send
#           with the new key, else the vault re-read already done.
# finalize: authenticates with the CURRENT vault value (= the new key when the
#           entry authenticates itself) and deletes exactly the recorded ids;
#           an id that is already gone (404) is fine.
#
# Registry knobs (entry "config" object):
#   key_name       REQUIRED  stable key name; new keys are "<key_name> <ts>"
#                            and predecessors match "^<key_name> [0-9]{8}T".
#   permission     optional  full_access (default) | sending_access
#   auth_key_ref   optional  op ref of the key used for the API; default = the
#                            project's tools resend.api_key_ref, else the
#                            rotated ref itself (self-authenticated).
#   canary         optional  {"from": ..., "to": ...} canary send in verify.
# shellcheck source=../lib/provider-common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/provider-common.sh"

_RESEND_API="$(provider_api_base RESEND_API_BASE https://api.resend.com)"
_RESEND_NEW_KEY=""

_resend_curl() { # method path [body on stdin]  (auth in $_RESEND_AUTH_KEY)
  BEARER_KEY="$_RESEND_AUTH_KEY" bearer_curl "$1" "${_RESEND_API}$2"
}

_resend_auth() { # -> _RESEND_AUTH_KEY from the vault (fresh read each call)
  local auth_ref
  auth_ref="$(entry_field '.config.auth_key_ref')"
  if [[ -z "$auth_ref" && -f "${PROJECT_TOOLS_CONFIG:-}" ]]; then
    auth_ref="$(jq -r --arg p "$ROTATE_PROJECT" '.projects[$p].resend.api_key_ref // ""' "$PROJECT_TOOLS_CONFIG")"
  fi
  [[ -n "$auth_ref" ]] || auth_ref="$ROTATE_REF"
  _RESEND_AUTH_KEY="$(op_vault_read "$auth_ref")" || return 4
  [[ -n "$_RESEND_AUTH_KEY" ]] || { echo "ERROR: Resend auth key resolved empty ($auth_ref)." >&2; return 4; }
}

_resend_predecessor_ids() { # key_name -> ids of keys named exactly "<key_name> <ts>"
  local listing re
  listing="$(_resend_curl GET /api-keys)" || return 4
  printf '%s' "$listing" | jq -e '(.data // .) | type == "array"' >/dev/null \
    || { echo "ERROR: Resend key inventory shape is invalid." >&2; return 4; }
  re="^$(regex_escape "$1") [0-9]{8}T"
  printf '%s' "$listing" | jq -r --arg re "$re" '(.data // .)[] | select(.name | type == "string" and test($re)) | .id'
}

_resend_delete_key() { # id -> 0 deleted or already gone
  _resend_curl DELETE "/api-keys/$1" >/dev/null 2>&1 && return 0
  [[ "$BEARER_HTTP_STATUS" == "404" ]]
}

provider_auto_ready() {
  [[ -n "$(entry_field '.config.key_name')" ]]
}

provider_rotate() {
  local key_name permission old_ids created new_id rc=0
  key_name="$(entry_field '.config.key_name')"
  if [[ -z "$key_name" ]]; then
    provider_playbook
    return 3
  fi
  permission="$(entry_field '.config.permission')"
  [[ -n "$permission" ]] || permission="full_access"
  _resend_auth || return 4

  # Predecessor snapshot BEFORE the create; finalize deletes exactly these.
  old_ids="$(_resend_predecessor_ids "$key_name")" || { _RESEND_AUTH_KEY=""; return 4; }

  created="$(jq -n --arg name "$key_name $(date -u +%Y%m%dT%H%M%SZ)" --arg perm "$permission" \
    '{name:$name, permission:$perm}' | _resend_curl POST /api-keys)" || rc=$?
  if [[ "$rc" -ne 0 ]]; then _RESEND_AUTH_KEY=""; return 4; fi
  new_id="$(printf '%s' "$created" | jq -r '.id // ""')"
  _RESEND_NEW_KEY="$(printf '%s' "$created" | jq -er '.token | select(type == "string" and length > 0)')" || {
    echo "ERROR: Resend create response carried no token; nothing was written to the vault." >&2
    created=""; _RESEND_AUTH_KEY=""
    return 4
  }
  created=""
  if ! VAULT_VALUE="$_RESEND_NEW_KEY" vault_write_value "$ROTATE_REF"; then
    # Nobody holds the new key yet: retire it so a rerun starts clean.
    _RESEND_NEW_KEY=""
    [[ -n "$new_id" ]] && _resend_delete_key "$new_id" && echo "  resend: vault write failed; deleted the unused new key $new_id" >&2
    _RESEND_AUTH_KEY=""
    return 4
  fi
  _RESEND_AUTH_KEY=""
  PROVIDER_FINALIZE_JSON="$(jq -nc --arg ids "$old_ids" '{delete_ids: ($ids | split("\n") | map(select(length > 0)))}')"
  echo "  resend: minted new key for '$key_name' and updated the vault; predecessor(s) still valid"
}

provider_verify() {
  local canary_from canary_to new_key rc=0
  new_key="$_RESEND_NEW_KEY"
  [[ -n "$new_key" ]] || new_key="$(op_vault_read "$ROTATE_REF")" || return 1
  if verify_command_configured; then
    run_verify_command "$new_key"
    return $?
  fi
  canary_from="$(entry_field '.config.canary.from')"
  canary_to="$(entry_field '.config.canary.to')"
  if [[ -n "$canary_from" && -n "$canary_to" ]]; then
    jq -n --arg from "$canary_from" --arg to "$canary_to" \
        '{from:$from, to:[$to], subject:"rotate-secret canary", text:"Resend key rotation canary."}' \
      | _RESEND_AUTH_KEY="$new_key" _resend_curl POST /emails >/dev/null || rc=1
    [[ "$rc" -eq 0 ]] && echo "  resend: canary send succeeded with the new key"
    return "$rc"
  fi
  # No behavioural check configured; the vault write was verified by re-read.
  return 0
}

provider_finalize() { # json: {"delete_ids":[...]}
  local rc=0
  _RESEND_NEW_KEY=""
  _resend_auth || return 4   # fresh read: the vault already holds the new key
  finalize_delete_ids "$1" '.delete_ids' _resend_delete_key resend || rc=$?
  _RESEND_AUTH_KEY=""
  return "$rc"
}

provider_playbook() {
  if [[ -z "$(entry_field '.config.key_name')" ]]; then
    playbook_unconfigured "config.key_name (the stable Resend key name)" <<EOF
  1. resend.com -> API keys: create a new key with the same permission.
  2. printf %s '<new-key>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
  3. After every consumer redeployed and verified, delete the old key in the dashboard.
EOF
    return 0
  fi
  cat <<EOF
resend dual rotation for $ROTATE_REF:
  1. Snapshot predecessor key ids named exactly "<config.key_name> <timestamp>".
  2. Create a new API key via the Resend API; vault-replace by immutable id.
  3. rotate-secret fans out sync-secrets, deploys, waits live, health-gates.
  4. Verify (entry verify_command / config.canary send / vault re-read).
  5. finalize: delete the snapshotted predecessors, authenticating with the
     current vault value (the new key).
EOF
}

# A SYNC-only entry (no config.key_name) gets its value from the dashboard.
provider_auto_ready || PROVIDER_ACCEPTS_COMPLETE=1

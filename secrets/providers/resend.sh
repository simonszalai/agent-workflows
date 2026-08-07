# shellcheck shell=bash
# providers/resend.sh — dual create/delete rotation for Resend API keys.
#
# Flow (create -> vault -> sync -> verify -> delete-old; the old key is deleted
# only in provider_finalize, i.e. AFTER verify and the consumer fan-out):
#   1. snapshot the ids of every existing key whose name starts with the
#      entry's config.key_name (these are the predecessors);
#   2. POST /api-keys to mint "<key_name> <UTC timestamp>" (full_access unless
#      config.permission overrides), capture the token from the response body;
#   3. replace the canonical vault item in place (immutable id, verified);
#   4. rotate-secret verifies (entry verify_command, else config.canary send,
#      else the vault re-read already done) and fans out sync-secrets;
#   5. provider_finalize deletes exactly the pre-snapshot predecessor ids.
#
# Registry knobs (entry "config" object):
#   key_name       REQUIRED  stable name prefix of the managed key (predecessor
#                            discovery + new-key naming). Missing => exit 3.
#   permission     optional  full_access (default) | sending_access
#   auth_key_ref   optional  op ref of the key used to call the Resend API;
#                            default = the project's tools resend.api_key_ref,
#                            else the rotated ref itself (self-authenticated).
#   canary         optional  {"from": ..., "to": ...} — provider_verify sends a
#                            canary email with the NEW key.
# Entry "verify_command" (optional): shell command run by provider_verify.
#
# Values never reach argv/logs: auth via curl --config, bodies on stdin, the
# new token lives only in shell memory until the vault write verifies.

_RESEND_API="${RESEND_API_BASE:-https://api.resend.com}"
_RESEND_NEW_KEY=""
_RESEND_OLD_IDS=""

_resend_curl() { # method path [body on stdin]  (auth key in $_RESEND_AUTH_KEY)
  local method="$1" path="$2"
  if [[ "$method" == "GET" || "$method" == "DELETE" ]]; then
    curl --silent --show-error --fail-with-body \
      --request "$method" \
      --url "${_RESEND_API}${path}" \
      --header "Content-Type: application/json" \
      --config <(printf 'header = "Authorization: Bearer %s"\n' "$_RESEND_AUTH_KEY") \
      < /dev/null
  else
    curl --silent --show-error --fail-with-body \
      --request "$method" \
      --url "${_RESEND_API}${path}" \
      --header "Content-Type: application/json" \
      --config <(printf 'header = "Authorization: Bearer %s"\n' "$_RESEND_AUTH_KEY") \
      --data-binary @-
  fi
}

_resend_auth() { # -> sets _RESEND_AUTH_KEY
  local auth_ref
  auth_ref="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.auth_key_ref // ""')"
  if [[ -z "$auth_ref" && -f "${PROJECT_TOOLS_CONFIG:-}" ]]; then
    auth_ref="$(jq -r --arg p "$ROTATE_PROJECT" '.projects[$p].resend.api_key_ref // ""' "$PROJECT_TOOLS_CONFIG")"
  fi
  [[ -n "$auth_ref" ]] || auth_ref="$ROTATE_REF"
  _RESEND_AUTH_KEY="$(op_vault_read "$auth_ref")" || return $?
  [[ -n "$_RESEND_AUTH_KEY" ]] || { echo "ERROR: Resend auth key resolved empty ($auth_ref)." >&2; return 1; }
}

provider_rotate() {
  local key_name permission listing created rc=0
  key_name="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.key_name // ""')"
  if [[ -z "$key_name" ]]; then
    echo "MANUAL: registry entry $ROTATE_ID has no config.key_name — the provider cannot"
    echo "identify the managed Resend key. Add config.key_name (the stable key-name"
    echo "prefix in the Resend dashboard), or rotate in the dashboard and use:"
    echo "  printf %s '<new-key>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete"
    return 3
  fi
  permission="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.permission // "full_access"')"
  _resend_auth || return 4

  # Predecessor snapshot BEFORE the create: exactly these ids are deleted in
  # finalize. The list endpoint exposes id+name only, never tokens.
  listing="$(printf '' | _resend_curl GET /api-keys)" || { _RESEND_AUTH_KEY=""; return 4; }
  jq -e '(.data // .) | type == "array"' < <(printf '%s' "$listing") >/dev/null \
    || { echo "ERROR: Resend key inventory shape is invalid." >&2; _RESEND_AUTH_KEY=""; return 4; }
  _RESEND_OLD_IDS="$(printf '%s' "$listing" | jq -r --arg n "$key_name" \
    '(.data // .)[] | select(.name | startswith($n)) | .id')"

  created="$(jq -n --arg name "$key_name $(date -u +%Y%m%dT%H%M%SZ)" --arg perm "$permission" \
    '{name:$name, permission:$perm}' | _resend_curl POST /api-keys)" || rc=$?
  if [[ "$rc" -ne 0 ]]; then _RESEND_AUTH_KEY=""; return 4; fi
  _RESEND_NEW_KEY="$(printf '%s' "$created" | jq -er '.token | select(type == "string" and length > 0)')" || {
    echo "ERROR: Resend create response carried no token; nothing was written to the vault." >&2
    _RESEND_AUTH_KEY=""
    return 4
  }
  created=""
  VAULT_VALUE="$_RESEND_NEW_KEY" vault_write_value "$ROTATE_REF" || { _RESEND_NEW_KEY=""; _RESEND_AUTH_KEY=""; return 4; }
  echo "  resend: minted new key for '$key_name' and updated the vault; predecessor(s) still valid"
}

provider_verify() {
  local verify_command canary_from canary_to rc=0
  verify_command="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.verify_command // ""')"
  if [[ -n "$verify_command" ]]; then
    bash -c "$verify_command" || return 1
    return 0
  fi
  canary_from="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.canary.from // ""')"
  canary_to="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.canary.to // ""')"
  if [[ -n "$canary_from" && -n "$canary_to" && -n "$_RESEND_NEW_KEY" ]]; then
    jq -n --arg from "$canary_from" --arg to "$canary_to" \
        '{from:$from, to:[$to], subject:"rotate-secret canary", text:"Resend key rotation canary."}' \
      | _RESEND_AUTH_KEY="$_RESEND_NEW_KEY" _resend_curl POST /emails >/dev/null || rc=1
    [[ "$rc" -eq 0 ]] && echo "  resend: canary send succeeded with the new key"
    return "$rc"
  fi
  # No behavioural check configured; the vault write was verified by re-read.
  return 0
}

provider_finalize() { # runs AFTER verify + consumer fan-out succeeded
  local id failed=0
  _RESEND_NEW_KEY=""
  if [[ -z "$_RESEND_OLD_IDS" ]]; then
    echo "  resend: no predecessor keys matched config.key_name — nothing to delete"
    _RESEND_AUTH_KEY=""
    return 0
  fi
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    if printf '' | _resend_curl DELETE "/api-keys/${id}" >/dev/null; then
      echo "  resend: deleted predecessor key $id"
    else
      echo "ERROR: could not delete predecessor Resend key $id — delete it in the dashboard." >&2
      failed=1
    fi
  done <<< "$_RESEND_OLD_IDS"
  _RESEND_AUTH_KEY=""
  return "$failed"
}

provider_playbook() {
  cat <<EOF
resend dual rotation for $ROTATE_REF:
  1. Snapshot predecessor key ids by config.key_name prefix.
  2. Create a new API key via the Resend API; vault-replace by immutable id.
  3. Fan out sync-secrets to every registered consumer (deploy-last).
  4. Verify (entry verify_command / config.canary send / vault re-read).
  5. Delete the snapshotted predecessor keys ONLY after verify + fan-out.
EOF
}

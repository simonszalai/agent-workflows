# shellcheck shell=bash
# providers/openai.sh — dual rotation for OpenAI project API keys via the
# OpenAI Admin API (project service accounts).
#
# The Admin API cannot rotate dashboard user keys; it CAN mint project service
# accounts whose api_key acts as a project API key. Rotation therefore requires
# per-entry admin configuration; without it, nothing is changed (exit 3).
#
# Registry knobs (entry "config" object):
#   admin_key_ref  REQUIRED  op ref of an OpenAI ADMIN key (sk-admin-...).
#                            Missing => exit 3 playbook.
#   project_id     REQUIRED  OpenAI project id (proj_...). Missing => exit 3.
#   sa_prefix      optional  service-account name prefix (default
#                            "rotate-<entry id>") used for predecessor
#                            discovery + new-account naming.
# Entry "verify_command" (optional) overrides the default GET /v1/models check.
#
# Flow: snapshot predecessor service-account ids by name prefix -> create a new
# service account (response carries the key ONCE) -> vault-replace by immutable
# id -> rotate-secret verifies + fans out -> provider_finalize deletes exactly
# the snapshotted predecessors. A dashboard-minted original key cannot be
# deleted via the API; finalize prints a manual step for it instead.

_OPENAI_API="${OPENAI_API_BASE:-https://api.openai.com}"
_OPENAI_NEW_KEY=""
_OPENAI_OLD_SA_IDS=""
_OPENAI_PROJECT_ID=""
_OPENAI_SA_PREFIX=""

_openai_curl() { # method path [body on stdin]  (auth key in $_OPENAI_AUTH_KEY)
  local method="$1" path="$2"
  if [[ "$method" == "GET" || "$method" == "DELETE" ]]; then
    curl --silent --show-error --fail-with-body \
      --request "$method" \
      --url "${_OPENAI_API}${path}" \
      --header "Content-Type: application/json" \
      --config <(printf 'header = "Authorization: Bearer %s"\n' "$_OPENAI_AUTH_KEY") \
      < /dev/null
  else
    curl --silent --show-error --fail-with-body \
      --request "$method" \
      --url "${_OPENAI_API}${path}" \
      --header "Content-Type: application/json" \
      --config <(printf 'header = "Authorization: Bearer %s"\n' "$_OPENAI_AUTH_KEY") \
      --data-binary @-
  fi
}

_openai_playbook_unconfigured() {
  cat <<EOF
MANUAL: registry entry $ROTATE_ID has no config.admin_key_ref/config.project_id,
so the OpenAI Admin API leg is unavailable. Rotate in the dashboard:
  1. platform.openai.com -> the project -> API keys: create a new key.
  2. printf %s '<new-key>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
  3. After every consumer redeployed and verified, delete the old key in the
     dashboard.
To automate this entry, add config.admin_key_ref (an sk-admin key in the vault)
and config.project_id (proj_...) to config/secret-rotation.json.
EOF
}

provider_rotate() {
  local admin_ref listing created rc=0
  admin_ref="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.admin_key_ref // ""')"
  _OPENAI_PROJECT_ID="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.project_id // ""')"
  if [[ -z "$admin_ref" || -z "$_OPENAI_PROJECT_ID" ]]; then
    _openai_playbook_unconfigured
    return 3
  fi
  _OPENAI_SA_PREFIX="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.sa_prefix // ""')"
  [[ -n "$_OPENAI_SA_PREFIX" ]] || _OPENAI_SA_PREFIX="rotate-$ROTATE_ID"
  _OPENAI_AUTH_KEY="$(op_vault_read "$admin_ref")" || return 4
  [[ -n "$_OPENAI_AUTH_KEY" ]] || { echo "ERROR: OpenAI admin key resolved empty ($admin_ref)." >&2; return 4; }

  # Predecessor snapshot BEFORE the create: exactly these service-account ids
  # are deleted in finalize.
  listing="$(_openai_curl GET "/v1/organization/projects/${_OPENAI_PROJECT_ID}/service_accounts?limit=100")" \
    || { _OPENAI_AUTH_KEY=""; return 4; }
  jq -e '.data | type == "array"' < <(printf '%s' "$listing") >/dev/null \
    || { echo "ERROR: OpenAI service-account inventory shape is invalid." >&2; _OPENAI_AUTH_KEY=""; return 4; }
  _OPENAI_OLD_SA_IDS="$(printf '%s' "$listing" | jq -r --arg n "$_OPENAI_SA_PREFIX" \
    '.data[] | select(.name | startswith($n)) | .id')"

  created="$(jq -n --arg name "${_OPENAI_SA_PREFIX}-$(date -u +%Y%m%dT%H%M%SZ)" '{name:$name}' \
    | _openai_curl POST "/v1/organization/projects/${_OPENAI_PROJECT_ID}/service_accounts")" || rc=$?
  if [[ "$rc" -ne 0 ]]; then _OPENAI_AUTH_KEY=""; return 4; fi
  _OPENAI_NEW_KEY="$(printf '%s' "$created" | jq -er '.api_key.value | select(type == "string" and length > 0)')" || {
    echo "ERROR: OpenAI create response carried no api_key.value; nothing was written to the vault." >&2
    _OPENAI_AUTH_KEY=""
    return 4
  }
  created=""
  VAULT_VALUE="$_OPENAI_NEW_KEY" vault_write_value "$ROTATE_REF" || { _OPENAI_NEW_KEY=""; _OPENAI_AUTH_KEY=""; return 4; }
  echo "  openai: minted new project service-account key and updated the vault; predecessor(s) still valid"
}

provider_verify() {
  local verify_command
  verify_command="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.verify_command // ""')"
  if [[ -n "$verify_command" ]]; then
    bash -c "$verify_command" || return 1
    return 0
  fi
  [[ -n "$_OPENAI_NEW_KEY" ]] || return 0
  _OPENAI_AUTH_KEY="$_OPENAI_NEW_KEY" _openai_curl GET /v1/models >/dev/null || {
    echo "ERROR: the new OpenAI key failed its GET /v1/models check." >&2
    return 1
  }
  echo "  openai: new key verified against /v1/models"
}

provider_finalize() { # runs AFTER verify + consumer fan-out succeeded
  local id failed=0
  _OPENAI_NEW_KEY=""
  if [[ -z "$_OPENAI_OLD_SA_IDS" ]]; then
    echo "  openai: no predecessor service accounts matched '$_OPENAI_SA_PREFIX' —"
    echo "  if the previous key was dashboard-minted, delete it manually in the dashboard."
    _OPENAI_AUTH_KEY=""
    return 0
  fi
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    if _openai_curl DELETE "/v1/organization/projects/${_OPENAI_PROJECT_ID}/service_accounts/${id}" >/dev/null; then
      echo "  openai: deleted predecessor service account $id"
    else
      echo "ERROR: could not delete predecessor OpenAI service account $id — remove it manually." >&2
      failed=1
    fi
  done <<< "$_OPENAI_OLD_SA_IDS"
  _OPENAI_AUTH_KEY=""
  return "$failed"
}

provider_playbook() {
  _openai_playbook_unconfigured
}

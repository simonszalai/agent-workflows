# shellcheck shell=bash
# providers/openai.sh — dual rotation for OpenAI project API keys via the
# OpenAI Admin API (project service accounts). The Admin API cannot rotate
# dashboard user keys; it CAN mint project service accounts whose api_key acts
# as a project API key.
#
# rotate:   page through the project's service accounts (has_more/after) ->
#           predecessors = names matching "^<sa_prefix>-[0-9]{8}T" -> create
#           "<sa_prefix>-<UTC ts>" (key returned once) -> vault-replace.
#           PROVIDER_FINALIZE_JSON = {"delete_ids":[...]}.
# verify:   entry verify_command (ROTATE_NEW_VALUE), else GET /v1/models.
# finalize: delete the recorded service accounts with the admin key; already
#           gone (404) is fine. A dashboard-minted original cannot be deleted
#           via the API; the playbook says so.
#
# Registry knobs (entry "config" object):
#   admin_key_ref  REQUIRED  op ref of an OpenAI ADMIN key (sk-admin-...).
#   project_id     REQUIRED  OpenAI project id (proj_...).
#   sa_prefix      optional  service-account name prefix (default "rotate-<id>").
# shellcheck source=../lib/provider-common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/provider-common.sh"

_OPENAI_API="$(provider_api_base OPENAI_API_BASE https://api.openai.com)"
_OPENAI_NEW_KEY=""
_OPENAI_AUTH_KEY=""
_OPENAI_PROJECT_ID=""

_openai_curl() { # method path [body on stdin]  (auth in $_OPENAI_AUTH_KEY)
  BEARER_KEY="$_OPENAI_AUTH_KEY" bearer_curl "$1" "${_OPENAI_API}$2"
}

_openai_sa_prefix() {
  local p
  p="$(entry_field '.config.sa_prefix')"
  printf '%s' "${p:-rotate-$ROTATE_ID}"
}

_openai_setup() { # -> _OPENAI_PROJECT_ID, _OPENAI_AUTH_KEY (rc 3 unconfigured)
  local admin_ref
  admin_ref="$(entry_field '.config.admin_key_ref')"
  _OPENAI_PROJECT_ID="$(entry_field '.config.project_id')"
  [[ -n "$admin_ref" && -n "$_OPENAI_PROJECT_ID" ]] || return 3
  _OPENAI_AUTH_KEY="$(op_vault_read "$admin_ref")" || return 4
  [[ -n "$_OPENAI_AUTH_KEY" ]] || { echo "ERROR: OpenAI admin key resolved empty ($admin_ref)." >&2; return 4; }
}

_openai_predecessor_ids() { # -> ids of service accounts named "<prefix>-<ts>" (all pages)
  local re after="" page ids="" more
  re="^$(regex_escape "$(_openai_sa_prefix)")-[0-9]{8}T"
  while :; do
    page="$(_openai_curl GET "/v1/organization/projects/${_OPENAI_PROJECT_ID}/service_accounts?limit=100${after:+&after=$after}")" || return 4
    printf '%s' "$page" | jq -e '.data | type == "array"' >/dev/null \
      || { echo "ERROR: OpenAI service-account inventory shape is invalid." >&2; return 4; }
    ids+="$(printf '%s' "$page" | jq -r --arg re "$re" '.data[] | select(.name | type == "string" and test($re)) | .id')"$'\n'
    more="$(printf '%s' "$page" | jq -r '.has_more // false')"
    [[ "$more" == "true" ]] || break
    after="$(printf '%s' "$page" | jq -r '.last_id // (.data[-1].id // "")')"
    [[ -n "$after" ]] || break
  done
  printf '%s' "$ids" | sed '/^$/d'
}

_openai_delete_sa() { # id -> 0 deleted or already gone
  _openai_curl DELETE "/v1/organization/projects/${_OPENAI_PROJECT_ID}/service_accounts/$1" >/dev/null 2>&1 && return 0
  [[ "$BEARER_HTTP_STATUS" == "404" ]]
}

provider_auto_ready() {
  [[ -n "$(entry_field '.config.admin_key_ref')" && -n "$(entry_field '.config.project_id')" ]]
}

provider_rotate() {
  local old_ids created new_id rc=0
  _openai_setup || { rc=$?; [[ "$rc" -eq 3 ]] && provider_playbook; return "$rc"; }

  old_ids="$(_openai_predecessor_ids)" || { _OPENAI_AUTH_KEY=""; return 4; }

  created="$(jq -n --arg name "$(_openai_sa_prefix)-$(date -u +%Y%m%dT%H%M%SZ)" '{name:$name}' \
    | _openai_curl POST "/v1/organization/projects/${_OPENAI_PROJECT_ID}/service_accounts")" || rc=$?
  if [[ "$rc" -ne 0 ]]; then _OPENAI_AUTH_KEY=""; return 4; fi
  new_id="$(printf '%s' "$created" | jq -r '.id // ""')"
  _OPENAI_NEW_KEY="$(printf '%s' "$created" | jq -er '.api_key.value | select(type == "string" and length > 0)')" || {
    echo "ERROR: OpenAI create response carried no api_key.value; nothing was written to the vault." >&2
    created=""; _OPENAI_AUTH_KEY=""
    return 4
  }
  created=""
  if ! VAULT_VALUE="$_OPENAI_NEW_KEY" vault_write_value "$ROTATE_REF"; then
    _OPENAI_NEW_KEY=""
    [[ -n "$new_id" ]] && _openai_delete_sa "$new_id" && echo "  openai: vault write failed; deleted the unused service account $new_id" >&2
    _OPENAI_AUTH_KEY=""
    return 4
  fi
  _OPENAI_AUTH_KEY=""
  PROVIDER_FINALIZE_JSON="$(jq -nc --arg ids "$old_ids" '{delete_ids: ($ids | split("\n") | map(select(length > 0)))}')"
  echo "  openai: minted new project service-account key and updated the vault; predecessor(s) still valid"
}

provider_verify() {
  local new_key
  new_key="$_OPENAI_NEW_KEY"
  [[ -n "$new_key" ]] || new_key="$(op_vault_read "$ROTATE_REF")" || return 1
  if verify_command_configured; then
    run_verify_command "$new_key"
    return $?
  fi
  _OPENAI_AUTH_KEY="$new_key" _openai_curl GET /v1/models >/dev/null || {
    echo "ERROR: the new OpenAI key failed its GET /v1/models check." >&2
    return 1
  }
  echo "  openai: new key verified against /v1/models"
}

provider_finalize() { # json: {"delete_ids":[...]}
  local rc=0
  _OPENAI_NEW_KEY=""
  _openai_setup || return $?
  finalize_delete_ids "$1" '.delete_ids' _openai_delete_sa openai || rc=$?
  [[ -n "$(finalize_ids "$1" '.delete_ids' 2>/dev/null)" ]] \
    || echo "  openai: if the previous key was dashboard-minted, delete it manually in the dashboard."
  _OPENAI_AUTH_KEY=""
  return "$rc"
}

provider_playbook() {
  if ! provider_auto_ready; then
    playbook_unconfigured "config.admin_key_ref (an sk-admin key in the vault) + config.project_id (proj_...)" <<EOF
  1. platform.openai.com -> the project -> API keys: create a new key.
  2. printf %s '<new-key>' | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
  3. After every consumer redeployed and verified, delete the old key in the dashboard.
EOF
    return 0
  fi
  cat <<EOF
openai dual rotation for $ROTATE_REF (project service accounts):
  1. Snapshot predecessor service accounts named "<sa_prefix>-<timestamp>" (all pages).
  2. Create a new service account; its one-time api_key replaces the vault item.
  3. rotate-secret fans out sync-secrets, deploys, waits live, health-gates.
  4. Verify (entry verify_command / GET /v1/models with the new key).
  5. finalize: delete the snapshotted service accounts. A dashboard-minted
     original key must be deleted by hand in the dashboard.
EOF
}

# A SYNC-only entry (no admin config) gets its value from the dashboard.
provider_auto_ready || PROVIDER_ACCEPTS_COMPLETE=1

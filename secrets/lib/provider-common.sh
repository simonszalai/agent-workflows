# shellcheck shell=bash
# provider-common.sh — helpers shared by secrets/providers/*.sh. Each provider
# sources this file itself (guarded), so rotate-secret only sources the
# provider. Depends on read.sh + vault.sh (op_vault_read, need).
#
# Provider contract (sourced by bin/rotate-secret; ROTATE_* env is set):
#   provider_auto_ready          rc 0 iff config.* is sufficient to mint (read-free)
#   provider_plan                optional, read-free dry-run detail
#   provider_rotate              mint + vault write; predecessor stays valid.
#                                rc 0 ok (may set PROVIDER_FINALIZE_JSON, value-free)
#                                rc 3 playbook/refused, nothing changed
#                                rc 4 provider error, vault consistent
#                                rc 7 leftovers found — call provider_reconcile
#   provider_reconcile           rc 0 = rotation completed without a mint
#                                (PROVIDER_FINALIZE_JSON set); rc 3 = playbook
#   provider_verify              rc 0 ok; uses entry verify_command when set
#   provider_finalize <json>     retire predecessors named in json; idempotent
#                                (already gone = ok); rc≠0 = cleanup pending
#   provider_playbook            human description
#   PROVIDER_ACCEPTS_COMPLETE=1  only providers whose value is minted elsewhere
#                                (manual) — enables rotate-secret --complete
#
# Values never reach argv/logs: bearer auth via curl --config, bodies on stdin.
[[ -n "${_PROVIDER_COMMON_LOADED:-}" ]] && return 0
_PROVIDER_COMMON_LOADED=1

PROVIDER_FINALIZE_JSON=""
PROVIDER_ACCEPTS_COMPLETE=0
BEARER_HTTP_STATUS=""

# entry_field JQ_PATH — string field of the rotation entry, "" when absent.
entry_field() {
  printf '%s' "$ROTATE_ENTRY_JSON" | jq -r "$1 // \"\""
}

# provider_api_base ENVVAR DEFAULT — API base URL. The override env var is
# honoured ONLY under SECRETS_TEST_MODE=1 so a stray variable can never point a
# live rotation at another host.
provider_api_base() {
  if [[ "${SECRETS_TEST_MODE:-0}" == "1" && -n "${!1:-}" ]]; then
    printf '%s' "${!1}"
  else
    printf '%s' "$2"
  fi
}

# bearer_curl METHOD URL — JSON request with `Authorization: Bearer $BEARER_KEY`
# (key via curl --config on a pipe, never argv). POST/PUT/PATCH bodies come on
# stdin. Body on stdout; BEARER_HTTP_STATUS holds the HTTP status; rc 22 on a
# non-2xx status (first 200 bytes of the body's first line on stderr), curl's
# rc on transport failure.
bearer_curl() {
  local method="$1" url="$2" out rc=0
  local args=(--silent --show-error --request "$method" --url "$url"
              --header "Content-Type: application/json"
              --write-out $'\n%{http_code}')
  BEARER_HTTP_STATUS=""
  case "$method" in
    GET|DELETE)
      out="$(curl "${args[@]}" \
        --config <(printf 'header = "Authorization: Bearer %s"\n' "$BEARER_KEY") < /dev/null)" || rc=$? ;;
    *)
      out="$(curl "${args[@]}" \
        --config <(printf 'header = "Authorization: Bearer %s"\n' "$BEARER_KEY") --data-binary @-)" || rc=$? ;;
  esac
  [[ "$rc" -eq 0 ]] || return "$rc"
  BEARER_HTTP_STATUS="${out##*$'\n'}"
  out="${out%$'\n'*}"
  printf '%s' "$out"
  [[ "$BEARER_HTTP_STATUS" =~ ^2[0-9][0-9]$ ]] || {
    echo "ERROR: $method $url returned HTTP ${BEARER_HTTP_STATUS:-?}: $(printf '%s' "$out" | head -n 1 | head -c 200)" >&2
    return 22
  }
}

# verify_command_configured — rc 0 when the entry declares verify_command.
verify_command_configured() {
  [[ -n "$(entry_field '.verify_command')" ]]
}

# run_verify_command NEW_VALUE — run the entry's verify_command in a child
# shell. The new credential is exported ONLY to that child as ROTATE_NEW_VALUE
# (aws_iam additionally passes ROTATE_NEW_SECRET_VALUE); it never touches argv.
run_verify_command() {
  local cmd
  cmd="$(entry_field '.verify_command')"
  [[ -n "$cmd" ]] || { echo "ERROR: run_verify_command called without verify_command" >&2; return 2; }
  ROTATE_NEW_VALUE="$1" bash -c "$cmd" || {
    echo "ERROR: verify_command failed for $ROTATE_ID" >&2
    return 1
  }
}

# finalize_ids JSON JQ_PATH — newline list of ids under JQ_PATH (array), or
# empty. Refuses an empty/invalid json (rc 2): finalize without its state
# would silently leave predecessors alive.
finalize_ids() {
  local json="$1" path="$2"
  [[ -n "$json" ]] || { echo "ERROR: provider_finalize needs the persisted finalize json" >&2; return 2; }
  printf '%s' "$json" | jq -er 'type == "object"' >/dev/null 2>&1 \
    || { echo "ERROR: finalize json is not an object" >&2; return 2; }
  printf '%s' "$json" | jq -r "($path // []) | .[] | select(type == \"string\" and length > 0)"
}

# finalize_delete_ids JSON JQ_PATH DELETE_FN LABEL — call DELETE_FN <id> for
# every id; DELETE_FN returns 0 (deleted or already gone) or ≠0 (still there).
# rc 0 when every id is gone, 1 when any remains (cleanup pending).
finalize_delete_ids() {
  local json="$1" path="$2" fn="$3" label="$4" ids id failed=0
  ids="$(finalize_ids "$json" "$path")" || return $?
  [[ -n "$ids" ]] || { echo "  $label: no predecessors recorded — nothing to delete"; return 0; }
  while IFS= read -r id; do
    [[ -n "$id" ]] || continue
    if "$fn" "$id"; then
      echo "  $label: predecessor $id retired"
    else
      echo "ERROR: $label: predecessor $id could not be deleted — remove it manually." >&2
      failed=1
    fi
  done <<< "$ids"
  return "$failed"
}

# regex_escape STRING — literal string as an ERE/jq regex fragment.
regex_escape() {
  printf '%s' "$1" | sed 's/[][\.*^$+?(){}|\\/]/\\&/g'
}

# playbook_unconfigured WHAT — header for an entry whose config.* cannot drive
# the API leg; the provider's manual steps follow on stdin.
playbook_unconfigured() {
  echo "MANUAL: registry entry $ROTATE_ID lacks $1, so the $ROTATE_PROVIDER API leg is unavailable."
  echo "Rotate manually:"
  cat
  cat <<EOF
To automate this entry, add the config.* fields above to the project secrets.yaml
rotation entry; rotate-secret --dry-run shows whether the entry is auto-ready.
EOF
}

# Defaults; providers override what they implement.
provider_finalize() { return 0; }
provider_reconcile() {
  echo "ERROR: provider '$ROTATE_PROVIDER' has no reconcile path." >&2
  return 3
}

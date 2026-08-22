# shellcheck shell=bash
# providers/aws_iam.sh — dual rotation for AWS IAM user access keys.
#
# The credential is a PAIR (access key id + secret access key) that consumers
# read as two env vars. The pair is written to the vault as one unit BEFORE any
# consumer sync (vault_replace_fields under the vault lock); the deploy-last
# fan-out delivers both to every consumer atomically.
#
# rotate:   vault id -> list the user's keys. No other key: create-access-key,
#           pair vault write, PROVIDER_FINALIZE_JSON={"old_key_id":<vault id>}.
#           Exactly one other key (unfinished rotation / orphan of a crash
#           between create and vault write): rc 7 -> provider_reconcile.
# reconcile: the vault pair authenticates via STS and the user has exactly
#           one other key -> that key is the predecessor (finalize json set,
#           rc 0, nothing minted); otherwise rc 3 with the console playbook.
# verify:   entry verify_command (ROTATE_NEW_VALUE = id, ROTATE_NEW_SECRET_VALUE
#           = secret, child env only), else sts get-caller-identity with the
#           pair (polls: IAM keys are eventually consistent).
# finalize: update-access-key Inactive then delete-access-key for old_key_id;
#           already gone = ok; any failure -> rc 1 (cleanup pending, retryable).
#
# Registry knobs (entry "config" object):
#   iam_user            REQUIRED  IAM user whose access keys rotate.
#   secret_ref          REQUIRED  op ref of the SECRET ACCESS KEY field; same
#                                 vault item as the entry ref (the ACCESS KEY ID
#                                 field) so the pair is ONE locked edit.
#   profile             REQUIRED* aws CLI --profile for the admin identity, OR
#   admin_key_id_ref /            op refs of an admin access key pair used via
#   admin_secret_ref              env instead of a profile (*one of the two).
# shellcheck source=../lib/provider-common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/../lib/provider-common.sh"

_AWS_NEW_ID=""
_AWS_NEW_SECRET=""
_AWS_IAM_USER=""
_AWS_SECRET_REF=""
_AWS_PROFILE=""
_AWS_ADMIN_ID=""
_AWS_ADMIN_SECRET=""

_aws_admin() { # aws CLI as the configured admin identity; args pass through
  if [[ -n "$_AWS_PROFILE" ]]; then
    aws --profile "$_AWS_PROFILE" --output json "$@"
  else
    AWS_ACCESS_KEY_ID="$_AWS_ADMIN_ID" AWS_SECRET_ACCESS_KEY="$_AWS_ADMIN_SECRET" \
      AWS_SESSION_TOKEN="" aws --output json "$@"
  fi
}

_aws_pair_ok() { # id secret -> rc 0 iff the pair authenticates
  AWS_ACCESS_KEY_ID="$1" AWS_SECRET_ACCESS_KEY="$2" AWS_SESSION_TOKEN="" \
    aws sts get-caller-identity --output json >/dev/null 2>&1
}

_aws_clear_admin() { _AWS_ADMIN_ID="" _AWS_ADMIN_SECRET=""; }

_aws_setup() { # config -> globals + admin credentials (rc 3 unconfigured, 4 read error)
  local admin_id_ref admin_secret_ref
  _AWS_IAM_USER="$(entry_field '.config.iam_user')"
  _AWS_SECRET_REF="$(entry_field '.config.secret_ref')"
  _AWS_PROFILE="$(entry_field '.config.profile')"
  admin_id_ref="$(entry_field '.config.admin_key_id_ref')"
  admin_secret_ref="$(entry_field '.config.admin_secret_ref')"
  provider_auto_ready || return 3
  need aws
  if [[ -z "$_AWS_PROFILE" ]]; then
    _AWS_ADMIN_ID="$(op_vault_read "$admin_id_ref")" || return 4
    _AWS_ADMIN_SECRET="$(op_vault_read "$admin_secret_ref")" || return 4
    [[ -n "$_AWS_ADMIN_ID" && -n "$_AWS_ADMIN_SECRET" ]] || { echo "ERROR: AWS admin credentials resolved empty." >&2; return 4; }
  fi
}

_aws_vault_id() { # -> the canonical access key id from the vault (validated shape)
  local id
  id="$(op_vault_read "$ROTATE_REF")" || return 4
  [[ "$id" =~ ^A[A-Z0-9]{15,}$ ]] || {
    echo "ERROR: the canonical item does not look like an AWS access key id; refusing." >&2
    return 4
  }
  printf '%s' "$id"
}

_aws_list_keys() { # -> AccessKeyMetadata JSON array
  local listing
  listing="$(_aws_admin iam list-access-keys --user-name "$_AWS_IAM_USER")" || return 4
  printf '%s' "$listing" | jq -ec '.AccessKeyMetadata | select(type == "array")' \
    || { echo "ERROR: AWS list-access-keys response shape is invalid." >&2; return 4; }
}

_aws_other_ids() { # keys_json vault_id -> ids on the user other than vault_id
  printf '%s' "$1" | jq -r --arg id "$2" '.[] | select(.AccessKeyId != $id) | .AccessKeyId'
}

_aws_delete_key() { # id -> 0 deleted (or already gone); nonzero otherwise
  local keys
  keys="$(_aws_list_keys)" || return 1
  printf '%s' "$keys" | jq -e --arg id "$1" 'any(.[]; .AccessKeyId == $id)' >/dev/null || {
    echo "  aws: key $1 is already gone"
    return 0
  }
  _aws_admin iam update-access-key --user-name "$_AWS_IAM_USER" --access-key-id "$1" --status Inactive >/dev/null || {
    echo "ERROR: could not deactivate key $1 — deactivate+delete it in the console." >&2
    return 1
  }
  echo "  aws: deactivated key $1"
  _aws_admin iam delete-access-key --user-name "$_AWS_IAM_USER" --access-key-id "$1" >/dev/null || {
    echo "ERROR: key $1 is Inactive but could not be deleted — delete it in the console." >&2
    return 1
  }
  echo "  aws: deleted key $1"
}

provider_auto_ready() {
  local iam_user secret_ref profile admin_id admin_secret
  iam_user="$(entry_field '.config.iam_user')"
  secret_ref="$(entry_field '.config.secret_ref')"
  profile="$(entry_field '.config.profile')"
  admin_id="$(entry_field '.config.admin_key_id_ref')"
  admin_secret="$(entry_field '.config.admin_secret_ref')"
  [[ -n "$iam_user" && -n "$secret_ref" ]] || return 1
  [[ -n "$profile" || ( -n "$admin_id" && -n "$admin_secret" ) ]]
}

provider_rotate() {
  local old_id keys other created rc=0
  _aws_setup || { rc=$?; [[ "$rc" -eq 3 ]] && provider_playbook; return "$rc"; }
  old_id="$(_aws_vault_id)" || { _aws_clear_admin; return 4; }
  keys="$(_aws_list_keys)" || { _aws_clear_admin; return 4; }
  other="$(_aws_other_ids "$keys" "$old_id")"
  if [[ -n "$other" ]]; then
    _aws_clear_admin
    if [[ "$(printf '%s\n' "$other" | grep -c .)" -eq 1 ]]; then
      echo "  aws: IAM user $_AWS_IAM_USER has another key ($other) besides the vault's $old_id — reconcile"
      return 7
    fi
    echo "REFUSED: the vault key id $old_id is not among the IAM user's keys:" >&2
    printf '%s\n' "$other" >&2
    echo "Fix the vault (rotate-secret --complete with the live pair) or delete a key in the console; nothing was changed." >&2
    return 3
  fi

  created="$(_aws_admin iam create-access-key --user-name "$_AWS_IAM_USER")" || { _aws_clear_admin; return 4; }
  _AWS_NEW_ID="$(printf '%s' "$created" | jq -er '.AccessKey.AccessKeyId | select(type == "string" and length > 0)')" || rc=1
  _AWS_NEW_SECRET="$(printf '%s' "$created" | jq -er '.AccessKey.SecretAccessKey | select(type == "string" and length > 0)')" || rc=1
  created=""
  if [[ "$rc" -ne 0 ]]; then
    echo "ERROR: AWS create-access-key response carried no usable pair; nothing was written to the vault." >&2
    _AWS_NEW_ID="" _AWS_NEW_SECRET=""
    _aws_clear_admin
    return 4
  fi

  # PAIR write: one locked edit of both fields (values via env var names, never
  # argv), before any consumer sync.
  if ! vault_replace_fields "$ROTATE_REF=_AWS_NEW_ID" "$_AWS_SECRET_REF=_AWS_NEW_SECRET"; then
    # Nobody holds the new pair yet: retire it so a rerun starts clean (a
    # failure here is handled by the reconcile path on the next run).
    echo "ERROR: vault pair write failed; retiring the unused new key $_AWS_NEW_ID." >&2
    _aws_delete_key "$_AWS_NEW_ID" || true
    _AWS_NEW_ID="" _AWS_NEW_SECRET=""
    _aws_clear_admin
    return 4
  fi
  _aws_clear_admin
  PROVIDER_FINALIZE_JSON="$(jq -nc --arg id "$old_id" '{old_key_id: $id}')"
  echo "  aws: minted new access key pair for $_AWS_IAM_USER and updated the vault; old key $old_id still active"
}

provider_reconcile() {
  local vault_id vault_secret keys other vault_date other_date rc=0
  _aws_setup || { rc=$?; [[ "$rc" -eq 3 ]] && provider_playbook; return "$rc"; }
  vault_id="$(_aws_vault_id)" || { _aws_clear_admin; return 4; }
  vault_secret="$(op_vault_read "$_AWS_SECRET_REF")" || { _aws_clear_admin; return 4; }
  keys="$(_aws_list_keys)" || { _aws_clear_admin; return 4; }
  _aws_clear_admin
  other="$(_aws_other_ids "$keys" "$vault_id")"
  if [[ -z "$other" || "$(printf '%s\n' "$other" | grep -c .)" -ne 1 ]] \
     || ! printf '%s' "$keys" | jq -e --arg id "$vault_id" 'any(.[]; .AccessKeyId == $id)' >/dev/null; then
    vault_secret=""
    echo "REFUSED: cannot reconcile IAM user $_AWS_IAM_USER: expected exactly the vault key $vault_id plus one other key." >&2
    printf '%s' "$keys" | jq -r '.[] | "  key \(.AccessKeyId) status=\(.Status) created=\(.CreateDate)"' >&2
    echo "Delete the stray key in the console (or fix the vault pair with --complete), then rerun." >&2
    return 3
  fi
  if ! _aws_pair_ok "$vault_id" "$vault_secret"; then
    vault_secret=""
    echo "REFUSED: the vault pair ($vault_id) does not authenticate via STS; the other key is $other." >&2
    echo "If $other is the live pair, write it to the vault (rotate-secret --complete for id+secret) and delete $vault_id in the console; otherwise delete $other. Nothing was changed." >&2
    return 3
  fi
  vault_secret=""
  vault_date="$(printf '%s' "$keys" | jq -r --arg id "$vault_id" '.[] | select(.AccessKeyId == $id) | .CreateDate // ""')"
  other_date="$(printf '%s' "$keys" | jq -r --arg id "$other" '.[] | select(.AccessKeyId == $id) | .CreateDate // ""')"
  if [[ -n "$vault_date" && -n "$other_date" && "$other_date" > "$vault_date" ]]; then
    echo "  aws: reconcile — $other is an orphan created after the vault key $vault_id (crash before the vault write);"
    echo "       the vault pair stays, $other is retired at finalize. Rerun rotate-secret afterwards for a fresh key."
  else
    echo "  aws: reconcile — $other predates the vault key $vault_id: completing the unfinished rotation (no new key minted)."
  fi
  PROVIDER_FINALIZE_JSON="$(jq -nc --arg id "$other" '{old_key_id: $id}')"
}

provider_verify() {
  local new_id new_secret deadline
  new_id="$_AWS_NEW_ID"; new_secret="$_AWS_NEW_SECRET"
  if [[ -z "$new_id" || -z "$new_secret" ]]; then
    new_id="$(_aws_vault_id)" || return 1
    new_secret="$(op_vault_read "$(entry_field '.config.secret_ref')")" || return 1
  fi
  if verify_command_configured; then
    ROTATE_NEW_SECRET_VALUE="$new_secret" run_verify_command "$new_id"
    return $?
  fi
  need aws
  # New IAM keys propagate eventually-consistently; poll briefly.
  deadline=$(( $(date +%s) + ${AWS_KEY_VERIFY_TIMEOUT_SECONDS:-60} ))
  while :; do
    if _aws_pair_ok "$new_id" "$new_secret"; then
      echo "  aws: key pair $new_id verified via sts get-caller-identity"
      return 0
    fi
    [[ $(date +%s) -lt $deadline ]] || break
    sleep "${AWS_KEY_VERIFY_POLL_SECONDS:-5}"
  done
  echo "ERROR: the AWS key pair $new_id failed sts get-caller-identity; the predecessor remains active." >&2
  return 1
}

provider_finalize() { # json: {"old_key_id": "AKIA..."}
  local old_id rc=0
  _AWS_NEW_ID="" _AWS_NEW_SECRET=""
  old_id="$(finalize_ids "$1" '[.old_key_id]')" || return $?
  [[ -n "$old_id" ]] || { echo "  aws: no predecessor recorded — nothing to delete"; return 0; }
  _aws_setup || return $?
  _aws_delete_key "$old_id" || rc=1
  _aws_clear_admin
  return "$rc"
}

provider_playbook() {
  if ! provider_auto_ready; then
    playbook_unconfigured "config.iam_user + config.secret_ref + (config.profile or config.admin_key_id_ref/config.admin_secret_ref)" <<EOF
  1. IAM console -> the user -> security credentials: create a new access key.
  2. Write BOTH vault fields (id + secret) and sync each:
       printf %s '<new-secret>' | rotate-secret --ref '$(entry_field '.config.secret_ref')' --reason '<why>' --complete
       printf %s '<new-id>'     | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
  3. After every consumer redeployed and verified, deactivate then delete the
     old key in the console.
EOF
    return 0
  fi
  cat <<EOF
aws_iam dual rotation for $ROTATE_REF (id+secret PAIR):
  1. List the IAM user's keys: none besides the vault's -> mint; exactly one
     other -> reconcile (vault pair must pass STS; the other key becomes the
     predecessor); otherwise refuse.
  2. create-access-key; write BOTH vault fields as a pair (one locked write).
  3. rotate-secret fans out sync-secrets (both refs), deploys, waits live,
     health-gates.
  4. Verify the pair (verify_command or sts get-caller-identity).
  5. finalize: deactivate then delete the predecessor key; a failure leaves it
     valid and is retried with rotate-secret --finalize.
EOF
}

# A SYNC-only entry (no admin config) gets its pair from the console.
provider_auto_ready || PROVIDER_ACCEPTS_COMPLETE=1

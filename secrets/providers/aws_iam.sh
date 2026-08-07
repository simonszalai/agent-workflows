# shellcheck shell=bash
# providers/aws_iam.sh — dual rotation for AWS IAM user access keys.
#
# The credential is a PAIR (access key id + secret access key) that consumers
# read as two env vars. The pair is written to the vault as one unit BEFORE any
# consumer sync: same-item refs are updated with a single `op item edit` (both
# fields in one write); separate items are both written back-to-back, and the
# deploy-last fan-out delivers them to every consumer atomically. The old key
# is deactivated then deleted only in provider_finalize (after verify+fan-out).
#
# Registry knobs (entry "config" object):
#   iam_user            REQUIRED  IAM user whose access keys rotate.
#   secret_ref          REQUIRED  op ref of the SECRET ACCESS KEY item (the
#                                 entry's own ref is the ACCESS KEY ID item).
#   profile             optional  aws CLI --profile for the admin identity.
#   admin_key_id_ref /  optional  op refs of an admin access key pair used via
#   admin_secret_ref              env instead of a profile.
#   One of profile / admin refs is required; nothing configured => exit 3.
# Entry "verify_command" (optional) overrides the default sts get-caller-identity
# probe with the NEW pair.
#
# Flow: read old key id from the vault -> refuse if the IAM user has any OTHER
# key (no room / ambiguous) -> create-access-key -> pair vault write -> verify ->
# fan-out -> finalize: Inactive then delete the OLD id only.

_AWS_NEW_ID=""
_AWS_NEW_SECRET=""
_AWS_OLD_ID=""
_AWS_IAM_USER=""
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

_aws_playbook_unconfigured() {
  cat <<EOF
MANUAL: registry entry $ROTATE_ID lacks config.iam_user + config.secret_ref +
(config.profile or config.admin_key_id_ref/config.admin_secret_ref), so the
aws CLI leg is unavailable. Rotate manually:
  1. IAM console -> the user -> security credentials: create a new access key.
  2. Update BOTH vault items (id + secret), then sync each:
       printf %s '<new-secret>' | rotate-secret --ref '<secret item ref>' --reason '<why>' --complete
       printf %s '<new-id>'     | rotate-secret --ref '$ROTATE_REF' --reason '<why>' --complete
  3. After every consumer redeployed and verified, deactivate then delete the
     old key in the console.
EOF
}

# One-write pair update when both refs live on the SAME vault item (two fields).
_aws_vault_replace_pair_same_item() { # id_ref secret_ref (values in _AWS_NEW_ID/_AWS_NEW_SECRET)
  local id_ref="$1" secret_ref="$2" item_id check=""
  local REF_VAULT REF_TITLE REF_FIELD id_field secret_field vault
  ref_parts "$id_ref" || return 2
  vault="$REF_VAULT"; id_field="$REF_FIELD"
  ref_parts "$secret_ref" || return 2
  secret_field="$REF_FIELD"
  item_id="$(vault_item_id "$id_ref")" || {
    echo "ERROR: refusing to pair-update an absent or unproven vault item ($id_ref)." >&2
    return 2
  }
  op_vault_mutation "$vault" item get "$item_id" --vault "$vault" --format json \
    | ID_FIELD="$id_field" SECRET_FIELD="$secret_field" \
      PAIR_ID="$_AWS_NEW_ID" PAIR_SECRET="$_AWS_NEW_SECRET" jq -e '
        if ([.fields[]? | select(.label == env.ID_FIELD)] | length) == 1
           and ([.fields[]? | select(.label == env.SECRET_FIELD)] | length) == 1
        then .fields |= map(
          if .label == env.ID_FIELD then .value = env.PAIR_ID
          elif .label == env.SECRET_FIELD then .value = env.PAIR_SECRET
          else . end)
        else error("item must contain exactly one id field and one secret field") end' \
    | op_vault_mutation "$vault" item edit "$item_id" --vault "$vault" >/dev/null
  check="$(op_vault_read "$id_ref")" || return $?
  [[ "$check" == "$_AWS_NEW_ID" ]] || { echo "ERROR: pair id write did not verify." >&2; return 1; }
  check="$(op_vault_read "$secret_ref")" || return $?
  [[ "$check" == "$_AWS_NEW_SECRET" ]] || { echo "ERROR: pair secret write did not verify." >&2; return 1; }
  check=""
  echo "  vault: updated id+secret pair in one item write ($id_ref)"
}

provider_rotate() {
  local secret_ref admin_id_ref admin_secret_ref listing other created rc=0
  local REF_VAULT REF_TITLE REF_FIELD id_vault id_title
  _AWS_IAM_USER="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.iam_user // ""')"
  secret_ref="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.secret_ref // ""')"
  _AWS_PROFILE="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.profile // ""')"
  admin_id_ref="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.admin_key_id_ref // ""')"
  admin_secret_ref="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.config.admin_secret_ref // ""')"
  if [[ -z "$_AWS_IAM_USER" || -z "$secret_ref" ]] \
     || [[ -z "$_AWS_PROFILE" && ( -z "$admin_id_ref" || -z "$admin_secret_ref" ) ]]; then
    _aws_playbook_unconfigured
    return 3
  fi
  need aws
  if [[ -z "$_AWS_PROFILE" ]]; then
    _AWS_ADMIN_ID="$(op_vault_read "$admin_id_ref")" || return 4
    _AWS_ADMIN_SECRET="$(op_vault_read "$admin_secret_ref")" || return 4
    [[ -n "$_AWS_ADMIN_ID" && -n "$_AWS_ADMIN_SECRET" ]] || { echo "ERROR: AWS admin credentials resolved empty." >&2; return 4; }
  fi

  _AWS_OLD_ID="$(op_vault_read "$ROTATE_REF")" || return 4
  [[ "$_AWS_OLD_ID" =~ ^A[A-Z0-9]{15,}$ ]] || {
    echo "ERROR: the canonical item does not look like an AWS access key id; refusing." >&2
    return 4
  }

  # No room / ambiguity guard: IAM allows two keys per user. Any key on the
  # user that is NOT the canonical one means a previous rotation did not clean
  # up (or an unknown key exists) — refuse before creating anything.
  listing="$(_aws_admin iam list-access-keys --user-name "$_AWS_IAM_USER")" || return 4
  jq -e '.AccessKeyMetadata | type == "array"' < <(printf '%s' "$listing") >/dev/null \
    || { echo "ERROR: AWS list-access-keys response shape is invalid." >&2; return 4; }
  other="$(printf '%s' "$listing" | jq -r --arg id "$_AWS_OLD_ID" \
    '.AccessKeyMetadata[] | select(.AccessKeyId != $id) | .AccessKeyId')"
  if [[ -n "$other" ]]; then
    echo "REFUSED: IAM user $_AWS_IAM_USER already has a non-canonical access key:" >&2
    printf '%s\n' "$other" >&2
    echo "Delete/reconcile it first (IAM allows only two keys per user); nothing was changed." >&2
    return 3
  fi

  created="$(_aws_admin iam create-access-key --user-name "$_AWS_IAM_USER")" || return 4
  _AWS_NEW_ID="$(printf '%s' "$created" | jq -er '.AccessKey.AccessKeyId | select(type == "string" and length > 0)')" || rc=1
  _AWS_NEW_SECRET="$(printf '%s' "$created" | jq -er '.AccessKey.SecretAccessKey | select(type == "string" and length > 0)')" || rc=1
  created=""
  if [[ "$rc" -ne 0 ]]; then
    echo "ERROR: AWS create-access-key response carried no usable pair; nothing was written to the vault." >&2
    _AWS_NEW_ID="" _AWS_NEW_SECRET=""
    return 4
  fi

  # PAIR write: one item write when both fields share an item; otherwise both
  # items are written before returning (the deploy-last fan-out then delivers
  # the pair to each consumer in a single deploy).
  ref_parts "$ROTATE_REF" || return 4
  id_vault="$REF_VAULT"; id_title="$REF_TITLE"
  ref_parts "$secret_ref" || return 4
  if [[ "$REF_VAULT" == "$id_vault" && "$REF_TITLE" == "$id_title" ]]; then
    _aws_vault_replace_pair_same_item "$ROTATE_REF" "$secret_ref" || { _AWS_NEW_ID="" _AWS_NEW_SECRET=""; return 4; }
  else
    VAULT_VALUE="$_AWS_NEW_SECRET" vault_write_value "$secret_ref" || { _AWS_NEW_ID="" _AWS_NEW_SECRET=""; return 4; }
    VAULT_VALUE="$_AWS_NEW_ID" vault_write_value "$ROTATE_REF" || { _AWS_NEW_ID="" _AWS_NEW_SECRET=""; return 4; }
  fi
  echo "  aws: minted new access key pair for $_AWS_IAM_USER and updated the vault; old key still active"
}

provider_verify() {
  local verify_command deadline
  verify_command="$(printf '%s' "$ROTATE_ENTRY_JSON" | jq -r '.verify_command // ""')"
  if [[ -n "$verify_command" ]]; then
    bash -c "$verify_command" || return 1
    return 0
  fi
  [[ -n "$_AWS_NEW_ID" && -n "$_AWS_NEW_SECRET" ]] || return 0
  # New IAM keys propagate eventually-consistently; poll briefly.
  deadline=$(( $(date +%s) + ${AWS_KEY_VERIFY_TIMEOUT_SECONDS:-60} ))
  while :; do
    if AWS_ACCESS_KEY_ID="$_AWS_NEW_ID" AWS_SECRET_ACCESS_KEY="$_AWS_NEW_SECRET" AWS_SESSION_TOKEN="" \
       aws sts get-caller-identity --output json >/dev/null 2>&1; then
      echo "  aws: new key pair verified via sts get-caller-identity"
      return 0
    fi
    [[ $(date +%s) -lt $deadline ]] || break
    sleep "${AWS_KEY_VERIFY_POLL_SECONDS:-5}"
  done
  echo "ERROR: the new AWS key pair failed sts get-caller-identity; old key remains active." >&2
  return 1
}

provider_finalize() { # runs AFTER verify + consumer fan-out succeeded
  local failed=0
  _AWS_NEW_ID="" _AWS_NEW_SECRET=""
  if [[ -z "$_AWS_OLD_ID" ]]; then
    _AWS_ADMIN_ID="" _AWS_ADMIN_SECRET=""
    return 0
  fi
  if _aws_admin iam update-access-key --user-name "$_AWS_IAM_USER" \
       --access-key-id "$_AWS_OLD_ID" --status Inactive >/dev/null; then
    echo "  aws: deactivated old access key $_AWS_OLD_ID"
    if _aws_admin iam delete-access-key --user-name "$_AWS_IAM_USER" \
         --access-key-id "$_AWS_OLD_ID" >/dev/null; then
      echo "  aws: deleted old access key $_AWS_OLD_ID"
    else
      echo "ERROR: old key $_AWS_OLD_ID is Inactive but could not be deleted — delete it in the console." >&2
      failed=1
    fi
  else
    echo "ERROR: could not deactivate old key $_AWS_OLD_ID — deactivate+delete it in the console." >&2
    failed=1
  fi
  _AWS_ADMIN_ID="" _AWS_ADMIN_SECRET=""
  return "$failed"
}

provider_playbook() {
  cat <<EOF
aws_iam dual rotation for $ROTATE_REF (id+secret PAIR):
  1. Refuse if the IAM user has any non-canonical key (two-key limit).
  2. create-access-key; write BOTH vault items as a pair before any sync.
  3. Fan out sync-secrets (both refs); deploy-last pushes both envs together.
  4. Verify the new pair (verify_command or sts get-caller-identity).
  5. Deactivate then delete the OLD key only after verify + fan-out.
EOF
}

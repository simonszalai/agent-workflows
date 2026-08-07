# shellcheck shell=bash
# vault.sh — 1Password vault WRITE helpers for rotation (port of amaru's
# rotate-credentials vault semantics). Depends on read.sh (op_vault_mutation,
# op_desktop, OP_BIN, guard_agent_shell).
#
# All mutations address items by IMMUTABLE ID, never by title, and verify by
# re-read. Values travel via env into `jq -n` / item JSON on stdin — never argv.
# The canonical bin/op shim owns sensitive-account selection, reason
# enforcement, and notification; this file carries NO notification code.
#
# Usage (after sourcing read.sh):
#   vault_item_id op://V/Item/field       # id on stdout; rc 1 confirmed absent,
#                                         # rc 2 unproven/duplicate title
#   VAULT_VALUE=<v> vault_write_value op://V/Item/field   # create-or-replace

ref_parts() { # op://vault/item/field -> REF_VAULT REF_TITLE REF_FIELD
  local rest="${1#op://}"
  REF_VAULT="${rest%%/*}"
  rest="${rest#*/}"
  REF_TITLE="${rest%%/*}"
  REF_FIELD="${rest#*/}"
  [[ -n "$REF_VAULT" && -n "$REF_TITLE" && -n "$REF_FIELD" && "$REF_FIELD" != "$REF_TITLE" ]] || {
    echo "ERROR: not a full op://vault/item/field reference: $1" >&2
    return 2
  }
}

op_vault_read() { # ref -> value on stdout, routed like mutations (never ambient)
  local ref="$1"
  if [[ "$ref" == op://*-sensitive/* ]]; then
    guard_agent_shell || return $?
    "$OP_BIN" read --no-newline "$ref"
  else
    op_desktop read --no-newline "$ref"
  fi
}

vault_item_id() { # ref -> immutable item id; 1=confirmed absent, 2=unproven/duplicate
  local ref="$1" listing ids count
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$ref" || return 2
  listing="$(op_vault_mutation "$REF_VAULT" item list --vault "$REF_VAULT" --format json)" || {
    echo "ERROR: could not enumerate vault items while checking $ref." >&2
    return 2
  }
  jq -e 'type == "array" and all(.[];
    (.id | type) == "string" and (.id | length) > 0
    and (.title | type) == "string")' < <(printf '%s' "$listing") >/dev/null || {
    echo "ERROR: vault item inventory shape is invalid for $ref." >&2
    return 2
  }
  ids="$(printf '%s' "$listing" | jq -r --arg title "$REF_TITLE" '.[] | select(.title == $title) | .id')" || return 2
  count="$(printf '%s\n' "$ids" | sed '/^$/d' | wc -l | tr -d ' ')"
  case "$count" in
    0) return 1 ;;
    1) printf %s "$ids" ;;
    *) echo "ERROR: duplicate vault item title for $ref." >&2; return 2 ;;
  esac
}

vault_create_value() { # ref  (value in $VAULT_VALUE env)
  local ref="$1" rc check=""
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$ref" || return 2
  [[ -n "${VAULT_VALUE:-}" ]] || { echo "ERROR: refusing to create $ref with an empty value." >&2; return 1; }
  if vault_item_id "$ref" >/dev/null; then
    echo "ERROR: refusing to create duplicate item $ref." >&2
    return 2
  else
    rc=$?
    [[ "$rc" == "1" ]] || return "$rc"
  fi
  jq -n --arg vault "$REF_VAULT" --arg title "$REF_TITLE" --arg field "$REF_FIELD" \
    '{title:$title, vault:{name:$vault}, category:"SECURE_NOTE",
      fields:[{label:$field, type:"CONCEALED", value:env.VAULT_VALUE}]}' \
    | op_vault_mutation "$REF_VAULT" item create --format json - >/dev/null
  # A lost response can be ambiguous. Prove there is exactly one resulting item
  # and that ref resolution returns the intended value.
  vault_item_id "$ref" >/dev/null || return 2
  check="$(op_vault_read "$ref")" || return $?
  [[ "$check" == "$VAULT_VALUE" ]] || { echo "ERROR: created vault item did not verify ($ref)." >&2; return 1; }
  check=""
  echo "  vault: created $ref"
}

vault_replace_value() { # ref  (value in $VAULT_VALUE env)
  local ref="$1" item_id existing="" check=""
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$ref" || return 2
  [[ -n "${VAULT_VALUE:-}" ]] || { echo "ERROR: refusing to replace $ref with an empty value." >&2; return 1; }
  item_id="$(vault_item_id "$ref")" || {
    echo "ERROR: refusing to replace an absent or unproven vault item ($ref)." >&2
    return 2
  }
  if existing="$(op_vault_read "$ref")" && [[ "$existing" == "$VAULT_VALUE" ]]; then
    existing=""
    echo "  vault: item already has this value ($ref)"
    return 0
  fi
  existing=""
  # Preserve the item's immutable identity. The existing JSON and replacement
  # secret stay on stdin/in memory, never argv or disk. Exactly one matching
  # field must exist.
  op_vault_mutation "$REF_VAULT" item get "$item_id" --vault "$REF_VAULT" --format json \
    | REF_FIELD="$REF_FIELD" jq -e '
        if ([.fields[]? | select(.label == env.REF_FIELD)] | length) == 1
        then .fields |= map(if .label == env.REF_FIELD then .value = env.VAULT_VALUE else . end)
        else error("item must contain exactly one matching field") end' \
    | op_vault_mutation "$REF_VAULT" item edit "$item_id" --vault "$REF_VAULT" >/dev/null
  check="$(op_vault_read "$ref")" || return $?
  [[ "$check" == "$VAULT_VALUE" ]] || { echo "ERROR: vault item replacement did not verify ($ref)." >&2; return 1; }
  [[ "$(vault_item_id "$ref")" == "$item_id" ]] || { echo "ERROR: vault item identity changed during replacement ($ref)." >&2; return 1; }
  check=""
  echo "  vault: updated item in place ($ref)"
}

vault_write_value() { # ref  (value in $VAULT_VALUE env) — create if absent, else replace
  local ref="$1" rc
  if vault_item_id "$ref" >/dev/null 2>&1; then
    vault_replace_value "$ref"
  else
    rc=$?
    [[ "$rc" == "1" ]] || return "$rc"
    vault_create_value "$ref"
  fi
}

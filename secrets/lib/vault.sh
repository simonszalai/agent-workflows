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
#   A=<v1> B=<v2> vault_replace_fields op://V/Item/f1=A op://V/Item/f2=B

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

# Listing cache: one `op item list` per vault per process. vault_item_id is
# usually called inside $(...), so callers that need several lookups load the
# listing in the main shell first (vault_listing_load) and invalidate it after
# creating an item.
vault_listing_load() { # vault -> sets _VAULT_LIST_VAULT/_VAULT_LIST_JSON
  local vault="$1" listing
  [[ "${_VAULT_LIST_VAULT:-}" == "$vault" && -n "${_VAULT_LIST_JSON:-}" ]] && return 0
  listing="$(op_vault_mutation "$vault" item list --vault "$vault" --format json)" || {
    echo "ERROR: could not enumerate vault items in $vault." >&2
    return 2
  }
  jq -e 'type == "array" and all(.[];
    (.id | type) == "string" and (.id | length) > 0
    and (.title | type) == "string")' < <(printf '%s' "$listing") >/dev/null || {
    echo "ERROR: vault item inventory shape is invalid for $vault." >&2
    return 2
  }
  _VAULT_LIST_VAULT="$vault"; _VAULT_LIST_JSON="$listing"
}
vault_listing_invalidate() { _VAULT_LIST_VAULT=""; _VAULT_LIST_JSON=""; }

vault_item_id() { # ref -> immutable item id; 1=confirmed absent, 2=unproven/duplicate
  local ref="$1" ids count
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$ref" || return 2
  vault_listing_load "$REF_VAULT" || return 2
  ids="$(printf '%s' "$_VAULT_LIST_JSON" | jq -r --arg title "$REF_TITLE" '.[] | select(.title == $title) | .id')" || return 2
  count="$(printf '%s\n' "$ids" | sed '/^$/d' | wc -l | tr -d ' ')"
  case "$count" in
    0) return 1 ;;
    1) printf %s "$ids" ;;
    *) echo "ERROR: duplicate vault item title for $ref." >&2; return 2 ;;
  esac
}

vault_create_value() { # ref  (value in $VAULT_VALUE env); serialized per vault
  local vault_lock rc=0
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$1" || return 2
  vault_lock="$(vault_item_lock_acquire "$REF_VAULT")" || return 1
  vault_create_value_locked "$1" || rc=$?
  vault_item_lock_release "$vault_lock"
  return "$rc"
}

vault_create_value_locked() { # ref  (value in $VAULT_VALUE env)
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
    | op_vault_mutation "$REF_VAULT" item create --vault "$REF_VAULT" --format json - >/dev/null
  # A lost response can be ambiguous. Prove there is exactly one resulting item
  # and that ref resolution returns the intended value.
  vault_listing_invalidate
  vault_item_id "$ref" >/dev/null || return 2
  check="$(op_vault_read "$ref")" || return $?
  [[ "$check" == "$VAULT_VALUE" ]] || { echo "ERROR: created vault item did not verify ($ref)." >&2; return 1; }
  check=""
  echo "  vault: created $ref"
}

# Per-VAULT mutex for read-modify-write edits. Observed live: 1Password
# returns 409 Conflict for concurrent edits of DIFFERENT items in the same
# vault (server-side vault versioning), so item-level serialization is not
# enough — all writes into one vault are sequential. Edits take ~2-3s, so a
# full parallel batch serializes into a few tens of seconds at worst; reads
# and Render syncs stay fully parallel. mkdir is the portable atomic lock.
vault_item_lock_acquire() { # vault [ignored] -> echoes lock dir
  local lockroot="${VAULT_LOCK_DIR:-$HOME/.local/state/agent-workflows/vault-locks}" key lockdir waited=0 holder
  mkdir -p "$lockroot"
  key="$(printf '%s' "$1" | shasum -a 256 | cut -c1-16)"
  lockdir="$lockroot/$key.lock"
  until mkdir "$lockdir" 2>/dev/null; do
    # Stale-lock reclaim: the holder pid is gone (crashed mid-edit), or the dir
    # never got a pid file and is old. The stale dir is moved aside with ONE
    # atomic rename (only one waiter can win it; a waiter that loses just loops
    # back to mkdir), never deleted in place — deleting the pid file of a lock
    # another waiter just re-took would let two holders through.
    holder="$(cat "$lockdir/pid" 2>/dev/null || true)"
    if [[ -n "$holder" ]] && ! kill -0 "$holder" 2>/dev/null; then
      # Re-read inside the branch: reclaim only if the same dead pid still owns it.
      if [[ "$(cat "$lockdir/pid" 2>/dev/null || true)" == "$holder" ]] && ! kill -0 "$holder" 2>/dev/null \
         && mv "$lockdir" "$lockdir.stale.$$" 2>/dev/null; then
        echo "  vault: reclaiming stale lock ($1; pid $holder is gone)" >&2
        rm -rf "$lockdir.stale.$$"
      fi
      continue
    elif [[ -z "$holder" && -n "$(find "$lockdir" -maxdepth 0 -mmin +1 2>/dev/null)" ]]; then
      if [[ ! -e "$lockdir/pid" ]] && mv "$lockdir" "$lockdir.stale.$$" 2>/dev/null; then
        rm -rf "$lockdir.stale.$$"
      fi
      continue
    fi
    waited=$((waited + 1))
    [[ "$waited" -le "${VAULT_LOCK_TIMEOUT_SECONDS:-180}" ]] || {
      echo "ERROR: timed out waiting for the vault item lock ($1; holder pid ${holder:-unknown})." >&2
      return 1
    }
    sleep 1
  done
  printf '%s' "$$" > "$lockdir/pid"
  printf '%s' "$lockdir"
}

vault_item_lock_release() { rm -f "$1/pid" 2>/dev/null; rmdir "$1" 2>/dev/null || true; }

# Edit one item's fields in place: stdin-fed item JSON, exactly one matching
# field per label, values from the named env vars (never argv). Caller holds the
# vault lock. Single attempt by design: the orchestrator wave-partitions
# same-item entries and the per-vault lock serializes local concurrency, so a
# 409 here means an EXTERNAL editor raced us — fail loudly and let the human
# rerun rather than silently replaying writes.
_vault_edit_fields() { # vault item_id FIELD=VAR...
  local vault="$1" item_id="$2"; shift 2
  local spec specs="" f v rc=0
  for spec in "$@"; do
    f="${spec%%=*}"; v="${spec#*=}"
    specs="$specs$(printf '%s\t%s\n' "$f" "$v")"$'\n'
  done
  local item edited
  item="$(op_vault_mutation "$vault" item get "$item_id" --vault "$vault" --format json)" || return 1
  # The value variables are exported only inside this command substitution so
  # jq can read them from env; they never reach argv or the caller's environment.
  edited="$(for spec in "$@"; do export "${spec#*=}"; done
      printf '%s' "$item" | EDIT_SPECS="$specs" jq -e '
        (env.EDIT_SPECS | split("\n") | map(select(length > 0) | split("\t") | {label: .[0], value: env[.[1]]})) as $edits
        | reduce $edits[] as $e (.;
            if ([.fields[]? | select(.label == $e.label)] | length) == 1
            then .fields |= map(if .label == $e.label then .value = $e.value else . end)
            else error("item must contain exactly one field labelled " + $e.label) end)')" || { item=""; return 1; }
  item=""
  printf '%s' "$edited" | op_vault_mutation "$vault" item edit "$item_id" --vault "$vault" >/dev/null
  rc=$?
  edited=""
  return "$rc"
}

vault_replace_value() { # ref  (value in $VAULT_VALUE env)
  local ref="$1" item_id existing="" check=""
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$ref" || return 2
  [[ -n "${VAULT_VALUE:-}" ]] || { echo "ERROR: refusing to replace $ref with an empty value." >&2; return 1; }
  vault_listing_load "$REF_VAULT" || return 2
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
  local vault_lock
  vault_lock="$(vault_item_lock_acquire "$REF_VAULT" "$item_id")" || return 1
  if ! _vault_edit_fields "$REF_VAULT" "$item_id" "$REF_FIELD=VAULT_VALUE"; then
    vault_item_lock_release "$vault_lock"
    echo "ERROR: vault item edit failed for $ref (a concurrent external edit? rerun to converge)." >&2
    return 1
  fi
  check="$(op_vault_read "$ref")" || { vault_item_lock_release "$vault_lock"; return 1; }
  vault_item_lock_release "$vault_lock"
  [[ "$check" == "$VAULT_VALUE" ]] || { echo "ERROR: vault item replacement did not verify ($ref)." >&2; return 1; }
  [[ "$(vault_item_id "$ref")" == "$item_id" ]] || { echo "ERROR: vault item identity changed during replacement ($ref)." >&2; return 1; }
  check=""
  echo "  vault: updated item in place ($ref)"
}

# vault_replace_fields REF=VAR REF=VAR... — replace several fields of ONE item in
# a single edit under the vault lock (e.g. an AWS key id + secret pair). Every
# REF must name the same vault/item; values come from the named env vars and
# must be non-empty; each field is verified by re-read.
vault_replace_fields() {
  local spec ref var item_id vault="" title="" edits=() check
  local REF_VAULT REF_TITLE REF_FIELD
  [[ $# -ge 1 ]] || { echo "ERROR: vault_replace_fields needs REF=VAR arguments." >&2; return 2; }
  for spec in "$@"; do
    ref="${spec%%=*}"; var="${spec#*=}"
    [[ "$spec" == *=* && -n "$var" && "$var" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || { echo "ERROR: bad field spec (want REF=VARNAME): ${spec%%=*}" >&2; return 2; }
    ref_parts "$ref" || return 2
    [[ -n "${!var:-}" ]] || { echo "ERROR: refusing to write an empty value to $ref." >&2; return 1; }
    if [[ -z "$vault" ]]; then vault="$REF_VAULT"; title="$REF_TITLE"
    elif [[ "$vault" != "$REF_VAULT" || "$title" != "$REF_TITLE" ]]; then
      echo "ERROR: vault_replace_fields: all refs must address one item ($vault/$title vs $REF_VAULT/$REF_TITLE)." >&2
      return 2
    fi
    edits+=("$REF_FIELD=$var")
  done
  vault_listing_load "$vault" || return 2
  item_id="$(vault_item_id "op://$vault/$title/${edits[0]%%=*}")" || {
    echo "ERROR: refusing to edit an absent or unproven vault item ($vault/$title)." >&2
    return 2
  }
  local vault_lock
  vault_lock="$(vault_item_lock_acquire "$vault")" || return 1
  if ! _vault_edit_fields "$vault" "$item_id" "${edits[@]}"; then
    vault_item_lock_release "$vault_lock"
    echo "ERROR: vault item edit failed for $vault/$title (a concurrent external edit? rerun to converge)." >&2
    return 1
  fi
  for spec in "${edits[@]}"; do
    var="${spec#*=}"
    check="$(op_vault_read "op://$vault/$title/${spec%%=*}")" || { vault_item_lock_release "$vault_lock"; return 1; }
    [[ "$check" == "${!var}" ]] || { vault_item_lock_release "$vault_lock"; echo "ERROR: vault field ${spec%%=*} did not verify ($vault/$title)." >&2; check=""; return 1; }
  done
  check=""
  vault_item_lock_release "$vault_lock"
  echo "  vault: updated ${#edits[@]} fields in place (op://$vault/$title)"
}

vault_write_value() { # ref  (value in $VAULT_VALUE env) — create if absent, else replace
  local ref="$1" rc
  local REF_VAULT REF_TITLE REF_FIELD
  ref_parts "$ref" || return 2
  vault_listing_load "$REF_VAULT" || return 2
  if vault_item_id "$ref" >/dev/null 2>&1; then
    vault_replace_value "$ref"
  else
    rc=$?
    [[ "$rc" == "1" ]] || return "$rc"
    vault_create_value "$ref"
  fi
}

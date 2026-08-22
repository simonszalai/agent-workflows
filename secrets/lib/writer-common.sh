# shellcheck shell=bash
# writer-common.sh — the shared half of every secrets writer (github/render/
# prefect/hermes): argument parsing, row selection, dry-run plan, sensitivity
# precheck, and the resolve-whole-batch-first phase with a per-ref value cache.
# Sourced after read.sh/derive.sh/config.sh.
#
# Writer protocol:
#   W_KIND=github W_LABEL=gh W_FAIL_NOTE="nothing written"
#   writer_flag() { case "$1" in --no-deploy) do_deploy=0; return 1 ;; esac; return 0; }
#       # optional: consume writer-specific flags; return = number of args consumed
#   writer_parse_args "$@"       # sets W_DRY W_DEST W_ONLY W_REF W_REF_PREFIX
#   writer_select_rows           # W_SELECTED (KIND\tDEST\tENV\tREF\tTRANSFORM lines)
#   writer_print_plan [suffix_fn] # "  label[dest] ENV <- ref (transform)" per row
#   writer_precheck bin...       # need bins + op; one sensitivity regex -> guard
#   writer_resolve_batch         # W_DESTS[] W_ENVS[] W_VALS[] (values in memory only)
#   writer_each_row fn           # fn kind dest env ref transform, per selected row
#
# IRON RULE: values travel env/stdin/arrays only — never argv, stdout or logs.

W_DRY=0 W_DEST="" W_ONLY="" W_REF="" W_REF_PREFIX="" W_SELECTED=""

# One regex for "this ref costs a human (Touch ID) read": *-sensitive vaults
# and the human-only "OP SA" service-account-token vault.
W_HUMAN_REF_RE=$'\t'"op://([^/]*-sensitive|OP SA)/"

writer_flag() { return 0; } # default: no writer-specific flags

writer_parse_args() {
  local n
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --dry-run) W_DRY=1 ;;
      --reason)
        [[ -n "${2:-}" ]] || { echo "ERROR: --reason requires non-empty text" >&2; exit 2; }
        SENSITIVE_ACCESS_REASON="$2"; export SENSITIVE_ACCESS_REASON; shift ;;
      --dest) W_DEST="${2:-}"; [[ -n "$W_DEST" ]] || { echo "ERROR: --dest needs a value" >&2; exit 2; }; shift ;;
      --only) W_ONLY="${2:-}"; [[ -n "$W_ONLY" ]] || { echo "ERROR: --only needs a value" >&2; exit 2; }; shift ;;
      --ref) W_REF="${2:-}"; [[ "$W_REF" == op://*/*/* ]] || { echo "ERROR: --ref needs a full op://VAULT/ITEM/field ref" >&2; exit 2; }; shift ;;
      --ref-prefix) W_REF_PREFIX="${2:-}"; [[ "$W_REF_PREFIX" == op://*/*/ ]] || { echo "ERROR: --ref-prefix needs op://VAULT/ITEM/" >&2; exit 2; }; shift ;;
      -*)
        n=0; writer_flag "$1" "${2:-}" || n=$?
        [[ "$n" -gt 0 ]] || { echo "ERROR: unknown flag $1" >&2; exit 2; }
        shift $((n - 1)) ;;
      *) echo "ERROR: unexpected arg $1" >&2; exit 2 ;;
    esac
    shift
  done
}

want() { [[ -z "$W_ONLY" ]] || case ",$W_ONLY," in *",$1,"*) ;; *) return 1 ;; esac; }

writer_each_row() { # fn — fn KIND DEST ENV REF TRANSFORM for each selected row
  local _k _d _e _r _t
  while IFS=$'\t' read -r _k _d _e _r _t; do
    [[ -n "$_e" ]] || continue
    "$1" "$_k" "$_d" "$_e" "$_r" "$_t"
  done <<< "$W_SELECTED"
}

# Select rows for W_KIND from the config (dest/ref/prefix filters are pushed
# into config_rows; --only is applied here). Exits 0 with a note when empty.
writer_select_rows() { # [dest-override]
  local dest="${1-$W_DEST}" rows _k _d _e _r _t
  rows="$(config_rows "$W_KIND" "$dest" "$W_REF" "$W_REF_PREFIX")" || exit $?
  W_SELECTED=""
  while IFS=$'\t' read -r _k _d _e _r _t; do
    [[ -n "$_e" ]] || continue
    want "$_e" || continue
    W_SELECTED="${W_SELECTED:+$W_SELECTED$'\n'}$(printf '%s\t%s\t%s\t%s\t%s' "$_k" "$_d" "$_e" "$_r" "$_t")"
  done <<< "$rows"
  [[ -n "$W_SELECTED" ]] || { echo "No $W_KIND rows${dest:+ for $dest} selected in manifest."; exit 0; }
}

writer_print_plan() { # [suffix_fn: DEST -> extra text]
  local fn="${1:-}"
  _plan_line() {
    local extra=""
    [[ -z "$fn" ]] || extra="$("$fn" "$2")"
    printf "  %s[%s] %s <- %s (%s)%s\n" "$W_LABEL" "$2" "$3" "$4" "$5" "$extra"
  }
  writer_each_row _plan_line
}

# Dependencies + sensitivity precheck: if ANY selected row needs a human read,
# refuse an agent shell BEFORE the first read of anything. Then read the project
# SA token once (cached) when any row needs it, so per-ref subshells never hit
# the Keychain again.
writer_precheck() { # bins...
  local b
  for b in "$@"; do need "$b"; done
  need "$OP_BIN"
  if grep -qE "$W_HUMAN_REF_RE" <<< "$W_SELECTED"; then
    guard_agent_shell || exit 3
  fi
  if grep -qE $'\t'"op://" <<< "$W_SELECTED" && ! grep -qE "$W_HUMAN_REF_RE" <<< "$W_SELECTED"; then
    sa_token >/dev/null || exit $?
  fi
}

# Resolve+transform+validate the ENTIRE batch before the first write: a failed
# or empty read must never blank a live destination or leave a half-written
# batch. Each DISTINCT ref is resolved once (one Touch ID per sensitive ref no
# matter how many rows share it); transforms are pure and applied per row.
W_DESTS=(); W_ENVS=(); W_VALS=()
_rv_refs=(); _rv_vals=()
_rv_lookup() { local j=0; while [[ $j -lt ${#_rv_refs[@]} ]]; do [[ "${_rv_refs[$j]}" == "$1" ]] && { printf %s "${_rv_vals[$j]}"; return 0; }; j=$((j + 1)); done; return 1; }
writer_resolve_batch() {
  local _k d env r transform raw val rc
  while IFS=$'\t' read -r _k d env r transform; do
    [[ -n "$env" ]] || continue
    if ! raw="$(_rv_lookup "$r")"; then
      rc=0
      raw="$(resolve_ref "$r")" || rc=$?
      if [[ "$rc" -ne 0 ]]; then
        echo "  $W_LABEL[$d] $env: RESOLVE FAILED ($r) — $W_FAIL_NOTE" >&2
        [[ "$rc" == "3" ]] && exit 3
        exit 1
      fi
      [[ -n "$raw" ]] || { echo "  $W_LABEL[$d] $env: EMPTY VALUE ($r) — $W_FAIL_NOTE" >&2; exit 1; }
      _rv_refs+=("$r"); _rv_vals+=("$raw")
    fi
    val="$(printf %s "$raw" | apply_transform "$transform")" \
      || { echo "  $W_LABEL[$d] $env: DERIVE FAILED ($r) — $W_FAIL_NOTE" >&2; exit 1; }
    [[ -n "$val" ]] || { echo "  $W_LABEL[$d] $env: EMPTY VALUE ($r) — $W_FAIL_NOTE" >&2; exit 1; }
    W_DESTS+=("$d"); W_ENVS+=("$env"); W_VALS+=("$val"); val=""; raw=""
  done <<< "$W_SELECTED"
  _rv_vals=() # raw values are no longer needed once every row is derived
}

# Parallel-wave concurrency for independent per-row writes.
writer_concurrency() { # -> validated SYNC_PUT_CONCURRENCY (default 8)
  local c="${SYNC_PUT_CONCURRENCY:-8}"
  [[ "$c" =~ ^[1-9][0-9]*$ ]] || { echo "ERROR: SYNC_PUT_CONCURRENCY must be a positive integer, got: $c" >&2; exit 2; }
  printf %s "$c"
}

# --- DB-credential guard (shared by writers/render and bin/sync-secrets) ----
# The three canonical runtime/migration DB env names are rotated ONLY by the
# postgres tooling (rotate-secret provider postgres / db-provision-roles): a
# targeted ref selection of one of them is refused; full sweeps skip them.
# EXACT match only — derived names like DATABASE_URL_GLOBAL are routine pushes.
is_db_cred_env() {
  case "$1" in
    DATABASE_URL|MIGRATE_DATABASE_URL|SYSTEM_DATABASE_URL) return 0 ;;
  esac
  return 1
}

db_guard_refuse() { # label rows-on-stdin -> exit 2 if any row is a DB credential
  local label="$1" _k d env r _t hit=""
  while IFS=$'\t' read -r _k d env r _t; do
    [[ -n "$env" ]] || continue
    is_db_cred_env "$env" && hit="${hit}  ${label}[$d] $env ($r)"$'\n'
  done
  [[ -n "$hit" ]] || return 0
  echo "ERROR: selection includes DB credential rows — refusing ref-selected sync:" >&2
  printf '%s' "$hit" >&2
  echo "Rotate Postgres credentials through the postgres tooling instead:" >&2
  echo "  rotate-secret --ref '<op-ref>' --reason ...   (provider postgres)" >&2
  echo "  db-provision-roles --project <p> [--app <app>] <tier> --reason ..." >&2
  echo "Initial cutover to a fresh per-app item ONLY: rerun with --include-db --reason ..." >&2
  exit 2
}

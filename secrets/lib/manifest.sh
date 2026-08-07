# shellcheck shell=bash
# manifest.sh — read, VALIDATE, and filter a repo's secret-routing manifest.
# Rows are tab-separated with exactly five fields:
#   KIND<TAB>DEST<TAB>ENVNAME<TAB>REF<TAB>TRANSFORM
# Comments (lines whose first non-space char is #) and blank lines are ignored.
#
# The parser is STRICT and fail-closed: a malformed manifest is rejected
# wholesale so a dropped tab can never silently mis-route or blank a secret.
#
# The manifest path comes from the caller (sync-secrets sets it from the target
# repo): export _MANIFEST_FILE before calling any function here.
#
# Usage:
#   _MANIFEST_FILE=/repo/scripts/secrets/manifest
#   manifest_validate                 # whole-file check; rc 1 bad rows, rc 2 missing file
#   manifest_rows render srv-x        # rows for one kind, optional dest filter
#   manifest_rows render "" op://V/I/f   # exact-REF filter (never substring)
#   manifest_dests github             # unique DEST values for a kind

# manifest_validate — verify the whole file. Prints every problem to stderr and
# returns nonzero if any row is malformed. Rules:
#   * exactly 5 tab-separated fields, none empty;
#   * KIND in {github, render, prefect, dev};
#   * REF is literal:<value> or op://<vault>/<item>/<field> (any field name —
#     product-grouped items keep per-app credentials in named fields);
#   * TRANSFORM in {self, conn-id} or db=/pgbouncer=/asyncpg-internal=/
#     asyncpg-external= with a non-empty tail;
#   * no duplicate (KIND, DEST, ENVNAME) route.
manifest_validate() {
  [[ -n "${_MANIFEST_FILE:-}" ]] || { echo "ERROR: _MANIFEST_FILE is not set" >&2; return 2; }
  [[ -f "$_MANIFEST_FILE" ]] || { echo "ERROR: manifest not found: $_MANIFEST_FILE" >&2; return 2; }
  awk -F'\t' '
    # skip comments (first non-space char is #) and blank lines
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    {
      if (NF != 5) {
        printf("manifest:%d: expected 5 tab-separated fields, got %d\n", NR, NF) > "/dev/stderr"
        bad = 1
        next
      }
      for (i = 1; i <= 5; i++) {
        if ($i == "") {
          printf("manifest:%d: field %d is empty\n", NR, i) > "/dev/stderr"
          bad = 1
        }
      }
      kind = $1; dest = $2; env = $3; ref = $4; tr = $5
      if (kind != "github" && kind != "render" && kind != "prefect" && kind != "dev") {
        printf("manifest:%d: unknown KIND %s\n", NR, kind) > "/dev/stderr"
        bad = 1
      }
      if (ref !~ "^literal:" && ref !~ "^op://[^/]+/[^/]+/[^/]+$") {
        printf("manifest:%d: unsupported REF %s (want literal:<v> or op://<vault>/<item>/<field>)\n", NR, ref) > "/dev/stderr"
        bad = 1
      }
      if (tr != "self" && tr != "conn-id" \
          && tr !~ "^db=." && tr !~ "^pgbouncer=." \
          && tr !~ "^asyncpg-internal=." && tr !~ "^asyncpg-external=.") {
        printf("manifest:%d: unknown TRANSFORM %s\n", NR, tr) > "/dev/stderr"
        bad = 1
      }
      key = kind SUBSEP dest SUBSEP env
      if (key in seen) {
        printf("manifest:%d: duplicate route (%s, %s, %s) first seen at line %d\n", NR, kind, dest, env, seen[key]) > "/dev/stderr"
        bad = 1
      } else {
        seen[key] = NR
      }
    }
    END { if (bad) exit 1 }
  ' "$_MANIFEST_FILE"
}

# manifest_rows KIND [DEST] [EXACT_REF] — print matching rows (fail-closed: the
# whole manifest is validated first). DEST filters column 2 by equality when
# nonempty. EXACT_REF filters column 4 by EQUALITY (never substring) when
# nonempty — this is what makes `sync-secrets --changed` tier-safe.
manifest_rows() {
  local kind="$1" dest="${2:-}" ref="${3:-}"
  manifest_validate || return $?
  awk -F'\t' -v k="$kind" -v d="$dest" -v r="$ref" '
    /^[[:space:]]*#/ { next }
    /^[[:space:]]*$/ { next }
    NF != 5 { next }
    $1 == k && (d == "" || $2 == d) && (r == "" || $4 == r) { print }
  ' "$_MANIFEST_FILE"
}

# manifest_dests KIND — unique DEST values for a kind (validated).
manifest_dests() {
  manifest_rows "$1" | awk -F'\t' '{ print $2 }' | sort -u
}

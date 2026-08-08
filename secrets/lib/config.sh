# shellcheck shell=bash
# config.sh — read, VALIDATE, and query a project's secrets config.
#
# One file per project, at the repo root of the project's PRIMARY repo:
#
#   project:  <id>
#   repos:    [<repo>, ...]          every repo the project routes into
#   health:   {<dest>: <url>, ...}   fail-closed probe registry
#   rotation: {<id>: {...}, ...}     rotation policy, keyed on the op:// ref
#   routes:   [{repo, kind, dest, env, ref, transform}, ...]
#
# A repo that is not its project's primary repo carries a one-line POINTER
# instead, so the engine can be invoked from any repo in the project:
#
#   extends: ../<primary-repo>/secrets.yaml
#
# A pointer is a reference, never a copy: exactly one file per project holds
# routing and rotation, and a rotation entry's consumers are DERIVED from the
# routes sharing its ref. The predecessor layout stored those consumers a second
# time in agent-workflows/config/secret-rotation.json, where 58 of 93 entries
# had silently drifted out of agreement with the routes they restated.
#
# The parser is STRICT and fail-closed: a malformed config is rejected wholesale
# so a bad row can never silently mis-route or blank a secret.
#
# Callers export _SECRETS_CONFIG (a repo path or a secrets.yaml path) and then
# use the query functions; parsing happens once per process.
#
# Usage:
#   _SECRETS_CONFIG=/repo            # or /repo/secrets.yaml
#   config_validate                  # whole-file check; rc 1 bad, rc 2 missing
#   config_rows render srv-x         # rows for one kind, optional dest
#   config_rows render "" op://V/I/f # exact-REF filter (never substring)
#   config_dests github              # unique DEST values for a kind
#   config_health srv-x              # probe URL for a dest, empty if none
#   config_json                      # the whole document as JSON (for jq)

CONFIG_BASENAME="secrets.yaml"

# config_path — resolve _SECRETS_CONFIG to a concrete config file, following one
# `extends:` pointer. Prints the path; rc 2 when nothing is there.
config_path() {
  local start="${_SECRETS_CONFIG:-}"
  [[ -n "$start" ]] || { echo "ERROR: _SECRETS_CONFIG is not set" >&2; return 2; }
  [[ -d "$start" ]] && start="$start/$CONFIG_BASENAME"
  if [[ ! -f "$start" ]]; then
    echo "ERROR: no secrets config at $start — this repo is not routed." >&2
    echo "       Add $CONFIG_BASENAME at the repo root, or a pointer to the project's primary repo:" >&2
    echo "         extends: ../<primary-repo>/$CONFIG_BASENAME" >&2
    return 2
  fi
  local target
  target="$(_config_py "$start" pointer)" || return 1
  if [[ -n "$target" ]]; then
    [[ -f "$target" ]] || {
      echo "ERROR: $start points at $target, which does not exist" >&2
      return 2
    }
    # One hop only: a pointer to a pointer is a configuration error, not a chain.
    if [[ -n "$(_config_py "$target" pointer)" ]]; then
      echo "ERROR: $target is itself a pointer — pointers must reference a project config directly" >&2
      return 1
    fi
    start="$target"
  fi
  printf '%s\n' "$start"
}

# _config_py FILE MODE — the single python entrypoint. MODE is one of
# pointer|rows|json|validate. Kept in one place so YAML parsing, validation and
# row shaping cannot drift apart.
_config_py() {
  python3 - "$1" "$2" <<'PY'
import os, sys, json
try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML required (pip install pyyaml)")

path, mode = sys.argv[1], sys.argv[2]
try:
    doc = yaml.safe_load(open(path)) or {}
except Exception as exc:
    sys.exit(f"ERROR: {path}: cannot parse YAML: {exc}")
if not isinstance(doc, dict):
    sys.exit(f"ERROR: {path}: top level must be a mapping")

if mode == "pointer":
    ext = doc.get("extends")
    if ext:
        if len(doc) != 1:
            sys.exit(f"ERROR: {path}: a pointer must contain only 'extends'")
        print(os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), ext)))
    sys.exit(0)

KINDS = {"github", "render", "prefect", "dev"}
TRANSFORM_PREFIXES = ("db=", "pgbouncer=", "asyncpg-internal=", "asyncpg-external=")
bad = []

for key in ("project", "routes"):
    if key not in doc:
        bad.append(f"missing top-level '{key}'")

routes = doc.get("routes") or []
if not isinstance(routes, list):
    bad.append("'routes' must be a list")
    routes = []

seen = {}
for i, r in enumerate(routes, 1):
    if not isinstance(r, dict):
        bad.append(f"route {i}: not a mapping")
        continue
    missing = [k for k in ("repo", "kind", "dest", "env", "ref", "transform") if not r.get(k)]
    if missing:
        bad.append(f"route {i}: missing/empty {', '.join(missing)}")
        continue
    kind, dest, env, ref, tr = r["kind"], r["dest"], r["env"], r["ref"], r["transform"]
    for name, val in (("repo", r["repo"]), ("kind", kind), ("dest", dest), ("env", env),
                      ("ref", ref), ("transform", tr)):
        if not isinstance(val, str):
            bad.append(f"route {i}: {name} must be a string")
    if kind not in KINDS:
        bad.append(f"route {i}: unknown kind {kind!r}")
    if not (ref.startswith("literal:") or ref.startswith("op://")):
        bad.append(f"route {i}: REF must be literal:<value> or op://<vault>/<item>/<field>, got {ref!r}")
    elif ref.startswith("op://") and len(ref[len("op://"):].split("/")) != 3:
        bad.append(f"route {i}: op:// REF needs vault/item/field, got {ref!r}")
    if tr not in ("self", "conn-id") and not any(
            tr.startswith(p) and len(tr) > len(p) for p in TRANSFORM_PREFIXES):
        bad.append(f"route {i}: unknown transform {tr!r}")
    key = (kind, dest, env)
    if key in seen:
        bad.append(f"route {i}: duplicate route {key} first seen at route {seen[key]}")
    else:
        seen[key] = i

# A rotation entry whose ref no route serves would rotate a credential nothing
# consumes — the drift this layout exists to make impossible.
rotation = doc.get("rotation") or {}
refs = {r.get("ref") for r in routes if isinstance(r, dict)}
for rid, entry in (rotation.items() if isinstance(rotation, dict) else []):
    if not isinstance(entry, dict) or not entry.get("ref"):
        bad.append(f"rotation '{rid}': missing ref")
    elif entry["ref"] not in refs:
        bad.append(f"rotation '{rid}': ref {entry['ref']} has no route — it would rotate nothing")

if bad:
    for b in bad:
        print(f"{path}: {b}", file=sys.stderr)
    sys.exit(1)

if mode == "validate":
    sys.exit(0)
if mode == "json":
    print(json.dumps(doc))
    sys.exit(0)
if mode == "rows":
    for r in routes:
        print("\t".join((r["kind"], r["dest"], r["env"], r["ref"], r["transform"], r["repo"])))
    sys.exit(0)
sys.exit(f"ERROR: unknown mode {mode}")
PY
}

# _config_cache — parse once per process into _CONFIG_ROWS/_CONFIG_DOC.
_config_cache() {
  [[ -n "${_CONFIG_ROWS+x}" ]] && return 0
  local file
  file="$(config_path)" || return $?
  _CONFIG_FILE="$file"
  _CONFIG_ROWS="$(_config_py "$file" rows)" || return 1
  _CONFIG_DOC="$(_config_py "$file" json)" || return 1
  export _CONFIG_FILE
}

# config_validate — verify the whole config. Prints every problem to stderr.
config_validate() {
  local file
  file="$(config_path)" || return $?
  _config_py "$file" validate
}

# config_rows KIND [DEST] [EXACT_REF] — print matching routes as
# KIND<TAB>DEST<TAB>ENVNAME<TAB>REF<TAB>TRANSFORM (the shape the writers consume;
# the route's repo is dropped here because a push targets DEST, not a checkout).
# DEST filters by equality when nonempty. EXACT_REF filters by EQUALITY (never
# substring) when nonempty — this is what makes `--changed` tier-safe.
config_rows() {
  local kind="$1" dest="${2:-}" ref="${3:-}"
  _config_cache || return $?
  awk -F'\t' -v k="$kind" -v d="$dest" -v r="$ref" '
    (k == "" || $1 == k) && (d == "" || $2 == d) && (r == "" || $4 == r) {
      print $1 "\t" $2 "\t" $3 "\t" $4 "\t" $5
    }
  ' <<< "$_CONFIG_ROWS"
}

# config_rows_full — as config_rows but keeps the route's repo as a 6th field,
# for callers that report provenance (which repo a destination belongs to).
config_rows_full() {
  local kind="${1:-}" dest="${2:-}" ref="${3:-}"
  _config_cache || return $?
  awk -F'\t' -v k="$kind" -v d="$dest" -v r="$ref" '
    (k == "" || $1 == k) && (d == "" || $2 == d) && (r == "" || $4 == r)
  ' <<< "$_CONFIG_ROWS"
}

# config_dests KIND — unique DEST values for a kind (validated).
config_dests() {
  config_rows "$1" | awk -F'\t' '{ print $2 }' | sort -u
}

# config_health DEST — probe URL for a dest; empty when unregistered.
config_health() {
  _config_cache || return $?
  jq -r --arg d "$1" '.health[$d] // empty' <<< "$_CONFIG_DOC"
}

# config_json — the whole document, for jq queries against `rotation`.
config_json() {
  _config_cache || return $?
  printf '%s\n' "$_CONFIG_DOC"
}

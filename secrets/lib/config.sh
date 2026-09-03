# shellcheck shell=bash
# config.sh — read, VALIDATE, and query a project's secrets config.
#
# One file per project, at the repo root of the project's PRIMARY repo:
#
#   project:  <id>
#   repos:    [<repo>, ...]          every repo the project routes into
#   health:   {<dest>: <url>, ...}   fail-closed probe registry
#   hermes:   {ssh: <dest>}          only when hermes routes exist
#   rotation: {<id>: {...}, ...}     rotation policy, keyed on a stable id
#   routes:   [{repo, kind, dest, env, ref, transform}, ...]
#
# Rotation entry keys: ref provider mode owner_repo (required); verify
# verify_command generate playbook sync_refs sync_repos config hook
# exclude_dests project disabled_reason (optional). Anything else is rejected.
#
# A rotation entry may declare `sync_repos: [../<other-primary-repo>]` when a
# SECOND project routes the same op:// ref. The fan-out then runs sync-secrets
# against those repos too. Validation is fail-closed: each named repo must
# exist, belong to a different project, and actually route one of the entry's
# refs.
#
# A repo that is not its project's primary repo carries a one-line POINTER
# instead, so the engine can be invoked from any repo in the project:
#
#   extends: ../<primary-repo>/secrets.yaml
#
# The parser is STRICT and fail-closed: duplicate YAML keys, unknown keys, a
# malformed route or entry reject the whole config (exit 2) so a bad row can
# never silently mis-route or blank a secret.
#
# Callers export _SECRETS_CONFIG (a repo path or a secrets.yaml path) and then
# use the query functions; the file is parsed, validated and cached in ONE
# python call per process.
#
# Usage:
#   _SECRETS_CONFIG=/repo            # or /repo/secrets.yaml
#   config_validate                  # whole-file check; rc 2 bad or missing
#   config_path                      # resolved config file path
#   config_rows render srv-x         # rows for one kind, optional dest
#   config_rows render "" op://V/I/f # exact-REF filter (never substring)
#   config_rows render "" "" op://V/I/ # REF-prefix filter (field-less --changed)
#   config_dests github              # unique DEST values for a kind
#   config_health srv-x              # probe URL for a dest, empty if none
#   config_json                      # the whole document as JSON (for jq)

CONFIG_BASENAME="secrets.yaml"
_CONFIG_LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# _config_py START — resolve one `extends:` pointer hop, validate, and print
# {"file": <resolved path>, "doc": <document>} as JSON. rc 2 on any problem
# (every problem is listed on stderr first). The ONLY python entrypoint.
_config_py() {
  SECRETS_PROVIDERS_DIR="${SECRETS_PROVIDERS_DIR:-$_CONFIG_LIB_DIR/../providers}" \
  python3 - "$1" "$CONFIG_BASENAME" <<'PY'
import json, os, re, sys
try:
    import yaml
except ImportError:
    sys.exit("ERROR: PyYAML required (pip install pyyaml)")

start, basename = sys.argv[1], sys.argv[2]
providers_dir = os.environ["SECRETS_PROVIDERS_DIR"]


class StrictLoader(yaml.SafeLoader):
    """SafeLoader that rejects duplicate mapping keys (PyYAML keeps the last)."""

    def construct_mapping(self, node, deep=False):
        seen = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in seen:
                raise yaml.constructor.ConstructorError(
                    None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def load(path):
    """(doc, error) — error is a one-line reason."""
    try:
        with open(path) as fh:
            doc = yaml.load(fh, Loader=StrictLoader)
    except Exception as exc:  # noqa: BLE001 — every parse problem is fatal
        return None, f"{path}: cannot parse YAML: {exc}"
    doc = doc if doc is not None else {}
    if not isinstance(doc, dict):
        return None, f"{path}: top level must be a mapping"
    return doc, None


def resolve(start):
    """Follow one pointer hop. (path, doc, error)."""
    if os.path.isdir(start):
        start = os.path.join(start, basename)
    if not os.path.isfile(start):
        return None, None, (
            f"ERROR: no secrets config at {start} — this repo is not routed.\n"
            f"       Add {basename} at the repo root, or a pointer to the project's primary repo:\n"
            f"         extends: ../<primary-repo>/{basename}")
    doc, err = load(start)
    if err:
        return None, None, f"ERROR: {err}"
    ext = doc.get("extends")
    if ext is None:
        return start, doc, None
    if len(doc) != 1 or not isinstance(ext, str) or not ext:
        return None, None, f"ERROR: {start}: a pointer must contain only 'extends: <path>'"
    target = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(start)), ext))
    if os.path.isdir(target):
        target = os.path.join(target, basename)
    if not os.path.isfile(target):
        return None, None, f"ERROR: {start} points at {target}, which does not exist"
    doc, err = load(target)
    if err:
        return None, None, f"ERROR: {err}"
    if "extends" in doc:
        # One hop only: a pointer to a pointer is a configuration error.
        return None, None, f"ERROR: {target} is itself a pointer — pointers must reference a project config directly"
    return target, doc, None


path, doc, err = resolve(start)
if err:
    print(err, file=sys.stderr)
    sys.exit(2)

TOP_KEYS = {"project", "repos", "health", "hermes", "rotation", "routes"}
ROUTE_KEYS = {"repo", "kind", "dest", "env", "ref", "transform"}
KINDS = {"github", "render", "prefect", "dev", "hermes"}
TRANSFORM_PREFIXES = ("db=", "pgbouncer=", "asyncpg-internal=", "asyncpg-external=", "rehost=")
ENTRY_KEYS = {
    "ref", "provider", "mode", "owner_repo", "verify", "verify_command", "generate",
    "playbook", "sync_refs", "sync_repos", "config", "hook", "exclude_dests",
    "project", "disabled_reason", "sweep",
}
ENTRY_REQUIRED = ("ref", "provider", "mode", "owner_repo")
ENTRY_STRINGS = ("ref", "provider", "mode", "owner_repo", "verify", "verify_command",
                 "playbook", "hook", "project", "disabled_reason")
MODES = {"SELF_MINTED", "MANUAL", "DUAL_KEY", "IN_PLACE"}
GENERATE_FORMATS = {"hex", "base64"}
# Provider config: {provider: (required keys, optional keys)}. A provider
# whose required keys are missing is still valid: the entry is SYNC-only and
# provider_auto_ready is false. postgres config is owned by the rotator.
PROVIDER_CONFIG = {
    "resend": ({"key_name"}, {"permission", "auth_key_ref", "canary"}),
    "openai": ({"admin_key_ref", "project_id"}, {"sa_prefix"}),
    "aws_iam": ({"iam_user", "secret_ref"}, {"profile", "admin_key_id_ref", "admin_secret_ref"}),
}
OP_REF = re.compile(r"^op://[^/]+/[^/]+/[^/]+$")
bad = []


def is_str(v):
    return isinstance(v, str) and bool(v)


for key in sorted(set(doc) - TOP_KEYS):
    bad.append(f"unknown top-level key {key!r} (allowed: {', '.join(sorted(TOP_KEYS))})")
for key in ("project", "repos", "routes"):
    if key not in doc:
        bad.append(f"missing top-level '{key}'")
if "project" in doc and not is_str(doc["project"]):
    bad.append("'project' must be a non-empty string")

repos = doc.get("repos")
if repos is None:
    repos = []
elif not isinstance(repos, list) or not repos or not all(is_str(x) for x in repos):
    bad.append("'repos' must be a non-empty list of repo names")
    repos = []
elif len(set(repos)) != len(repos):
    bad.append("'repos' lists a repo twice")

health = doc.get("health")
if health is None:
    health = {}
elif not isinstance(health, dict):
    bad.append("'health' must be a mapping of dest -> url")
    health = {}
else:
    for dest, url in health.items():
        if not is_str(dest) or not is_str(url):
            bad.append(f"health[{dest!r}]: dest and url must be non-empty strings")

hermes = doc.get("hermes")
if hermes is not None:
    if not isinstance(hermes, dict) or set(hermes) != {"ssh"} or not is_str(hermes.get("ssh")):
        bad.append("'hermes' must be exactly {ssh: <user@host or ssh alias>}")

routes = doc.get("routes")
if routes is None:
    routes = []
elif not isinstance(routes, list):
    bad.append("'routes' must be a list")
    routes = []

seen = {}
valid_routes = []
for i, r in enumerate(routes, 1):
    if not isinstance(r, dict):
        bad.append(f"route {i}: not a mapping")
        continue
    for key in sorted(set(r) - ROUTE_KEYS):
        bad.append(f"route {i}: unknown key {key!r} (allowed: {', '.join(sorted(ROUTE_KEYS))})")
    missing = [k for k in ("repo", "kind", "dest", "env", "ref", "transform") if not r.get(k)]
    if missing:
        bad.append(f"route {i}: missing/empty {', '.join(missing)}")
        continue
    if not all(isinstance(r[k], str) for k in ROUTE_KEYS if k in r):
        bad.append(f"route {i}: every field must be a string")
        continue
    kind, dest, env, ref, tr = r["kind"], r["dest"], r["env"], r["ref"], r["transform"]
    if kind not in KINDS:
        bad.append(f"route {i}: unknown kind {kind!r}")
    if kind == "hermes":
        # hermes DEST is the absolute root-only credential file path on the box.
        if not dest.startswith("/"):
            bad.append(f"route {i}: hermes dest must be an absolute file path, got {dest!r}")
        if not isinstance(hermes, dict) or not hermes.get("ssh"):
            bad.append(f"route {i}: hermes routes need top-level hermes.ssh (the box's SSH destination)")
    if kind == "prefect" and dest not in ("staging", "prod"):
        bad.append(f"route {i}: prefect dest must be staging or prod, got {dest!r}")
    if r["repo"] not in repos:
        bad.append(f"route {i}: repo {r['repo']!r} is not listed in top-level 'repos'")
    if not (ref.startswith("literal:") or ref.startswith("op://")):
        bad.append(f"route {i}: REF must be literal:<value> or op://<vault>/<item>/<field>, got {ref!r}")
    elif ref.startswith("op://") and not OP_REF.match(ref):
        bad.append(f"route {i}: op:// REF needs vault/item/field, got {ref!r}")
    if tr not in ("self", "conn-id", "no-query") and not any(
            tr.startswith(p) and len(tr) > len(p) for p in TRANSFORM_PREFIXES):
        bad.append(f"route {i}: unknown transform {tr!r}")
    key = (kind, dest, env)
    if key in seen:
        bad.append(f"route {i}: duplicate route {key} first seen at route {seen[key]}")
    else:
        seen[key] = i
    valid_routes.append(r)

refs = {r["ref"] for r in valid_routes}
dests_by_ref = {}
for r in valid_routes:
    dests_by_ref.setdefault(r["ref"], set()).add(r["dest"])


def _sibling_doc(rel):
    """Another project's config named relative to this file, following one
    `extends:` pointer exactly as resolve() does. Returns (doc, error)."""
    target = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(path)), rel))
    if os.path.isdir(target):
        target = os.path.join(target, basename)
    if not os.path.isfile(target):
        return None, f"{target} does not exist"
    sib, err = load(target)
    if err:
        return None, err
    ext = sib.get("extends")
    if ext:
        target = os.path.normpath(os.path.join(os.path.dirname(target), ext))
        if not os.path.isfile(target):
            return None, f"{target} does not exist"
        sib, err = load(target)
        if err:
            return None, err
        if sib.get("extends"):
            return None, f"{target} is itself a pointer"
    return sib, None


rotation = doc.get("rotation")
if rotation is None:
    rotation = {}
elif not isinstance(rotation, dict):
    bad.append("'rotation' must be a mapping of id -> entry")
    rotation = {}

seen_refs = {}
for rid, entry in rotation.items():
    tag = f"rotation '{rid}'"
    if not isinstance(entry, dict):
        bad.append(f"{tag}: entry must be a mapping")
        continue
    for key in sorted(set(entry) - ENTRY_KEYS):
        bad.append(f"{tag}: unknown key {key!r} (allowed: {', '.join(sorted(ENTRY_KEYS))})")
    missing = [k for k in ENTRY_REQUIRED if not entry.get(k)]
    if missing:
        bad.append(f"{tag}: missing {', '.join(missing)}")
    for key in ENTRY_STRINGS:
        if key in entry and not isinstance(entry[key], str):
            bad.append(f"{tag}: {key} must be a string")
    # sweep: false excludes the entry from rotate-project sweeps (targeted
    # rotate-secret runs and --only still work; unlike disabled_reason, which
    # refuses everything).
    if "sweep" in entry and not isinstance(entry["sweep"], bool):
        bad.append(f"{tag}: sweep must be a boolean")
    ref = entry.get("ref")
    if is_str(ref):
        if not OP_REF.match(ref):
            bad.append(f"{tag}: ref must be op://<vault>/<item>/<field>, got {ref!r}")
        elif ref not in refs:
            bad.append(f"{tag}: ref {ref} has no route — it would rotate nothing")
        if ref in seen_refs:
            bad.append(f"{tag}: ref {ref} is already rotated by '{seen_refs[ref]}' — one entry per ref")
        else:
            seen_refs[ref] = rid
    provider = entry.get("provider")
    if is_str(provider):
        if not re.match(r"^[a-z][a-z0-9_]*$", provider) \
                or not os.path.isfile(os.path.join(providers_dir, provider + ".sh")):
            bad.append(f"{tag}: provider {provider!r} has no handler ({providers_dir}/{provider}.sh)")
    mode = entry.get("mode")
    if is_str(mode) and mode not in MODES:
        bad.append(f"{tag}: mode must be one of {', '.join(sorted(MODES))}, got {mode!r}")
    owner = entry.get("owner_repo")
    if is_str(owner) and owner not in repos:
        bad.append(f"{tag}: owner_repo {owner!r} is not listed in top-level 'repos'")
    if entry.get("hook") not in (None, "activate", "full"):
        bad.append(f"{tag}: hook must be 'activate' or 'full', got {entry['hook']!r}")

    gen = entry.get("generate")
    if gen is not None:
        if not isinstance(gen, dict):
            bad.append(f"{tag}: generate must be a mapping {{format, bytes}}")
        else:
            for key in sorted(set(gen) - {"format", "bytes"}):
                bad.append(f"{tag}: generate: unknown key {key!r}")
            if "format" in gen and gen["format"] not in GENERATE_FORMATS:
                bad.append(f"{tag}: generate.format must be hex or base64, got {gen['format']!r}")
            b = gen.get("bytes")
            if b is not None and (isinstance(b, bool) or not isinstance(b, int) or not 1 <= b <= 4096):
                bad.append(f"{tag}: generate.bytes must be an integer 1..4096, got {b!r}")

    sync_refs = entry.get("sync_refs")
    if sync_refs is not None:
        if not isinstance(sync_refs, list) or not all(is_str(x) for x in sync_refs):
            bad.append(f"{tag}: sync_refs must be a list of op:// refs")
            sync_refs = None
        else:
            for sr in sync_refs:
                if not OP_REF.match(sr):
                    bad.append(f"{tag}: sync_refs entry {sr!r} is not an op://vault/item/field ref")
                elif sr not in refs:
                    bad.append(f"{tag}: sync_refs entry {sr} has no route")
    fanout = set(sync_refs if sync_refs is not None else ([ref] if is_str(ref) else []))

    excl = entry.get("exclude_dests")
    if excl is not None:
        if not isinstance(excl, list) or not all(is_str(x) for x in excl):
            bad.append(f"{tag}: exclude_dests must be a list of dests")
        else:
            routed = set().union(*(dests_by_ref.get(x, set()) for x in fanout)) if fanout else set()
            for d in excl:
                if d not in routed:
                    bad.append(f"{tag}: exclude_dests names {d!r}, which routes none of the entry's refs")

    cfg = entry.get("config")
    if cfg is not None:
        if not isinstance(cfg, dict):
            bad.append(f"{tag}: config must be a mapping")
        elif provider in PROVIDER_CONFIG:
            required, optional = PROVIDER_CONFIG[provider]
            for key in sorted(set(cfg) - required - optional):
                bad.append(f"{tag}: config: unknown key {key!r} for provider {provider} "
                           f"(allowed: {', '.join(sorted(required | optional))})")
            for key, val in cfg.items():
                if key == "canary":
                    if not isinstance(val, dict) or set(val) != {"from", "to"} \
                            or not all(is_str(val.get(k)) for k in ("from", "to")):
                        bad.append(f"{tag}: config.canary must be {{from, to}} strings")
                elif not is_str(val):
                    bad.append(f"{tag}: config.{key} must be a non-empty string")
            for key in ("secret_ref", "admin_key_ref", "auth_key_ref", "admin_key_id_ref", "admin_secret_ref"):
                if is_str(cfg.get(key)) and not OP_REF.match(cfg[key]):
                    bad.append(f"{tag}: config.{key} must be an op://vault/item/field ref")
            if provider == "aws_iam" and is_str(cfg.get("secret_ref")) and cfg["secret_ref"] not in refs:
                bad.append(f"{tag}: config.secret_ref {cfg['secret_ref']} has no route")
            if provider == "aws_iam" and is_str(cfg.get("secret_ref")) and is_str(entry.get("ref")) \
                    and cfg["secret_ref"].rsplit("/", 1)[0] != entry["ref"].rsplit("/", 1)[0]:
                bad.append(f"{tag}: aws_iam config.secret_ref must be a field of the entry's own vault item (the pair is written as one edit)")
            if provider == "aws_iam" and is_str(cfg.get("secret_ref")) and sync_refs is not None \
                    and cfg["secret_ref"] not in sync_refs:
                bad.append(f"{tag}: aws_iam sync_refs must include config.secret_ref (the pair fans out together)")
        elif provider in ("self_minted", "manual"):
            bad.append(f"{tag}: provider {provider} takes no config")

    # sync_repos: this credential is consumed by ANOTHER project's routes too.
    sync_repos = entry.get("sync_repos")
    if sync_repos is None:
        continue
    if not isinstance(sync_repos, list) or not all(is_str(x) for x in sync_repos):
        bad.append(f"{tag}: sync_repos must be a list of non-empty strings")
        continue
    for rel in sync_repos:
        sib, err = _sibling_doc(rel)
        if err:
            bad.append(f"{tag}: sync_repos entry {rel!r}: {err}")
            continue
        if sib.get("project") == doc.get("project"):
            bad.append(f"{tag}: sync_repos entry {rel!r} is the same project "
                       f"({doc.get('project')!r}) — its routes are already covered")
            continue
        sib_refs = {r.get("ref") for r in (sib.get("routes") or []) if isinstance(r, dict)}
        if not (fanout & sib_refs):
            bad.append(f"{tag}: sync_repos entry {rel!r} routes none of "
                       f"{sorted(fanout)} — remove it or fix the ref")

if bad:
    for b in bad:
        print(f"{path}: {b}", file=sys.stderr)
    sys.exit(2)

json.dump({"file": path, "doc": doc}, sys.stdout, separators=(",", ":"))
PY
}

# _config_cache — parse+validate once per process into _CONFIG_FILE /
# _CONFIG_DOC / _CONFIG_ROWS (rc 2 on a missing or invalid config).
_config_cache() {
  [[ -n "${_CONFIG_ROWS+x}" ]] && return 0
  local start="${_SECRETS_CONFIG:-}" out
  [[ -n "$start" ]] || { echo "ERROR: _SECRETS_CONFIG is not set" >&2; return 2; }
  out="$(_config_py "$start")" || return 2
  _CONFIG_FILE="$(jq -r '.file' <<< "$out")"
  _CONFIG_DOC="$(jq -c '.doc' <<< "$out")"
  _CONFIG_ROWS="$(jq -r '.routes[] | [.kind, .dest, .env, .ref, .transform, .repo] | @tsv' <<< "$_CONFIG_DOC")"
  export _CONFIG_FILE
}

# config_path — the resolved config file (after one `extends:` hop).
config_path() {
  _config_cache || return $?
  printf '%s\n' "$_CONFIG_FILE"
}

# config_validate — verify the whole config. Every problem goes to stderr.
config_validate() {
  _config_cache
}

# config_rows KIND [DEST] [EXACT_REF] [REF_PREFIX] — print matching routes as
# KIND<TAB>DEST<TAB>ENVNAME<TAB>REF<TAB>TRANSFORM (the shape the writers consume;
# the route's repo is dropped here because a push targets DEST, not a checkout).
# DEST filters by equality when nonempty. EXACT_REF filters by EQUALITY (never
# substring) when nonempty — this is what makes `--changed` tier-safe.
# REF_PREFIX (op://VAULT/ITEM/, the field-less --changed form) filters by
# leading-prefix match when nonempty.
config_rows() {
  local kind="$1" dest="${2:-}" ref="${3:-}" prefix="${4:-}"
  _config_cache || return $?
  awk -F'\t' -v k="$kind" -v d="$dest" -v r="$ref" -v p="$prefix" '
    (k == "" || $1 == k) && (d == "" || $2 == d) && (r == "" || $4 == r) && (p == "" || index($4, p) == 1) {
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

# config_sync_repos REL... — resolve a rotation entry's sync_repos values (paths
# relative to THIS project's config file, same convention as `extends:`) to
# absolute repo roots, one per line. Validation already proved they exist and
# route the entry's refs; this is the path arithmetic the fan-out needs.
config_sync_repos() {
  _config_cache || return $?
  local base rel abs
  base="$(cd "$(dirname "$_CONFIG_FILE")" && pwd)" || return 1
  for rel in "$@"; do
    [[ -n "$rel" ]] || continue
    abs="$(cd "$base/$rel" 2>/dev/null && pwd)" || {
      # A pointer file was named directly rather than its directory.
      abs="$(cd "$(dirname "$base/$rel")" 2>/dev/null && pwd)" || return 1
    }
    printf '%s\n' "$abs"
  done
}

# config_repo_path NAME — absolute path of a repo named in `repos:` (repos are
# sibling directories of the primary repo). rc 1 when the directory is missing.
config_repo_path() {
  _config_cache || return $?
  local base
  base="$(cd "$(dirname "$_CONFIG_FILE")/.." && pwd)" || return 1
  [[ -n "$1" && -d "$base/$1" ]] || { echo "ERROR: repo '$1' (repos:) not found at $base/$1" >&2; return 1; }
  printf '%s\n' "$base/$1"
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

# config_hermes_ssh — the Hermes box's SSH destination (user@host or an ssh
# alias). Empty when the project has no hermes section.
config_hermes_ssh() {
  _config_cache || return $?
  jq -r '.hermes.ssh // empty' <<< "$_CONFIG_DOC"
}

# config_registry — synthesize the registry JSON shape from the project
# config, with each rotation entry's consumers[] DERIVED from the routes that
# share its ref (render + github kinds — the activation/fan-out surface the
# providers consume) and a routes[] array carrying every kind for display.
# Content-addressed: written once per distinct config to
# ${SECRETS_REGISTRY_DIR:-~/.cache/agent-workflows/registry}/<sha256>.json
# (dir 0700, file 0600); reruns reuse it, files untouched for 7 days are
# pruned, so nothing accumulates per run. Prints the path.
config_registry() {
  _config_cache || return $?
  if [[ -z "${_CONFIG_REGISTRY_FILE:-}" ]]; then
    local dir hash tmp
    dir="${SECRETS_REGISTRY_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/agent-workflows/registry}"
    mkdir -p "$dir" && chmod 700 "$dir" || return 1
    hash="$(printf '%s' "$_CONFIG_DOC" | shasum -a 256 | cut -c1-32)"
    _CONFIG_REGISTRY_FILE="$dir/$hash.json"
    if [[ ! -s "$_CONFIG_REGISTRY_FILE" ]]; then
      tmp="$(mktemp "$dir/.registry.XXXXXX")" || return 1
      chmod 600 "$tmp"
      jq '
        . as $doc
        | {
            schema_version: 1,
            health_urls: ($doc.health // {}),
            secrets: [
              ($doc.rotation // {}) | to_entries[] | .key as $id | .value as $e
              | ($doc.routes | map(select(.ref as $rr
                  | ($rr == $e.ref) or (($e.sync_refs // []) | index($rr) != null)))) as $matched
              | $e + {
                  id: $id,
                  # An entry may pin a different project scope (shared-instance
                  # DB roles); default is the config project.
                  project: ($e.project // $doc.project),
                  # Activation/fan-out surface: render+github routes, minus any
                  # dest the entry explicitly excludes (exclude_dests declares
                  # "this service consumes the value but must never be an
                  # activation target" — e.g. the Prefect server retains the
                  # canonical migration-capable DB credential).
                  consumers: [ $matched[] | select(.kind == "render" or .kind == "github")
                               | select(.dest as $d | (($e.exclude_dests // []) | index($d)) | not)
                               | {repo: .repo, dest: .dest, env: .env} ],
                  routes: $matched
                }
            ]
          }' <<< "$_CONFIG_DOC" > "$tmp" || { rm -f "$tmp"; return 1; }
      mv -f "$tmp" "$_CONFIG_REGISTRY_FILE"
      find "$dir" -name '*.json' -mtime +7 -delete 2>/dev/null || true
    fi
    export _CONFIG_REGISTRY_FILE
  fi
  printf '%s\n' "$_CONFIG_REGISTRY_FILE"
}

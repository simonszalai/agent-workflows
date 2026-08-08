# shellcheck shell=bash
# render-api.sh — Render API helpers. Used only by writers/render.
# Depends on read.sh (op_read_ref) for the API key.
#
# The API key and every value are held in shell vars and passed via curl config
# on a file descriptor / stdin — never argv. Every upsert refuses an empty
# value: a failed op read must never blank a live env var (2026-07-07: a
# timed-out read piped an empty body into a push and blanked DATABASE_URL_PROD).
#
# API key source, first match wins — NO fallback to another account (silent-403
# incident):
#   1. RENDER_API_KEY already in the process env at source time -> used as-is
#      (no op read). Snapshotted ONCE, because writers export RENDER_API_KEY
#      per-service mid-run and the override check must never match those.
#   2. SECRETS_RENDER_KEY_REF — the target repo's project render.api_key_ref,
#      wired by bin/sync-secrets from bin/project-context. The manifest lives in
#      the consuming repo, so project resolution routes autodev services to the
#      autodev key without any hardcoded service table here.
_RENDER_KEY_ENV_OVERRIDE="${RENDER_API_KEY:-}"

render_key_ref_for() { # service_id -> key source for that service's API key
  if [[ -n "$_RENDER_KEY_ENV_OVERRIDE" ]]; then
    echo "env:RENDER_API_KEY"
  elif [[ -n "${SECRETS_RENDER_KEY_REF:-}" ]]; then
    echo "$SECRETS_RENDER_KEY_REF"
  else
    echo "ERROR: no Render API key ref (SECRETS_RENDER_KEY_REF unset — run via sync-secrets)" >&2
    return 3
  fi
}

# Resolve a key source from render_key_ref_for: the env sentinel reads the
# already-exported key; anything else goes through op (values stay off argv).
render_key_resolve() { # key_source -> key value on stdout
  local kr="$1"
  if [[ "$kr" == "env:RENDER_API_KEY" ]]; then
    printf %s "$_RENDER_KEY_ENV_OVERRIDE"
  else
    op_read_ref "$kr"
  fi
}

render_curl() { # method path [json-body-on-stdin]
  local method="$1" path="$2"
  local key="${RENDER_API_KEY:-}"
  [[ -n "$key" ]] || { echo "ERROR: RENDER_API_KEY not set (caller must resolve via render_key_ref_for)" >&2; return 3; }
  # 429 means the request was NOT executed, so retrying a mutation is safe.
  local body
  body="$(cat)"
  printf '%s' "$body" | render_retry_429 --silent --show-error --fail-with-body \
    --request "$method" \
    --url "https://api.render.com/v1${path}" \
    --header "Accept: application/json" \
    --header "Content-Type: application/json" \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$key") \
    --data-binary @-
  local rc=$?
  body=""
  return "$rc"
}

# Upsert ONE env var on a service from a VALUE ON STDIN. Refuses empty, and
# returns the API call's real exit code (a failed PUT — e.g. 403 from a
# wrong-account key — must NOT report success).
render_upsert_env_value() { # service_id key  (value piped on stdin)
  local sid="$1" key="$2" val rc
  val="$(cat)"
  [[ -n "$val" ]] || { echo "  render[$sid] $key: EMPTY DERIVED VALUE — not written" >&2; return 1; }
  printf %s "$val" \
    | jq -Rs '{value: .}' \
    | render_curl PUT "/services/${sid}/env-vars/${key}" >/dev/null
  rc=$?
  val=""
  return "$rc"
}

# Rate-limit aware curl: on HTTP 429 back off and retry (Render's API limits
# are per-minute; a rotation sweep legitimately bursts). Bounded, then fails.
render_retry_429() { # curl args...
  local attempt=0 max="${RENDER_429_RETRIES:-5}" out rc
  while :; do
    out="$(curl "$@" 2>&1)"; rc=$?
    if [[ "$rc" -eq 22 && "$out" == *429* && "$attempt" -lt "$max" ]]; then
      attempt=$((attempt + 1))
      echo "  render API rate-limited (429) — backing off $((attempt * 15))s (retry $attempt/$max)" >&2
      sleep $((attempt * 15))
      continue
    fi
    [[ -n "$out" ]] && { if [[ "$rc" -eq 0 ]]; then printf '%s' "$out"; else printf '%s\n' "$out" >&2; fi; }
    return "$rc"
  done
}

render_get() { # path (GET, no request body) — read-only helpers
  local path="$1"
  local key="${RENDER_API_KEY:-}"
  [[ -n "$key" ]] || { echo "ERROR: RENDER_API_KEY not set (caller must resolve via render_key_ref_for)" >&2; return 3; }
  render_retry_429 --silent --show-error --fail-with-body \
    --request GET \
    --url "https://api.render.com/v1${path}" \
    --header "Accept: application/json" \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$key")
}

render_trigger_deploy() { # service_id
  local sid="$1"
  printf '{"clearCache":"do_not_clear"}' \
    | render_curl POST "/services/${sid}/deploys" >/dev/null \
    && echo "  render[$sid] deploy triggered"
}

render_get_env_value() { # service_id key -> value on stdout (CALLER MUST PIPE)
  local sid="$1" name="$2"
  render_get "/services/${sid}/env-vars/${name}" \
    | jq -re '.value | select(type == "string" and length > 0)'
}

# Exact-deploy proof: the trigger must return HTTP 201 with a request-correlated
# deploy id. A bodyless 202 is rejected — waiting on "some deploy" can attest a
# different change than the one this rotation staged.
render_trigger_deploy_id() { # service_id -> deploy id on stdout
  local sid="$1" body_file status body id
  local key="${RENDER_API_KEY:-}"
  [[ -n "$key" ]] || { echo "ERROR: RENDER_API_KEY not set (caller must resolve via render_key_ref_for)" >&2; return 3; }
  body_file="$(mktemp "${TMPDIR:-/tmp}/render-deploy.XXXXXX")" || return $?
  chmod 600 "$body_file"

  status="$(curl --silent --show-error \
    --request POST \
    --url "https://api.render.com/v1/services/${sid}/deploys" \
    --header "Accept: application/json" \
    --header "Content-Type: application/json" \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$key") \
    --data-binary '{"deployMode":"deploy_only"}' \
    --output "$body_file" \
    --write-out '%{http_code}')" || {
      rm -f "$body_file"
      return 1
    }
  body="$(cat "$body_file")"
  rm -f "$body_file"

  case "$status" in
    201)
      id="$(printf '%s' "$body" | jq -er '.id | select(type == "string" and length > 0)')" || return 1
      printf %s "$id"
      ;;
    202)
      echo "ERROR: render[$sid] accepted a deploy without a request-correlated id; exact deploy is unprovable" >&2
      return 1
      ;;
    *)
      echo "ERROR: render[$sid] deploy trigger returned HTTP $status" >&2
      return 1
      ;;
  esac
}

render_wait_deploy_live() { # service_id deploy_id — live=0, terminal/unknown=1 (fail closed)
  local sid="$1" deploy_id="$2" status deadline
  deadline=$(( $(date +%s) + ${RENDER_DEPLOY_TIMEOUT_SECONDS:-1800} ))
  while [[ $(date +%s) -lt $deadline ]]; do
    status="$(render_get "/services/${sid}/deploys/${deploy_id}" | jq -er '.status')" || return $?
    case "$status" in
      live) return 0 ;;
      created|queued|build_in_progress|update_in_progress|pre_deploy_in_progress) ;;
      deactivated|build_failed|update_failed|canceled|pre_deploy_failed)
        echo "ERROR: render[$sid] deploy $deploy_id reached terminal status $status" >&2
        return 1
        ;;
      *)
        echo "ERROR: render[$sid] deploy $deploy_id returned unknown status $status" >&2
        return 1
        ;;
    esac
    sleep "${RENDER_POLL_SECONDS:-10}"
  done
  echo "ERROR: render[$sid] deploy $deploy_id did not become live before timeout" >&2
  return 1
}

# shellcheck shell=bash
# render-api.sh — Render API helpers. Used by writers/render, rotate-project and
# deploy-wait.sh. Depends on read.sh (op_read_ref, retry_transient) for the API
# key and retries.
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

# One authenticated request. Auth config and the request body (RENDER_RETRY_BODY,
# env) are rebuilt per attempt: a piped stdin is a one-shot fd. The HTTP status
# is read from --write-out; without one (a fake curl) curl's rc is authoritative.
# HTTP 429/5xx -> rc 75 (EX_TEMPFAIL, retried by retry_transient); other
# HTTP >= 400 -> rc 22 with "status + first body line" on stderr, never the full
# body. The response body is written to $RENDER_BODY_FILE when set, else stdout.
_render_curl_once() { # curl args (WITHOUT auth config / body)...
  local out rc=0 status="" body
  out="$(printf '%s' "${RENDER_RETRY_BODY:-}" | curl "$@" --write-out '\n%{http_code}' \
    --config <(printf 'header = "Authorization: Bearer %s"\n' "$RENDER_API_KEY"))" || rc=$?
  status="${out##*$'\n'}"
  if [[ "$status" =~ ^[0-9]{3}$ ]]; then body="${out%$'\n'*}"; else body="$out"; status=""; fi
  if [[ "$rc" -ne 0 ]]; then
    return "$rc"
  fi
  case "$status" in
    429|5[0-9][0-9]) echo "render API HTTP $status: $(printf '%s' "$body" | head -n1)" >&2; return 75 ;;
    4[0-9][0-9]) echo "render API HTTP $status: $(printf '%s' "$body" | head -n1)" >&2; return 22 ;;
  esac
  if [[ -n "${RENDER_BODY_FILE:-}" ]]; then printf '%s' "$body" > "$RENDER_BODY_FILE"; else printf '%s' "$body"; fi
}

render_curl_retry() { # curl args (WITHOUT auth config / body)...
  [[ -n "${RENDER_API_KEY:-}" ]] || { echo "ERROR: RENDER_API_KEY not set (caller must resolve via render_key_ref_for)" >&2; return 3; }
  RETRY_STDIN="" retry_transient _render_curl_once --silent --show-error "$@"
}

render_curl() { # method path [json-body-on-stdin]
  local method="$1" path="$2" body rc=0
  body="$(cat)"
  RENDER_RETRY_BODY="$body" render_curl_retry \
    --request "$method" \
    --url "https://api.render.com/v1${path}" \
    --header "Accept: application/json" \
    --header "Content-Type: application/json" \
    --data-binary @- || rc=$?
  body=""
  return "$rc"
}

render_get() { # path (GET, no request body) — read-only helpers
  local path="$1"
  RENDER_RETRY_BODY="" render_curl_retry \
    --request GET \
    --url "https://api.render.com/v1${path}" \
    --header "Accept: application/json"
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

render_get_env_value() { # service_id key -> value on stdout (CALLER MUST PIPE)
  local sid="$1" name="$2"
  render_get "/services/${sid}/env-vars/${name}" \
    | jq -re '.value | select(type == "string" and length > 0)'
}

# Latest-deploy status is idle (or there is no deploy). In-flight deploys make
# POST /deploys return HTTP 202 with no id; waiting on "some deploy" can attest
# a different change than the one this rotation staged.
render_wait_service_idle() { # service_id
  local sid="$1" status deadline
  deadline=$(( $(date +%s) + ${RENDER_DEPLOY_TIMEOUT_SECONDS:-1800} ))
  while [[ $(date +%s) -lt $deadline ]]; do
    status="$(render_get "/services/${sid}/deploys?limit=1" | jq -r '.[0].deploy.status // .[0].status // empty')" || return 1
    case "$status" in
      ""|live|deactivated|build_failed|update_failed|canceled|pre_deploy_failed) return 0 ;;
      created|queued|build_in_progress|update_in_progress|pre_deploy_in_progress)
        echo "  render[$sid] waiting for in-flight deploy ($status) to finish" >&2
        ;;
      *)
        echo "ERROR: render[$sid] latest deploy returned unknown status $status" >&2
        return 1
        ;;
    esac
    sleep "${RENDER_POLL_SECONDS:-10}"
  done
  echo "ERROR: render[$sid] still had an in-flight deploy before timeout" >&2
  return 1
}

# Exact-deploy proof: the trigger must answer with a request-correlated deploy
# id (HTTP 201). A bodyless 202 (deploy already in flight) is retried only after
# the service is idle again — never by waiting on an uncorrelated deploy.
# Env-only changes use deployMode deploy_only (no rebuild).
render_trigger_deploy_id() { # service_id -> deploy id on stdout
  local sid="$1" body id attempt=0
  local max="${RENDER_DEPLOY_TRIGGER_RETRIES:-6}"
  [[ -n "${RENDER_API_KEY:-}" ]] || { echo "ERROR: RENDER_API_KEY not set (caller must resolve via render_key_ref_for)" >&2; return 3; }
  while [[ "$attempt" -lt "$max" ]]; do
    attempt=$((attempt + 1))
    render_wait_service_idle "$sid" || return 1
    body="$(printf '{"deployMode":"deploy_only"}' | render_curl POST "/services/${sid}/deploys")" || return 1
    id="$(printf '%s' "$body" | jq -r 'if type == "object" then (.id // empty) else empty end' 2>/dev/null)"
    if [[ -n "$id" ]]; then
      printf %s "$id"
      return 0
    fi
    echo "  render[$sid] deploy POST returned no id (HTTP 202, deploy in flight); waiting for idle and retrying ($attempt/$max)" >&2
  done
  echo "ERROR: render[$sid] accepted a deploy without a request-correlated id; exact deploy is unprovable" >&2
  return 1
}

# Trigger + announce. Records `dest<TAB>deployId` to $SYNC_DEPLOYS_FILE when set
# so orchestrators can wait on exactly this deploy.
render_trigger_deploy() { # service_id
  local sid="$1" id
  id="$(render_trigger_deploy_id "$sid")" || return 1
  [[ -z "${SYNC_DEPLOYS_FILE:-}" ]] || printf '%s\t%s\n' "$sid" "$id" >> "$SYNC_DEPLOYS_FILE"
  echo "  render[$sid] deploy triggered ($id)"
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

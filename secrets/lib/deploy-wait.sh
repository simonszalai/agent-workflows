# shellcheck shell=bash
# deploy-wait.sh — deploy-liveness and health proof shared by rotate-secret and
# rotate-project. Finalize (predecessor retirement) never runs until the deploys
# that carry the new value are live and the registered health URLs pass.
#
# Requires read.sh + render-api.sh sourced first. Health URLs come from the
# registry file in SECRET_ROTATION_CONFIG (health_urls).
#
#   render_key_once [repo]          resolve the project Render key ONCE, export RENDER_API_KEY
#   deploy_wait_live DEST DEPLOY_ID poll /deploys/<id> until live. A recorded
#                                   id that is deactivated is proven if a later
#                                   deploy of the same service is live (or we
#                                   wait on that later deploy if it is still
#                                   rolling). Other terminal statuses fail.
#   deploy_wait_all FILE            wait every `dest<TAB>deployId` row of FILE concurrently
#   health_gate ENTRY_JSON          probe the health URL of every consumer dest (fail closed)

_DEPLOY_WAIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

render_key_once() { # [repo] — no-op once RENDER_API_KEY is exported
  [[ -n "${RENDER_API_KEY:-}" ]] && return 0
  local repo="${1:-}" ctx
  if [[ -z "${SECRETS_RENDER_KEY_REF:-}" ]]; then
    [[ -n "$repo" ]] || { echo "ERROR: no Render API key ref (SECRETS_RENDER_KEY_REF unset and no repo to resolve it from)" >&2; return 1; }
    ctx="$("$_DEPLOY_WAIT_DIR/../../bin/project-context" --cwd "$repo")" \
      || { echo "ERROR: project context resolution failed for $repo" >&2; return 1; }
    SECRETS_SA_TOKEN_ENV="$(printf '%s' "$ctx" | jq -er '.service_account.token_env')" || return 1
    SECRETS_SA_KEYCHAIN_ITEM="$(printf '%s' "$ctx" | jq -r '.service_account.keychain_item // ""')"
    SECRETS_RENDER_KEY_REF="$(printf '%s' "$ctx" | jq -r '.tools.render.api_key_ref // ""')"
    export SECRETS_SA_TOKEN_ENV SECRETS_SA_KEYCHAIN_ITEM SECRETS_RENDER_KEY_REF
    [[ -n "$SECRETS_RENDER_KEY_REF" ]] || { echo "ERROR: no Render API key ref in project context for $repo" >&2; return 1; }
  fi
  RENDER_API_KEY="$(render_key_resolve "$SECRETS_RENDER_KEY_REF")" || { echo "ERROR: could not resolve the Render API key" >&2; return 1; }
  [[ -n "$RENDER_API_KEY" ]] || { echo "ERROR: resolved an empty Render API key" >&2; return 1; }
  export RENDER_API_KEY
}

deploy_wait_live() { # dest deployId
  local dest="$1" id="$2" t0=$SECONDS deadline status latest latest_id latest_st
  [[ -n "$dest" && -n "$id" ]] || { echo "ERROR: deploy_wait_live needs dest and deploy id" >&2; return 2; }
  deadline=$(( $(date +%s) + ${RENDER_DEPLOY_TIMEOUT_SECONDS:-1800} ))
  while [[ $(date +%s) -lt $deadline ]]; do
    status="$(render_get "/services/${dest}/deploys/${id}" | jq -er '.status')" || return 1
    case "$status" in
      live)
        echo "  render[$dest] deploy $id live ($((SECONDS - t0))s)"
        return 0 ;;
      created|queued|build_in_progress|update_in_progress|pre_deploy_in_progress) ;;
      deactivated)
        # A later deploy of the same service replaced this one. Env PUTs persist,
        # so a later live deploy carries the new value. Exact-id wait would
        # fail an otherwise successful batched sweep (2026-08-22).
        latest="$(render_get "/services/${dest}/deploys?limit=1")" || return 1
        latest_id="$(jq -r '.[0].deploy.id // .[0].id // empty' <<<"$latest")"
        latest_st="$(jq -r '.[0].deploy.status // .[0].status // empty' <<<"$latest")"
        if [[ "$latest_st" == "live" && -n "$latest_id" ]]; then
          echo "  render[$dest] deploy $id deactivated; later $latest_id is live ($((SECONDS - t0))s)"
          return 0
        fi
        case "$latest_st" in
          created|queued|build_in_progress|update_in_progress|pre_deploy_in_progress)
            [[ -n "$latest_id" ]] || {
              echo "ERROR: render[$dest] deploy $id deactivated and no later deploy id" >&2
              return 1
            }
            echo "  render[$dest] deploy $id deactivated; waiting for later $latest_id ($latest_st)"
            id="$latest_id"
            ;;
          *)
            echo "ERROR: render[$dest] deploy $id deactivated and later deploy ${latest_id:-?} ended ${latest_st:-empty}" >&2
            return 1
            ;;
        esac
        ;;
      build_failed|update_failed|canceled|pre_deploy_failed)
        echo "ERROR: render[$dest] deploy $id reached terminal status $status" >&2
        return 1 ;;
      *)
        echo "ERROR: render[$dest] deploy $id returned unknown status $status" >&2
        return 1 ;;
    esac
    sleep "${RENDER_POLL_SECONDS:-10}"
  done
  echo "ERROR: render[$dest] deploy $id did not become live before timeout" >&2
  return 1
}

deploy_wait_all() { # file of dest<TAB>deployId rows -> 0 only when every deploy is live
  local file="$1" dest id pid ok=1
  local pids=()
  [[ -s "$file" ]] || return 0
  while IFS=$'\t' read -r dest id; do
    [[ -n "$dest" && -n "$id" ]] || continue
    deploy_wait_live "$dest" "$id" &
    pids+=($!)
  done < <(sort -u "$file")
  for pid in "${pids[@]-}"; do
    [[ -n "$pid" ]] || continue
    wait "$pid" || ok=0
  done
  [[ "$ok" -eq 1 ]]
}

health_gate() { # entry json -> verify every consumer dest registered in health_urls
  local entry="$1" registry="${SECRET_ROTATION_CONFIG:?SECRET_ROTATION_CONFIG is required}" dest url body ok=1
  while IFS= read -r dest; do
    [[ -n "$dest" ]] || continue
    url="$(jq -r --arg d "$dest" '.health_urls[$d] // empty' "$registry")"
    [[ -n "$url" && "$url" != "deploy-only" ]] || continue
    if body="$(curl -sf --max-time 30 "$url")"; then
      if jq -e 'has("databaseRoleSafe")' <<< "$body" >/dev/null 2>&1 \
         && ! jq -e '.status == "ok" and .databaseRoleSafe == true' <<< "$body" >/dev/null; then
        echo "  HEALTH FAIL $dest ($url): $body" >&2; ok=0
      else
        echo "  health ok: $dest"
      fi
    else
      echo "  HEALTH FAIL $dest ($url): unreachable/non-200" >&2; ok=0
    fi
  done < <(jq -r '.consumers[]?.dest' <<< "$entry" | sort -u)
  [[ "$ok" -eq 1 ]]
}

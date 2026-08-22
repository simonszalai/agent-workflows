# shellcheck shell=bash
# deploy-wait.sh — deploy-liveness and health proof shared by rotate-secret and
# rotate-project. Finalize (predecessor retirement) never runs until the deploys
# that carry the new value are live and the registered health URLs pass.
#
# Requires read.sh + render-api.sh sourced first. Health URLs come from the
# registry file in SECRET_ROTATION_CONFIG (health_urls).
#
#   render_key_once [repo]          resolve the project Render key ONCE, export RENDER_API_KEY
#   deploy_wait_live DEST DEPLOY_ID poll /deploys/<id> until live (RENDER_DEPLOY_TIMEOUT_SECONDS)
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
  local dest="$1" id="$2" t0=$SECONDS
  [[ -n "$dest" && -n "$id" ]] || { echo "ERROR: deploy_wait_live needs dest and deploy id" >&2; return 2; }
  render_wait_deploy_live "$dest" "$id" || return 1
  echo "  render[$dest] deploy $id live ($((SECONDS - t0))s)"
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

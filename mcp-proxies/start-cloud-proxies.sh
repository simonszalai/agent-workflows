#!/usr/bin/env bash
# Start the same two loopback MCP endpoints inside one Conductor cloud workspace.
# The repository's exact Git origin selects one project profile. Only that project's
# restricted AutoDEV bearer is resolved, once, before the long-lived Node process starts.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROXY="${ROOT}/mcp-proxies/mcp-proxy.mjs"
WAF_ENCODER="${ROOT}/mcp-proxies/waf-encode.mjs"
VERIFIER="${ROOT}/mcp-proxies/verify-autodev-routes.mjs"
PROJECT_CONTEXT="${ROOT}/bin/project-context"
REPO_DIR="${MCP_PROXY_PROJECT_CWD:-$PWD}"
AUTODEV_PORT=8792
CONTEXT7_PORT=8793
OP_VERSION=2.30.0
LOG_DIR="${HOME}/.cache/mcp-proxies"
mkdir -p "$LOG_DIR"

log() { echo "[cloud-mcp] $*"; }
listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

is_cloud() {
  [ "${CONDUCTOR_IS_LOCAL:-1}" = "0" ] ||
    [ -n "${CONDUCTOR_BASE_DIR:-}" ] ||
    [ "${CLAUDE_CODE_REMOTE:-}" = "true" ] ||
    [ "${MCP_PROXY_CLOUD_TEST:-}" = "1" ]
}

load_profile() {
  local profile
  profile="$($PROJECT_CONTEXT --cwd "$REPO_DIR" --tool autodev_memory)"
  IFS=$'\t' read -r PROJECT ROUTE TOKEN_ENV TOKEN_REF < <(
    PROFILE="$profile" python3 - <<'PY'
import json, os
profile = json.loads(os.environ["PROFILE"])
memory = profile["tools"]["autodev_memory"]
print(profile["project"], memory["route"], profile["service_account"]["token_env"], memory["token_ref"], sep="\t")
PY
  )
  [ -n "$PROJECT" ] && [ -n "$ROUTE" ] && [ -n "$TOKEN_ENV" ] && [ -n "$TOKEN_REF" ]
}

op_usable() {
  local version
  version="$(op --version 2>/dev/null)" || return 1
  case "$version" in [0-9]*) return 0 ;; *) return 1 ;; esac
}

ensure_op() {
  op_usable && return 0
  log "installing 1Password CLI v${OP_VERSION}"
  local arch archive tmp
  case "$(uname -m)" in aarch64|arm64) arch=arm64 ;; *) arch=amd64 ;; esac
  archive="op_linux_${arch}_v${OP_VERSION}.zip"
  tmp="$(mktemp -d)"
  curl -sSfLo "${tmp}/op.zip" "https://cache.agilebits.com/dist/1P/op2/pkg/v${OP_VERSION}/${archive}"
  unzip -oq "${tmp}/op.zip" -d "$tmp"
  mkdir -p "${HOME}/.local/bin"
  install -m 0755 "${tmp}/op" "${HOME}/.local/bin/op"
  rm -rf "$tmp"
  export PATH="${HOME}/.local/bin:${PATH}"
  hash -r 2>/dev/null || true
  op_usable
}

verify_autodev() {
  node "$VERIFIER" --route "/${ROUTE}" "${PROJECT//-/_}" "$AUTODEV_PORT"
}

stop_autodev() {
  pkill -f "mcp-proxy.mjs autodev-memory-cloud-${PROJECT}" 2>/dev/null || true
}

start_autodev() {
  local service_token restricted_token
  service_token="$(printenv "$TOKEN_ENV" 2>/dev/null || true)"
  [ -n "$service_token" ] || { log "ERROR: ${TOKEN_ENV} is not set"; return 1; }
  restricted_token="$(OP_SERVICE_ACCOUNT_TOKEN="$service_token" op read --no-newline "$TOKEN_REF" 2>/dev/null || true)"
  service_token=""
  [ -n "$restricted_token" ] || { log "ERROR: restricted AutoDEV credential is unreadable for ${PROJECT}"; return 1; }

  (
    set +x
    export AUTODEV_MEMORY_API_TOKEN="$restricted_token"
    exec env -u "$TOKEN_ENV" -u OP_SERVICE_ACCOUNT_TOKEN -u OP_CONNECT_TOKEN \
      MCP_PROXY_PORT="$AUTODEV_PORT" \
      MCP_PROXY_UPSTREAM="https://autodev-memory.onrender.com" \
      MCP_PROXY_PREFIX="/${ROUTE}" \
      MCP_PROXY_AUTH_ENV=AUTODEV_MEMORY_API_TOKEN \
      MCP_PROXY_BODY_TRANSFORM="$WAF_ENCODER" \
      node "$PROXY" "autodev-memory-cloud-${PROJECT}"
  ) >"${LOG_DIR}/autodev-memory.log" 2>&1 </dev/null &
  restricted_token=""

  local attempt
  for attempt in $(seq 1 20); do
    listening "$AUTODEV_PORT" && break
    sleep 1
  done
  listening "$AUTODEV_PORT" || { log "ERROR: AutoDEV proxy did not bind :${AUTODEV_PORT}"; return 1; }
  verify_autodev || { stop_autodev; log "ERROR: AutoDEV route identity canary failed"; return 1; }
  log "autodev-memory: /${ROUTE} pinned to ${PROJECT//-/_}"
}

stop_context7() {
  pkill -f "mcp-proxy.mjs context7-cloud" 2>/dev/null || true
}

start_context7() {
  # Context7 documents unauthenticated MCP access with lower rate limits. If the cloud
  # environment already supplies CONTEXT7_API_KEY, the proxy injects it; otherwise it
  # forwards no Authorization header and remains secret-free.
  (
    set +x
    export CONTEXT7_API_KEY="${CONTEXT7_API_KEY:-}"
    exec env -u "$TOKEN_ENV" -u OP_SERVICE_ACCOUNT_TOKEN -u OP_CONNECT_TOKEN \
      MCP_PROXY_PORT="$CONTEXT7_PORT" \
      MCP_PROXY_UPSTREAM="https://mcp.context7.com/mcp" \
      MCP_PROXY_AUTH_ENV=CONTEXT7_API_KEY MCP_PROXY_AUTH_OPTIONAL=1 \
      node "$PROXY" context7-cloud
  ) >"${LOG_DIR}/context7.log" 2>&1 </dev/null &
  local attempt
  for attempt in $(seq 1 20); do
    listening "$CONTEXT7_PORT" && { log "context7: ready"; return 0; }
    sleep 1
  done
  log "ERROR: Context7 proxy did not bind :${CONTEXT7_PORT}"
  return 1
}

approve_clients() {
  local settings="${REPO_DIR}/.claude/settings.local.json" claude_config="${HOME}/.claude.json"
  mkdir -p "${REPO_DIR}/.claude"
  SETTINGS="$settings" CONFIG="$claude_config" REPO="$REPO_DIR" python3 - <<'PY'
import json, os, pathlib
settings = pathlib.Path(os.environ["SETTINGS"])
config = pathlib.Path(os.environ["CONFIG"])
repo = os.environ["REPO"]
def load(path):
    try: return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError): return {}
approved = {"autodev-memory", "context7"}
s = load(settings)
s["enabledMcpjsonServers"] = sorted(set(s.get("enabledMcpjsonServers", [])) | approved)
settings.write_text(json.dumps(s, indent=2) + "\n")
c = load(config)
c.setdefault("projects", {}).setdefault(repo, {})["hasTrustDialogAccepted"] = True
for name in approved: c.get("mcpServers", {}).pop(name, None)
config.parent.mkdir(parents=True, exist_ok=True)
config.write_text(json.dumps(c, indent=2) + "\n")
PY

  local codex_config="${HOME}/.codex/config.toml"
  mkdir -p "$(dirname "$codex_config")"; touch "$codex_config"
  CONFIG="$codex_config" REPO="$REPO_DIR" python3 - <<'PY'
import os, pathlib, re
path = pathlib.Path(os.environ["CONFIG"]); repo = os.environ["REPO"]; text = path.read_text()
header = f'projects."{repo}"'
if not re.search(rf"^\s*\[{re.escape(header)}\]", text, re.M):
    path.write_text(text.rstrip("\n") + f'\n\n[{header}]\ntrust_level = "trusted"\n')
PY
}

status() {
  local rc=0
  if listening "$AUTODEV_PORT" && verify_autodev; then log "autodev-memory: healthy"; else log "autodev-memory: DOWN or wrong project"; rc=1; fi
  if listening "$CONTEXT7_PORT"; then log "context7: healthy"; else log "context7: DOWN"; rc=1; fi
  return "$rc"
}

main() {
  is_cloud || { log "skipping: local workspaces use the launchd-managed Mac proxies"; return 0; }
  load_profile
  case "${1:-ensure}" in
    status) status ;;
    install|ensure)
      ensure_op
      approve_clients
      if ! listening "$AUTODEV_PORT" || ! verify_autodev >/dev/null 2>&1; then stop_autodev; start_autodev; fi
      listening "$CONTEXT7_PORT" || start_context7
      status
      ;;
    *) echo "usage: $0 {install|ensure|status}" >&2; return 2 ;;
  esac
}

main "$@"

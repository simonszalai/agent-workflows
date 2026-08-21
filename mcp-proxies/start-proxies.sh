#!/usr/bin/env bash
# Start the loopback MCP auth proxies on the Mac. Stable ports keep client configs
# identical across supported local and cloud environments:
#
#   autodev-memory  127.0.0.1:8792/<project>/* -> https://autodev-memory.onrender.com/*
#   context7        127.0.0.1:8793  -> https://mcp.context7.com/mcp
#
# These two are the ONLY MCP servers left (2026-07-28 decision): render, tailscale,
# slack, and postgres are CLIs now — bin/render-cli, tailscale + bin/tailscale-admin,
# bin/slack-api, and bin/psql-cli (see skills/tool-*).
#
# Credentials are resolved once at process startup with each project's own Keychain
# service-account token. The resulting `node` process keeps the restricted bearers only
# in memory; there is no persistent `op run` parent and no 1Password call per request.
# AutoDEV route selection comes from
# each repo's checked-in URL prefix; its project-restricted bearer then pins the server
# identity even if an agent supplies the wrong project argument.
#
# Runs under launchd (com.simon.mcp-proxies.plist: RunAtLoad + StartInterval
# self-heal) and is manually invokable: start-proxies.sh {ensure|status|stop}.
# `ensure` is idempotent — a healthy listener is left alone.
set -euo pipefail

# launchd starts us with a minimal PATH: add homebrew (op) and the newest nvm node.
# Absolute-path pinning (the gateway's approach) broke on every node upgrade; detect
# instead.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
if ! command -v node >/dev/null 2>&1; then
  _nvm_bin="$(ls -d "${HOME}/.nvm/versions/node"/*/bin 2>/dev/null | sort -V | tail -1)"
  [ -n "${_nvm_bin}" ] && export PATH="${_nvm_bin}:${PATH}"
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTODEV_ENV_FILE="${HERE}/autodev-routes.env"
CONTEXT7_ENV_FILE="${HERE}/context7.env"
AUTODEV_ROUTES_FILE="${HERE}/autodev-routes.json"
PROXY="${HERE}/mcp-proxy.mjs"
WAF_ENCODER="${HERE}/waf-encode.mjs"
ROUTE_VERIFIER="${HERE}/verify-autodev-routes.mjs"

AUTODEV_PORT=8792
CONTEXT7_PORT=8793

LOG_DIR="${HOME}/Library/Logs/mcp-proxies"
mkdir -p "$LOG_DIR"

log() { echo "[mcp-proxies] $*"; }

listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

# Resolve every checked-in reference once, using the service account for its own project.
# printf -v keeps both the service-account token and resolved secret out of argv/stdout.
load_secret_refs() {
  local env_file="$1" line name ref keychain op_token secret
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ""|\#*) continue ;; esac
    name="${line%%=*}"
    ref="${line#*=}"
    case "$name" in
      AMARU_AUTODEV_MEMORY_API_TOKEN)       keychain=op-amaru-token ;;
      AUTODEV_AUTODEV_MEMORY_API_TOKEN)     keychain=op-autodev-token ;;
      TS_AUTODEV_MEMORY_API_TOKEN|CONTEXT7_API_KEY) keychain=op-ts-token ;;
      WORKFLOW_PRO_AUTODEV_MEMORY_API_TOKEN) keychain=op-workflow-pro-token ;;
      *) log "ERROR: unsupported credential name in ${env_file}: ${name}"; return 1 ;;
    esac
    op_token="$(security find-generic-password -s "$keychain" -a simon -w 2>/dev/null || true)"
    [ -n "$op_token" ] || { log "ERROR: Keychain service account missing: ${keychain}"; return 1; }
    secret="$(OP_SERVICE_ACCOUNT_TOKEN="$op_token" op read --no-newline "$ref" 2>/dev/null || true)"
    op_token=""
    if [ -z "$secret" ]; then
      # mcp-proxy.mjs omits routes whose auth env is empty. Failing closed here
      # used to take down every project's AutoDEV route when one vault field was
      # pending (AUTODEV Autodev memory has no api_token).
      log "WARN: credential is unreadable, skipping: ${name}"
      continue
    fi
    printf -v "$name" '%s' "$secret"
    export "$name"
    secret=""
  done < "$env_file"
}

# One credential resolution pass per long-lived process. The subshell execs node, so
# only the two Node proxies remain resident after startup.
spawn_proxy() { # label port env_file [extra env k=v ...]
  local label="$1" port="$2" env_file="$3"; shift 3
  (
    set +x
    load_secret_refs "$env_file" || exit 1
    unset OP_SERVICE_ACCOUNT_TOKEN OP_CONNECT_TOKEN
    export MCP_PROXY_PORT="$port"
    exec env "$@" node "$PROXY" "$label"
  ) >"${LOG_DIR}/${label}.log" 2>&1 </dev/null &
  local i
  for i in $(seq 1 20); do
    listening "$port" && { log "${label}: ready on ${port}"; return 0; }
    sleep 1
  done
  log "ERROR: ${label} did not bind :${port}. Last log lines:"
  tail -5 "${LOG_DIR}/${label}.log" >&2 || true
  return 1
}

start_autodev() {
  for required in "$WAF_ENCODER" "$AUTODEV_ROUTES_FILE" "$ROUTE_VERIFIER" "$AUTODEV_ENV_FILE"; do
    [ -f "$required" ] || { log "ERROR: required AutoDEV proxy file missing at ${required}"; return 1; }
  done
  spawn_proxy autodev-memory-router "$AUTODEV_PORT" "$AUTODEV_ENV_FILE" \
    MCP_PROXY_ROUTES_FILE="$AUTODEV_ROUTES_FILE" MCP_PROXY_BODY_TRANSFORM="$WAF_ENCODER" || return 1
  if ! node "$ROUTE_VERIFIER" "$AUTODEV_ROUTES_FILE" "$AUTODEV_PORT"; then
    log "ERROR: AutoDEV route identity canary failed; stopping the unsafe router"
    pkill -f "mcp-proxy.mjs autodev-memory-router" 2>/dev/null || true
    return 1
  fi
}

start_context7() {
  spawn_proxy context7 "$CONTEXT7_PORT" "$CONTEXT7_ENV_FILE" \
    MCP_PROXY_UPSTREAM="https://mcp.context7.com/mcp" MCP_PROXY_AUTH_ENV=CONTEXT7_API_KEY
}

SERVERS=(autodev-memory context7)

healthy() {
  case "$1" in
    autodev-memory)
      listening "$AUTODEV_PORT" && pgrep -f "node .*mcp-proxy.mjs autodev-memory-router" >/dev/null ;;
    context7)       listening "$CONTEXT7_PORT" ;;
    *) return 1 ;;
  esac
}

start_server() {
  case "$1" in
    autodev-memory) start_autodev ;;
    context7)       start_context7 ;;
    *) return 1 ;;
  esac
}

ensure() {
  local rc=0 name
  for name in "${SERVERS[@]}"; do
    if healthy "$name"; then log "${name}: already healthy"; continue; fi
    start_server "$name" || rc=1
  done
  return "$rc"
}

case "${1:-ensure}" in
  ensure) ensure ;;
  status)
    rc=0
    for name in "${SERVERS[@]}"; do
      if healthy "$name"; then
        if [ "$name" = autodev-memory ] && ! node "$ROUTE_VERIFIER" "$AUTODEV_ROUTES_FILE" "$AUTODEV_PORT"; then
          log "${name}: ROUTE IDENTITY FAILURE"; rc=1
        else
          log "${name}: healthy"
        fi
      else
        log "${name}: DOWN"; rc=1
      fi
    done
    exit "$rc"
    ;;
  stop)
    pkill -f "mcp-proxy.mjs (autodev-memory-router|autodev-memory|context7)" 2>/dev/null || true
    log "stopped"
    ;;
  *) echo "usage: $0 {ensure|status|stop}" >&2; exit 2 ;;
esac

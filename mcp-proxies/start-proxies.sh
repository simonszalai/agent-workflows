#!/usr/bin/env bash
# Start the loopback MCP auth proxies on the Mac. Stable ports keep client configs
# identical across supported local and cloud environments:
#
#   autodev-memory  127.0.0.1:8792  -> https://autodev-memory.onrender.com/mcp (+ WAF encode)
#   context7        127.0.0.1:8793  -> https://mcp.context7.com/mcp
#
# These two are the ONLY MCP servers left (2026-07-28 decision): render, tailscale,
# slack, and postgres are CLIs now — bin/render-cli, tailscale + bin/tailscale-admin,
# bin/slack-api, and bin/psql-cli (see skills/tool-*).
#
# Credentials: resolved per proxy via `op run --env-file=proxies.env`, authenticated
# by the Keychain service-account token (op-dev-token) — silent, no Touch ID. Keys
# live only in each proxy's process memory; the clients hold nothing.
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
ENV_FILE="${HERE}/proxies.env"
PROXY="${HERE}/mcp-proxy.mjs"
WAF_ENCODER="${HERE}/waf-encode.mjs"

AUTODEV_PORT=8792
CONTEXT7_PORT=8793

LOG_DIR="${HOME}/Library/Logs/mcp-proxies"
mkdir -p "$LOG_DIR"

log() { echo "[mcp-proxies] $*"; }

listening() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

sa_token() {
  local tok="${OP_SERVICE_ACCOUNT_TOKEN:-}"
  [ -n "$tok" ] || tok="$(security find-generic-password -s op-dev-token -a simon -w 2>/dev/null || true)"
  [ -n "$tok" ] || { log "ERROR: no service-account token (Keychain op-dev-token)"; return 1; }
  printf '%s' "$tok"
}

# One op run per proxy: each child gets only what proxies.env resolves, in memory.
spawn_proxy() { # label port upstream auth_env [extra env k=v ...]
  local label="$1" port="$2" upstream="$3" auth_env="$4"; shift 4
  local tok; tok="$(sa_token)" || return 1
  nohup env OP_SERVICE_ACCOUNT_TOKEN="$tok" \
    MCP_PROXY_PORT="$port" MCP_PROXY_UPSTREAM="$upstream" MCP_PROXY_AUTH_ENV="$auth_env" "$@" \
    op run --env-file="$ENV_FILE" --no-masking -- \
    node "$PROXY" "$label" >"${LOG_DIR}/${label}.log" 2>&1 &
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
  [ -f "$WAF_ENCODER" ] || { log "ERROR: WAF encoder missing at ${WAF_ENCODER}"; return 1; }
  spawn_proxy autodev-memory "$AUTODEV_PORT" "https://autodev-memory.onrender.com/mcp" \
    AUTODEV_MEMORY_API_TOKEN MCP_PROXY_BODY_TRANSFORM="$WAF_ENCODER"
}

start_context7() {
  spawn_proxy context7 "$CONTEXT7_PORT" "https://mcp.context7.com/mcp" CONTEXT7_API_KEY
}

SERVERS=(autodev-memory context7)

healthy() {
  case "$1" in
    autodev-memory) listening "$AUTODEV_PORT" ;;
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
      if healthy "$name"; then log "${name}: healthy"; else log "${name}: DOWN"; rc=1; fi
    done
    exit "$rc"
    ;;
  stop)
    pkill -f "mcp-proxy.mjs (autodev-memory|context7)" 2>/dev/null || true
    log "stopped"
    ;;
  *) echo "usage: $0 {ensure|status|stop}" >&2; exit 2 ;;
esac

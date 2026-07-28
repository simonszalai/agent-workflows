#!/usr/bin/env bash
# Start the loopback MCP auth proxies on the Mac. Counterpart of ts-prefect's
# scripts/setup/cloud-mcp.sh (Conductor cloud) — SAME proxy, SAME ports, so client
# configs are static URLs valid in both environments:
#
#   render          127.0.0.1:8789  -> https://mcp.render.com/mcp        (+ workspace preflight)
#   tailscale       127.0.0.1:8790  -> local tailscale-mcp-server :8791  (per-boot bearer)
#   autodev-memory  127.0.0.1:8792  -> https://autodev-memory.onrender.com/mcp (+ WAF encode)
#   context7        127.0.0.1:8793  -> https://mcp.context7.com/mcp
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
# instead. `node` and `npx` from the same bin dir keep proxy and tailscale consistent.
export PATH="/opt/homebrew/bin:/usr/local/bin:${PATH}"
if ! command -v node >/dev/null 2>&1; then
  _nvm_bin="$(ls -d "${HOME}/.nvm/versions/node"/*/bin 2>/dev/null | sort -V | tail -1)"
  [ -n "${_nvm_bin}" ] && export PATH="${_nvm_bin}:${PATH}"
fi

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${HERE}/proxies.env"
PROXY="${HERE}/mcp-proxy.mjs"
WAF_ENCODER="${HERE}/../mcp-gateway/waf-encode.mjs"

RENDER_PORT=8789
TAILSCALE_PORT=8790
TAILSCALE_UPSTREAM_PORT=8791
AUTODEV_PORT=8792
CONTEXT7_PORT=8793
RENDER_WORKSPACE="tea-ct11rp0gph6c73bf2kf0"

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

start_render() {
  spawn_proxy render "$RENDER_PORT" "https://mcp.render.com/mcp" TS_RENDER_API_KEY \
    MCP_PROXY_RENDER_WORKSPACE="$RENDER_WORKSPACE"
}

start_autodev() {
  [ -f "$WAF_ENCODER" ] || { log "ERROR: WAF encoder missing at ${WAF_ENCODER}"; return 1; }
  spawn_proxy autodev-memory "$AUTODEV_PORT" "https://autodev-memory.onrender.com/mcp" \
    AUTODEV_MEMORY_API_TOKEN MCP_PROXY_BODY_TRANSFORM="$WAF_ENCODER"
}

start_context7() {
  spawn_proxy context7 "$CONTEXT7_PORT" "https://mcp.context7.com/mcp" CONTEXT7_API_KEY
}

# The upstream npm server mandates a bearer in --http mode; it is generated per boot
# and lives only in the environments of the two processes that need it. Both halves
# start and stop together — a surviving half cannot reattach to a fresh one.
start_tailscale() {
  stop_tailscale
  local tok bearer
  tok="$(sa_token)" || return 1
  bearer="$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"

  nohup env OP_SERVICE_ACCOUNT_TOKEN="$tok" \
    TAILSCALE_TAILNET="-" MCP_HTTP_BEARER_TOKEN="$bearer" \
    op run --env-file="$ENV_FILE" --no-masking -- \
    npx -y --package=@hexsleeves/tailscale-mcp-server tailscale-mcp-server \
    --http --port "$TAILSCALE_UPSTREAM_PORT" --host 127.0.0.1 \
    >"${LOG_DIR}/tailscale-upstream.log" 2>&1 &

  local i ready=""
  for i in $(seq 1 60); do
    listening "$TAILSCALE_UPSTREAM_PORT" && { ready=1; break; }
    sleep 1
  done
  [ -n "$ready" ] || {
    log "ERROR: tailscale MCP did not become ready in 60s. Last log lines:"
    tail -5 "${LOG_DIR}/tailscale-upstream.log" >&2 || true
    return 1
  }

  nohup env MCP_PROXY_PORT="$TAILSCALE_PORT" \
    MCP_PROXY_UPSTREAM="http://127.0.0.1:${TAILSCALE_UPSTREAM_PORT}/mcp" \
    MCP_PROXY_AUTH_ENV="TS_TAILSCALE_BEARER" TS_TAILSCALE_BEARER="$bearer" \
    node "$PROXY" tailscale >"${LOG_DIR}/tailscale.log" 2>&1 &
  local j
  for j in $(seq 1 20); do
    listening "$TAILSCALE_PORT" && { log "tailscale: ready on ${TAILSCALE_PORT}"; return 0; }
    sleep 1
  done
  log "ERROR: tailscale proxy did not bind :${TAILSCALE_PORT}"
  return 1
}

stop_tailscale() {
  pkill -f "tailscale-mcp-server --http --port ${TAILSCALE_UPSTREAM_PORT}" 2>/dev/null || true
  pkill -f "mcp-proxy.mjs tailscale" 2>/dev/null || true
}

SERVERS=(render autodev-memory context7 tailscale)

healthy() {
  case "$1" in
    render)         listening "$RENDER_PORT" ;;
    autodev-memory) listening "$AUTODEV_PORT" ;;
    context7)       listening "$CONTEXT7_PORT" ;;
    tailscale)      listening "$TAILSCALE_PORT" && listening "$TAILSCALE_UPSTREAM_PORT" ;;
    *) return 1 ;;
  esac
}

start_server() {
  case "$1" in
    render)         start_render ;;
    autodev-memory) start_autodev ;;
    context7)       start_context7 ;;
    tailscale)      start_tailscale ;;
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
    pkill -f "mcp-proxy.mjs (render|autodev-memory|context7)" 2>/dev/null || true
    stop_tailscale
    log "stopped"
    ;;
  *) echo "usage: $0 {ensure|status|stop}" >&2; exit 2 ;;
esac

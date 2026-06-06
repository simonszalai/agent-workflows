#!/usr/bin/env zsh
# Launchd entrypoint for mcp-gateway. Loads every MCP secret ONCE (one 1Password
# biometric prompt for the daemon's whole lifetime), exports them, then execs the
# Node gateway. This is the "1Password connection pooling" goal: secrets resolved
# once, upstream sockets pooled by the daemon — instead of every workspace's
# mcp-remote re-reading 1Password and opening its own connection.
#
# Secret sources mirror bin/project-mcp exactly:
#   - mount file (1Password "MCP env" item, FIFO): AUTODEV_MEMORY_API_TOKEN, CONTEXT7_API_KEY
#   - per-project op:// items: <PROJECT>_RENDER_API_KEY
set -euo pipefail

HERE="${0:A:h}"
NODE_BIN="${NODE_BIN:-/Users/simon/.nvm/versions/node/v24.14.1/bin/node}"
OP_BIN="${OP_BIN:-/opt/homebrew/bin/op}"
OP_ACCOUNT="${OP_ACCOUNT:-my.1password.com}"
[[ -x "$NODE_BIN" ]] || NODE_BIN="$(command -v node)"
[[ -x "$OP_BIN" ]] || OP_BIN="$(command -v op)"

TS_MCP_MOUNT_FILE="${TS_MCP_MOUNT_FILE:-/Users/simon/Library/Application Support/6b18dff57e135dcf477c9180dc0d3c88/71e2f97219e5f7cc8fe3b17d4ff23de6}"
TS_OP_ITEM="${TS_OP_ITEM:-op://Personal/6vfcrew2nps7r3po7f4zxssjva}"
AMARU_OP_ITEM="${AMARU_OP_ITEM:-op://Personal/pm2niiuqvqq26ytb2oimytrrdm}"
WORKFLOW_OP_ITEM="${WORKFLOW_OP_ITEM:-op://Personal/w2imwaf7f3o3p7okpifswnxdmm}"

# Local listener secret (OPT-IN). v1 relies on the 127.0.0.1-only bind as the
# boundary, so clients need no header — this avoids depending on `${VAR}`
# expansion inside client config headers. Set MCP_GATEWAY_REQUIRE_TOKEN=1 to
# harden later (clients then must send `x-mcp-gateway-token: <.gateway-token>`).
if [[ "${MCP_GATEWAY_REQUIRE_TOKEN:-0}" == "1" ]]; then
  TOKEN_FILE="${MCP_GATEWAY_TOKEN_FILE:-$HERE/.gateway-token}"
  if [[ ! -s "$TOKEN_FILE" ]]; then
    umask 077
    /usr/bin/openssl rand -hex 24 > "$TOKEN_FILE"
  fi
  export MCP_GATEWAY_TOKEN="$(<"$TOKEN_FILE")"
fi

# --- read the 1Password mount once ---
typeset -gA MOUNT
load_mount() {
  [[ -r "$TS_MCP_MOUNT_FILE" ]] || { print -u2 "mcp-gateway: 1Password mount not readable: $TS_MCP_MOUNT_FILE"; exit 2; }
  local line key val
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line//$'\r'/}"
    [[ -z "$line" || "$line" == \#* ]] && continue
    key="${line%%=*}"; val="${line#*=}"
    key="${key//[[:space:]]/}"
    [[ "$key" =~ '^[A-Za-z_][A-Za-z0-9_]*$' ]] || continue
    val="${val# }"; val="${val% }"
    if [[ "${val[1]:-}" == '"' && "${val[-1]:-}" == '"' ]]; then val="${val[2,-2]}"; fi
    MOUNT[$key]="$val"
  done < "$TS_MCP_MOUNT_FILE"
}
load_mount

op_read() { # item-ref key
  [[ -x "$OP_BIN" ]] || { print -u2 "mcp-gateway: op CLI not found"; exit 2; }
  "$OP_BIN" whoami >/dev/null 2>&1 || "$OP_BIN" signin --account "$OP_ACCOUNT" >/dev/null
  "$OP_BIN" read "$1/$2"
}

export AUTODEV_MEMORY_API_TOKEN="${MOUNT[AUTODEV_MEMORY_API_TOKEN]:-}"
export CONTEXT7_API_KEY="${MOUNT[CONTEXT7_API_KEY]:-}"
export TS_RENDER_API_KEY="$(op_read "$TS_OP_ITEM" TS_RENDER_API_KEY)"
export AMARU_RENDER_API_KEY="$(op_read "$AMARU_OP_ITEM" AMARU_RENDER_API_KEY)"
export WORKFLOW_RENDER_API_KEY="$(op_read "$WORKFLOW_OP_ITEM" WORKFLOW_RENDER_API_KEY)"

export MCP_GATEWAY_HOST="${MCP_GATEWAY_HOST:-127.0.0.1}"
export MCP_GATEWAY_PORT="${MCP_GATEWAY_PORT:-8765}"

exec "$NODE_BIN" "$HERE/gateway.mjs"

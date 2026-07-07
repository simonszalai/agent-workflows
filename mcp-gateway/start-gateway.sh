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
# TS round (E0022 M2): TS secrets live in the TS / TS-sensitive vaults now
# (item name = env var name, field `value`). AMARU/WORKFLOW stay on their
# Personal items until their migration rounds.
TS_SENS_VAULT="${TS_SENS_VAULT:-op://TS-sensitive}"
TS_VAULT="${TS_VAULT:-op://TS}"
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

# Join a base postgres URL and a database name, preserving any query string.
# Mirrors bin/project-mcp's postgres_url_for_database so prod URLs come out identical.
postgres_url_for_database() { # base-url database-name
  local base="$1" db="$2" head tail
  if [[ "$base" == *\?* ]]; then head="${base%%\?*}"; tail="?${base#*\?}"; else head="$base"; tail=""; fi
  head="${head%/}"
  print -r -- "$head/$db$tail"
}

export AUTODEV_MEMORY_API_TOKEN="${MOUNT[AUTODEV_MEMORY_API_TOKEN]:-}"
export CONTEXT7_API_KEY="${MOUNT[CONTEXT7_API_KEY]:-}"
export TS_RENDER_API_KEY="$(op_read "$TS_SENS_VAULT" TS_RENDER_API_KEY/value)"
export AMARU_RENDER_API_KEY="$(op_read "$AMARU_OP_ITEM" AMARU_RENDER_API_KEY)"
export WORKFLOW_RENDER_API_KEY="$(op_read "$WORKFLOW_OP_ITEM" WORKFLOW_RENDER_API_KEY)"

# --- Phase 2: postgres DATABASE_URIs (resolved ONCE; mirror bin/project-mcp) ---
# The daemon spawns one long-lived `postgres-mcp --transport sse` per DB from these,
# replacing the per-workspace `project-mcp ts postgres_*` stdio spawns (and their
# per-workspace 1Password reads). Direct mount values:
export TS_POSTGRES_DEV_URL="${MOUNT[TS_DEV_DATABASE_URL]:-}"
export TS_POSTGRES_STAGING_URL="$(op_read "$TS_VAULT" STAGING_DATABASE_URL/value)"
# mem_ts is the autodev-memory project DB (autodev round) — stays on the mount.
export TS_POSTGRES_AUTODEV_TS_URL="${MOUNT[TS_PROD_MEM_TS_DATABASE_URL_EXTERNAL]:-}"
# Prod + prod_prefect: base URL is a high-sensitivity op:// read, joined with the DB
# name from the mount (same as project-mcp's ts_prod_postgres_value). One `op read`,
# in the same biometric window as the render tokens above.
ts_prod_base="$(op_read "$TS_SENS_VAULT" TS_PROD_POSTGRES_URL_BASE/value 2>/dev/null || true)"
if [[ -n "$ts_prod_base" ]]; then
  export TS_POSTGRES_PROD_URL="$(postgres_url_for_database "$ts_prod_base" "${MOUNT[TS_PROD_DATABASE_NAME]:-}")"
  export TS_POSTGRES_PROD_PREFECT_URL="$(postgres_url_for_database "$ts_prod_base" "${MOUNT[TS_PROD_PREFECT_DATABASE_NAME]:-}")"
else
  print -u2 "mcp-gateway: warning — TS_PROD_POSTGRES_URL_BASE empty; ts/postgres_prod* routes will 502 until set"
fi

# amaru / workflow / shared postgres DBs — all plain mount values (no op read). Access
# modes (prod=restricted, others=unrestricted) live in routes.json, mirroring project-mcp.
export AMARU_POSTGRES_DEV_URL="${MOUNT[AMARU_DEV_DATABASE_URL]:-}"
export AMARU_POSTGRES_STAGING_URL="${MOUNT[AMARU_STAGING_DATABASE_URL]:-}"
export AMARU_POSTGRES_PROD_URL="${MOUNT[AMARU_PROD_DATABASE_URL]:-}"
export WORKFLOW_POSTGRES_DEV_URL="${MOUNT[WORKFLOW_DEV_DATABASE_URL]:-}"
export WORKFLOW_POSTGRES_STAGING_URL="${MOUNT[WORKFLOW_STAGING_DATABASE_URL]:-}"
export WORKFLOW_POSTGRES_PROD_URL="${MOUNT[WORKFLOW_PROD_DATABASE_URL]:-}"
export AUTODEV_GLOBAL_POSTGRES_URL="${MOUNT[AUTODEV_GLOBAL_DATABASE_URL_EXTERNAL]:-}"

# postgres-mcp launcher the daemon spawns (one SSE server per DB). Absolute path to the
# ts-prefect dev venv binary by default; override POSTGRES_MCP_BIN for another env.
export POSTGRES_MCP_BIN="${POSTGRES_MCP_BIN:-/Users/simon/dev/ts-prefect/.venv/bin/postgres-mcp}"

export MCP_GATEWAY_HOST="${MCP_GATEWAY_HOST:-127.0.0.1}"
export MCP_GATEWAY_PORT="${MCP_GATEWAY_PORT:-8765}"

exec "$NODE_BIN" "$HERE/gateway.mjs"

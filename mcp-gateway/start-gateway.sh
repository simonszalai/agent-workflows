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
# TS round (E0022 M2): all op:// refs (TS/TS-sensitive vaults + the AMARU/
# WORKFLOW Personal items) live in gateway.env, resolved by one `op run` below.

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

# --- secrets via ONE `op run` (E0022 M2) -----------------------------------
# Every op:// ref lives in gateway.env; a single op process resolves them all
# in one auth window (one biometric, no per-spawn TCC prompt storm — the old
# op_read helper spawned 2 op processes per secret and triggered 11 macOS
# dialogs). Composition of the prod postgres URLs happens in finish-start.zsh
# INSIDE the op run (op can't compose partial values in env files).
export AUTODEV_MEMORY_API_TOKEN="${MOUNT[AUTODEV_MEMORY_API_TOKEN]:-}"
export CONTEXT7_API_KEY="${MOUNT[CONTEXT7_API_KEY]:-}"

# --- postgres DATABASE_URIs from the mount (non-op values) -------------------
export TS_POSTGRES_DEV_URL="${MOUNT[TS_DEV_DATABASE_URL]:-}"
# mem_ts is the autodev-memory project DB (autodev round) — stays on the mount.
export TS_POSTGRES_AUTODEV_TS_URL="${MOUNT[TS_PROD_MEM_TS_DATABASE_URL_EXTERNAL]:-}"
# prod URL composition inputs for finish-start.zsh:
export TS_PROD_DATABASE_NAME="${MOUNT[TS_PROD_DATABASE_NAME]:-}"
export TS_PROD_PREFECT_DATABASE_NAME="${MOUNT[TS_PROD_PREFECT_DATABASE_NAME]:-}"

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

# ONE op invocation resolves gateway.env and execs stage 2 (which composes the
# prod postgres URLs and execs node). --no-masking: gateway stdout is its own
# log stream; masking would scan every log line for secret substrings.
[[ -x "$OP_BIN" ]] || { print -u2 "mcp-gateway: op CLI not found"; exit 2; }
# Audit line (the gateway bypasses the bin/op shim via absolute OP_BIN):
# gateway restarts are the one KNOWN biometric event — log them so op-audit
# attributes every prompt, including this one.
AUDIT_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
mkdir -p "$AUDIT_DIR" 2>/dev/null || true
print -r -- "$(date '+%F %T') pid=$$ parent=mcp-gateway(launchd) auth=interactive BIOMETRIC-PROMPT :: op run --env-file=gateway.env (daemon restart, one-per-lifetime)" \
  >> "$AUDIT_DIR/op-audit.log" 2>/dev/null || true
exec "$OP_BIN" run --account "$OP_ACCOUNT" --env-file="$HERE/gateway.env" --no-masking -- \
  /bin/zsh "$HERE/finish-start.zsh"

#!/usr/bin/env zsh
# Launchd entrypoint for mcp-gateway. Loads every MCP secret ONCE (one 1Password
# biometric prompt for the daemon's whole lifetime), exports them, then execs the
# Node gateway. This is the "1Password connection pooling" goal: secrets resolved
# once, upstream sockets pooled by the daemon — instead of every workspace's
# mcp-remote re-reading 1Password and opening its own connection.
#
# Every secret is an op:// ref in gateway.env, resolved by the single `op run`
# below (one auth window). The daemon no longer reads the 1Password "MCP env"
# mount — that survives only for the project-mcp fallback / analyst path.
set -euo pipefail

HERE="${0:A:h}"
NODE_BIN="${NODE_BIN:-/Users/simon/.nvm/versions/node/v24.14.1/bin/node}"
OP_BIN="${OP_BIN:-/opt/homebrew/bin/op}"
OP_ACCOUNT="${OP_ACCOUNT:-my.1password.com}"
[[ -x "$NODE_BIN" ]] || NODE_BIN="$(command -v node)"
[[ -x "$OP_BIN" ]] || OP_BIN="$(command -v op)"

# Local listener secret (ON by default since 2026-07-08). The 127.0.0.1 bind
# alone does not stop browser-borne requests (DNS rebinding bypasses same-origin
# and we don't validate Host); requiring `x-mcp-gateway-token: <.gateway-token>`
# gates access on reading a 0600 user file, which webpages and other local
# users cannot do. Set MCP_GATEWAY_REQUIRE_TOKEN=0 to roll back.
if [[ "${MCP_GATEWAY_REQUIRE_TOKEN:-1}" == "1" ]]; then
  TOKEN_FILE="${MCP_GATEWAY_TOKEN_FILE:-$HERE/.gateway-token}"
  if [[ ! -s "$TOKEN_FILE" ]]; then
    umask 077
    /usr/bin/openssl rand -hex 24 > "$TOKEN_FILE"
  fi
  export MCP_GATEWAY_TOKEN="$(<"$TOKEN_FILE")"
  # GUI-launched apps (Conductor → claude) never source shell rc files; publish
  # the token into the launchd user session so their ${MCP_GATEWAY_TOKEN}
  # header expansion works. CLI shells get it from ~/.zshenv instead.
  /bin/launchctl setenv MCP_GATEWAY_TOKEN "$MCP_GATEWAY_TOKEN" 2>/dev/null || true
fi

AUDIT_DIR="${XDG_STATE_HOME:-$HOME/.local/state}"
mkdir -p "$AUDIT_DIR" 2>/dev/null || true

sanitize_gateway_message() {
  sed -E \
    -e 's#op://[^[:space:]]+#op://[REDACTED_REF]#g' \
    -e 's#([A-Za-z0-9_-]{32,})#[REDACTED_TOKENLIKE]#g' \
    | tr '\n' ' '
}

notify_gateway_failure() {
  local summary="$1"
  local body="${summary[1,220]}"
  [[ ${#summary} -gt 220 ]] && body="${body}…"
  local escaped="${body//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"

  /usr/bin/osascript \
    -e "display notification \"$escaped\" with title \"MCP Gateway failed\" subtitle \"Not retrying\"" \
    >/dev/null 2>&1 || true
}

gateway_fail_once() {
  local summary="$1"
  local safe
  safe="$(print -r -- "$summary" | sanitize_gateway_message)"

  print -u2 -- "mcp-gateway: startup failed (not retrying): $safe"
  print -r -- "$(date '+%F %T') pid=$$ parent=mcp-gateway(launchd) status=startup-failed NO-RETRY :: $safe" \
    >> "$AUDIT_DIR/op-audit.log" 2>/dev/null || true
  notify_gateway_failure "$safe"

  # Critical: exit successfully so launchd does NOT KeepAlive-restart into
  # another `op run` / Touch ID prompt. The user fixes the config/vault and
  # starts the daemon manually.
  exit 0
}

summarize_error_file() {
  local file="$1"
  local msg
  msg="$(grep -E -m1 'could not resolve item UUID|No accounts configured|not found|invalid|Invalid|error|Error|ERROR|mcp-gateway:' "$file" 2>/dev/null || true)"
  [[ -n "$msg" ]] || msg="$(tail -n 1 "$file" 2>/dev/null || true)"
  [[ -n "$msg" ]] || msg="op run exited non-zero with no stderr"
  print -r -- "$msg"
}

# --- secrets ----------------------------------------------------------------
# All secrets are op:// refs in gateway.env, resolved by the ONE `op run` at the
# end of this script (single auth window). Postgres/token/render-key env vars
# (TS_*, AMARU_*, WORKFLOW_*, AUTODEV_*, CONTEXT7_*) all arrive from there; the
# prod postgres URLs are composed from the canonicals in finish-start.zsh INSIDE
# that op run (op can't transform values in an env file). Nothing is read from
# the 1Password mount here anymore.

# postgres-mcp launcher the daemon spawns (one SSE server per DB). Absolute path to the
# ts-prefect dev venv binary by default; override POSTGRES_MCP_BIN for another env.
export POSTGRES_MCP_BIN="${POSTGRES_MCP_BIN:-/Users/simon/dev/ts-prefect/.venv/bin/postgres-mcp}"

export MCP_GATEWAY_HOST="${MCP_GATEWAY_HOST:-127.0.0.1}"
export MCP_GATEWAY_PORT="${MCP_GATEWAY_PORT:-8765}"

# ONE op invocation resolves gateway.env and execs stage 2 (which composes the
# prod postgres URLs and execs node). --no-masking: gateway stdout is its own
# log stream; masking would scan every log line for secret substrings.
[[ -x "$OP_BIN" ]] || gateway_fail_once "op CLI not found at $OP_BIN"
# Audit line (the gateway bypasses the bin/op shim via absolute OP_BIN):
# gateway restarts are the one KNOWN biometric event — log them so op-audit
# attributes every prompt, including this one.
print -r -- "$(date '+%F %T') pid=$$ parent=mcp-gateway(launchd) auth=interactive BIOMETRIC-PROMPT :: op run --env-file=gateway.env (daemon restart, one-per-lifetime)" \
  >> "$AUDIT_DIR/op-audit.log" 2>/dev/null || true

START_ERR_FILE="$(mktemp -t mcp-gateway-op-run.XXXXXX.err)"
trap 'rm -f "${START_ERR_FILE:-}"' EXIT

set +e
"$OP_BIN" run --account "$OP_ACCOUNT" --env-file="$HERE/gateway.env" --no-masking -- \
  /bin/zsh "$HERE/finish-start.zsh" 2> >(tee "$START_ERR_FILE" >&2)
status=$?
set -e

if (( status != 0 )); then
  summary="$(summarize_error_file "$START_ERR_FILE")"
  gateway_fail_once "op/gateway exited status $status: $summary"
fi

exit 0

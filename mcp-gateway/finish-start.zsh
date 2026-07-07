#!/usr/bin/env zsh
# Stage 2 of gateway startup — runs INSIDE `op run` with all gateway.env refs
# resolved. Composes the prod postgres URLs (op run can't compose partial
# values), scrubs the raw base from the env, then execs the Node gateway.
set -euo pipefail
HERE="${0:A:h}"
NODE_BIN="${NODE_BIN:-/Users/simon/.nvm/versions/node/v24.14.1/bin/node}"
[[ -x "$NODE_BIN" ]] || NODE_BIN="$(command -v node)"

postgres_url_for_database() { # base-url database-name
  local base="$1" db="$2" head tail
  if [[ "$base" == *\?* ]]; then head="${base%%\?*}"; tail="?${base#*\?}"; else head="$base"; tail=""; fi
  head="${head%/}"
  print -r -- "$head/$db$tail"
}

if [[ -n "${TS_PROD_POSTGRES_URL_BASE:-}" ]]; then
  export TS_POSTGRES_PROD_URL="$(postgres_url_for_database "$TS_PROD_POSTGRES_URL_BASE" "${TS_PROD_DATABASE_NAME:-}")"
  export TS_POSTGRES_PROD_PREFECT_URL="$(postgres_url_for_database "$TS_PROD_POSTGRES_URL_BASE" "${TS_PROD_PREFECT_DATABASE_NAME:-}")"
else
  print -u2 "mcp-gateway: warning — TS_PROD_POSTGRES_URL_BASE empty; ts/postgres_prod* routes will 502 until set"
fi
unset TS_PROD_POSTGRES_URL_BASE TS_PROD_DATABASE_NAME TS_PROD_PREFECT_DATABASE_NAME

exec "$NODE_BIN" "$HERE/gateway.mjs"

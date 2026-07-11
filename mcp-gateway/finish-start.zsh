#!/usr/bin/env zsh
# Stage 2 of gateway startup — runs INSIDE `op run` with all gateway.env refs
# resolved. Composes the prod postgres URLs (op run can't compose partial
# values), scrubs the raw base from the env, then execs the Node gateway.
set -euo pipefail
HERE="${0:A:h}"
NODE_BIN="${NODE_BIN:-/Users/simon/.nvm/versions/node/v24.14.1/bin/node}"
[[ -x "$NODE_BIN" ]] || NODE_BIN="$(command -v node)"

postgres_url_swap_database() { # full-url database-name
  local url="$1" db="$2" head tail
  if [[ "$url" == *\?* ]]; then head="${url%%\?*}"; tail="?${url#*\?}"; else head="$url"; tail=""; fi
  head="${head%/*}"
  print -r -- "$head/$db$tail"
}

# Canonical-only DB design (2026-07-08): TS_PROD_POSTGRES_URL is the canonical
# external app-db URL (from op://TS-sensitive/PROD_POSTGRES_URL). Every other TS
# prod shape is DERIVED from it here — nothing read from the 1Password env mount.
# The prefect db name is a fixed topology constant, mirroring ts-prefect
# scripts/secrets/lib.sh `_db_topology` (prod prefect db = "prefect"); override
# TS_PROD_PREFECT_DATABASE_NAME only if that infra constant ever changes.
TS_PROD_PREFECT_DB="${TS_PROD_PREFECT_DATABASE_NAME:-prefect}"
# 1Password item values can carry stray leading/trailing whitespace or newlines
# (a leading newline in PROD_POSTGRES_URL_RO made psycopg reject the URL as
# conninfo, 2026-07-09). Strip all whitespace from every postgres URL — URLs
# never legitimately contain it.
for _v in TS_PROD_POSTGRES_URL TS_POSTGRES_STAGING_URL TS_POSTGRES_DEV_URL \
          TS_POSTGRES_AUTODEV_TS_URL AMARU_POSTGRES_PROD_URL AMARU_POSTGRES_STAGING_URL \
          AMARU_POSTGRES_DEV_URL WORKFLOW_POSTGRES_PROD_URL WORKFLOW_POSTGRES_STAGING_URL \
          WORKFLOW_POSTGRES_DEV_URL AUTODEV_GLOBAL_POSTGRES_URL; do
  [[ -n "${(P)_v:-}" ]] && export "$_v"="${${(P)_v}//[$'\r\n\t ']/}"
done
unset _v
if [[ -n "${TS_PROD_POSTGRES_URL:-}" ]]; then
  export TS_POSTGRES_PROD_URL="$TS_PROD_POSTGRES_URL"
  export TS_POSTGRES_PROD_PREFECT_URL="$(postgres_url_swap_database "$TS_PROD_POSTGRES_URL" "$TS_PROD_PREFECT_DB")"
else
  print -u2 "mcp-gateway: warning — TS_PROD_POSTGRES_URL empty; ts/postgres_prod* routes will 502 until set"
fi
unset TS_PROD_POSTGRES_URL TS_PROD_DATABASE_NAME TS_PROD_PREFECT_DATABASE_NAME TS_PROD_PREFECT_DB

exec "$NODE_BIN" "$HERE/gateway.mjs"

# shellcheck shell=bash
# db-url.sh — value-silent Postgres URL helpers (port of amaru scripts/db/lib.sh).
# Sourced by the postgres rotation provider; no `op` access, no network.
#
# Usage:
#   db_parse_url "$url"            # -> DB_URL_{USER,PASS,HOST,PORT,DB,QUERY}
#   db_url_username "$url"         # -> decoded username on stdout
#   db_compose_url base user pw [role]
#   db_rehost_url source target    # credentials from source, host/db from target
#   db_run_psql_url url [args...]  # PG* env subshell exec psql -X (stdin flows)

db_urldecode() {
	local s="${1//+/ }"
	printf '%b' "${s//%/\\x}"
}

db_parse_url() { # url -> DB_URL_{USER,PASS,HOST,PORT,DB,QUERY}
	local url="$1"
	[[ "$url" =~ ^postgres(ql)?://(([^:@/]+)(:([^@]*))?@)?([^:/?]+)(:([0-9]+))?/([^?]+)(\?(.*))?$ ]] || {
		echo "ERROR: database URL did not parse as postgres://[user[:pass]@]host[:port]/db" >&2
		return 3
	}
	DB_URL_USER="${BASH_REMATCH[3]}"
	DB_URL_PASS="${BASH_REMATCH[5]}"
	DB_URL_HOST="${BASH_REMATCH[6]}"
	DB_URL_PORT="${BASH_REMATCH[8]:-5432}"
	DB_URL_DB="${BASH_REMATCH[9]}"
	DB_URL_QUERY="${BASH_REMATCH[11]:-}"
}

db_url_username() {
	local DB_URL_USER DB_URL_PASS DB_URL_HOST DB_URL_PORT DB_URL_DB DB_URL_QUERY
	db_parse_url "$1" || return $?
	db_urldecode "$DB_URL_USER"
}

db_query_without_options() {
	local query="$1" part out=""
	local parts=()
	IFS='&' read -r -a parts < <(printf '%s\n' "$query")
	for part in "${parts[@]-}"; do
		[[ -n "$part" && "$part" != options=* ]] || continue
		if [[ -n "$out" ]]; then out="$out&$part"; else out="$part"; fi
	done
	printf %s "$out"
}

db_query_option() { # query key -> raw encoded value
	local query="$1" key="$2" part
	local parts=()
	IFS='&' read -r -a parts < <(printf '%s\n' "$query")
	for part in "${parts[@]-}"; do
		if [[ "$part" == "$key="* ]]; then
			printf %s "${part#*=}"
			return 0
		fi
	done
	return 1
}

db_with_role_option() { # url role -> url
	local url="$1" role="$2"
	local DB_URL_USER DB_URL_PASS DB_URL_HOST DB_URL_PORT DB_URL_DB DB_URL_QUERY query
	db_parse_url "$url" || return $?
	query="$(db_query_without_options "$DB_URL_QUERY")"
	[[ -n "$query" ]] && query="$query&"
	query="${query}options=-c%20role%3D${role}"
	printf 'postgresql://%s:%s@%s:%s/%s?%s' \
		"$DB_URL_USER" "$DB_URL_PASS" "$DB_URL_HOST" "$DB_URL_PORT" "$DB_URL_DB" "$query"
}

db_compose_url() { # base_url raw_user raw_password [set_role] -> url
	local base="$1" user="$2" pass="$3" role="${4:-}"
	local DB_URL_USER DB_URL_PASS DB_URL_HOST DB_URL_PORT DB_URL_DB DB_URL_QUERY query url
	db_parse_url "$base" || return $?
	query="$(db_query_without_options "$DB_URL_QUERY")"
	url="postgresql://${user}:${pass}@${DB_URL_HOST}:${DB_URL_PORT}/${DB_URL_DB}"
	[[ -n "$query" ]] && url="$url?$query"
	if [[ -n "$role" ]]; then db_with_role_option "$url" "$role"; else printf %s "$url"; fi
}

db_url_with_database() { # url database -> url (same credentials/host/query, different db)
	local url="$1" database="$2"
	local DB_URL_USER DB_URL_PASS DB_URL_HOST DB_URL_PORT DB_URL_DB DB_URL_QUERY out
	db_parse_url "$url" || return $?
	out="postgresql://${DB_URL_USER}:${DB_URL_PASS}@${DB_URL_HOST}:${DB_URL_PORT}/${database}"
	[[ -n "$DB_URL_QUERY" ]] && out="$out?$DB_URL_QUERY"
	printf %s "$out"
}

db_rehost_url() { # source_credentials_url target_host_url -> url
	local source="$1" target="$2"
	local source_user source_pass source_query target_host target_port target_db target_query role_options query
	local DB_URL_USER DB_URL_PASS DB_URL_HOST DB_URL_PORT DB_URL_DB DB_URL_QUERY
	db_parse_url "$source" || return $?
	source_user="$DB_URL_USER" source_pass="$DB_URL_PASS" source_query="$DB_URL_QUERY"
	db_parse_url "$target" || return $?
	target_host="$DB_URL_HOST" target_port="$DB_URL_PORT" target_db="$DB_URL_DB" target_query="$DB_URL_QUERY"
	query="$(db_query_without_options "$target_query")"
	role_options="$(db_query_option "$source_query" options 2>/dev/null || true)"
	if [[ -n "$role_options" ]]; then
		[[ -n "$query" ]] && query="$query&"
		query="${query}options=${role_options}"
	fi
	printf 'postgresql://%s:%s@%s:%s/%s' "$source_user" "$source_pass" "$target_host" "$target_port" "$target_db"
	# NOTE: guarded printf must not decide the function's exit status — a
	# query-less URL is valid (upstream amaru lib.sh returned 1 here).
	if [[ -n "$query" ]]; then printf '?%s' "$query"; fi
	return 0
}

db_run_psql_url() { # url [psql args...] ; stdin flows through
	local url="$1"
	shift
	local DB_URL_USER DB_URL_PASS DB_URL_HOST DB_URL_PORT DB_URL_DB DB_URL_QUERY
	db_parse_url "$url" || return $?
	local sslmode="" options=""
	sslmode="$(db_query_option "$DB_URL_QUERY" sslmode 2>/dev/null || true)"
	options="$(db_query_option "$DB_URL_QUERY" options 2>/dev/null || true)"
	[[ -n "$options" ]] && options="$(db_urldecode "$options")"
	(
		export PGHOST="$DB_URL_HOST" PGPORT="$DB_URL_PORT" PGDATABASE="$DB_URL_DB" PGCONNECT_TIMEOUT=15
		if [[ -n "$DB_URL_USER" ]]; then export PGUSER="$(db_urldecode "$DB_URL_USER")"; fi
		if [[ -n "$DB_URL_PASS" ]]; then export PGPASSWORD="$(db_urldecode "$DB_URL_PASS")"; fi
		if [[ -n "$sslmode" ]]; then export PGSSLMODE="$sslmode"; fi
		if [[ -n "$options" ]]; then export PGOPTIONS="$options"; fi
		exec "${PSQL_BIN:-psql}" -X "$@"
	)
}

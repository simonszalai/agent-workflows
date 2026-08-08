# shellcheck shell=bash
# db-rotation.sh — testable rotation activation state machine + Render evidence
# helpers (port of amaru scripts/db/rotation-lib.sh, project-neutral).
#
# Callers provide value-silent callbacks:
#   rotation_get_env sid key                  -> value on stdout
#   rotation_put_env sid key                  <- value on stdin
#   rotation_trigger_deploy sid               -> deploy id on stdout
#   rotation_wait_deploy sid deploy_id
#   rotation_probe_service sid
#   all_old_logins                            -> one predecessor login per line
#   render_get path                           -> Render API GET (render-api.sh)
# Global aligned arrays: ROTATION_SIDS, ROTATION_ENVS, ROTATION_NEW_VALUES.

rotation_unique_services() {
	local sid seen=""
	for sid in "${ROTATION_SIDS[@]-}"; do
		[[ " $seen " == *" $sid "* ]] && continue
		seen="${seen:+$seen }$sid"
		printf '%s\n' "$sid"
	done
}

rotation_probe_all_services() {
	local sid
	while IFS= read -r sid; do
		[[ -n "$sid" ]] || continue
		if ! rotation_probe_service "$sid"; then
			return 1
		fi
	done < <(rotation_unique_services)
}

# One fail-closed application health attempt. Redirects are not followed and
# are not accepted; HTTP 200 is necessary but insufficient. The endpoint must
# also attest that the process started with a safe database role.
rotation_probe_health_once() { # url
	local url="$1" body_file status
	body_file="$(mktemp "${TMPDIR:-/tmp}/db-rotation-health.XXXXXX")" || return $?
	status="$(curl --silent --show-error --max-time 20 \
		--output "$body_file" --write-out '%{http_code}' "$url")" || {
		rm -f "$body_file"
		return 1
	}
	if [[ "$status" != "200" ]] || ! jq -e '
		type == "object"
		and .status == "ok"
		and .databaseRoleSafe == true' "$body_file" >/dev/null 2>&1; then
		rm -f "$body_file"
		return 1
	fi
	rm -f "$body_file"
}

# Render credential evidence is authoritative only when the response is an
# array, a username appears at most once, and openConnections is a non-negative
# integer. A missing record means the provider credential is already absent;
# a missing/null counter on a present record is incomplete evidence.
rotation_render_credential_open_connections() { # credentials-json username
	local json="$1" username="$2"
	jq -er --arg user "$username" '
		if type != "array" then error("credentials response is not an array")
		elif ([.[] | select(.username == $user)] | length) > 1 then error("duplicate credential")
		elif ([.[] | select(.username == $user)] | length) == 0 then 0
		else .[] | select(.username == $user)
			| if (.openConnections | type) == "number" and .openConnections >= 0 and (.openConnections | floor) == .openConnections
			  then .openConnections
			  else error("openConnections is missing or invalid") end
		end' < <(printf '%s' "$json")
}

rotation_restore_predeploy_values() {
	local applied="$1" i=0 failed=0
	while [[ $i -lt $applied ]]; do
		if printf %s "${ROTATION_OLD_VALUES[$i]}" | rotation_put_env "${ROTATION_SIDS[$i]}" "${ROTATION_ENVS[$i]}"; then
			echo "  render[${ROTATION_SIDS[$i]}] ${ROTATION_ENVS[$i]} restored"
		else
			echo "ERROR: render[${ROTATION_SIDS[$i]}] ${ROTATION_ENVS[$i]} restore failed; both database logins remain valid" >&2
			failed=1
		fi
		i=$((i + 1))
	done
	return "$failed"
}

rotation_activate() {
	local total="${#ROTATION_SIDS[@]}" i=0 sid deploy_id value="" trigger_failed=0
	[[ "$total" -gt 0 && "$total" -eq "${#ROTATION_ENVS[@]}" && "$total" -eq "${#ROTATION_NEW_VALUES[@]}" ]] || {
		echo "ERROR: rotation activation rows are empty or misaligned" >&2
		return 2
	}

	ROTATION_OLD_VALUES=()
	ROTATION_DEPLOY_SIDS=()
	ROTATION_DEPLOY_IDS=()

	# Snapshot the whole live batch before the first write. Values remain only in
	# process memory and are used solely for a pre-deploy restore.
	while [[ $i -lt $total ]]; do
		if ! value="$(rotation_get_env "${ROTATION_SIDS[$i]}" "${ROTATION_ENVS[$i]}")" || [[ -z "$value" ]]; then
			echo "ERROR: could not snapshot render[${ROTATION_SIDS[$i]}] ${ROTATION_ENVS[$i]}; nothing written" >&2
			return 3
		fi
		ROTATION_OLD_VALUES+=("$value")
		value=""
		i=$((i + 1))
	done

	# All values are written before any deployment is triggered. If a PUT fails,
	# no new process can have consumed the batch, so restore every earlier PUT.
	i=0
	while [[ $i -lt $total ]]; do
		if printf %s "${ROTATION_NEW_VALUES[$i]}" | rotation_put_env "${ROTATION_SIDS[$i]}" "${ROTATION_ENVS[$i]}"; then
			echo "  render[${ROTATION_SIDS[$i]}] ${ROTATION_ENVS[$i]} staged"
		else
			echo "ERROR: render[${ROTATION_SIDS[$i]}] ${ROTATION_ENVS[$i]} PUT failed; restoring pre-deploy values" >&2
			# A network error can arrive after Render committed the failed PUT.
			# Restore the entire snapshot, including the nominally failed row and
			# rows not attempted yet, so a later unrelated deploy cannot activate a
			# partially staged credential batch.
			rotation_restore_predeploy_values "$total" || return 4
			return 4
		fi
		i=$((i + 1))
	done

	# Trigger every service before waiting for any one service. Once the first
	# trigger is accepted, do not restore env values underneath an in-flight
	# deploy. The predecessor credential remains valid and the state is resumable.
	while IFS= read -r sid; do
		[[ -n "$sid" ]] || continue
		if ! deploy_id="$(rotation_trigger_deploy "$sid")" || [[ -z "$deploy_id" ]]; then
			echo "ERROR: render[$sid] deploy trigger was not confirmed; no predecessor will be retired" >&2
			trigger_failed=1
			continue
		fi
		ROTATION_DEPLOY_SIDS+=("$sid")
		ROTATION_DEPLOY_IDS+=("$deploy_id")
		echo "  render[$sid] deploy $deploy_id triggered"
	done < <(rotation_unique_services)
	# Every service is attempted even when an earlier trigger is ambiguous. No
	# deploy is waited/attested unless the complete trigger batch is confirmed.
	[[ "$trigger_failed" -eq 0 ]] || return 5

	i=0
	while [[ $i -lt ${#ROTATION_DEPLOY_IDS[@]} ]]; do
		if ! rotation_wait_deploy "${ROTATION_DEPLOY_SIDS[$i]}" "${ROTATION_DEPLOY_IDS[$i]}"; then
			echo "ERROR: render[${ROTATION_DEPLOY_SIDS[$i]}] deploy ${ROTATION_DEPLOY_IDS[$i]} did not become live; no predecessor will be retired" >&2
			return 6
		fi
		i=$((i + 1))
	done

	if declare -F rotation_probe_service >/dev/null 2>&1; then
		for sid in "${ROTATION_DEPLOY_SIDS[@]-}"; do
			[[ -n "$sid" ]] || continue
			if ! rotation_probe_service "$sid"; then
				echo "ERROR: render[$sid] public health probe failed; no predecessor will be retired" >&2
				return 7
			fi
		done
	fi

	ROTATION_OLD_VALUES=()
	return 0
}

rotation_urlencode() { jq -nr --arg value "$1" '$value|@uri'; }

# Exhaustive undeclared-consumer inventory: word-boundary scan for every
# predecessor login across every Render service env var / secret file (cursor
# paginated, previews included) and every env group. Fail-closed shape checks;
# unprovable completeness returns 2, a found reference returns 1.
render_inventory_has_predecessor() {
	local regex="" user service_cursor="" service_page service_ids sid env_cursor env_page secret_cursor secret_page
	local group_page group_ids gid group_detail matches found=0 next length pages=0 env_pages secret_pages marker
	# A predecessor login is only dangerous where it can authenticate: a value
	# must ALSO reference this instance's host (db id marker) to count. Bare
	# role names in EXPECTED_DB_ROLE-style vars or same-named logins on other
	# instances are not credentials for this box. Fail closed without a marker.
	marker="${ROTATION_INSTANCE_MARKER:-}"
	[[ -n "$marker" ]] || { echo "ERROR: ROTATION_INSTANCE_MARKER is unset; cannot scope the predecessor scan." >&2; return 2; }
	while IFS= read -r user; do regex="${regex:+$regex|}$user"; done < <(all_old_logins)
	[[ -n "$regex" ]] || return 1
	regex="(^|[^A-Za-z0-9_])(${regex})([^A-Za-z0-9_]|$)"

	while :; do
		service_page="$(render_get "/services?limit=100&includePreviews=true${service_cursor:+&cursor=$(rotation_urlencode "$service_cursor")}")" || return 2
		jq -e 'type == "array" and all(.[];
			(.service.id | type) == "string"
			and (.cursor | type) == "string" and (.cursor | length) > 0)' \
			< <(printf '%s' "$service_page") >/dev/null || { echo "ERROR: Render service inventory response shape is invalid." >&2; return 2; }
		service_ids="$(printf '%s' "$service_page" | jq -r '.[].service.id')" || return 2
		while IFS= read -r sid; do
			[[ -n "$sid" ]] || continue
			env_cursor=""
			env_pages=0
			while :; do
				env_page="$(render_get "/services/${sid}/env-vars?limit=100${env_cursor:+&cursor=$(rotation_urlencode "$env_cursor")}")" || return 2
				jq -e 'type == "array" and all(.[];
					(.envVar.key | type) == "string" and (.envVar.value | type) == "string"
					and (.cursor | type) == "string" and (.cursor | length) > 0)' \
					< <(printf '%s' "$env_page") >/dev/null || { echo "ERROR: render[$sid] env inventory response shape is invalid." >&2; return 2; }
				matches="$(printf '%s' "$env_page" | jq -r --arg re "$regex" --arg marker "$marker" '.[] | select((.envVar.value | test($re)) and (.envVar.value | contains($marker))) | .envVar.key')" || return 2
				while IFS= read -r match; do [[ -n "$match" ]] && { echo "ERROR: predecessor reference remains at render[$sid] env $match" >&2; found=1; }; done < <(printf '%s\n' "$matches")
				next="$(printf '%s' "$env_page" | jq -r 'if length == 0 then "" else .[-1].cursor // "" end')" || return 2
				length="$(printf '%s' "$env_page" | jq -r 'length')" || return 2
				[[ "$length" -gt 0 ]] || break
				[[ "$next" != "$env_cursor" ]] || { echo "ERROR: render[$sid] env inventory cursor repeated." >&2; return 2; }
				env_cursor="$next"
				env_page=""
				env_pages=$((env_pages + 1)); [[ "$env_pages" -lt 1000 ]] || { echo "ERROR: render[$sid] env inventory pagination exceeded its bound." >&2; return 2; }
			done

			secret_cursor=""
			secret_pages=0
			while :; do
				secret_page="$(render_get "/services/${sid}/secret-files?limit=100${secret_cursor:+&cursor=$(rotation_urlencode "$secret_cursor")}")" || return 2
				jq -e 'type == "array" and all(.[];
					(.secretFile.name | type) == "string" and (.secretFile.content | type) == "string"
					and (.cursor | type) == "string" and (.cursor | length) > 0)' \
					< <(printf '%s' "$secret_page") >/dev/null || { echo "ERROR: render[$sid] secret-file inventory response shape is invalid." >&2; return 2; }
				matches="$(printf '%s' "$secret_page" | jq -r --arg re "$regex" --arg marker "$marker" '.[] | select((.secretFile.content | test($re)) and (.secretFile.content | contains($marker))) | .secretFile.name')" || return 2
				while IFS= read -r match; do [[ -n "$match" ]] && { echo "ERROR: predecessor reference remains at render[$sid] secret-file $match" >&2; found=1; }; done < <(printf '%s\n' "$matches")
				next="$(printf '%s' "$secret_page" | jq -r 'if length == 0 then "" else .[-1].cursor // "" end')" || return 2
				length="$(printf '%s' "$secret_page" | jq -r 'length')" || return 2
				[[ "$length" -gt 0 ]] || break
				[[ "$next" != "$secret_cursor" ]] || { echo "ERROR: render[$sid] secret-file inventory cursor repeated." >&2; return 2; }
				secret_cursor="$next"
				secret_page=""
				secret_pages=$((secret_pages + 1)); [[ "$secret_pages" -lt 1000 ]] || { echo "ERROR: render[$sid] secret-file inventory pagination exceeded its bound." >&2; return 2; }
			done
		done < <(printf '%s\n' "$service_ids")
		next="$(printf '%s' "$service_page" | jq -r 'if length == 0 then "" else .[-1].cursor // "" end')" || return 2
		length="$(printf '%s' "$service_page" | jq -r 'length')" || return 2
		[[ "$length" -gt 0 ]] || break
		[[ "$next" != "$service_cursor" ]] || { echo "ERROR: Render service inventory cursor repeated." >&2; return 2; }
		service_cursor="$next"
		service_page=""
		pages=$((pages + 1)); [[ "$pages" -lt 1000 ]] || { echo "ERROR: Render service inventory pagination exceeded its bound." >&2; return 2; }
	done

	# Render's published env-group response has no cursor field even though the
	# endpoint accepts a cursor parameter. A short page is therefore the only
	# complete result the API contract lets us prove; a full page fails closed.
	group_page="$(render_get "/env-groups?limit=100")" || return 2
	jq -e 'type == "array" and all(.[];
		(.id | type) == "string" and (.id | length) > 0)' \
		< <(printf '%s' "$group_page") >/dev/null || { echo "ERROR: Render env-group inventory response shape is invalid." >&2; return 2; }
	length="$(printf '%s' "$group_page" | jq -r 'length')" || return 2
	[[ "$length" -lt 100 ]] || { echo "ERROR: Render env-group inventory cannot prove completeness at the API page limit." >&2; return 2; }
	group_ids="$(printf '%s' "$group_page" | jq -r '.[].id')" || return 2
	while IFS= read -r gid; do
		[[ -n "$gid" ]] || continue
		group_detail="$(render_get "/env-groups/${gid}")" || return 2
		jq -e 'type == "object"
			and (.envVars | type) == "array"
			and (.secretFiles | type) == "array"
			and all(.envVars[]; (.key | type) == "string" and (.value | type) == "string")
			and all(.secretFiles[]; (.name | type) == "string" and (.content | type) == "string")' \
			< <(printf '%s' "$group_detail") >/dev/null || { echo "ERROR: render env-group[$gid] detail response shape is invalid." >&2; return 2; }
		matches="$(jq -r --arg re "$regex" --arg marker "$marker" '
			(.envVars[] | select((.value | test($re)) and (.value | contains($marker))) | "env " + .key),
			(.secretFiles[] | select((.content | test($re)) and (.content | contains($marker))) | "secret-file " + .name)' < <(printf '%s' "$group_detail"))" || return 2
		while IFS= read -r match; do [[ -n "$match" ]] && { echo "ERROR: predecessor reference remains at render env-group[$gid] $match" >&2; found=1; }; done < <(printf '%s\n' "$matches")
		group_detail=""
	done < <(printf '%s\n' "$group_ids")

	[[ "$found" -eq 0 ]]
}

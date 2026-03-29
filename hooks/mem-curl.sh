#!/usr/bin/env bash
# =============================================================================
# mem-curl.sh — Shared curl wrapper for autodev-memory hooks
# =============================================================================
#
# Wraps curl to capture HTTP status codes and detect API error responses.
# Without this, hooks silently treat HTTP 500 / error JSON as "0 results".
#
# Usage:
#   source "$HOOK_DIR/mem-curl.sh"
#   RESULT=$(mem_curl GET "/entries/starred?project=ts")
#   RESULT=$(mem_curl POST "/search" "$JSON_BODY")
#
# On success: prints the response body, returns 0
# On failure: prints an error message prefixed with "ERROR:", returns 1
#
# Requires: MEM_URL, MEM_TOKEN (from mem-env.sh)
# =============================================================================

# Resolve git branch once at source time (available to all mem_curl calls)
_MEM_GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")

mem_curl() {
  local method="$1"
  local path="$2"
  local body="${3:-}"
  local hook_source="${4:-hook}"

  local curl_args=(
    -sS
    --max-time 30
    -w '\n%{http_code}'
    -H "Authorization: Bearer $MEM_TOKEN"
    -H "X-Hook-Source: $hook_source"
    -H "X-Session-Id: ${MEM_SESSION_ID:-}"
    -H "X-Claude-Session-Id: ${MEM_CLAUDE_SESSION_ID:-}"
    -H "X-Conductor-Title: ${MEM_CONDUCTOR_TITLE:-}"
    -H "X-Repo: ${MEM_REPO:-}"
    -H "X-Cwd: ${_MEM_LOG_CWD:-}"
    -H "X-Trigger-Source: ${MEM_TRIGGER_SOURCE:-}"
    -H "X-Git-Branch: ${_MEM_GIT_BRANCH:-}"
    -H "X-User-Prompt: ${MEM_USER_PROMPT:-}"
    -H "X-Workspace: ${CONDUCTOR_WORKSPACE_NAME:-}"
    -H "X-Conductor-Root: ${CONDUCTOR_ROOT_PATH:-}"
  )

  if [[ "$method" == "POST" ]]; then
    curl_args+=(-X POST -H "Content-Type: application/json" -d "$body")
  fi

  local raw_output
  raw_output=$(curl "${curl_args[@]}" "${MEM_URL}${path}" 2>&1) || {
    echo "ERROR: curl failed: $raw_output"
    return 1
  }

  # Split response body from HTTP status code (last line)
  local http_code
  http_code=$(echo "$raw_output" | tail -1)
  local response_body
  response_body=$(echo "$raw_output" | sed '$d')

  # Check HTTP status
  if [[ "$http_code" -lt 200 || "$http_code" -ge 300 ]] 2>/dev/null; then
    local detail
    detail=$(echo "$response_body" | jq -r '.detail // .error // empty' 2>/dev/null || true)
    if [[ -n "$detail" ]]; then
      echo "ERROR: HTTP $http_code — $detail"
    else
      echo "ERROR: HTTP $http_code — $(echo "$response_body" | head -c 500)"
    fi
    return 1
  fi

  # Check for error field in response body (some API errors return 200 with error key)
  local api_error
  api_error=$(echo "$response_body" | jq -r '.error // empty' 2>/dev/null || true)
  if [[ -n "$api_error" ]]; then
    echo "ERROR: API error — $api_error"
    return 1
  fi

  echo "$response_body"
  return 0
}

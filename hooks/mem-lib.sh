#!/usr/bin/env bash
# =============================================================================
# mem-lib.sh — Shared library for autodev-memory hooks
# =============================================================================
#
# Consolidates logging, env parsing, initialization, HTTP requests, and
# entry loading. Source after mem-err-trap.sh.
#
# Usage:
#   source "$HOOK_DIR/mem-err-trap.sh"
#   _HOOK_EVENT_NAME="SessionStart"
#   source "$HOOK_DIR/mem-lib.sh"
#   INPUT=$(cat)
#   mem_init "$INPUT"
#   case "$MEM_INIT_STATUS" in
#     skip)  echo '{}'; exit 0 ;;
#     error) mem_init_offline_output "session-start" "SessionStart"; exit 0 ;;
#   esac
#   MEM_TRIGGER_SOURCE="session_start"
#   mem_load_entries
#   # Sets: STARRED_RESULT, STARRED_COUNT, MENU_RESULT, MENU_COUNT,
#   #       TOTAL_COUNT, _LOAD_ERROR
# =============================================================================


# =============================================================================
# Logging
# =============================================================================

_MEM_LOG_DIR="$HOME/.config/autodev-memory"
_MEM_LOG_FILE="$_MEM_LOG_DIR/hooks.log"
_MEM_LOG_MAX_BYTES=1048576  # 1MB
_MEM_LOG_HOOK_NAME=$(basename "${0:-unknown}" .sh)
_MEM_LOG_CWD=""

mkdir -p "$_MEM_LOG_DIR" 2>/dev/null || true

mem_log() {
  local level="$1"; shift
  local message="$*"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')

  if [[ ${#message} -gt 2000 ]]; then
    message="${message:0:2000}...[truncated]"
  fi

  local cwd_tag=""
  if [[ -n "$_MEM_LOG_CWD" ]]; then
    cwd_tag=" cwd=$_MEM_LOG_CWD"
  fi
  printf '%s [%-14s] %-5s%s %s\n' \
    "$timestamp" "$_MEM_LOG_HOOK_NAME" "$level" "$cwd_tag" "$message" \
    >> "$_MEM_LOG_FILE" 2>/dev/null || true

  if [[ -f "$_MEM_LOG_FILE" ]]; then
    local size
    size=$(wc -c < "$_MEM_LOG_FILE" 2>/dev/null || echo 0)
    if [[ $size -gt $_MEM_LOG_MAX_BYTES ]]; then
      tail -c 524288 "$_MEM_LOG_FILE" > "$_MEM_LOG_FILE.tmp" 2>/dev/null
      mv "$_MEM_LOG_FILE.tmp" "$_MEM_LOG_FILE" 2>/dev/null || true
    fi
  fi
}

mem_log_output() {
  local json="$1"
  local ctx
  ctx=$(echo "$json" | jq -r '.hookSpecificOutput.additionalContext // "(empty)"' 2>/dev/null || echo "(parse failed)")
  mem_log DEBUG "output -> $ctx"
}


# =============================================================================
# Environment parsing (internal)
# =============================================================================

_mem_parse_env() {
  local input="$1"
  _MEM_ENV_SKIP=""

  # Load env from dotfile
  if [[ -f "$HOME/.config/autodev-memory/.env" ]]; then
    set -a; source "$HOME/.config/autodev-memory/.env"; set +a
  fi

  # CWD: different hook events use different schemas
  _CWD=$(echo "$input" | jq -r '(.cwd // .session.cwd) // empty' 2>/dev/null)
  if [[ -z "$_CWD" ]]; then
    echo "HOOK ERROR [mem-lib]: no cwd found in hook input" >&2
    return 1
  fi
  _MEM_LOG_CWD=$(basename "$_CWD")

  # Parse mem stub from CLAUDE.md
  local claude_md="$_CWD/CLAUDE.md"
  if [[ ! -f "$claude_md" ]]; then
    _MEM_ENV_SKIP=1; return 0
  fi

  # Support both formats: <!-- mem:project=X repo=Y --> and <!-- mem:project=X -->
  local mem_line
  mem_line=$(grep -o '<!-- mem:project=[^ ]* repo=[^ ]* -->' "$claude_md" 2>/dev/null || true)
  if [[ -z "$mem_line" ]]; then
    mem_line=$(grep -o '<!-- mem:project=[^ ]* -->' "$claude_md" 2>/dev/null || true)
  fi
  if [[ -z "$mem_line" ]]; then
    _MEM_ENV_SKIP=1; return 0
  fi

  MEM_PROJECT=$(echo "$mem_line" | sed 's/.*project=\([^ ]*\).*/\1/' | sed 's/ *-->//')

  # Auto-detect repo from git remote
  local git_remote
  git_remote=$(git -C "$_CWD" remote get-url origin 2>/dev/null || true)
  if [[ -n "$git_remote" ]]; then
    MEM_REPO=$(echo "$git_remote" | sed 's/.*[/:]\([^/]*\)\.git$/\1/' | sed 's/.*[/:]\([^/]*\)$/\1/')
    MEM_GITHUB_URL=$(echo "$git_remote" | sed 's|^git@github\.com:|https://github.com/|' | sed 's|\.git$||')
  else
    MEM_REPO=$(echo "$mem_line" | sed -n 's/.*repo=\([^ ]*\).*/\1/p' | sed 's/ *-->//')
    MEM_GITHUB_URL=""
    if [[ -z "$MEM_REPO" ]]; then
      MEM_REPO=$(basename "$_CWD")
    fi
  fi

  MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
  MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"
  if [[ -z "$MEM_TOKEN" ]]; then
    echo "HOOK ERROR [mem-lib]: AUTODEV_MEMORY_API_TOKEN not set" >&2
    return 1
  fi

  # Fetch topology
  local topo_raw topo_http topo_body
  topo_raw=$(curl -sS --max-time 15 \
    -w '\n%{http_code}' \
    -H "Authorization: Bearer $MEM_TOKEN" \
    "$MEM_URL/topology?project=$MEM_PROJECT" 2>&1) || {
    echo "HOOK ERROR [mem-lib]: memory API unreachable at $MEM_URL: $topo_raw" >&2
    return 1
  }
  topo_http=$(echo "$topo_raw" | tail -1)
  topo_body=$(echo "$topo_raw" | sed '$d')

  if [[ "$topo_http" -lt 200 || "$topo_http" -ge 300 ]] 2>/dev/null; then
    local detail
    detail=$(echo "$topo_body" | jq -r '.detail // .error // empty' 2>/dev/null || true)
    echo "HOOK ERROR [mem-lib]: topology API returned HTTP $topo_http: ${detail:-$topo_body}" >&2
    return 1
  fi

  MEM_TOPOLOGY=$(echo "$topo_body" | jq -r '
    "Project: " + .project + " \u2014 " + .project_description + "\nRepos:\n" +
    ([.repos[] | "  - " + .repo_name + ": " + .repo_description +
      (if (.tech_tags | length) > 0 then " [" + (.tech_tags | join(", ")) + "]" else "" end)
    ] | join("\n"))
  ' 2>/dev/null)
  if [[ -z "$MEM_TOPOLOGY" ]]; then
    echo "HOOK ERROR [mem-lib]: failed to parse topology: $topo_body" >&2
    return 1
  fi

  MEM_TECH_TAGS=$(echo "$topo_body" | jq -r --arg repo "$MEM_REPO" '
    [.repos[] | select(.repo_name == $repo) | .tech_tags // [] | .[]] | join(",")
  ' 2>/dev/null || echo "")

  MEM_SIBLING_REPOS=$(echo "$topo_body" | jq -r --arg repo "$MEM_REPO" '
    [.repos[] | select(.repo_name != $repo) | .repo_name] | join(",")
  ' 2>/dev/null || echo "")

  MEM_SIBLING_REPOS_DETAIL=$(echo "$topo_body" | jq -r --arg repo "$MEM_REPO" '
    [.repos[] | select(.repo_name != $repo) |
      "- **" + .repo_name + "**: " + (.repo_description // "no description") +
      (if (.tech_tags | length) > 0 then " [" + (.tech_tags | join(", ")) + "]" else "" end)
    ] | join("\n")
  ' 2>/dev/null || echo "")

  # Session ID resolution (Claude session ID → stable Conductor session ID)
  MEM_CLAUDE_SESSION_ID=$(echo "$input" | jq -r '.session_id // .sessionId // empty' 2>/dev/null)
  MEM_SESSION_ID=""
  MEM_CONDUCTOR_TITLE=""
  if [[ -n "$MEM_CLAUDE_SESSION_ID" ]]; then
    local conductor_db="$HOME/Library/Application Support/com.conductor.app/conductor.db"
    if [[ -f "$conductor_db" ]]; then
      local conductor_row
      conductor_row=$(sqlite3 -separator $'\t' "$conductor_db" \
        "SELECT id, title FROM sessions WHERE claude_session_id = '$MEM_CLAUDE_SESSION_ID' LIMIT 1;" 2>/dev/null || true)
      if [[ -n "$conductor_row" ]]; then
        MEM_SESSION_ID=$(echo "$conductor_row" | cut -f1)
        MEM_CONDUCTOR_TITLE=$(echo "$conductor_row" | cut -f2-)
      fi
    fi
    if [[ -z "$MEM_SESSION_ID" ]]; then
      MEM_SESSION_ID="$MEM_CLAUDE_SESSION_ID"
    fi
  fi

  # User prompt (available in SessionStart)
  local raw_prompt
  raw_prompt=$(echo "$input" | jq -r '.prompt // empty' 2>/dev/null || true)
  if [[ -n "$raw_prompt" ]]; then
    MEM_USER_PROMPT=$(echo "$raw_prompt" | head -c 200 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')
  else
    MEM_USER_PROMPT=""
  fi

  export MEM_PROJECT MEM_REPO MEM_URL MEM_TOKEN MEM_TOPOLOGY MEM_TECH_TAGS MEM_GITHUB_URL
  export MEM_SESSION_ID MEM_CLAUDE_SESSION_ID MEM_CONDUCTOR_TITLE MEM_USER_PROMPT
  export MEM_SIBLING_REPOS MEM_SIBLING_REPOS_DETAIL
}


# =============================================================================
# Initialization
# =============================================================================

mem_init() {
  local input="$1"
  MEM_INIT_STATUS="ok"
  MEM_INIT_ERROR=""

  if ! _mem_parse_env "$input"; then
    MEM_INIT_STATUS="error"
    MEM_INIT_ERROR=$(cat "$_ERR_FILE" 2>/dev/null || true)
    mem_log ERROR "env parse failed: $MEM_INIT_ERROR"
    return 0
  fi

  if [[ -n "${_MEM_ENV_SKIP:-}" ]]; then
    MEM_INIT_STATUS="skip"
    mem_log INFO "skip (no mem config)"
    return 0
  fi

  # Resolve git branch once (used in curl headers)
  _MEM_GIT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
}

mem_init_offline_output() {
  local source="$1"
  local event="$2"
  local message="${3:-memory API unreachable}"

  exec 2>&3
  : > "$_ERR_FILE" 2>/dev/null || true

  local warning="<autodev-memory-hook-result source=\"$source\" status=\"error\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: OFFLINE -- $message

The autodev-memory API is not reachable. Starred entries and search are unavailable.
Tell the user the memory system is offline so they can start it if needed.
</autodev-memory-hook-result>"

  jq -n --arg ctx "$warning" --arg event "$event" \
    '{hookSpecificOutput: {hookEventName: $event, additionalContext: $ctx}}'
}


# =============================================================================
# HTTP requests
# =============================================================================

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

  local http_code response_body
  http_code=$(echo "$raw_output" | tail -1)
  response_body=$(echo "$raw_output" | sed '$d')

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

  local api_error
  api_error=$(echo "$response_body" | jq -r '.error // empty' 2>/dev/null || true)
  if [[ -n "$api_error" ]]; then
    echo "ERROR: API error — $api_error"
    return 1
  fi

  echo "$response_body"
  return 0
}


# =============================================================================
# Load entries
# =============================================================================

mem_load_entries() {
  _LOAD_ERROR=""

  local init_body
  init_body=$(jq -n \
    --arg project "$MEM_PROJECT" \
    --arg repo "$MEM_REPO" \
    --arg url "${MEM_GITHUB_URL:-}" \
    '{project: $project, repo: $repo, github_url: (if $url == "" then null else $url end)}')

  INIT_RESULT=""
  if ! INIT_RESULT=$(mem_curl POST "/session-init" "$init_body" "$MEM_TRIGGER_SOURCE"); then
    _LOAD_ERROR="$INIT_RESULT"
    return 0
  fi

  REG_STATUS=$(echo "$INIT_RESULT" | jq -r '.register_status // "unknown"' 2>/dev/null || echo "unknown")
  mem_log INFO "repo registration: $REG_STATUS"

  STARRED_RESULT=$(echo "$INIT_RESULT" | jq '.starred' 2>/dev/null || echo '{"entries":[],"count":0}')
  STARRED_COUNT=$(echo "$STARRED_RESULT" | jq '.count // 0' 2>/dev/null || echo "0")
  mem_log INFO "starred entries: $STARRED_COUNT"

  MENU_RESULT=$(echo "$INIT_RESULT" | jq '.knowledge_menu' 2>/dev/null || echo '{"items":[],"count":0}')
  MENU_COUNT=$(echo "$MENU_RESULT" | jq '.count // 0' 2>/dev/null || echo "0")
  mem_log INFO "menu entries: $MENU_COUNT"

  TOTAL_COUNT=$((STARRED_COUNT + MENU_COUNT))
}

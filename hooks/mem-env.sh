#!/usr/bin/env bash
# Shared helper: parse mem identity from CLAUDE.md and validate config.
# Source this from hooks: source "$(dirname "$0")/mem-env.sh" "$INPUT"
# Sets: MEM_PROJECT, MEM_REPO, MEM_URL, MEM_TOKEN, MEM_TOPOLOGY, MEM_GITHUB_URL,
#       MEM_TECH_TAGS, MEM_SIBLING_REPOS, MEM_SIBLING_REPOS_DETAIL, MEM_CACHE_DIR,
#       MEM_CACHE_KEY, MEM_SESSION_ID (stable Conductor ID), MEM_CLAUDE_SESSION_ID
#       (volatile Claude API ID), MEM_CONDUCTOR_TITLE (tab title), MEM_USER_PROMPT
# On skip (no mem tag): sets MEM_ENV_SKIP=1, returns 0. Caller should exit 0.
# On error: writes to stderr, returns 1. Caller's mem-err-trap catches it.

_INPUT="${1:-}"

# --- Load env from dotfile if present ---
if [[ -f "$HOME/.config/autodev-memory/.env" ]]; then
  set -a
  source "$HOME/.config/autodev-memory/.env"
  set +a
fi

# --- CWD: different hook events use different schemas ---
_CWD=$(echo "$_INPUT" | jq -r '(.cwd // .session.cwd) // empty' 2>/dev/null)
if [[ -z "$_CWD" ]]; then
  echo "HOOK ERROR [mem-env]: no cwd found in hook input (tried .cwd and .session.cwd)" >&2
  return 1
fi
_MEM_LOG_CWD=$(basename "$_CWD")

# --- Parse mem stub from CLAUDE.md ---
_CLAUDE_MD="$_CWD/CLAUDE.md"
if [[ ! -f "$_CLAUDE_MD" ]]; then
  MEM_ENV_SKIP=1
  return 0
fi

# Support both old format (with repo=) and new format (project only)
_MEM_LINE=$(grep -o '<!-- mem:project=[^ ]* repo=[^ ]* -->' "$_CLAUDE_MD" 2>/dev/null || true)
if [[ -z "$_MEM_LINE" ]]; then
  # Try new simplified format: <!-- mem:project=name -->
  _MEM_LINE=$(grep -o '<!-- mem:project=[^ ]* -->' "$_CLAUDE_MD" 2>/dev/null || true)
fi
if [[ -z "$_MEM_LINE" ]]; then
  MEM_ENV_SKIP=1
  return 0
fi

MEM_PROJECT=$(echo "$_MEM_LINE" | sed 's/.*project=\([^ ]*\).*/\1/' | sed 's/ *-->//')

# --- Auto-detect repo name from git remote ---
_GIT_REMOTE=$(git -C "$_CWD" remote get-url origin 2>/dev/null || true)
if [[ -n "$_GIT_REMOTE" ]]; then
  # Extract repo name from remote URL:
  # git@github.com:user/repo-name.git -> repo-name
  # https://github.com/user/repo-name.git -> repo-name
  MEM_REPO=$(echo "$_GIT_REMOTE" | sed 's/.*[/:]\([^/]*\)\.git$/\1/' | sed 's/.*[/:]\([^/]*\)$/\1/')

  # Normalize to HTTPS GitHub URL
  MEM_GITHUB_URL=$(echo "$_GIT_REMOTE" | sed 's|^git@github\.com:|https://github.com/|' | sed 's|\.git$||')
else
  # Fallback: try old repo= tag format
  MEM_REPO=$(echo "$_MEM_LINE" | sed -n 's/.*repo=\([^ ]*\).*/\1/p' | sed 's/ *-->//')
  MEM_GITHUB_URL=""
  if [[ -z "$MEM_REPO" ]]; then
    # Last resort: use directory name
    MEM_REPO=$(basename "$_CWD")
  fi
fi

MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"

if [[ -z "$MEM_TOKEN" ]]; then
  echo "HOOK ERROR [mem-env]: AUTODEV_MEMORY_API_TOKEN not set" >&2
  return 1
fi

# --- Fetch topology with HTTP status checking ---
_TOPO_RAW=$(curl -sS --max-time 15 \
  -w '\n%{http_code}' \
  -H "Authorization: Bearer $MEM_TOKEN" \
  "$MEM_URL/topology?project=$MEM_PROJECT" 2>&1) || {
  echo "HOOK ERROR [mem-env]: memory API unreachable at $MEM_URL: $_TOPO_RAW" >&2
  return 1
}

_TOPO_HTTP=$(echo "$_TOPO_RAW" | tail -1)
_TOPO_BODY=$(echo "$_TOPO_RAW" | sed '$d')

# Check HTTP status
if [[ "$_TOPO_HTTP" -lt 200 || "$_TOPO_HTTP" -ge 300 ]] 2>/dev/null; then
  _TOPO_DETAIL=$(echo "$_TOPO_BODY" | jq -r '.detail // .error // empty' 2>/dev/null || true)
  echo "HOOK ERROR [mem-env]: topology API returned HTTP $_TOPO_HTTP: ${_TOPO_DETAIL:-$_TOPO_BODY}" >&2
  return 1
fi

MEM_TOPOLOGY=$(echo "$_TOPO_BODY" | jq -r '
  "Project: " + .project + " — " + .project_description + "\nRepos:\n" +
  ([.repos[] | "  - " + .repo_name + ": " + .repo_description +
    (if (.tech_tags | length) > 0 then " [" + (.tech_tags | join(", ")) + "]" else "" end)
  ] | join("\n"))
' 2>/dev/null)

if [[ -z "$MEM_TOPOLOGY" ]]; then
  echo "HOOK ERROR [mem-env]: failed to parse topology response: $_TOPO_BODY" >&2
  return 1
fi

# Extract tech_tags for the current repo (comma-separated, empty string if none)
MEM_TECH_TAGS=$(echo "$_TOPO_BODY" | jq -r --arg repo "$MEM_REPO" '
  [.repos[] | select(.repo_name == $repo) | .tech_tags // [] | .[]] | join(",")
' 2>/dev/null || echo "")

# Sibling repo names (all repos in the project except current, comma-separated)
MEM_SIBLING_REPOS=$(echo "$_TOPO_BODY" | jq -r --arg repo "$MEM_REPO" '
  [.repos[] | select(.repo_name != $repo) | .repo_name] | join(",")
' 2>/dev/null || echo "")

# Sibling repo details (formatted with descriptions and tech tags for context injection)
MEM_SIBLING_REPOS_DETAIL=$(echo "$_TOPO_BODY" | jq -r --arg repo "$MEM_REPO" '
  [.repos[] | select(.repo_name != $repo) |
    "- **" + .repo_name + "**: " + (.repo_description // "no description") +
    (if (.tech_tags | length) > 0 then " [" + (.tech_tags | join(", ")) + "]" else "" end)
  ] | join("\n")
' 2>/dev/null || echo "")

# Cache dir for inter-hook state (session start → prompt submit)
MEM_CACHE_DIR="$HOME/.config/autodev-memory/cache"
mkdir -p "$MEM_CACHE_DIR" 2>/dev/null || true

# Key by session ID so concurrent sessions don't share exclude lists
# Claude Code may send session_id (snake_case) or sessionId (camelCase)
MEM_CLAUDE_SESSION_ID=$(echo "$_INPUT" | jq -r '.session_id // .sessionId // empty' 2>/dev/null)

# Resolve volatile Claude session ID to stable Conductor session ID + tab title via local DB
MEM_SESSION_ID=""
MEM_CONDUCTOR_TITLE=""
if [[ -n "$MEM_CLAUDE_SESSION_ID" ]]; then
  _CONDUCTOR_DB="$HOME/Library/Application Support/com.conductor.app/conductor.db"
  if [[ -f "$_CONDUCTOR_DB" ]]; then
    _CONDUCTOR_ROW=$(sqlite3 -separator $'\t' "$_CONDUCTOR_DB" \
      "SELECT id, title FROM sessions WHERE claude_session_id = '$MEM_CLAUDE_SESSION_ID' LIMIT 1;" 2>/dev/null || true)
    if [[ -n "$_CONDUCTOR_ROW" ]]; then
      MEM_SESSION_ID=$(echo "$_CONDUCTOR_ROW" | cut -f1)
      MEM_CONDUCTOR_TITLE=$(echo "$_CONDUCTOR_ROW" | cut -f2-)
    fi
  fi
  # Fall back to Claude session ID if Conductor DB lookup fails (non-Conductor usage)
  if [[ -z "$MEM_SESSION_ID" ]]; then
    MEM_SESSION_ID="$MEM_CLAUDE_SESSION_ID"
  fi
  MEM_CACHE_KEY="$MEM_SESSION_ID"
else
  MEM_CACHE_KEY=$(echo -n "$_CWD" | md5 -q 2>/dev/null || echo -n "$_CWD" | md5sum 2>/dev/null | cut -d' ' -f1)
fi

# Extract user prompt from hook input (available in SessionStart and UserPromptSubmit)
_RAW_PROMPT=$(echo "$_INPUT" | jq -r '.prompt // empty' 2>/dev/null || true)
if [[ -n "$_RAW_PROMPT" ]]; then
  MEM_USER_PROMPT=$(echo "$_RAW_PROMPT" | head -c 200 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')
else
  MEM_USER_PROMPT=""
fi

# Clean up stale cache files older than 24h
find "$MEM_CACHE_DIR" -name "*.ids" -mtime +1 -delete 2>/dev/null || true

export MEM_PROJECT MEM_REPO MEM_URL MEM_TOKEN MEM_TOPOLOGY MEM_TECH_TAGS MEM_GITHUB_URL MEM_CACHE_DIR MEM_CACHE_KEY
export MEM_SESSION_ID MEM_CLAUDE_SESSION_ID MEM_CONDUCTOR_TITLE MEM_USER_PROMPT MEM_SIBLING_REPOS MEM_SIBLING_REPOS_DETAIL

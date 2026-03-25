#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# Parses project identity from CLAUDE.md stub, fetches topology from the mem
# service, and caches env vars (MEM_PROJECT, MEM_REPO, MEM_TOPOLOGY) for use
# by subsequent hooks (UserPromptSubmit, PreToolUse).
#
# Fires on: startup, compact
# Output: No additionalContext (env var setup only)
#
# SETUP — Add to ~/.claude/settings.json:
#   "SessionStart": [{
#     "hooks": [{
#       "type": "command",
#       "command": "~/.claude/hooks/autodev-memory-session-start.sh",
#       "timeout": 15
#     }]
#   }]
# =============================================================================

set -euo pipefail

# Read hook input from stdin
INPUT=$(cat)

# Only run on startup or compact
SOURCE=$(echo "$INPUT" | jq -r '.session.source // "startup"')
if [[ "$SOURCE" != "startup" && "$SOURCE" != "compact" ]]; then
  exit 0
fi

CWD=$(echo "$INPUT" | jq -r '.session.cwd // empty')
if [[ -z "$CWD" ]]; then
  exit 0
fi

# --- Parse project identity from CLAUDE.md ---
CLAUDE_MD="$CWD/CLAUDE.md"
if [[ ! -f "$CLAUDE_MD" ]]; then
  exit 0
fi

# Look for <!-- mem:project=X repo=Y -->
MEM_LINE=$(grep -o '<!-- mem:project=[^ ]* repo=[^ ]* -->' "$CLAUDE_MD" 2>/dev/null || true)
if [[ -z "$MEM_LINE" ]]; then
  # No mem stub — this project doesn't use the memory system
  exit 0
fi

MEM_PROJECT=$(echo "$MEM_LINE" | sed 's/.*project=\([^ ]*\).*/\1/')
MEM_REPO=$(echo "$MEM_LINE" | sed 's/.*repo=\([^ ]*\).*/\1/' | sed 's/ *-->//')

if [[ -z "$MEM_PROJECT" || -z "$MEM_REPO" ]]; then
  exit 0
fi

# --- Check service availability ---
MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"

if [[ -z "$MEM_TOKEN" ]]; then
  echo "mem-session-start: AUTODEV_MEMORY_API_TOKEN not set, skipping" >&2
  exit 0
fi

# --- Fetch topology ---
TOPOLOGY=$(curl -sf --max-time 5 \
  -H "Authorization: Bearer $MEM_TOKEN" \
  "$MEM_URL/topology?project=$MEM_PROJECT" 2>/dev/null || true)

if [[ -z "$TOPOLOGY" ]]; then
  echo "mem-session-start: could not fetch topology (service down?), continuing without memory" >&2
  # Still set project/repo so hooks can attempt searches
  TOPOLOGY_DESC="(topology unavailable)"
else
  # Build human-readable topology description for prompts
  TOPOLOGY_DESC=$(echo "$TOPOLOGY" | jq -r '
    "Project: " + .project + " — " + .project_description + "\nRepos:\n" +
    ([.repos[] | "  - " + .repo_name + ": " + .repo_description] | join("\n"))
  ' 2>/dev/null || echo "(topology parse error)")
fi

# --- Persist env vars for subsequent hooks ---
ENV_FILE="${CLAUDE_ENV_FILE:-}"
if [[ -n "$ENV_FILE" ]]; then
  # Append to the env file Claude Code reads between hooks
  {
    echo "MEM_PROJECT=$MEM_PROJECT"
    echo "MEM_REPO=$MEM_REPO"
    echo "MEM_TOPOLOGY=$TOPOLOGY_DESC"
  } >> "$ENV_FILE"
fi

# Also export for any child processes in this session
export MEM_PROJECT MEM_REPO

echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO" >&2

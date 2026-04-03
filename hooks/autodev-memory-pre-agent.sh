#!/usr/bin/env bash
# =============================================================================
# autodev-memory-pre-agent.sh — PreToolUse[Agent] hook for memory system
# =============================================================================
#
# When Claude spawns a subagent, inject starred entries (full) + knowledge
# menu (compact) — identical to session-start. Subagents search on demand
# using the menu as a guide.
#
# Requires: AUTODEV_MEMORY_API_TOKEN
# =============================================================================

set -euo pipefail

# --- Recursion guard ---
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  echo '{}'
  exit 0
fi
export _MEM_HOOK_ACTIVE=1

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-err-trap.sh"
_HOOK_EVENT_NAME="PreToolUse"
source "$HOOK_DIR/mem-lib.sh"

INPUT=$(cat)

mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip|error) echo '{}'; exit 0 ;;
esac

# --- Skip if agent prompt is too short ---
AGENT_PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general"')

if [[ -z "$AGENT_PROMPT" || ${#AGENT_PROMPT} -lt 30 ]]; then
  mem_log INFO "skip (prompt too short: ${#AGENT_PROMPT} chars)"
  echo '{}'
  exit 0
fi

mem_log INFO "start type=$AGENT_TYPE"

MEM_TRIGGER_SOURCE="pre_tool_use(Agent)"
mem_load_entries

if [[ -n "$_LOAD_ERROR" ]]; then
  mem_log ERROR "session-init failed: $_LOAD_ERROR"
  echo '{}'
  exit 0
fi

if [[ "$TOTAL_COUNT" -eq 0 ]]; then
  mem_log INFO "done (0 entries)"
  echo '{}'
  exit 0
fi

# =============================================================================
# Format and inject (same structure as session-start, minus status line)
# =============================================================================

CONTEXT="<autodev-memory-hook-result source=\"pre-agent\">"

if [[ "$STARRED_COUNT" -gt 0 ]]; then
  STARRED_LIST=$(echo "$STARRED_RESULT" | jq -r '
    .entries[] |
    "### [" + .type + "] " + .title + "\n" +
    "*Tags: " + (.tags | join(", ")) + "*\n\n" +
    .content + "\n"
  ' 2>/dev/null || echo "(formatting error)")

  CONTEXT="$CONTEXT
## Starred Memories ($STARRED_COUNT entries)

$STARRED_LIST"
fi

if [[ "$MENU_COUNT" -gt 0 ]]; then
  MENU_LIST=$(echo "$MENU_RESULT" | jq -r '
    .items[] |
    "- [" + .type + "] " + .title + " (" + (.tags | join(", ")) + ")"
  ' 2>/dev/null || echo "(formatting error)")

  CONTEXT="$CONTEXT

## Knowledge Menu ($MENU_COUNT entries) — use search() to retrieve full content

$MENU_LIST"
fi

CONTEXT="$CONTEXT
</autodev-memory-hook-result>"

OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $ctx}}')
mem_log INFO "done starred=$STARRED_COUNT menu=$MENU_COUNT"
mem_log_output "$OUTPUT"
echo "$OUTPUT"

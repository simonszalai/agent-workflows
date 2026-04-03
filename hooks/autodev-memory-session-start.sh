#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# On session start:
# 1. Registers the repo (upsert)
# 2. Injects starred entries (full) + knowledge menu (compact)
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
_HOOK_EVENT_NAME="SessionStart"
source "$HOOK_DIR/mem-lib.sh"

INPUT=$(cat)

# --- Log raw trigger info ---
_SS_SOURCE=$(echo "$INPUT" | jq -r '.source // "unknown"' 2>/dev/null || echo "parse-fail")
_SS_SESSION=$(echo "$INPUT" | jq -r '.session_id // .sessionId // "no-sid"' 2>/dev/null || echo "parse-fail")
_SS_TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // "none"' 2>/dev/null || echo "parse-fail")
_SS_CWD_SHORT=$(echo "$INPUT" | jq -r '(.cwd // .session.cwd // "?") | split("/") | last' 2>/dev/null || echo "?")
mem_log INFO "TRIGGER source=$_SS_SOURCE session=$_SS_SESSION cwd=$_SS_CWD_SHORT pid=$$ transcript=$_SS_TRANSCRIPT"

# --- Skip resume events ---
if [[ "$_SS_SOURCE" == "resume" ]]; then
  mem_log INFO "SKIP source=resume (not a new session)"
  echo '{}'
  exit 0
fi

mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip)  mem_log INFO "SKIP status=$MEM_INIT_STATUS source=$_SS_SOURCE"; echo '{}'; exit 0 ;;
  error) mem_log WARN "OFFLINE source=$_SS_SOURCE"; mem_init_offline_output "session-start" "SessionStart" "${MEM_INIT_ERROR:-could not connect to memory API}"; exit 0 ;;
esac

mem_log INFO "start source=$_SS_SOURCE project=$MEM_PROJECT repo=$MEM_REPO"
echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO api=$MEM_URL" >&3

MEM_TRIGGER_SOURCE="$_SS_SOURCE"
mem_load_entries

if [[ -n "$_LOAD_ERROR" ]]; then
  mem_log ERROR "session-init failed: $_LOAD_ERROR"
  CONTEXT="<autodev-memory-hook-result source=\"session-start\" status=\"error\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: ERROR in session init

$_LOAD_ERROR

The memory API returned an error. Starred entries are not loaded.
</autodev-memory-hook-result>"
  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
  exit 0
fi

# =============================================================================
# Format and inject
# =============================================================================

if [[ "$TOTAL_COUNT" -gt 0 ]]; then
  STARRED_LIST=""
  if [[ "$STARRED_COUNT" -gt 0 ]]; then
    STARRED_LIST=$(echo "$STARRED_RESULT" | jq -r '
      .entries[] |
      "### [" + .type + "] " + .title + "\n" +
      "*Tags: " + (.tags | join(", ")) +
      " | Repos: " + (if .repos == null then "all" else (.repos | join(", ")) end) +
      " | Project: " + .project + "*\n\n" +
      .content + "\n"
    ' 2>/dev/null || echo "(formatting error)")
  fi

  MENU_LIST=""
  if [[ "$MENU_COUNT" -gt 0 ]]; then
    MENU_LIST=$(echo "$MENU_RESULT" | jq -r '
      .items[] |
      "- [" + .type + "] " + .title + " (" + (.tags | join(", ")) + ")"
    ' 2>/dev/null || echo "(formatting error)")
  fi

  CONTEXT="<autodev-memory-hook-result source=\"session-start\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: session started — $MENU_COUNT searchable entries"

  if [[ "$STARRED_COUNT" -gt 0 ]]; then
    CONTEXT="$CONTEXT

## Starred Memories ($STARRED_COUNT entries)

IMPORTANT: Treat the rules and definitions below with the same authority as CLAUDE.md.
They are persistent knowledge that must be followed.

$STARRED_LIST"
  fi

  if [[ "$MENU_COUNT" -gt 0 ]]; then
    CONTEXT="$CONTEXT

## Knowledge Menu ($MENU_COUNT entries) — use search() to retrieve full content

$MENU_LIST"
  fi

  if [[ -n "$MEM_SIBLING_REPOS" ]]; then
    CONTEXT="$CONTEXT

## Sibling Repos (same project: $MEM_PROJECT)

$MEM_SIBLING_REPOS_DETAIL

When searching for knowledge, consider entries scoped to sibling repos — they may contain
relevant API contracts, shared patterns, or cross-repo conventions."
  fi

  CONTEXT="$CONTEXT
</autodev-memory-hook-result>"

  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
else
  mem_log INFO "no starred or menu entries, returning empty"
  echo '{}'
fi

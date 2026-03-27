#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# On session start:
# 1. Validates that the memory system is configured and reachable
# 2. Fetches glossary terms and injects them as persistent context
#
# Requires: AUTODEV_MEMORY_API_TOKEN
# =============================================================================

set -euo pipefail

# --- Recursion guard: inner claude -p sessions also trigger this ---
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  echo '{}'
  exit 0
fi

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-err-trap.sh"
source "$HOOK_DIR/mem-log.sh"

INPUT=$(cat)

# --- Parse mem config (errors caught by mem-err-trap EXIT handler) ---
MEM_ENV_SKIP=""
source "$HOOK_DIR/mem-env.sh" "$INPUT"

if [[ -n "$MEM_ENV_SKIP" ]]; then
  mem_log INFO "skip (no mem config)"
  echo '{}'
  exit 0
fi

mem_log INFO "start project=$MEM_PROJECT repo=$MEM_REPO"
echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO api=$MEM_URL" >&3

# --- Fetch and inject glossary terms ---
GLOSSARY=$(curl -sS --max-time 5 \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "X-Hook-Source: session_start" \
  "$MEM_URL/glossary?project=$MEM_PROJECT" 2>/dev/null) || true

TERM_COUNT=$(echo "$GLOSSARY" | jq '.count // 0' 2>/dev/null || echo "0")
mem_log INFO "glossary fetched: $TERM_COUNT terms"

if [[ "$TERM_COUNT" -gt 0 ]]; then
  TERM_LIST=$(echo "$GLOSSARY" | jq -r '
    .terms[] | "- **" + .term + "**: " + .description +
    (if .project != "global" then " _(" + .project + " only)_" else "" end)
  ' 2>/dev/null || echo "- (autodev-memory session-start: glossary formatting failed)")

  CONTEXT="<autodev-memory-hook-result source=\"session-start\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: session started — $TERM_COUNT glossary terms loaded

## Your User's Terminology
$TERM_LIST
</autodev-memory-hook-result>"

  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{additionalContext: $ctx}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
else
  mem_log INFO "no glossary terms, returning empty"
  echo '{}'
fi

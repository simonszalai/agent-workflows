#!/usr/bin/env bash
# =============================================================================
# mem-init.sh — Shared initialization for autodev-memory hooks
# =============================================================================
#
# Source after mem-err-trap.sh and mem-log.sh. Handles mem-env loading,
# skip detection, and error reporting — the boilerplate every hook needs.
#
# Usage:
#   source "$HOOK_DIR/mem-init.sh"
#   mem_init "$INPUT"
#   # MEM_INIT_STATUS is now "ok", "skip", or "error"
#
#   case "$MEM_INIT_STATUS" in
#     skip)  echo '{}'; exit 0 ;;
#     error) mem_init_offline_output "session-start" "SessionStart"; exit 0 ;;
#   esac
#
# For hooks that silently skip on error (e.g., pre-agent):
#   case "$MEM_INIT_STATUS" in
#     skip|error) echo '{}'; exit 0 ;;
#   esac
# =============================================================================

# Run mem-env.sh and set MEM_INIT_STATUS to "ok", "skip", or "error".
# On error, MEM_INIT_ERROR contains the error message.
mem_init() {
  local input="$1"
  MEM_ENV_SKIP=""
  MEM_INIT_STATUS="ok"
  MEM_INIT_ERROR=""

  if ! source "$HOOK_DIR/mem-env.sh" "$input"; then
    MEM_INIT_STATUS="error"
    MEM_INIT_ERROR=$(cat "$_ERR_FILE" 2>/dev/null || true)
    mem_log ERROR "mem-env failed: $MEM_INIT_ERROR"
    return 0
  fi

  if [[ -n "$MEM_ENV_SKIP" ]]; then
    MEM_INIT_STATUS="skip"
    mem_log INFO "skip (no mem config)"
    return 0
  fi
}

# Output an OFFLINE warning as additionalContext JSON and return it on stdout.
# Usage: mem_init_offline_output "session-start" "SessionStart" ["custom message"]
mem_init_offline_output() {
  local source="$1"
  local event="$2"
  local message="${3:-memory API unreachable}"

  # Restore fd 2 so jq output goes only to stdout
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

#!/usr/bin/env bash
# =============================================================================
# mem-log.sh — Shared logging helper for autodev-memory hooks
# =============================================================================
#
# Source this from any hook script to get structured logging to a persistent
# log file at ~/.config/autodev-memory/hooks.log
#
# Usage:
#   source "$HOOK_DIR/mem-log.sh"
#   mem_log INFO "search decision: should_search=true queries=3"
#   mem_log DEBUG "full output: $CONTEXT"
#   mem_log ERROR "curl failed: $RESULT"
#
# Levels: DEBUG, INFO, WARN, ERROR
# Auto-rotates at ~1MB (keeps last ~500KB).
#
# View live:
#   tail -f ~/.config/autodev-memory/hooks.log
#
# Search for errors:
#   grep ERROR ~/.config/autodev-memory/hooks.log
#
# See what a specific hook did:
#   grep prompt-submit ~/.config/autodev-memory/hooks.log | tail -20
# =============================================================================

_MEM_LOG_DIR="$HOME/.config/autodev-memory"
_MEM_LOG_FILE="$_MEM_LOG_DIR/hooks.log"
_MEM_LOG_MAX_BYTES=1048576  # 1MB
_MEM_LOG_HOOK_NAME=$(basename "${0:-unknown}" .sh)
_MEM_LOG_CWD=""  # Set by mem-env.sh after CWD is determined

# Ensure log directory exists
mkdir -p "$_MEM_LOG_DIR" 2>/dev/null || true

mem_log() {
  local level="$1"
  shift
  local message="$*"
  local timestamp
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')

  # Truncate long messages (keep first 2000 chars)
  if [[ ${#message} -gt 2000 ]]; then
    message="${message:0:2000}...[truncated]"
  fi

  # Append to log file (include cwd basename if known)
  local cwd_tag=""
  if [[ -n "$_MEM_LOG_CWD" ]]; then
    cwd_tag=" cwd=$_MEM_LOG_CWD"
  fi
  printf '%s [%-14s] %-5s%s %s\n' \
    "$timestamp" "$_MEM_LOG_HOOK_NAME" "$level" "$cwd_tag" "$message" \
    >> "$_MEM_LOG_FILE" 2>/dev/null || true

  # Rotate if over max size
  if [[ -f "$_MEM_LOG_FILE" ]]; then
    local size
    size=$(wc -c < "$_MEM_LOG_FILE" 2>/dev/null || echo 0)
    if [[ $size -gt $_MEM_LOG_MAX_BYTES ]]; then
      # Keep last ~500KB
      tail -c 524288 "$_MEM_LOG_FILE" > "$_MEM_LOG_FILE.tmp" 2>/dev/null
      mv "$_MEM_LOG_FILE.tmp" "$_MEM_LOG_FILE" 2>/dev/null || true
    fi
  fi
}

# Log the final JSON output that gets sent to Claude Code.
# Call this right before the final jq output at the end of each hook.
mem_log_output() {
  local json="$1"
  local ctx
  ctx=$(echo "$json" | jq -r '.hookSpecificOutput.additionalContext // "(empty)"' 2>/dev/null || echo "(parse failed)")
  mem_log DEBUG "output -> $ctx"
}

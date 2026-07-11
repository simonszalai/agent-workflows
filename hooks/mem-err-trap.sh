#!/usr/bin/env bash
# =============================================================================
# mem-err-trap.sh — Shared error trap for autodev-memory hooks
# =============================================================================
#
# Source this after set -euo pipefail and recursion guard, BEFORE any fallible
# commands. Captures stderr so it cannot corrupt hook JSON. On non-zero exit, emits a bounded
# unavailable marker; raw stderr is never persisted or injected.
#
# Usage:
#   HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
#   source "$HOOK_DIR/mem-err-trap.sh"
#
# After sourcing, fd 2 points to error file. Use >&3 for intentional stderr.
# =============================================================================

_ERR_FILE=$(mktemp)

_on_hook_exit() {
  local exit_code=$?
  exec 2>&3                        # restore stderr to original fd
  rm -f "$_ERR_FILE" 2>/dev/null || true
  local _hook_name
  _hook_name=$(basename "$0" .sh)

  # Log errors to persistent log file (mem_log may not be loaded yet, write directly)
  if [[ $exit_code -ne 0 ]]; then
    local _log_file="$HOME/.config/autodev-memory/hooks.log"
    mkdir -p "$HOME/.config/autodev-memory" 2>/dev/null || true
    printf '%s [%-14s] %-5s exit_code=%d status=unavailable\n' \
      "$(date '+%Y-%m-%d %H:%M:%S')" "$_hook_name" "ERROR" "$exit_code" \
      >> "$_log_file" 2>/dev/null || true
  fi

  # _HOOK_EVENT_NAME must be set by the sourcing script (e.g. "SessionStart")
  local _event="${_HOOK_EVENT_NAME:-SessionStart}"

  if [[ $exit_code -ne 0 ]]; then
    jq -n --arg ctx "<autodev-memory-hook-result source=\"${_hook_name}\" status=\"unavailable\">
Memory context is unavailable for this session. Do not infer that memories were loaded.
Use the memory search tool explicitly if it is available.
</autodev-memory-hook-result>" \
      --arg event "$_event" \
      '{hookSpecificOutput: {hookEventName: $event, additionalContext: $ctx}}' 2>/dev/null || echo '{}'
    exit 0
  fi
}

trap '_on_hook_exit' EXIT
exec 3>&2
exec 2>>"$_ERR_FILE"

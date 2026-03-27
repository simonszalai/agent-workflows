#!/usr/bin/env bash
# =============================================================================
# mem-err-trap.sh — Shared error trap for autodev-memory hooks
# =============================================================================
#
# Source this after set -euo pipefail and recursion guard, BEFORE any fallible
# commands. Captures stderr to a temp file. On non-zero exit, outputs captured
# errors as additionalContext JSON with instructions for the AI to alert the user.
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
  local errs
  errs=$(cat "$_ERR_FILE" 2>/dev/null || true)
  rm -f "$_ERR_FILE" 2>/dev/null || true
  local _hook_name
  _hook_name=$(basename "$0" .sh)

  # Log errors to persistent log file (mem_log may not be loaded yet, write directly)
  if [[ $exit_code -ne 0 ]]; then
    local _log_file="$HOME/.config/autodev-memory/hooks.log"
    mkdir -p "$HOME/.config/autodev-memory" 2>/dev/null || true
    printf '%s [%-14s] %-5s exit_code=%d stderr=%s\n' \
      "$(date '+%Y-%m-%d %H:%M:%S')" "$_hook_name" "ERROR" "$exit_code" \
      "${errs:-"(none)"}" >> "$_log_file" 2>/dev/null || true
  fi

  if [[ $exit_code -ne 0 && -n "$errs" ]]; then
    jq -n --arg ctx "<autodev-memory-hook-result source=\"${_hook_name}\" status=\"error\">
MANDATORY: Start your reply with this single status line (no extra text around it):
Memory: hook error in ${_hook_name}

Error details: $errs
</autodev-memory-hook-result>" \
      '{additionalContext: $ctx}' 2>/dev/null || true
    exit 0
  elif [[ $exit_code -ne 0 ]]; then
    # Non-zero exit but no captured stderr (e.g. 2>/dev/null suppressed it).
    # Must return valid JSON so Claude Code doesn't stall.
    jq -n --arg ctx "<autodev-memory-hook-result source=\"${_hook_name}\" status=\"error\">
MANDATORY: Start your reply with this single status line (no extra text around it):
Memory: hook error in ${_hook_name} (exit code $exit_code)
</autodev-memory-hook-result>" \
      '{additionalContext: $ctx}' 2>/dev/null || echo '{}'
    exit 0
  fi
}

trap '_on_hook_exit' EXIT
exec 3>&2
exec 2>>"$_ERR_FILE"

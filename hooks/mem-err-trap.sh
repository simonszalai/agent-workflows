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
  if [[ $exit_code -ne 0 && -n "$errs" ]]; then
    jq -n --arg ctx "[Memory Hook Error] $(basename "$0")

$errs

**IMPORTANT: Tell the user about this memory hook error before proceeding.**" \
      '{additionalContext: $ctx}' 2>/dev/null || true
    exit 0
  fi
}

trap '_on_hook_exit' EXIT
exec 3>&2
exec 2>>"$_ERR_FILE"

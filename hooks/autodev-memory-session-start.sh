#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# Validates that the memory system is configured and reachable.
# Actual work happens in prompt-submit and pre-agent hooks.
#
# Requires: AUTODEV_MEMORY_API_TOKEN
# =============================================================================

set -euo pipefail

# --- Recursion guard: inner claude -p sessions also trigger this ---
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  exit 0
fi

INPUT=$(cat)

# --- Parse mem config (dies on misconfiguration) ---
HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-env.sh" "$INPUT"

echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO api=$MEM_URL" >&2

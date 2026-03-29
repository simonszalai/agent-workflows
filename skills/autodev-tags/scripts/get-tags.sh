#!/usr/bin/env bash
# =============================================================================
# get-tags.sh — Fetch all unique tags from the memory system
# =============================================================================
#
# Usage:
#   ./get-tags.sh <project>
#
# Output: JSON with all unique tags and their usage counts
#
# Requires: AUTODEV_MEMORY_API_TOKEN, AUTODEV_MEMORY_API_URL (optional)
# =============================================================================

set -euo pipefail

PROJECT="${1:-global}"

# --- Load env from dotfile if present ---
if [[ -f "$HOME/.config/autodev-memory/.env" ]]; then
  set -a
  source "$HOME/.config/autodev-memory/.env"
  set +a
fi

MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"

if [[ -z "$MEM_TOKEN" ]]; then
  echo "ERROR: AUTODEV_MEMORY_API_TOKEN not set" >&2
  exit 1
fi

RAW=$(curl -sS --max-time 10 \
  -w '\n%{http_code}' \
  -H "Authorization: Bearer $MEM_TOKEN" \
  "$MEM_URL/tags?project=$PROJECT" 2>&1) || {
  echo "ERROR: curl failed: $RAW" >&2
  exit 1
}

HTTP_CODE=$(echo "$RAW" | tail -1)
BODY=$(echo "$RAW" | sed '$d')

if [[ "$HTTP_CODE" -lt 200 || "$HTTP_CODE" -ge 300 ]] 2>/dev/null; then
  echo "ERROR: HTTP $HTTP_CODE — $BODY" >&2
  exit 1
fi

echo "$BODY"

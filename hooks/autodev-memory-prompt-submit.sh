#!/usr/bin/env bash
# =============================================================================
# autodev-memory-prompt-submit.sh — UserPromptSubmit hook for memory system
# =============================================================================
#
# On every user message:
# 1. (blocking) Generate search queries via Haiku, search KB, return as context
# 2. (background) If regex gate matches, fork correction detection pipeline
#
# SETUP — Add to ~/.claude/settings.json:
#   "UserPromptSubmit": [{
#     "hooks": [{
#       "type": "command",
#       "command": "~/.claude/hooks/autodev-memory-prompt-submit.sh",
#       "timeout": 10
#     }]
#   }]
# =============================================================================

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Read hook input from stdin
INPUT=$(cat)

# --- Early exits ---

# Check if memory system is configured for this project
MEM_PROJECT="${MEM_PROJECT:-}"
MEM_REPO="${MEM_REPO:-}"
if [[ -z "$MEM_PROJECT" ]]; then
  exit 0
fi

MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"
if [[ -z "$MEM_TOKEN" ]]; then
  exit 0
fi

# Extract the user's prompt
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
if [[ -z "$PROMPT" || ${#PROMPT} -lt 20 ]]; then
  exit 0
fi

# --- Read recent conversation for context ---
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '.session.transcript_path // empty')
RECENT=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  # Last 3 messages, AI messages truncated to ~200 chars
  RECENT=$(jq -c '
    [.[] | select(.type == "human" or .type == "assistant")]
    | .[-3:]
    | [.[] | if .type == "assistant" then .content = (.content[:200] + "...") else . end]
  ' "$TRANSCRIPT_PATH" 2>/dev/null || echo "[]")
fi

# --- Correction detection regex gate (fork to background if match) ---
CORRECTION_REGEX='^(no[,.\s!]|nah\b|actually\b|wait[,.\s!]|but\s|not\s|that'\''?s (not|wrong|incorrect)\b|this is (wrong|not)\b|wrong\b|i (said|told|already|just said|just told|meant|mean)\b|i didn'\''?t (say|ask|mean|want)\b|you (forgot|missed|skipped|broke|removed|keep)\b|you (should|need to|shouldn'\''?t)\b|why (did|are|is|would|do)\b|don'\''?t\s|stop\s|never\s|just\s|revert\b)'

PROMPT_LOWER=$(echo "$PROMPT" | tr '[:upper:]' '[:lower:]')
if echo "$PROMPT_LOWER" | grep -qEi "$CORRECTION_REGEX"; then
  # Fork correction detection into background (fire-and-forget)
  "$HOOK_DIR/autodev-memory-correction-detect.sh" \
    "$MEM_PROJECT" "$MEM_REPO" "$MEM_URL" "$MEM_TOKEN" \
    "$PROMPT" "$TRANSCRIPT_PATH" &
  disown
fi

# --- Search path (blocking) ---

# Build query generation prompt
QUERY_TEMPLATE=$(cat "$HOOK_DIR/prompts/query-generation.md")
TOPOLOGY_DESC="${MEM_TOPOLOGY:-}"

QUERY_PROMPT="$QUERY_TEMPLATE

Current repo: ${MEM_REPO}
Project repos:
$TOPOLOGY_DESC

Recent conversation:
$(echo "$RECENT" | jq -r '.[] | .type + ": " + (.content // "" | tostring)[:500]' 2>/dev/null | tail -c 3000)

Current message: $PROMPT"

# Generate search queries via Haiku
QUERIES=$(echo "$QUERY_PROMPT" | claude -p --model haiku --output-format json 2>/dev/null || echo "[]")

# Validate we got a JSON array
if ! echo "$QUERIES" | jq -e 'type == "array"' >/dev/null 2>&1; then
  exit 0
fi

QUERY_COUNT=$(echo "$QUERIES" | jq 'length')
if [[ "$QUERY_COUNT" -eq 0 ]]; then
  exit 0
fi

# Build search request
SEARCH_BODY=$(jq -n \
  --argjson searches "$QUERIES" \
  --arg project "$MEM_PROJECT" \
  '{searches: $searches, project: $project, limit: 5}')

# Call the search endpoint
SEARCH_RESULT=$(curl -sf --max-time 5 \
  -X POST \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Hook-Source: user_prompt" \
  -d "$SEARCH_BODY" \
  "$MEM_URL/search" 2>/dev/null || echo '{"results":[]}')

# Extract results
RESULT_COUNT=$(echo "$SEARCH_RESULT" | jq '.results | length' 2>/dev/null || echo "0")

if [[ "$RESULT_COUNT" -eq 0 ]]; then
  exit 0
fi

# Format results as additionalContext
CONTEXT=$(echo "$SEARCH_RESULT" | jq -r '
  "## Knowledge Base Results\n\n" +
  ([.results[] |
    "### " + .title + " (" + .type + ")\n" +
    (if .canonical_key then "*Key: " + .canonical_key + "*\n" else "" end) +
    .content + "\n"
  ] | join("\n---\n\n"))
')

# Output as hookSpecificOutput with additionalContext
jq -n --arg context "$CONTEXT" '{additionalContext: $context}'

#!/usr/bin/env bash
# =============================================================================
# autodev-memory-pre-agent.sh — PreToolUse[Agent] hook for memory system
# =============================================================================
#
# When Claude spawns a subagent, search for task-specific knowledge based on
# the subagent's prompt and inject it as additionalContext.
#
# Fires only on Agent tool calls (~0.5/session avg, 85% sessions see zero).
#
# SETUP — Add to ~/.claude/settings.json:
#   "PreToolUse": [{
#     "matcher": "Agent",
#     "hooks": [{
#       "type": "command",
#       "command": "~/.claude/hooks/autodev-memory-pre-agent.sh",
#       "timeout": 10
#     }]
#   }]
# =============================================================================

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Read hook input from stdin
INPUT=$(cat)

# --- Early exits ---

MEM_PROJECT="${MEM_PROJECT:-}"
if [[ -z "$MEM_PROJECT" ]]; then
  exit 0
fi

MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"
if [[ -z "$MEM_TOKEN" ]]; then
  exit 0
fi

MEM_REPO="${MEM_REPO:-}"
TOPOLOGY_DESC="${MEM_TOPOLOGY:-}"

# Extract subagent prompt from tool_input
AGENT_PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')
AGENT_DESC=$(echo "$INPUT" | jq -r '.tool_input.description // empty')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general"')

if [[ -z "$AGENT_PROMPT" || ${#AGENT_PROMPT} -lt 30 ]]; then
  exit 0
fi

# --- Generate search queries via Haiku ---

QUERY_TEMPLATE=$(cat "$HOOK_DIR/prompts/query-generation.md")

QUERY_PROMPT="$QUERY_TEMPLATE

Current repo: ${MEM_REPO}
Project repos:
$TOPOLOGY_DESC

Subagent type: $AGENT_TYPE
Subagent description: $AGENT_DESC
Subagent prompt:
$(echo "$AGENT_PROMPT" | head -c 3000)"

QUERIES=$(echo "$QUERY_PROMPT" | claude -p --model haiku --output-format json 2>/dev/null || echo "[]")

if ! echo "$QUERIES" | jq -e 'type == "array"' >/dev/null 2>&1; then
  exit 0
fi

QUERY_COUNT=$(echo "$QUERIES" | jq 'length')
if [[ "$QUERY_COUNT" -eq 0 ]]; then
  exit 0
fi

# --- Search ---

SEARCH_BODY=$(jq -n \
  --argjson searches "$QUERIES" \
  --arg project "$MEM_PROJECT" \
  '{searches: $searches, project: $project, limit: 5}')

SEARCH_RESULT=$(curl -sf --max-time 5 \
  -X POST \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Hook-Source: pre_tool_use" \
  -d "$SEARCH_BODY" \
  "$MEM_URL/search" 2>/dev/null || echo '{"results":[]}')

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

jq -n --arg context "$CONTEXT" '{additionalContext: $context}'

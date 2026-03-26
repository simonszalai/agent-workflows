#!/usr/bin/env bash
# =============================================================================
# autodev-memory-pre-agent.sh — PreToolUse[Agent] hook for memory system
# =============================================================================
#
# When Claude spawns a subagent, search for task-specific knowledge based on
# the subagent's prompt and inject it as additionalContext.
#
# Requires: AUTODEV_MEMORY_API_TOKEN, claude CLI on PATH
# =============================================================================

set -euo pipefail

# --- Recursion guard ---
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  exit 0
fi
export _MEM_HOOK_ACTIVE=1

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)

# --- Parse mem config (dies on misconfiguration) ---
source "$HOOK_DIR/mem-env.sh" "$INPUT"

# --- Extract subagent info ---
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
$MEM_TOPOLOGY

Subagent type: $AGENT_TYPE
Subagent description: $AGENT_DESC
Subagent prompt:
$(echo "$AGENT_PROMPT" | head -c 3000)"

QUERIES=$(echo "$QUERY_PROMPT" | claude -p --model haiku --output-format json 2>/dev/null) || true

if [[ -z "$QUERIES" ]]; then
  echo "HOOK ERROR [pre-agent]: claude -p --model haiku returned nothing" >&2
  exit 1
fi

HAIKU_TEXT=$(echo "$QUERIES" | jq -r '.result // empty' 2>/dev/null)
if [[ -z "$HAIKU_TEXT" ]]; then
  IS_ERROR=$(echo "$QUERIES" | jq -r '.is_error // false' 2>/dev/null)
  if [[ "$IS_ERROR" == "true" ]]; then
    ERROR_MSG=$(echo "$QUERIES" | jq -r '.result // "unknown error"' 2>/dev/null)
    echo "HOOK ERROR [pre-agent]: Haiku CLI error: $ERROR_MSG" >&2
    exit 1
  fi
  echo "HOOK ERROR [pre-agent]: Haiku returned empty result. Full response: $QUERIES" >&2
  exit 1
fi

# Parse JSON array (may be wrapped in markdown code block)
PARSED=$(echo "$HAIKU_TEXT" | sed 's/^```json//; s/^```//; s/```$//' | jq -c '.' 2>/dev/null || echo "")
if [[ -z "$PARSED" ]] || ! echo "$PARSED" | jq -e 'type == "array"' >/dev/null 2>&1; then
  echo "HOOK ERROR [pre-agent]: Haiku returned non-array: $HAIKU_TEXT" >&2
  exit 1
fi

QUERY_COUNT=$(echo "$PARSED" | jq 'length')
if [[ "$QUERY_COUNT" -eq 0 ]]; then
  exit 0
fi

# --- Search ---
SEARCH_BODY=$(jq -n \
  --argjson searches "$PARSED" \
  --arg project "$MEM_PROJECT" \
  '{searches: $searches, project: $project, limit: 5}')

SEARCH_RESULT=$(curl -sS --max-time 30 \
  -X POST \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Hook-Source: pre_tool_use" \
  -d "$SEARCH_BODY" \
  "$MEM_URL/search" 2>&1) || true

if [[ "$SEARCH_RESULT" == curl:* ]]; then
  echo "HOOK ERROR [pre-agent]: search call failed: $SEARCH_RESULT" >&2
  exit 1
fi

RESULT_COUNT=$(echo "$SEARCH_RESULT" | jq '.results | length' 2>/dev/null)
if [[ -z "$RESULT_COUNT" || "$RESULT_COUNT" -eq 0 ]]; then
  exit 0
fi

# --- Format and return ---
CONTEXT=$(echo "$SEARCH_RESULT" | jq -r '
  "## Knowledge Base Results\n\n" +
  ([.results[] |
    "### " + .title + " (" + .type + ")\n" +
    (if (.tags | length) > 0 then "*Tags: " + (.tags | join(", ")) + "*\n" else "" end) +
    .content + "\n"
  ] | join("\n---\n\n"))
')

jq -n --arg context "$CONTEXT" '{additionalContext: $context}'

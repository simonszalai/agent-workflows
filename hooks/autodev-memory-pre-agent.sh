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
  echo '{}'
  exit 0
fi
export _MEM_HOOK_ACTIVE=1

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-err-trap.sh"
source "$HOOK_DIR/mem-log.sh"

INPUT=$(cat)

# --- Parse mem config (errors caught by mem-err-trap EXIT handler) ---
MEM_ENV_SKIP=""
source "$HOOK_DIR/mem-env.sh" "$INPUT"

if [[ -n "$MEM_ENV_SKIP" ]]; then
  mem_log INFO "skip (no mem config)"
  echo '{}'
  exit 0
fi

# --- Extract subagent info ---
AGENT_PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')
AGENT_DESC=$(echo "$INPUT" | jq -r '.tool_input.description // empty')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general"')

if [[ -z "$AGENT_PROMPT" || ${#AGENT_PROMPT} -lt 30 ]]; then
  mem_log INFO "skip (prompt too short: ${#AGENT_PROMPT} chars)"
  echo '{}'
  exit 0
fi

mem_log INFO "start type=$AGENT_TYPE desc=$AGENT_DESC"

# --- Generate search queries via Haiku ---
if [[ ! -f "$HOOK_DIR/prompts/query-generation.md" ]]; then
  echo "HOOK ERROR [pre-agent]: query-generation.md not found at $HOOK_DIR/prompts/" >&2
  exit 1
fi
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
mem_log INFO "queries: count=$QUERY_COUNT body=$PARSED"
if [[ "$QUERY_COUNT" -eq 0 ]]; then
  mem_log INFO "skip (0 queries generated)"
  echo '{}'
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
  mem_log ERROR "search API unreachable: $SEARCH_RESULT"
  echo "HOOK ERROR [pre-agent]: search call failed: $SEARCH_RESULT" >&2
  exit 1
fi

RESULT_COUNT=$(echo "$SEARCH_RESULT" | jq '.results | length' 2>/dev/null || echo "0")
mem_log INFO "search results: count=$RESULT_COUNT"
if [[ -z "$RESULT_COUNT" || "$RESULT_COUNT" -eq 0 ]]; then
  mem_log INFO "done (0 results)"
  echo '{}'
  exit 0
fi

# --- Format and return ---
CONTEXT=$(echo "$SEARCH_RESULT" | jq -r '
  "## Knowledge Base Results (autodev-memory pre-agent)\n\n" +
  ([.results[] |
    "### " + .title + " (" + .type + ")\n" +
    (if (.tags | length) > 0 then "*Tags: " + (.tags | join(", ")) + "*\n" else "" end) +
    .content + "\n"
  ] | join("\n---\n\n"))
' 2>/dev/null || echo "## Knowledge Base Results (autodev-memory pre-agent)\n\n(formatting failed)")

TAGGED="<autodev-memory-hook-result source=\"pre-agent\">
$CONTEXT
</autodev-memory-hook-result>"

OUTPUT=$(jq -n --arg context "$TAGGED" '{additionalContext: $context}')
mem_log INFO "done results=$RESULT_COUNT"
mem_log_output "$OUTPUT"
echo "$OUTPUT"

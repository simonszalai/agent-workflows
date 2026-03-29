#!/usr/bin/env bash
# =============================================================================
# autodev-memory-pre-agent.sh — PreToolUse[Agent] hook for memory system
# =============================================================================
#
# When Claude spawns a subagent, extract keywords from the subagent prompt
# and search for task-specific knowledge. No LLM call needed.
#
# Requires: AUTODEV_MEMORY_API_TOKEN
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
_HOOK_EVENT_NAME="PreToolUse"
source "$HOOK_DIR/mem-log.sh"

INPUT=$(cat)

source "$HOOK_DIR/mem-init.sh"
mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip) echo '{}'; exit 0 ;;
  error) mem_init_offline_output "pre-agent" "PreToolUse" "${MEM_INIT_ERROR:-memory API unreachable}"; exit 0 ;;
esac

MEM_TRIGGER_SOURCE="pre_tool_use(Agent)"
source "$HOOK_DIR/mem-curl.sh"

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

# =============================================================================
# Extract keywords locally — no LLM needed
# =============================================================================

# Combine description + first 500 chars of prompt for keyword extraction
COMBINED_TEXT="$AGENT_DESC $AGENT_PROMPT"

STOP_WORDS="a an and but or if so the is are was were be been being have has had do does did will would shall should may might can could of in to for on with at by from as into through during before after above below between out off over under again further then once here there when where why how all each every both few more most other some such no nor not only own same than too very just also about up its it this that these those i me my we our you your he him his she her they them their what which who whom need must use find search look check read write edit create make sure let get got now new old like want know think see take give tell try put say set run way thing things still even back well much many since last first next dont"

KEYWORDS_JSON=$(echo "$COMBINED_TEXT" | head -c 500 | tr '[:upper:]' '[:lower:]' | \
  tr -cs '[:alnum:]-' '\n' | \
  awk -v stops="$STOP_WORDS" '
    BEGIN { split(stops, a, " "); for (i in a) stop[a[i]]=1 }
    length >= 3 && !stop[$0] && !seen[$0]++ { print }
  ' | head -8 | jq -R -s 'split("\n") | map(select(length > 0))')

# Use description + first 200 chars of prompt as text query
SEARCH_TEXT=$(echo "$AGENT_DESC $(echo "$AGENT_PROMPT" | head -c 200)" | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')

QUERY_DISPLAY=$(echo "$KEYWORDS_JSON" | jq -r 'join(", ")' 2>/dev/null || echo "?")
mem_log INFO "keywords: $QUERY_DISPLAY"

QUERIES=$(jq -n \
  --argjson keywords "$KEYWORDS_JSON" \
  --arg text "$SEARCH_TEXT" \
  '[{keywords: $keywords, text: $text}]')

# --- Read cached entry IDs from session start ---
EXCLUDE_IDS_JSON="null"
_IDS_FILE="$MEM_CACHE_DIR/$MEM_CACHE_KEY.ids"
if [[ -f "$_IDS_FILE" && -s "$_IDS_FILE" ]]; then
  EXCLUDE_IDS_JSON=$(jq -R -s 'split("\n") | map(select(length > 0))' < "$_IDS_FILE" 2>/dev/null || echo "null")
fi

# --- Search ---
SEARCH_BODY=$(jq -n \
  --argjson searches "$QUERIES" \
  --arg project "$MEM_PROJECT" \
  --argjson exclude_ids "$EXCLUDE_IDS_JSON" \
  '{searches: $searches, project: $project, limit: 5} + (if $exclude_ids then {exclude_ids: $exclude_ids} else {} end)')

SEARCH_RESULT=""
SEARCH_ERROR=""
if ! SEARCH_RESULT=$(mem_curl POST "/search" "$SEARCH_BODY" "pre_tool_use(Agent)"); then
  SEARCH_ERROR="$SEARCH_RESULT"
  mem_log ERROR "search API error: $SEARCH_ERROR"
  echo '{}'
  exit 0
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

OUTPUT=$(jq -n --arg context "$TAGGED" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $context}}')
mem_log INFO "done results=$RESULT_COUNT"
mem_log_output "$OUTPUT"
echo "$OUTPUT"

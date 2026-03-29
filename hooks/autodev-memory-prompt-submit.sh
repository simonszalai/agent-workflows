#!/usr/bin/env bash
# =============================================================================
# autodev-memory-prompt-submit.sh — UserPromptSubmit hook for memory system
# =============================================================================
#
# On every user message:
# 1. Quick heuristic: skip messages that won't benefit from search (instant)
# 2. Init mem-env (only if searching)
# 3. Extract keywords locally (no LLM call)
# 4. Search the KB, let score cutoffs filter garbage
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
_HOOK_EVENT_NAME="UserPromptSubmit"
source "$HOOK_DIR/mem-log.sh"

INPUT=$(cat)

# --- Extract prompt EARLY (before mem-init) for fast skip ---
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
if [[ -z "$PROMPT" ]]; then
  mem_log INFO "skip (empty prompt)"
  echo '{}'
  exit 0
fi

# --- Strip Conductor's <system_instruction> wrapper to get the actual user prompt ---
if echo "$PROMPT" | head -1 | grep -q '^<system_instruction>'; then
  PROMPT=$(echo "$PROMPT" | sed -n '/<\/system_instruction>/,$ { /<\/system_instruction>/d; p; }')
  PROMPT=$(echo "$PROMPT" | sed '/^[[:space:]]*$/{ 1d; }')  # strip leading blank line
  if [[ -z "$PROMPT" ]]; then
    mem_log INFO "skip (system_instruction only, no user prompt)"
    echo '{}'
    exit 0
  fi
  mem_log INFO "stripped <system_instruction> wrapper"
fi

# =============================================================================
# Skip heuristic — instant, before any network calls
# =============================================================================

FIRST_LINE=$(echo "$PROMPT" | head -1 | sed 's/^[[:space:]]*//')
FIRST_LINE_LOWER=$(echo "$FIRST_LINE" | tr '[:upper:]' '[:lower:]')
WORD_COUNT=$(echo "$FIRST_LINE_LOWER" | wc -w | tr -d ' ')

SHOULD_SKIP="false"
SKIP_REASON=""

# 1. Starts with < (system injection, tool result, XML tag)
if [[ "$FIRST_LINE" == "<"* ]]; then
  SHOULD_SKIP="true"
  SKIP_REASON="system injection"
fi

# 2. Starts with # (skill/command prompt header like "# LFG Command")
if [[ "$SHOULD_SKIP" == "false" && "$FIRST_LINE" == "#"* ]]; then
  SHOULD_SKIP="true"
  SKIP_REASON="skill/command header"
fi

# 3. Starts with [ (interrupt markers like "[Request interrupted")
if [[ "$SHOULD_SKIP" == "false" && "$FIRST_LINE" == "["* ]]; then
  SHOULD_SKIP="true"
  SKIP_REASON="interrupt marker"
fi

# 4. Bare slash command (single word starting with /, no spaces)
if [[ "$SHOULD_SKIP" == "false" && "$FIRST_LINE_LOWER" == /* ]] && ! echo "$FIRST_LINE_LOWER" | grep -q ' '; then
  SHOULD_SKIP="true"
  SKIP_REASON="bare slash command"
fi

# 5. Very short (≤3 words) and not a question
if [[ "$SHOULD_SKIP" == "false" && "$WORD_COUNT" -le 3 ]]; then
  IS_QUESTION="false"
  case "$FIRST_LINE_LOWER" in
    how\ *|why\ *|what\ *|where\ *|when\ *|which\ *|does\ *|is\ *|are\ *|can\ *|could\ *|should\ *|would\ *)
      IS_QUESTION="true" ;;
  esac
  if [[ "$IS_QUESTION" == "false" ]]; then
    SHOULD_SKIP="true"
    SKIP_REASON="short non-question ($WORD_COUNT words)"
  fi
fi

if [[ "$SHOULD_SKIP" == "true" ]]; then
  mem_log INFO "skip ($SKIP_REASON)"
  # Return empty — no need for a status line on skipped messages
  echo '{}'
  exit 0
fi

mem_log INFO "start prompt=$(echo "$PROMPT" | head -c 120)"

# =============================================================================
# Init mem-env (only runs for messages that will be searched)
# =============================================================================

source "$HOOK_DIR/mem-init.sh"
mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip)  echo '{}'; exit 0 ;;
  error) mem_init_offline_output "prompt-submit" "UserPromptSubmit" "${MEM_INIT_ERROR:-memory API unreachable}"; exit 0 ;;
esac

MEM_TRIGGER_SOURCE="prompt_submit"
# MEM_USER_PROMPT is already set by mem-env.sh (extracted from .prompt field)

source "$HOOK_DIR/mem-curl.sh"

# =============================================================================
# Extract keywords locally — no LLM needed
# =============================================================================

STOP_WORDS="a an and but or if so the is are was were be been being have has had do does did will would shall should may might can could of in to for on with at by from as into through during before after above below between out off over under again further then once here there when where why how all each every both few more most other some such no nor not only own same than too very just also about up its it this that these those i me my we our you your he him his she her they them their what which who whom let lets get got now new old like want need know think see look make take give tell try put say set run way thing things still even back well much many since last first next dont anything nothing everything something hello hey thanks yeah yep nope okay sure right great nice cool fine please already always never maybe probably basically actually really quite pretty rather"

KEYWORDS_JSON=$(echo "$PROMPT" | head -c 500 | tr '[:upper:]' '[:lower:]' | \
  tr -cs '[:alnum:]-' '\n' | \
  awk -v stops="$STOP_WORDS" '
    BEGIN { split(stops, a, " "); for (i in a) stop[a[i]]=1 }
    length >= 3 && !stop[$0] && !seen[$0]++ { print }
  ' | head -8 | jq -R -s 'split("\n") | map(select(length > 0))')

KEYWORD_COUNT=$(echo "$KEYWORDS_JSON" | jq 'length' 2>/dev/null || echo "0")
if [[ "$KEYWORD_COUNT" -le 1 ]]; then
  mem_log INFO "skip (too few keywords after filtering: $KEYWORD_COUNT)"
  echo '{}'
  exit 0
fi

SEARCH_TEXT=$(echo "$PROMPT" | head -c 200 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')

QUERY_DISPLAY=$(echo "$KEYWORDS_JSON" | jq -r 'join(", ")' 2>/dev/null || echo "?")
mem_log INFO "keywords: $QUERY_DISPLAY | text: $(echo "$SEARCH_TEXT" | head -c 80)"

QUERIES=$(jq -n \
  --argjson keywords "$KEYWORDS_JSON" \
  --arg text "$SEARCH_TEXT" \
  '[{keywords: $keywords, text: $text}]')

# =============================================================================
# Search
# =============================================================================

EXCLUDE_IDS_JSON="null"
_IDS_FILE="$MEM_CACHE_DIR/$MEM_CACHE_KEY.ids"
if [[ -f "$_IDS_FILE" && -s "$_IDS_FILE" ]]; then
  EXCLUDE_IDS_JSON=$(jq -R -s 'split("\n") | map(select(length > 0))' < "$_IDS_FILE" 2>/dev/null || echo "null")
  _EXCLUDE_COUNT=$(echo "$EXCLUDE_IDS_JSON" | jq 'length' 2>/dev/null || echo "0")
  mem_log INFO "excluding $_EXCLUDE_COUNT already-injected entry IDs"
fi

SEARCH_BODY=$(jq -n \
  --argjson searches "$QUERIES" \
  --arg project "$MEM_PROJECT" \
  --argjson exclude_ids "$EXCLUDE_IDS_JSON" \
  '{searches: $searches, project: $project, limit: 5} + (if $exclude_ids then {exclude_ids: $exclude_ids} else {} end)')

SEARCH_RESULT=""
SEARCH_ERROR=""
if ! SEARCH_RESULT=$(mem_curl POST "/search" "$SEARCH_BODY" "user_prompt"); then
  SEARCH_ERROR="$SEARCH_RESULT"
fi

# =============================================================================
# Format results
# =============================================================================

SEARCH_SECTION=""
STATUS_LINE=""

if [[ -n "$SEARCH_ERROR" ]]; then
  mem_log ERROR "search API error: $SEARCH_ERROR"
  STATUS_LINE="Memory: search FAILED"
  SEARCH_SECTION="Queries: $QUERY_DISPLAY
Result: $SEARCH_ERROR"
else
  RESULT_COUNT=$(echo "$SEARCH_RESULT" | jq '.results | length' 2>/dev/null || echo "0")
  mem_log INFO "search results: count=$RESULT_COUNT"

  if [[ "$RESULT_COUNT" -eq 0 ]]; then
    STATUS_LINE="Memory: searched — 0 results"
    SEARCH_SECTION="Queries: $QUERY_DISPLAY
Result: 0 entries found"
  else
    RESULTS_FORMATTED=$(echo "$SEARCH_RESULT" | jq -r '
      [.results[] |
        "### " + .title + " (" + .type + ")\n" +
        (if (.tags | length) > 0 then "*Tags: " + (.tags | join(", ")) + "*\n" else "" end) +
        .content + "\n"
      ] | join("\n---\n\n")
    ' 2>/dev/null || echo "(autodev-memory prompt-submit: result formatting failed)")

    ENTRY_INDEX=$(echo "$SEARCH_RESULT" | jq -r '
      [.results[] | "- " + (.entry_id // .id | tostring | .[0:8]) + " " + .type + ": " + (.title[:60])] | join("\n")
    ' 2>/dev/null || echo "")
    STATUS_LINE="Memory: searched — $RESULT_COUNT results added to context
$ENTRY_INDEX"
    SEARCH_SECTION="Queries: $QUERY_DISPLAY
Result: $RESULT_COUNT entries

$RESULTS_FORMATTED"

    # Append new entry IDs to cache so subsequent prompts exclude them
    if [[ -n "$_IDS_FILE" ]]; then
      echo "$SEARCH_RESULT" | jq -r '.results[] | .entry_id // .id' 2>/dev/null >> "$_IDS_FILE"
      mem_log INFO "appended $RESULT_COUNT IDs to cache"
    fi
  fi
fi

# =============================================================================
# Assemble final context
# =============================================================================

CONTEXT="<autodev-memory-hook-result source=\"prompt-submit\">
MANDATORY: Start your reply with EXACTLY this text (all lines, verbatim):
$STATUS_LINE

$SEARCH_SECTION
</autodev-memory-hook-result>"

OUTPUT=$(jq -n --arg context "$CONTEXT" '{hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $context}}')
mem_log INFO "done status_line=$STATUS_LINE"
mem_log_output "$OUTPUT"
echo "$OUTPUT"

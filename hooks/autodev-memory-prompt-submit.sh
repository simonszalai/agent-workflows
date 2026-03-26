#!/usr/bin/env bash
# =============================================================================
# autodev-memory-prompt-submit.sh — UserPromptSubmit hook for memory system
# =============================================================================
#
# On every user message:
# 1. (blocking) Generate search queries via Haiku (claude -p), search KB, return as context
# 2. (blocking) If ??? detected, run correction + investigation
# 3. (blocking) If !!! detected, run correction detection synchronously
#
# Requires: AUTODEV_MEMORY_API_TOKEN, claude CLI on PATH
# =============================================================================

set -euo pipefail

# --- Recursion guard: claude -p subprocess also triggers this hook ---
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  exit 0
fi
export _MEM_HOOK_ACTIVE=1

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"

INPUT=$(cat)

# --- Parse mem config (dies on misconfiguration) ---
source "$HOOK_DIR/mem-env.sh" "$INPUT"

# --- Extract prompt ---
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
if [[ -z "$PROMPT" ]]; then
  exit 0
fi

# --- Read recent conversation for context ---
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '(.transcript_path // .session.transcript_path) // empty')

# --- WTF trigger: ??? runs correction-detect + signals investigation ---
if echo "$PROMPT" | grep -qF "???"; then
  CLEAN_PROMPT=$(echo "$PROMPT" | sed 's/???//g')

  DETECT_OUTPUT=$("$HOOK_DIR/autodev-memory-correction-detect.sh" \
    "$MEM_PROJECT" "$MEM_REPO" "$MEM_URL" "$MEM_TOKEN" \
    "$CLEAN_PROMPT" "$TRANSCRIPT_PATH" 2>&1) || true

  # Pull recent operation logs for investigation context
  RECENT_SEARCHES=$(curl -sS --max-time 5 \
    -H "Authorization: Bearer $MEM_TOKEN" \
    "$MEM_URL/debug-logs?project=$MEM_PROJECT&operation=search&hours=2&limit=10" 2>/dev/null) || true

  WTF_CONTEXT="[Memory Hook] ??? WTF trigger activated.

## Correction Result
$DETECT_OUTPUT

## Investigation Required
The user flagged this as a memory system failure. Use the autodev-wtf methodology to
investigate why the memory system didn\'t prevent this error.

Load the autodev-wtf skill for the investigation methodology, then:
1. Analyze the recent search operations below
2. Check if relevant knowledge existed but wasn\'t surfaced
3. Diagnose the root cause category
4. Report your verdict

## Recent Search Operations (for investigation)
$RECENT_SEARCHES"

  if [[ ${#PROMPT} -lt 20 ]]; then
    jq -n --arg ctx "$WTF_CONTEXT" '{additionalContext: $ctx}'
    exit 0
  fi

  FORCE_WTF_RESULT="$WTF_CONTEXT"
fi

# --- Force-compound shortcut: !!! runs correction-detect SYNCHRONOUSLY ---
if echo "$PROMPT" | grep -qF "!!!"; then
  DETECT_OUTPUT=$("$HOOK_DIR/autodev-memory-correction-detect.sh" \
    "$MEM_PROJECT" "$MEM_REPO" "$MEM_URL" "$MEM_TOKEN" \
    "$PROMPT" "$TRANSCRIPT_PATH" 2>&1) || true

  # If the prompt is short (just !!! or !!! with a few words), return result and stop
  if [[ ${#PROMPT} -lt 20 ]]; then
    jq -n --arg ctx "[Memory Hook] Correction detection (!!!): $DETECT_OUTPUT" \
      '{additionalContext: $ctx}'
    exit 0
  fi

  # Otherwise, continue with search but carry the result
  FORCE_COMPOUND_RESULT="$DETECT_OUTPUT"
fi

# --- Length guard: skip short prompts for search/correction ---
if [[ ${#PROMPT} -lt 20 ]]; then
  exit 0
fi

RECENT=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  RECENT=$(tail -100 "$TRANSCRIPT_PATH" | jq -sc '
    [.[] | select(.type == "human" or .type == "assistant")]
    | .[-3:]
    | [.[] | if .type == "assistant" then .content = (.content[:200] + "...") else . end]
  ' 2>/dev/null || echo "[]")
fi

# --- Generate search queries via Haiku ---
QUERY_TEMPLATE=$(cat "$HOOK_DIR/prompts/query-generation.md")

RECENT_TEXT=""
if [[ -n "$RECENT" && "$RECENT" != "[]" ]]; then
  RECENT_TEXT=$(echo "$RECENT" | jq -r '.[] | .type + ": " + (.content // "" | tostring)[:500]' 2>/dev/null | tail -c 3000)
fi

QUERY_PROMPT="$QUERY_TEMPLATE

Current repo: ${MEM_REPO}
Project repos:
$MEM_TOPOLOGY

Recent conversation:
$RECENT_TEXT

Current message: $PROMPT"

QUERIES=$(echo "$QUERY_PROMPT" | claude -p --model haiku --output-format json 2>/dev/null) || true

if [[ -z "$QUERIES" ]]; then
  echo "HOOK ERROR [prompt-submit]: claude -p --model haiku returned nothing" >&2
  exit 1
fi

# claude -p --output-format json returns envelope; extract .result
HAIKU_TEXT=$(echo "$QUERIES" | jq -r '.result // empty' 2>/dev/null)
if [[ -z "$HAIKU_TEXT" ]]; then
  IS_ERROR=$(echo "$QUERIES" | jq -r '.is_error // false' 2>/dev/null)
  if [[ "$IS_ERROR" == "true" ]]; then
    ERROR_MSG=$(echo "$QUERIES" | jq -r '.result // "unknown error"' 2>/dev/null)
    echo "HOOK ERROR [prompt-submit]: Haiku CLI error: $ERROR_MSG" >&2
    exit 1
  fi
  echo "HOOK ERROR [prompt-submit]: Haiku returned empty result. Full response: $QUERIES" >&2
  exit 1
fi

# Parse JSON array from Haiku text (may be wrapped in markdown code block)
PARSED=$(echo "$HAIKU_TEXT" | sed 's/^```json//; s/^```//; s/```$//' | jq -c '.' 2>/dev/null || echo "")
if [[ -z "$PARSED" ]] || ! echo "$PARSED" | jq -e 'type == "array"' >/dev/null 2>&1; then
  echo "HOOK ERROR [prompt-submit]: Haiku returned non-array: $HAIKU_TEXT" >&2
  exit 1
fi

QUERY_COUNT=$(echo "$PARSED" | jq 'length')
if [[ "$QUERY_COUNT" -eq 0 ]]; then
  # Still return WTF or force-compound result if we have one
  if [[ -n "${FORCE_WTF_RESULT:-}" ]]; then
    jq -n --arg ctx "$FORCE_WTF_RESULT" '{additionalContext: $ctx}'
  elif [[ -n "${FORCE_COMPOUND_RESULT:-}" ]]; then
    jq -n --arg ctx "[Memory Hook] Correction detection (!!!): $FORCE_COMPOUND_RESULT" \
      '{additionalContext: $ctx}'
  fi
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
  -H "X-Hook-Source: user_prompt" \
  -d "$SEARCH_BODY" \
  "$MEM_URL/search" 2>&1) || true

if [[ "$SEARCH_RESULT" == curl:* ]]; then
  echo "HOOK ERROR [prompt-submit]: search call failed: $SEARCH_RESULT" >&2
  exit 1
fi

RESULT_COUNT=$(echo "$SEARCH_RESULT" | jq '.results | length' 2>/dev/null)
if [[ -z "$RESULT_COUNT" || "$RESULT_COUNT" -eq 0 ]]; then
  if [[ -n "${FORCE_WTF_RESULT:-}" ]]; then
    jq -n --arg ctx "$FORCE_WTF_RESULT" '{additionalContext: $ctx}'
  elif [[ -n "${FORCE_COMPOUND_RESULT:-}" ]]; then
    jq -n --arg ctx "[Memory Hook] Correction detection (!!!): $FORCE_COMPOUND_RESULT" \
      '{additionalContext: $ctx}'
  fi
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

# Prepend WTF investigation result if present
if [[ -n "${FORCE_WTF_RESULT:-}" ]]; then
  CONTEXT="$FORCE_WTF_RESULT

$CONTEXT"
fi

# Prepend force-compound result if present
if [[ -n "${FORCE_COMPOUND_RESULT:-}" ]]; then
  CONTEXT="[Memory Hook] Correction detection (!!!): $FORCE_COMPOUND_RESULT

$CONTEXT"
fi

jq -n --arg context "$CONTEXT" '{additionalContext: $context}'

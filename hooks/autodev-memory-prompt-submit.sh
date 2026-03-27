#!/usr/bin/env bash
# =============================================================================
# autodev-memory-prompt-submit.sh — UserPromptSubmit hook for memory system
# =============================================================================
#
# On every user message (all steps blocking/sync):
# 1. If ??? detected → run correction-detect + fetch debug logs
# 2. If !!! detected → run correction-detect
# 3. If >>> detected → run glossary extraction
# 4. Ask Haiku whether a KB search is warranted (sees message + last 3 exchanges)
# 5. If yes → generate queries, search, return results
# 6. Return everything with explicit instructions for AI to report to user
#
# Requires: AUTODEV_MEMORY_API_TOKEN, claude CLI on PATH
# =============================================================================

set -euo pipefail

# --- Recursion guard: claude -p subprocess also triggers this hook ---
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

# --- Extract prompt ---
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty')
if [[ -z "$PROMPT" ]]; then
  mem_log INFO "skip (empty prompt)"
  echo '{}'
  exit 0
fi

mem_log INFO "start prompt=$(echo "$PROMPT" | head -c 120)"

# --- Read recent conversation (last 3 user messages + truncated AI responses) ---
TRANSCRIPT_PATH=$(echo "$INPUT" | jq -r '(.transcript_path // .session.transcript_path) // empty')

RECENT_CONTEXT=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  RECENT_CONTEXT=$(tail -200 "$TRANSCRIPT_PATH" | jq -sc '
    [.[] | select(.type == "human" or .type == "assistant")]
    | .[-6:]
    | [.[] |
        if .type == "assistant"
        then {type, content: (.content[:300] + "...")}
        else {type, content}
        end
      ]
  ' 2>/dev/null || echo "[]")
fi

RECENT_TEXT=""
if [[ -n "$RECENT_CONTEXT" && "$RECENT_CONTEXT" != "[]" ]]; then
  RECENT_TEXT=$(echo "$RECENT_CONTEXT" | jq -r '.[] | .type + ": " + (.content // "" | tostring)[:500]' 2>/dev/null | tail -c 3000)
fi

# =============================================================================
# Step 1: Triple-char trigger dispatch (all sync)
#
# To switch any trigger to async later, replace:
#   RESULT=$( "$HOOK_DIR/script.sh" args 2>&1 ) || true
# with:
#   "$HOOK_DIR/script.sh" args >/dev/null 2>&1 &
#   RESULT="[fired] running in background (pid $!)"
# =============================================================================

TRIGGER_SECTION=""
CLEAN_PROMPT="$PROMPT"

# --- WTF trigger: ??? ---
if echo "$PROMPT" | grep -qF "???"; then
  mem_log INFO "trigger: ??? WTF"
  CLEAN_PROMPT=$(echo "$PROMPT" | sed 's/???//g')

  DETECT_OUTPUT=$("$HOOK_DIR/autodev-memory-correction-detect.sh" \
    "$MEM_PROJECT" "$MEM_REPO" "$MEM_URL" "$MEM_TOKEN" \
    "$CLEAN_PROMPT" "$TRANSCRIPT_PATH" 2>&1) || true

  RECENT_SEARCHES=$(curl -sS --max-time 5 \
    -H "Authorization: Bearer $MEM_TOKEN" \
    "$MEM_URL/debug-logs?project=$MEM_PROJECT&operation=search&hours=2&limit=10" 2>/dev/null) || true

  TRIGGER_SECTION="## Trigger: ??? WTF Investigation

### Correction Result
$DETECT_OUTPUT

### Investigation Required
The user flagged this as a memory system failure. Use the autodev-wtf methodology to
investigate why the memory system didn\'t prevent this error.

Load the autodev-wtf skill for the investigation methodology, then:
1. Analyze the recent search operations below
2. Check if relevant knowledge existed but wasn\'t surfaced
3. Diagnose the root cause category
4. Report your verdict

### Recent Search Operations
$RECENT_SEARCHES

**IMPORTANT: Before doing anything else, report the WTF trigger results to the user.
Tell them what the correction detection found and that you are beginning the investigation.**"

# --- Force-compound: !!! ---
elif echo "$PROMPT" | grep -qF "!!!"; then
  mem_log INFO "trigger: !!! force-compound"
  CLEAN_PROMPT=$(echo "$PROMPT" | sed 's/!!!//g')

  DETECT_OUTPUT=$("$HOOK_DIR/autodev-memory-correction-detect.sh" \
    "$MEM_PROJECT" "$MEM_REPO" "$MEM_URL" "$MEM_TOKEN" \
    "$PROMPT" "$TRANSCRIPT_PATH" 2>&1) || true

  TRIGGER_SECTION="## Trigger: !!! Correction Detection

Result: $DETECT_OUTPUT

**IMPORTANT: Before doing anything else, report the correction detection result to the user.
Tell them what was captured/stored/skipped and why.**"

# --- Glossary: >>> ---
elif echo "$PROMPT" | grep -qF ">>>"; then
  mem_log INFO "trigger: >>> glossary"
  CLEAN_PROMPT=$(echo "$PROMPT" | sed 's/>>>//g')

  GLOSSARY_OUTPUT=$("$HOOK_DIR/autodev-memory-glossary-extract.sh" \
    "$MEM_PROJECT" "$MEM_URL" "$MEM_TOKEN" \
    "$PROMPT" "$TRANSCRIPT_PATH" 2>&1) || true

  TRIGGER_SECTION="## Trigger: >>> Glossary Extraction

Result: $GLOSSARY_OUTPUT

**IMPORTANT: Before doing anything else, report the glossary extraction result to the user.
Tell them what term was defined/updated or if extraction failed and why.**"
fi

# =============================================================================
# Step 2: Search decision — Haiku decides if KB search is warranted
# =============================================================================

if [[ ! -f "$HOOK_DIR/prompts/search-decision.md" ]]; then
  echo "HOOK ERROR [prompt-submit]: search-decision.md not found at $HOOK_DIR/prompts/" >&2
  exit 1
fi
DECISION_TEMPLATE=$(cat "$HOOK_DIR/prompts/search-decision.md")

DECISION_PROMPT="$DECISION_TEMPLATE

Current repo: ${MEM_REPO}
Project repos:
$MEM_TOPOLOGY

Recent conversation:
$RECENT_TEXT

Current message: $CLEAN_PROMPT"

DECISION_RAW=$(echo "$DECISION_PROMPT" | claude -p --model haiku --output-format json 2>/dev/null) || true
DECISION_TEXT=$(echo "$DECISION_RAW" | jq -r '.result // empty' 2>/dev/null || true)

# Parse decision — degrade gracefully if Haiku failed
SHOULD_SEARCH="false"
SEARCH_REASON="search decision unavailable (Haiku call failed)"

if [[ -n "$DECISION_TEXT" ]]; then
  DECISION=$(echo "$DECISION_TEXT" | sed 's/^```json//; s/^```//; s/```$//' | jq -c '.' 2>/dev/null || echo '{}')
  SHOULD_SEARCH=$(echo "$DECISION" | jq -r '.search // false')
  SEARCH_REASON=$(echo "$DECISION" | jq -r '.reason // "no reason given"')
fi

mem_log INFO "search decision: should_search=$SHOULD_SEARCH reason=$SEARCH_REASON"

# =============================================================================
# Step 3: If search warranted, extract queries and search
# =============================================================================

SEARCH_SECTION=""
STATUS_LINE=""

if [[ "$SHOULD_SEARCH" == "true" ]]; then
  QUERIES=$(echo "$DECISION" | jq -c '.queries // []' 2>/dev/null || echo '[]')
  QUERY_COUNT=$(echo "$QUERIES" | jq 'length' 2>/dev/null || echo "0")
  QUERY_DISPLAY=$(echo "$QUERIES" | jq -r '[.[] | (.keywords // [] | join(", ")) + ": " + (.text // .query // "")] | join(" | ")' 2>/dev/null || echo "(autodev-memory prompt-submit: query format error)")

  mem_log INFO "queries: count=$QUERY_COUNT display=$QUERY_DISPLAY"

  if [[ "$QUERY_COUNT" -eq 0 ]]; then
    STATUS_LINE="Memory: search warranted but no queries generated"
    SEARCH_SECTION="Queries: (none generated)"
  else
    # Execute search
    SEARCH_BODY=$(jq -n \
      --argjson searches "$QUERIES" \
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
      mem_log ERROR "search API unreachable: $SEARCH_RESULT"
      STATUS_LINE="Memory: search failed (API unreachable)"
      SEARCH_SECTION="Queries: $QUERY_DISPLAY
Result: API call failed"
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

        STATUS_LINE="Memory: searched — $RESULT_COUNT results added to context"
        SEARCH_SECTION="Queries: $QUERY_DISPLAY
Result: $RESULT_COUNT entries

$RESULTS_FORMATTED"
      fi
    fi
  fi
else
  STATUS_LINE="Memory: no search needed"
  SEARCH_SECTION="Reason: $SEARCH_REASON"
fi

# =============================================================================
# Assemble final context
# =============================================================================

CONTEXT="<autodev-memory-hook-result source=\"prompt-submit\">
MANDATORY: Start your reply with this single status line (no extra text around it):
$STATUS_LINE"

if [[ -n "$TRIGGER_SECTION" ]]; then
  CONTEXT="$CONTEXT

$TRIGGER_SECTION"
fi

CONTEXT="$CONTEXT

$SEARCH_SECTION
</autodev-memory-hook-result>"

OUTPUT=$(jq -n --arg context "$CONTEXT" '{additionalContext: $context}')
mem_log INFO "done status_line=$STATUS_LINE"
mem_log_output "$OUTPUT"
echo "$OUTPUT"

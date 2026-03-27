#!/usr/bin/env bash
# =============================================================================
# autodev-memory-glossary-extract.sh — Extract and store glossary terms
# =============================================================================
#
# Called by prompt-submit.sh when >>> trigger detected. Runs Sonnet to extract
# the term being defined, then POSTs to /glossary API.
#
# Arguments: $1=project $2=url $3=token $4=prompt $5=transcript_path
# =============================================================================

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-log.sh"

report() {
  local status="$1" message="$2"
  mem_log INFO "report: [$status] $message"
  echo "[$status] $message"
}

trap 'mem_log ERROR "crashed at line $LINENO"; report "error" "glossary-extract crashed at line $LINENO"' ERR

MEM_PROJECT="$1"
MEM_URL="$2"
MEM_TOKEN="$3"
PROMPT="$4"
TRANSCRIPT_PATH="${5:-}"

mem_log INFO "start project=$MEM_PROJECT prompt=$(echo "$PROMPT" | head -c 100)"

# Strip >>> from prompt
CLEAN_PROMPT=$(echo "$PROMPT" | sed 's/>>>//g')

# --- Get recent conversation for context ---
RECENT=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  RECENT=$(jq -c '
    [.[] | select(.type == "human" or .type == "assistant")]
    | .[-3:]
    | [.[] | {type, content: (.content[:300])}]
  ' "$TRANSCRIPT_PATH" 2>/dev/null || echo "[]")
fi

# --- Call Sonnet to extract term ---
if [[ ! -f "$HOOK_DIR/prompts/glossary-extract.md" ]]; then
  echo "HOOK ERROR [glossary-extract]: glossary-extract.md not found at $HOOK_DIR/prompts/" >&2
  exit 1
fi
EXTRACT_TEMPLATE=$(cat "$HOOK_DIR/prompts/glossary-extract.md")

RECENT_TEXT=""
if [[ -n "$RECENT" && "$RECENT" != "[]" ]]; then
  RECENT_TEXT=$(echo "$RECENT" | jq -r '.[] | .type + ": " + (.content // "" | tostring)[:300]' 2>/dev/null | tail -c 2000)
fi

EXTRACT_PROMPT="$EXTRACT_TEMPLATE

Project: $MEM_PROJECT

Recent conversation:
$RECENT_TEXT

User message (>>> stripped):
$CLEAN_PROMPT"

EXTRACTION=$(echo "$EXTRACT_PROMPT" | claude -p --output-format json 2>/dev/null) || true

if [[ -z "$EXTRACTION" ]]; then
  report "error" "claude -p returned nothing"
  exit 0
fi

EXTRACT_TEXT=$(echo "$EXTRACTION" | jq -r '.result // empty' 2>/dev/null)
if [[ -z "$EXTRACT_TEXT" ]]; then
  report "error" "Sonnet returned empty result"
  exit 0
fi

# Parse JSON (may be wrapped in markdown code block)
PARSED=$(echo "$EXTRACT_TEXT" | sed 's/^```json//; s/^```//; s/```$//' | jq -c '.' 2>/dev/null || echo '{}')

TERM=$(echo "$PARSED" | jq -r '.term // empty')
mem_log INFO "extracted term=$TERM"
if [[ -z "$TERM" || "$TERM" == "null" ]]; then
  REASON=$(echo "$PARSED" | jq -r '.reason // "could not identify term"')
  report "skipped" "No term extracted: $REASON"
  exit 0
fi

DESCRIPTION=$(echo "$PARSED" | jq -r '.description // empty')
TERM_PROJECT=$(echo "$PARSED" | jq -r 'if .project == null or .project == "null" then empty else .project end')

# --- POST to glossary API ---
GLOSSARY_BODY=$(jq -n \
  --arg term "$TERM" \
  --arg description "$DESCRIPTION" \
  --arg project "${TERM_PROJECT:-$MEM_PROJECT}" \
  '{term: $term, description: $description, project: $project}')

STORE_RESULT=$(curl -sS --max-time 5 \
  -X POST \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Hook-Source: glossary_extract" \
  -d "$GLOSSARY_BODY" \
  "$MEM_URL/glossary" 2>&1) || true

STORE_ID=$(echo "$STORE_RESULT" | jq -r '.id // empty' 2>/dev/null)
if [[ -n "$STORE_ID" ]]; then
  report "success" "Defined: **$TERM** = $DESCRIPTION (project=${TERM_PROJECT:-$MEM_PROJECT})"
else
  report "error" "Failed to store term: $(echo "$STORE_RESULT" | head -c 200)"
fi

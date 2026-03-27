#!/usr/bin/env bash
# =============================================================================
# autodev-memory-correction-detect.sh — Background correction detection pipeline
# =============================================================================
#
# Called by mem-prompt-submit.sh when the regex gate matches. Runs entirely in
# the background (fire-and-forget). Never blocks the main search path.
#
# 4-step pipeline:
#   Step 1: Classify + extract (Sonnet) — is this a real correction?
#   Step 2: Fetch KB entry index — titles + summaries
#   Step 3a: Pick candidates (Sonnet) — which entries might overlap?
#   Step 3b: Fetch candidate full content
#   Step 3c: Decide action (Sonnet) — new/supersede/append/rebalance/deprecate/skip
#   Step 4: Execute via POST /store
#
# Arguments: $1=project $2=repo $3=service_url $4=token $5=prompt $6=transcript_path
# =============================================================================

set -euo pipefail

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-log.sh"

report() {
  local status="$1" message="$2"
  mem_log INFO "report: [$status] $message"
  echo "[$status] $message"
}

trap 'mem_log ERROR "crashed at line $LINENO"; report "error" "correction-detect crashed at line $LINENO"' ERR

MEM_PROJECT="$1"
MEM_REPO="$2"
MEM_URL="$3"
MEM_TOKEN="$4"
PROMPT="$5"
TRANSCRIPT_PATH="${6:-}"

mem_log INFO "start project=$MEM_PROJECT force_trigger=$(echo "$PROMPT" | grep -oF '!!!' || echo "$PROMPT" | grep -oF '???' || echo 'none')"

# --- Detect forced trigger (!!! or ???) ---
FORCE_COMPOUND=false
if echo "$PROMPT" | grep -qF '!!!'; then
  FORCE_COMPOUND=true
fi
if echo "$PROMPT" | grep -qF '???'; then
  FORCE_COMPOUND=true
fi

# --- Step 1: Classify + Extract ---

# Get last 5 messages for context
RECENT=""
if [[ -n "$TRANSCRIPT_PATH" && -f "$TRANSCRIPT_PATH" ]]; then
  RECENT=$(jq -c '
    [.[] | select(.type == "human" or .type == "assistant")]
    | .[-5:]
    | [.[] | {type, content: (.content[:500])}]
  ' "$TRANSCRIPT_PATH"  || echo "[]")
fi

if [[ ! -f "$HOOK_DIR/prompts/classify-and-extract.md" ]]; then
  echo "HOOK ERROR [correction-detect]: classify-and-extract.md not found at $HOOK_DIR/prompts/" >&2
  exit 1
fi
CLASSIFY_TEMPLATE=$(cat "$HOOK_DIR/prompts/classify-and-extract.md")
if [[ "$FORCE_COMPOUND" == "true" ]]; then
  CLASSIFY_TEMPLATE="The user explicitly marked this message for knowledge capture (!!!).
Treat this as a CORRECTION — do NOT skip. Extract the knowledge the user wants to save.
Strip the !!! from the content before extracting.

$CLASSIFY_TEMPLATE"
fi
CLASSIFY_PROMPT="$CLASSIFY_TEMPLATE

Recent conversation:
$(echo "$RECENT" | jq -r '.[] | .type + ": " + (.content // "")'  | tail -c 4000)

User message to classify:
$PROMPT"

CLASSIFICATION=$(echo "$CLASSIFY_PROMPT" | claude -p --output-format json  || echo '{"type":"skip"}')

CLASS_TYPE=$(echo "$CLASSIFICATION" | jq -r '.type // "skip"')
mem_log INFO "step1 classify: type=$CLASS_TYPE"
if [[ "$CLASS_TYPE" != "correction" && "$FORCE_COMPOUND" != "true" ]]; then
  report "skipped" "Step 1 classify: type=$CLASS_TYPE (not a correction)"
  exit 0
fi

# Extract fields
SUMMARY=$(echo "$CLASSIFICATION" | jq -r '.summary // empty')
KNOWLEDGE=$(echo "$CLASSIFICATION" | jq -r '.knowledge // empty')
ENTRY_TYPE=$(echo "$CLASSIFICATION" | jq -r '.entry_type // "correction"')
SUGGESTED_TAGS=$(echo "$CLASSIFICATION" | jq -c '.suggested_tags // []')

if [[ -z "$KNOWLEDGE" ]]; then
  report "skipped" "Step 1 extract: classification returned empty knowledge"
  exit 0
fi

# --- Step 2: Fetch KB entry index ---

INDEX_RESULT=$(curl -sS --max-time 5 \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "X-Hook-Source: correction_detect" \
  "$MEM_URL/entries/index?project=$MEM_PROJECT"  || echo '{"entries":[]}')

INDEX_COUNT=$(echo "$INDEX_RESULT" | jq '.entries | length'  || echo "0")
mem_log INFO "step2 index: $INDEX_COUNT entries"

# --- Step 3a: Pick candidates ---

CANDIDATES='{"candidates":[]}'
if [[ "$INDEX_COUNT" -gt 0 ]]; then
  if [[ ! -f "$HOOK_DIR/prompts/match-entry.md" ]]; then
    echo "HOOK ERROR [correction-detect]: match-entry.md not found at $HOOK_DIR/prompts/" >&2
    exit 1
  fi
  MATCH_TEMPLATE=$(cat "$HOOK_DIR/prompts/match-entry.md")
  MATCH_PROMPT="$MATCH_TEMPLATE

EXTRACTED KNOWLEDGE:
Summary: $SUMMARY
Tags: $SUGGESTED_TAGS
Content:
$KNOWLEDGE

ENTRY INDEX:
$(echo "$INDEX_RESULT" | jq -r '.entries[] | "- " + .id + " | " + .title + " | tags=" + ((.tags // []) | join(",")) + " | " + (.summary // "no summary")')"

  CANDIDATES=$(echo "$MATCH_PROMPT" | claude -p --output-format json  || echo '{"candidates":[]}')
fi

CANDIDATE_IDS=$(echo "$CANDIDATES" | jq -r '.candidates // [] | .[]' )
mem_log INFO "step3a candidates: $CANDIDATE_IDS"

# --- Step 3b: Fetch candidate full content ---

CANDIDATE_ENTRIES=""
for CID in $CANDIDATE_IDS; do
  ENTRY=$(curl -sS --max-time 3 \
    -H "Authorization: Bearer $MEM_TOKEN" \
    "$MEM_URL/entries/$CID?project=$MEM_PROJECT"  || true)
  if [[ -n "$ENTRY" ]]; then
    TITLE=$(echo "$ENTRY" | jq -r '.title // "untitled"')
    CONTENT=$(echo "$ENTRY" | jq -r '.content // ""')
    CANDIDATE_ENTRIES="$CANDIDATE_ENTRIES
--- Entry $CID ---
Title: $TITLE
$CONTENT
"
  fi
done

# --- Step 3c: Decide action ---

if [[ ! -f "$HOOK_DIR/prompts/decide-action.md" ]]; then
  echo "HOOK ERROR [correction-detect]: decide-action.md not found at $HOOK_DIR/prompts/" >&2
  exit 1
fi
DECIDE_TEMPLATE=$(cat "$HOOK_DIR/prompts/decide-action.md")
DECIDE_PROMPT="$DECIDE_TEMPLATE

EXTRACTED KNOWLEDGE:
Summary: $SUMMARY
Suggested tags: $SUGGESTED_TAGS
Type: $ENTRY_TYPE
Content:
$KNOWLEDGE

CANDIDATE ENTRIES:
${CANDIDATE_ENTRIES:-No candidates found — this appears to be new knowledge.}"

DECISION=$(echo "$DECIDE_PROMPT" | claude -p --output-format json  || echo '{"action":"skip","reason":"decision call failed"}')

ACTION=$(echo "$DECISION" | jq -r '.action // "skip"')
mem_log INFO "step3c decide: action=$ACTION"
if [[ "$ACTION" == "skip" ]]; then
  REASON=$(echo "$DECISION" | jq -r '.reason // "no reason"')
  report "skipped" "Step 3c decide: action=skip reason=$REASON"
  exit 0
fi

# --- Step 4: Execute via POST /store ---

# Build store request based on action
case "$ACTION" in
  new)
    STORE_BODY=$(jq -n \
      --arg action "new" \
      --arg title "$SUMMARY" \
      --arg summary "$(echo "$DECISION" | jq -r '.summary // empty')" \
      --arg content "$KNOWLEDGE" \
      --arg type "$ENTRY_TYPE" \
      --arg project "$MEM_PROJECT" \
      '{
        action: $action,
        entry: {
          title: $title,
          summary: $summary,
          content: $content,
          tags: [],
          type: $type,
          source: "captured",
          project: $project
        }
      }')
    ;;
  supersede)
    STORE_BODY=$(jq -n \
      --arg action "supersede" \
      --arg target_id "$(echo "$DECISION" | jq -r '.target_id')" \
      --arg title "$(echo "$DECISION" | jq -r '.summary // empty')" \
      --arg summary "$(echo "$DECISION" | jq -r '.summary // empty')" \
      --arg content "$(echo "$DECISION" | jq -r '.new_content')" \
      --arg type "$ENTRY_TYPE" \
      --arg project "$MEM_PROJECT" \
      '{
        action: $action,
        target_id: $target_id,
        entry: {
          title: $title,
          summary: $summary,
          content: $content,
          tags: [],
          type: $type,
          source: "captured",
          project: $project
        }
      }')
    ;;
  append)
    STORE_BODY=$(jq -n \
      --arg action "append" \
      --arg target_id "$(echo "$DECISION" | jq -r '.target_id')" \
      --arg summary "$(echo "$DECISION" | jq -r '.summary // empty')" \
      --arg merged_content "$(echo "$DECISION" | jq -r '.merged_content')" \
      '{
        action: $action,
        target_id: $target_id,
        summary: $summary,
        merged_content: $merged_content
      }')
    ;;
  rebalance)
    STORE_BODY=$(jq -n \
      --arg action "rebalance" \
      --arg target_id "$(echo "$DECISION" | jq -r '.target_id')" \
      --arg summary "$(echo "$DECISION" | jq -r '.summary // empty')" \
      --arg updated_content "$(echo "$DECISION" | jq -r '.updated_content')" \
      --arg new_title "$(echo "$DECISION" | jq -r '.new_title')" \
      --arg new_summary "$(echo "$DECISION" | jq -r '.new_summary // empty')" \
      --arg new_content "$(echo "$DECISION" | jq -r '.new_content')" \
      '{
        action: $action,
        target_id: $target_id,
        summary: $summary,
        updated_content: $updated_content,
        new_title: $new_title,
        new_summary: $new_summary,
        new_content: $new_content,
        new_tags: []
      }')
    ;;
  deprecate)
    STORE_BODY=$(jq -n \
      --arg action "deprecate" \
      --arg target_id "$(echo "$DECISION" | jq -r '.target_id')" \
      --arg reason "$(echo "$DECISION" | jq -r '.reason // empty')" \
      '{
        action: $action,
        target_id: $target_id,
        reason: $reason
      }')
    ;;
  *)
    report "error" "Step 4: unknown action '$ACTION'"
    exit 0
    ;;
esac

# Execute the store
STORE_RESULT=$(curl -sS --max-time 5 \
  -X POST \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "Content-Type: application/json" \
  -H "X-Hook-Source: correction_detect" \
  -d "$STORE_BODY" \
  "$MEM_URL/store"  || echo '{"status":"error"}')

STORE_STATUS=$(echo "$STORE_RESULT" | jq -r '.status // "unknown"')
if [[ "$STORE_STATUS" == "ok" || "$STORE_STATUS" == "success" ]]; then
  ENTRY_ID=$(echo "$STORE_RESULT" | jq -r '.entry_id // .id // "unknown"')
  report "success" "action=$ACTION entry=$ENTRY_ID summary=$SUMMARY"
else
  report "error" "Step 4 store failed: action=$ACTION status=$STORE_STATUS body=$(echo "$STORE_RESULT" | head -c 200)"
fi

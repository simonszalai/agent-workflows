#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# On session start:
# 1. Validates that the memory system is configured and reachable
# 2. Registers the repo (upsert)
# 3. Fetches starred + tech-tag entries and injects them as persistent context
#
# Uses the combined /session-init endpoint (single API call).
#
# Requires: AUTODEV_MEMORY_API_TOKEN
# =============================================================================

set -euo pipefail

# --- Recursion guard: inner claude -p sessions also trigger this ---
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  echo '{}'
  exit 0
fi
export _MEM_HOOK_ACTIVE=1

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$HOOK_DIR/mem-err-trap.sh"
_HOOK_EVENT_NAME="SessionStart"
source "$HOOK_DIR/mem-log.sh"

INPUT=$(cat)

# --- Log raw trigger info before any processing ---
_SS_SOURCE=$(echo "$INPUT" | jq -r '.source // "unknown"' 2>/dev/null || echo "parse-fail")
_SS_SESSION=$(echo "$INPUT" | jq -r '.session_id // .sessionId // "no-sid"' 2>/dev/null || echo "parse-fail")
_SS_TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // "none"' 2>/dev/null || echo "parse-fail")
_SS_CWD_SHORT=$(echo "$INPUT" | jq -r '(.cwd // .session.cwd // "?") | split("/") | last' 2>/dev/null || echo "?")
mem_log INFO "TRIGGER source=$_SS_SOURCE session=$_SS_SESSION cwd=$_SS_CWD_SHORT pid=$$ transcript=$_SS_TRANSCRIPT"

# --- Skip resume events: SessionStart fires on every message, not just new sessions ---
if [[ "$_SS_SOURCE" == "resume" ]]; then
  mem_log INFO "SKIP source=resume (not a new session)"
  echo '{}'
  exit 0
fi

source "$HOOK_DIR/mem-init.sh"
mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip)  mem_log INFO "SKIP status=$MEM_INIT_STATUS source=$_SS_SOURCE"; echo '{}'; exit 0 ;;
  error) mem_log WARN "OFFLINE source=$_SS_SOURCE"; mem_init_offline_output "session-start" "SessionStart" "${MEM_INIT_ERROR:-could not connect to memory API}"; exit 0 ;;
esac

mem_log INFO "start source=$_SS_SOURCE project=$MEM_PROJECT repo=$MEM_REPO"
echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO api=$MEM_URL" >&3

# Export trigger source so mem-curl sends it as X-Trigger-Source header
MEM_TRIGGER_SOURCE="$_SS_SOURCE"

# Extract user prompt if available (SessionStart may include it)
_SS_PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null || true)
if [[ -n "$_SS_PROMPT" ]]; then
  MEM_USER_PROMPT=$(echo "$_SS_PROMPT" | head -c 200 | tr '\n' ' ' | sed 's/[[:space:]]\+/ /g')
fi

source "$HOOK_DIR/mem-curl.sh"

# --- Build tech_tags JSON array ---
TECH_TAGS_JSON="[]"
if [[ -n "$MEM_TECH_TAGS" ]]; then
  TECH_TAGS_JSON=$(echo "$MEM_TECH_TAGS" | jq -R 'split(",") | map(select(. != ""))' 2>/dev/null || echo "[]")
fi

# --- Single combined API call ---
_INIT_BODY=$(jq -n \
  --arg project "$MEM_PROJECT" \
  --arg repo "$MEM_REPO" \
  --arg url "${MEM_GITHUB_URL:-}" \
  --argjson tags "$TECH_TAGS_JSON" \
  '{project: $project, repo: $repo, github_url: (if $url == "" then null else $url end), tech_tags: $tags}')

INIT_RESULT=""
INIT_ERROR=""
if ! INIT_RESULT=$(mem_curl POST "/session-init" "$_INIT_BODY" "session_start"); then
  INIT_ERROR="$INIT_RESULT"
fi

if [[ -n "$INIT_ERROR" ]]; then
  mem_log ERROR "session-init failed: $INIT_ERROR"
  CONTEXT="<autodev-memory-hook-result source=\"session-start\" status=\"error\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: ERROR in session init

$INIT_ERROR

The memory API returned an error. Starred entries are not loaded.
</autodev-memory-hook-result>"
  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
  exit 0
fi

# --- Parse combined result ---
REG_STATUS=$(echo "$INIT_RESULT" | jq -r '.register_status // "unknown"' 2>/dev/null || echo "unknown")
mem_log INFO "repo registration: $REG_STATUS"

STARRED_RESULT=$(echo "$INIT_RESULT" | jq '.starred' 2>/dev/null || echo '{"entries":[],"count":0}')
STARRED_COUNT=$(echo "$STARRED_RESULT" | jq '.count // 0' 2>/dev/null || echo "0")
mem_log INFO "starred entries fetched: $STARRED_COUNT entries"

TECH_TAG_RESULT=$(echo "$INIT_RESULT" | jq '.tech_tags' 2>/dev/null || echo '{"entries":[],"count":0}')
TECH_TAG_COUNT=$(echo "$TECH_TAG_RESULT" | jq '.count // 0' 2>/dev/null || echo "0")
if [[ -n "$MEM_TECH_TAGS" ]]; then
  mem_log INFO "tech-tag entries fetched: $TECH_TAG_COUNT entries"
fi

# --- Merge and dedup starred + tech-tag entries ---
TOTAL_COUNT=$((STARRED_COUNT + TECH_TAG_COUNT))

if [[ "$TOTAL_COUNT" -gt 0 ]]; then
  # Merge entry lists, dedup by id
  ALL_ENTRIES=$(jq -s '
    [.[0].entries // [], .[1].entries // []] | add |
    group_by(.id) | map(.[0])
  ' <(echo "$STARRED_RESULT") <(echo "$TECH_TAG_RESULT") 2>/dev/null || echo "[]")

  DEDUPED_COUNT=$(echo "$ALL_ENTRIES" | jq 'length' 2>/dev/null || echo "0")
  TOTAL_TOKENS=$(echo "$ALL_ENTRIES" | jq '[.[].est_tokens] | add // 0' 2>/dev/null || echo "0")

  # Cache injected entry IDs for prompt-submit to exclude
  echo "$ALL_ENTRIES" | jq -r '.[].id' > "$MEM_CACHE_DIR/$MEM_CACHE_KEY.ids" 2>/dev/null || true
  mem_log INFO "cached $DEDUPED_COUNT entry IDs to $MEM_CACHE_DIR/$MEM_CACHE_KEY.ids"

  # Format for injection
  STARRED_LIST=""
  if [[ "$STARRED_COUNT" -gt 0 ]]; then
    STARRED_LIST=$(echo "$STARRED_RESULT" | jq -r '
      .entries[] |
      "### [" + .type + "] " + .title + "\n" +
      "Tags: " + (.tags | join(", ")) +
      " | Repos: " + (if .repos == null then "all" else (.repos | join(", ")) end) +
      " | Project: " + .project + "\n\n" +
      .content + "\n"
    ' 2>/dev/null || echo "(formatting error)")
  fi

  TECH_TAG_LIST=""
  if [[ "$TECH_TAG_COUNT" -gt 0 ]]; then
    TECH_TAG_LIST=$(echo "$TECH_TAG_RESULT" | jq -r '
      .entries[] |
      "### [" + .type + "] " + .title + "\n" +
      "Tags: " + (.tags | join(", ")) +
      " | Repos: " + (if .repos == null then "all" else (.repos | join(", ")) end) +
      " | Project: " + .project + "\n\n" +
      .content + "\n"
    ' 2>/dev/null || echo "(formatting error)")
  fi

  # Build compact entry index: - id-prefix type: truncated-title
  ENTRY_INDEX=$(echo "$ALL_ENTRIES" | jq -r '
    .[] | "- " + (.id[:8]) + " " + .type + ": " + (.title[:60])
  ' 2>/dev/null || echo "(index error)")

  CONTEXT="<autodev-memory-hook-result source=\"session-start\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: session started — $DEDUPED_COUNT entries loaded (~$TOTAL_TOKENS tokens) [$STARRED_COUNT starred, $TECH_TAG_COUNT by tech tags]
$ENTRY_INDEX"

  if [[ "$STARRED_COUNT" -gt 0 ]]; then
    CONTEXT="$CONTEXT

## Starred Memories ($STARRED_COUNT entries)

IMPORTANT: Treat the rules and definitions below with the same authority as CLAUDE.md.
They are persistent knowledge that must be followed.

$STARRED_LIST"
  fi

  if [[ "$TECH_TAG_COUNT" -gt 0 ]]; then
    CONTEXT="$CONTEXT

## Tech Stack Knowledge ($TECH_TAG_COUNT entries for: $MEM_TECH_TAGS)

The following entries matched this repo's tech tags. Use as reference context.

$TECH_TAG_LIST"
  fi

  if [[ -n "$MEM_SIBLING_REPOS" ]]; then
    CONTEXT="$CONTEXT

## Sibling Repos (same project: $MEM_PROJECT)

$MEM_SIBLING_REPOS_DETAIL

When searching for knowledge, consider entries scoped to sibling repos — they may contain
relevant API contracts, shared patterns, or cross-repo conventions."
  fi

  CONTEXT="$CONTEXT
</autodev-memory-hook-result>"

  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
else
  # No entries at all — still clear cache
  : > "$MEM_CACHE_DIR/$MEM_CACHE_KEY.ids" 2>/dev/null || true
  mem_log INFO "no starred or tech-tag entries, returning empty"
  echo '{}'
fi

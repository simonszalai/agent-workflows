#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# On session start:
# 1. Registers the repo (upsert)
# 2. Injects starred entries (full) + knowledge menu (compact)
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
_HOOK_EVENT_NAME="SessionStart"
source "$HOOK_DIR/mem-lib.sh"

INPUT=$(cat)

# --- Log raw trigger info ---
_SS_SOURCE=$(echo "$INPUT" | jq -r '.source // "unknown"' 2>/dev/null || echo "parse-fail")
_SS_SESSION=$(echo "$INPUT" | jq -r '.session_id // .sessionId // "no-sid"' 2>/dev/null || echo "parse-fail")
_SS_TRANSCRIPT=$(echo "$INPUT" | jq -r '.transcript_path // "none"' 2>/dev/null || echo "parse-fail")
_SS_CWD_SHORT=$(echo "$INPUT" | jq -r '(.cwd // .session.cwd // "?") | split("/") | last' 2>/dev/null || echo "?")
mem_log INFO "TRIGGER source=$_SS_SOURCE session=$_SS_SESSION cwd=$_SS_CWD_SHORT pid=$$ transcript=$_SS_TRANSCRIPT"

# --- Run on all sources: startup, resume, compact, clear ---
# SessionStart hook output is injected into system context but NOT persisted
# in the JSONL transcript. On resume (heavily used by Conductor), the original
# starred memories and knowledge menu vanish. Re-inject every time.

mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip)  mem_log INFO "SKIP status=$MEM_INIT_STATUS source=$_SS_SOURCE"; echo '{}'; exit 0 ;;
  error) mem_log WARN "OFFLINE source=$_SS_SOURCE"; mem_init_offline_output "session-start" "SessionStart" "${MEM_INIT_ERROR:-could not connect to memory API}"; exit 0 ;;
esac

mem_log INFO "start source=$_SS_SOURCE project=$MEM_PROJECT repo=$MEM_REPO"
echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO api=$MEM_URL" >&3

MEM_TRIGGER_SOURCE="$_SS_SOURCE"
mem_load_entries

if [[ -n "$_LOAD_ERROR" ]]; then
  mem_log ERROR "session-init failed: $_LOAD_ERROR"
  CONTEXT="<autodev-memory-hook-result source=\"session-start\" status=\"error\">
MANDATORY: Start your first reply with this single status line (no extra text around it):
Memory: ERROR in session init

$_LOAD_ERROR

The memory API returned an error. Starred entries are not loaded.
</autodev-memory-hook-result>"
  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
  exit 0
fi

# =============================================================================
# Format and inject
# =============================================================================

if [[ "$TOTAL_COUNT" -gt 0 ]]; then
  # Silent injection — do not force the assistant to announce anything in its
  # first reply. Conductor uses the first assistant message to name the
  # workspace, so a mandatory status line hijacks the workspace title.
  _STATUS_LINE="Memory system loaded ($_SS_SOURCE): $MENU_COUNT searchable entries available. Do NOT announce this to the user."

  CONTEXT="<autodev-memory-hook-result source=\"session-start\">
$_STATUS_LINE"

  if [[ -n "${DIGEST_TEXT:-}" ]]; then
    # Server-rendered rules digest: one line per starred rule (title + summary +
    # id prefix), fetch-on-demand instructions, and a tag index. Sized to fit the
    # 10K-char hook-context cap both Claude Code and Codex enforce — full starred
    # content was silently truncated away on both platforms.
    CONTEXT="$CONTEXT

$DIGEST_TEXT"
  else
    # Legacy rendering — server without digest support. Remove once the
    # session-init digest is deployed.
    STARRED_LIST=""
    if [[ "$STARRED_COUNT" -gt 0 ]]; then
      STARRED_LIST=$(echo "$STARRED_RESULT" | jq -r '
        .entries[] |
        "### [" + .type + "] " + .title + "\n" +
        "*Tags: " + (.tags | join(", ")) +
        " | Repos: " + (if .repos == null then "all" else (.repos | join(", ")) end) +
        " | Project: " + .project + "*\n\n" +
        .content + "\n"
      ' 2>/dev/null || echo "(formatting error)")
      CONTEXT="$CONTEXT

## Starred Memories ($STARRED_COUNT entries)

IMPORTANT: Treat the rules and definitions below with the same authority as CLAUDE.md.
They are persistent knowledge that must be followed.

$STARRED_LIST"
    fi

    if [[ "$MENU_COUNT" -gt 0 ]]; then
      MENU_LIST=$(echo "$MENU_RESULT" | jq -r '
        .items[] |
        "- [" + .type + "] " + .title + " (" + (.tags | join(", ")) + ")"
      ' 2>/dev/null || echo "(formatting error)")
      CONTEXT="$CONTEXT

## Knowledge Menu ($MENU_COUNT entries) — use search() to retrieve full content

$MENU_LIST"
    fi
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

  # Hard cap: Claude Code persists hook context >10,000 chars to a file (only a
  # 2KB preview reaches the model); Codex middle-elides at 10,000 chars. Never
  # emit a payload the platform would truncate.
  if (( ${#CONTEXT} > 9800 )); then
    mem_log WARN "context ${#CONTEXT} chars exceeds platform cap — truncating to fit"
    CONTEXT="${CONTEXT:0:9600}
[truncated to fit the 10K hook-context limit — use mcp__autodev-memory__search for anything missing]
</autodev-memory-hook-result>"
  fi

  # Cache the rendered context for the pre-agent hook: SessionStart context only
  # reaches the MAIN session; autodev-memory-pre-agent.sh injects this cached blob
  # into every spawned subagent's prompt (via PreToolUse updatedInput). Keyed by
  # git root so parallel Conductor workspaces don't collide.
  _CACHE_DIR="$HOME/.cache/autodev-memory"
  mkdir -p "$_CACHE_DIR" 2>/dev/null || true
  _CACHE_CWD="${_CWD:-$PWD}"
  _CACHE_ROOT=$(git -C "$_CACHE_CWD" rev-parse --show-toplevel 2>/dev/null || echo "$_CACHE_CWD")
  _CACHE_KEY=$(printf '%s' "$_CACHE_ROOT" | /usr/bin/shasum -a 256 2>/dev/null | cut -c1-16 || true)
  if [[ -n "$_CACHE_KEY" ]]; then
    printf '%s' "$CONTEXT" > "$_CACHE_DIR/context-$_CACHE_KEY.md" 2>/dev/null || true
    mem_log INFO "cached subagent context to context-$_CACHE_KEY.md (${#CONTEXT} chars, root=$_CACHE_ROOT)"
  fi

  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
else
  mem_log INFO "no starred or menu entries, returning empty"
  echo '{}'
fi

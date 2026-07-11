#!/usr/bin/env bash
# =============================================================================
# autodev-memory-session-start.sh — SessionStart hook for memory system
# =============================================================================
#
# On session start:
# 1. Registers the repo (upsert)
# 2. Injects one server-rendered, versioned, bounded packet
#
# Requires: AUTODEV_MEMORY_API_TOKEN
# =============================================================================

set -euo pipefail

# External/provider subprocesses receive one explicit bounded task packet.  Their ambient
# SessionStart hook must stay silent or Claude/Codex would receive the parent packet twice.
if [[ "${AUTODEV_MEMORY_EXPLICIT_PACKET:-}" == "1" ]]; then
  echo '{}'
  exit 0
fi

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

# --- Log metadata-only trigger info ---
_SS_SOURCE=$(echo "$INPUT" | jq -r '.source // "unknown"' 2>/dev/null || echo "parse-fail")
_SS_SESSION=$(echo "$INPUT" | jq -r '.session_id // .sessionId // "no-sid"' 2>/dev/null || echo "parse-fail")
_SS_CWD_SHORT=$(echo "$INPUT" | jq -r '(.cwd // .session.cwd // "?") | split("/") | last' 2>/dev/null || echo "?")
mem_log INFO "TRIGGER source=$_SS_SOURCE session_present=$([[ $_SS_SESSION == no-sid ]] && echo no || echo yes) cwd=$_SS_CWD_SHORT pid=$$"

_CACHE_DIR="$HOME/.cache/autodev-memory/v2"
_TELEMETRY_FILE="$HOME/.cache/autodev-memory/telemetry.jsonl"
_PACKET_HELPER="$HOOK_DIR/memory_context.py"
invalidate_cache() {
  [[ -n "$_SS_SESSION" && "$_SS_SESSION" != "no-sid" ]] || return 0
  python3 "$_PACKET_HELPER" invalidate --session-id "$_SS_SESSION" --cache-dir "$_CACHE_DIR" \
    >/dev/null 2>&1 || true
}

# --- Run on all sources: startup, resume, compact, clear ---
# SessionStart hook output is injected into system context but NOT persisted
# in the JSONL transcript. On resume (heavily used by Conductor), the original
# memory packet vanishes. Re-inject every time.

mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip)  mem_log INFO "SKIP status=$MEM_INIT_STATUS source=$_SS_SOURCE"; echo '{}'; exit 0 ;;
  error)
    mem_log WARN "UNAVAILABLE source=$_SS_SOURCE"
    invalidate_cache
    CONTEXT='<autodev-memory-hook-result source="session-start" status="unavailable">
Memory context is unavailable for this session. Do not infer that memories were loaded.
Use the memory search tool explicitly if it is available.
</autodev-memory-hook-result>'
    jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}'
    exit 0
    ;;
esac

mem_log INFO "start source=$_SS_SOURCE project=$MEM_PROJECT repo=$MEM_REPO"
echo "mem-session-start: project=$MEM_PROJECT repo=$MEM_REPO" >&3

MEM_TRIGGER_SOURCE="$_SS_SOURCE"
mem_load_entries

if [[ -n "$_LOAD_ERROR" ]]; then
  mem_log ERROR "session-init failed status=unavailable"
  invalidate_cache
  CONTEXT="<autodev-memory-hook-result source=\"session-start\" status=\"unavailable\">
Memory context is unavailable for this session. Do not infer that memories were loaded.
Use the memory search tool explicitly if it is available.
</autodev-memory-hook-result>"
  OUTPUT=$(jq -n --arg ctx "$CONTEXT" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $ctx}}')
  mem_log_output "$OUTPUT"
  echo "$OUTPUT"
  exit 0
fi

# Packet v2 is already semantically rendered by the backend.  The helper validates its exact
# count/hash, adds the small platform wrapper, and writes an atomic session-scoped cache.  During
# the additive rollout only the server's bounded digest is accepted as v1 fallback; full starred
# bodies and the legacy title menu are never rebuilt client-side.
_SID="$_SS_SESSION"
[[ "$_SID" != "no-sid" ]] || _SID=""
set +e
OUTPUT=$(printf '%s' "$INIT_RESULT" | python3 "$_PACKET_HELPER" render-session \
  --project "$MEM_PROJECT" \
  --repo "$MEM_REPO" \
  --session-id "$_SID" \
  --source "$_SS_SOURCE" \
  --cache-dir "$_CACHE_DIR" \
  --telemetry-file "$_TELEMETRY_FILE")
_RENDER_RC=$?
set -e
if [[ -z "$OUTPUT" ]] || ! jq -e '.hookSpecificOutput.additionalContext | type == "string"' \
  >/dev/null 2>&1 <<<"$OUTPUT"; then
  invalidate_cache
  mem_log ERROR "packet renderer failed rc=$_RENDER_RC"
  echo '{}'
  exit 0
fi
if [[ $_RENDER_RC -ne 0 ]]; then
  mem_log WARN "packet unavailable rc=$_RENDER_RC project=$MEM_PROJECT repo=$MEM_REPO"
fi
mem_log_output "$OUTPUT"
echo "$OUTPUT"

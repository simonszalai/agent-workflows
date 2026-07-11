#!/usr/bin/env bash
# Add one explicit, bounded memory task packet to a managed Claude Agent prompt.

set -uo pipefail

_LOG_FILE="$HOME/.config/autodev-memory/hooks.log"
_log() {
  printf '%s [pre-agent] %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" "$2" \
    >> "$_LOG_FILE" 2>/dev/null || true
}
emit_empty() { echo '{}'; exit 0; }

command -v jq >/dev/null 2>&1 || emit_empty
INPUT=$(cat) || emit_empty
[[ "$(jq -r '.tool_name // ""' <<<"$INPUT" 2>/dev/null)" == "Agent" ]] || emit_empty

PROMPT=$(jq -r '.tool_input.prompt // ""' <<<"$INPUT" 2>/dev/null) || emit_empty
[[ -n "$PROMPT" ]] || emit_empty
case "$PROMPT" in
  *autodev-memory-task-context*) emit_empty ;;
esac

CWD=$(jq -r '.cwd // .session.cwd // ""' <<<"$INPUT" 2>/dev/null)
[[ -n "$CWD" ]] || CWD="$PWD"
SESSION_ID=$(jq -r '.session_id // .sessionId // ""' <<<"$INPUT" 2>/dev/null)
[[ -n "$SESSION_ID" ]] || { _log SKIP 'session_id=absent'; emit_empty; }
AGENT_TYPE=$(jq -r '.tool_input.subagent_type // "generic"' <<<"$INPUT" 2>/dev/null)

HOOK_DIR="$(cd "$(dirname "$0")" && pwd)"
HELPER="$HOOK_DIR/../bin/autodev-memory-task-packet"
[[ -x "$HELPER" ]] || { _log SKIP 'helper=unavailable'; emit_empty; }
PACKET=$("$HELPER" --cwd "$CWD" --session-id "$SESSION_ID" --agent-type "$AGENT_TYPE" \
  --provider claude --mechanism prompt_rewrite 2>/dev/null) || {
  _log SKIP 'packet=unavailable'
  emit_empty
}
[[ -n "$PACKET" && ${#PACKET} -le 3000 ]] || emit_empty

NEW_PROMPT="$PROMPT

$PACKET"
OUTPUT=$(jq -n \
  --argjson ti "$(jq -c '.tool_input' <<<"$INPUT")" \
  --arg p "$NEW_PROMPT" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "allow",
    permissionDecisionReason: "autodev-memory: bounded task context injected",
    updatedInput: ($ti + {prompt: $p})}}') || emit_empty

_log INFO "status=delivered provider=claude mechanism=prompt_rewrite chars=${#PACKET}"
echo "$OUTPUT"

#!/usr/bin/env bash
# Add one explicit, bounded memory task packet to a managed Claude Agent prompt.

set -uo pipefail

_LOG_FILE="$HOME/.config/autodev-memory/hooks.log"
_TELEMETRY_FILE="$HOME/.cache/autodev-memory/telemetry.jsonl"
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
if [[ "$PROMPT" == *"<autodev-memory-task-context"* \
   && "$PROMPT" == *"</autodev-memory-task-context>"* ]]; then
  emit_empty
fi

CWD=$(jq -r '.cwd // .session.cwd // ""' <<<"$INPUT" 2>/dev/null)
[[ -n "$CWD" ]] || CWD="$PWD"
SESSION_ID=$(jq -r '.session_id // .sessionId // ""' <<<"$INPUT" 2>/dev/null)
[[ -n "$SESSION_ID" ]] || { _log SKIP 'session_id=absent'; emit_empty; }
AGENT_TYPE=$(jq -r '.tool_input.subagent_type // "generic"' <<<"$INPUT" 2>/dev/null)

SCRIPT_PATH="$0"
if _RESOLVED_SCRIPT=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$0" 2>/dev/null) \
  && [[ -n "$_RESOLVED_SCRIPT" ]]; then
  SCRIPT_PATH="$_RESOLVED_SCRIPT"
fi
HOOK_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
HELPER="$HOOK_DIR/../bin/autodev-memory-task-packet"
# Resolve the hook symlink first so the helper comes from the exact same immutable
# version tree. Never prefer ~/.claude/bin or an arbitrary PATH entry.
[[ -x "$HELPER" ]] || { _log SKIP 'helper=unavailable'; emit_empty; }
PACKET=$(printf '%s' "$PROMPT" | "$HELPER" --cwd "$CWD" --session-id "$SESSION_ID" \
  --agent-type "$AGENT_TYPE" --provider claude --mechanism prompt_rewrite \
  --task-prompt-stdin 2>/dev/null) || {
  _log SKIP 'packet=unavailable'
  emit_empty
}
[[ -n "$PACKET" && ${#PACKET} -le 3000 ]] || emit_empty

NEW_PROMPT="$PROMPT

$PACKET"
OUTPUT=$(
  printf '%s\0%s' "$INPUT" "$NEW_PROMPT" | python3 -c '
import json, sys
raw = sys.stdin.buffer.read()
source, prompt = raw.split(b"\0", 1)
payload = json.loads(source)
tool_input = payload.get("tool_input", {})
if not isinstance(tool_input, dict):
    raise SystemExit(2)
tool_input = {**tool_input, "prompt": prompt.decode("utf-8")}
print(json.dumps({"hookSpecificOutput": {
    "hookEventName": "PreToolUse", "updatedInput": tool_input,
}}, separators=(",", ":")))
') || emit_empty

if printf '%s\n' "$OUTPUT"; then
  _log INFO "status=delivered provider=claude mechanism=prompt_rewrite chars=${#PACKET}"
  printf '%s' "$PACKET" | python3 "$HOOK_DIR/memory_context.py" confirm-child \
    --provider claude --mechanism prompt_rewrite \
    --confirmation-stage pretool_output_emitted \
    --telemetry-file "$_TELEMETRY_FILE" --session-id "$SESSION_ID" \
    >/dev/null 2>&1 || true
fi

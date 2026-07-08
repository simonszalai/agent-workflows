#!/usr/bin/env bash
# =============================================================================
# autodev-memory-pre-agent.sh — inject memory context into spawned subagents
# =============================================================================
#
# SessionStart additionalContext reaches only the MAIN session, and PreToolUse
# additionalContext goes to the PARENT model — neither reaches a subagent.
# What DOES reach the subagent is the Agent tool's `prompt` input. So this hook
# rewrites tool_input.prompt via PreToolUse `updatedInput`, appending the same
# memory blob the session-start hook rendered (cached to disk, keyed by git
# root — see autodev-memory-session-start.sh).
#
# Fail-open everywhere: any missing dependency, missing/stale cache, or parse
# error emits '{}' and the Agent call proceeds unmodified.
# =============================================================================

set -uo pipefail

_LOG_FILE="$HOME/.config/autodev-memory/hooks.log"
_log() {
  printf '%s [pre-agent] %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" "$2" \
    >> "$_LOG_FILE" 2>/dev/null || true
}

emit_empty() { echo '{}'; exit 0; }

command -v jq >/dev/null 2>&1 || emit_empty

INPUT=$(cat) || emit_empty

TOOL=$(jq -r '.tool_name // ""' <<<"$INPUT" 2>/dev/null) || emit_empty
[[ "$TOOL" == "Agent" ]] || emit_empty

PROMPT=$(jq -r '.tool_input.prompt // ""' <<<"$INPUT" 2>/dev/null) || emit_empty
[[ -n "$PROMPT" ]] || emit_empty

# Never double-inject (parent retries the call, or a subagent spawns its own agents).
case "$PROMPT" in
  *autodev-memory-subagent-context*) emit_empty ;;
esac

CWD=$(jq -r '.cwd // ""' <<<"$INPUT" 2>/dev/null)
[[ -n "$CWD" ]] || CWD="$PWD"
GIT_ROOT=$(git -C "$CWD" rev-parse --show-toplevel 2>/dev/null || echo "$CWD")
KEY=$(printf '%s' "$GIT_ROOT" | /usr/bin/shasum -a 256 2>/dev/null | cut -c1-16)
[[ -n "$KEY" ]] || emit_empty

CACHE="$HOME/.cache/autodev-memory/context-$KEY.md"
[[ -f "$CACHE" ]] || { _log SKIP "no cache for root=$GIT_ROOT"; emit_empty; }

# Stale cache (>7 days): session-start refreshes it on every startup/resume/
# compact/clear, so anything older means the memory system has been offline —
# better to inject nothing than week-old rules.
if [[ -z "$(find "$CACHE" -mtime -7 2>/dev/null)" ]]; then
  _log SKIP "stale cache for root=$GIT_ROOT"
  emit_empty
fi

CTX=$(cat "$CACHE" 2>/dev/null)
[[ -n "$CTX" ]] || emit_empty

NEW_PROMPT="$PROMPT

<autodev-memory-subagent-context>
The following memory rules and knowledge index were injected at session start and carry the
same authority as CLAUDE.md. As a subagent you do NOT otherwise receive them — treat the
always-apply rules below as binding, and use mcp__autodev-memory__search (schema via
ToolSearch if not loaded) whenever your task touches an indexed topic.

$CTX
</autodev-memory-subagent-context>"

OUTPUT=$(jq -n \
  --argjson ti "$(jq -c '.tool_input' <<<"$INPUT")" \
  --arg p "$NEW_PROMPT" \
  '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "allow",
    permissionDecisionReason: "autodev-memory: subagent context injected",
    updatedInput: ($ti + {prompt: $p})}}') || emit_empty

_log INFO "injected ${#CTX} chars into subagent prompt (root=$GIT_ROOT)"
echo "$OUTPUT"
exit 0

#!/usr/bin/env bash
# =============================================================================
# autodev-memory-pre-agent.sh — PreToolUse[Agent] hook for memory system
# =============================================================================
#
# When Claude spawns a subagent:
# 1. Inject starred + tech-tag entries (same as session-start)
# 2. Load skill-specific entries based on agent's skill declarations
#
# Skills can declare memory needs in their SKILL.md frontmatter:
#   memory:
#     tags: ["python", "sqlalchemy"]
#     types: ["gotcha", "pattern"]
#
# The hook reads the agent definition → extracts skills → reads each skill's
# memory block → merges tags/types → calls /entries/by-skill endpoint.
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
_HOOK_EVENT_NAME="PreToolUse"
source "$HOOK_DIR/mem-log.sh"

INPUT=$(cat)

source "$HOOK_DIR/mem-init.sh"
mem_init "$INPUT"

case "$MEM_INIT_STATUS" in
  skip) echo '{}'; exit 0 ;;
  error) echo '{}'; exit 0 ;;
esac

MEM_TRIGGER_SOURCE="pre_tool_use(Agent)"
source "$HOOK_DIR/mem-curl.sh"

# --- Extract subagent info ---
AGENT_PROMPT=$(echo "$INPUT" | jq -r '.tool_input.prompt // empty')
AGENT_TYPE=$(echo "$INPUT" | jq -r '.tool_input.subagent_type // "general"')
AGENT_DESC=$(echo "$INPUT" | jq -r '.tool_input.description // empty')

if [[ -z "$AGENT_PROMPT" || ${#AGENT_PROMPT} -lt 30 ]]; then
  mem_log INFO "skip (prompt too short: ${#AGENT_PROMPT} chars)"
  echo '{}'
  exit 0
fi

mem_log INFO "start type=$AGENT_TYPE desc=$AGENT_DESC"

# =============================================================================
# Load entries (shared with session-start hook)
# =============================================================================

source "$HOOK_DIR/mem-load-entries.sh"

if [[ -n "$_LOAD_ERROR" ]]; then
  mem_log ERROR "session-init failed: $_LOAD_ERROR"
  echo '{}'
  exit 0
fi

mem_log INFO "entries: starred=$STARRED_COUNT tech_tags=$TECH_TAG_COUNT"

# --- Collect entry IDs for exclusion from skill loading ---
INIT_ENTRY_IDS=$(echo "$ALL_ENTRIES" | jq '[.[] | .id] | unique' 2>/dev/null || echo "[]")

# =============================================================================
# Skill-based memory loading — agent definition → skills → memory declarations
# =============================================================================

SKILL_ENTRIES="[]"
SKILL_COUNT=0

# Resolve agent definition file (project-level first, then user-level)
_CWD=$(echo "$INPUT" | jq -r '(.cwd // .session.cwd) // empty' 2>/dev/null)
_AGENT_FILE=""
if [[ -n "$AGENT_TYPE" && "$AGENT_TYPE" != "general" ]]; then
  # Convert type to lowercase for filename matching
  _AGENT_LC=$(echo "$AGENT_TYPE" | tr '[:upper:]' '[:lower:]')
  for _DIR in "$_CWD/.claude/agents" "$HOME/.claude/agents"; do
    # Try exact match first, then lowercase
    for _NAME in "$AGENT_TYPE" "$_AGENT_LC"; do
      if [[ -f "$_DIR/${_NAME}.md" ]]; then
        _AGENT_FILE="$_DIR/${_NAME}.md"
        break 2
      fi
    done
  done
fi

if [[ -n "$_AGENT_FILE" ]]; then
  # Extract skill names from agent YAML frontmatter (only lines under skills:)
  _SKILL_NAMES=()
  _IN_SKILLS=false
  while IFS= read -r line; do
    if echo "$line" | grep -q '^skills:'; then
      _IN_SKILLS=true; continue
    fi
    if $_IN_SKILLS; then
      if echo "$line" | grep -q '^ *- '; then
        _SKILL_NAMES+=("$(echo "$line" | sed 's/^ *- //')")
      else
        _IN_SKILLS=false
      fi
    fi
  done < <(sed -n '/^---$/,/^---$/p' "$_AGENT_FILE")

  # Read memory declarations from each skill's SKILL.md
  _ALL_SKILL_TAGS=()
  _ALL_SKILL_TYPES=()

  for _SKILL in "${_SKILL_NAMES[@]}"; do
    _SKILL_FILE=""
    for _DIR in "$_CWD/.claude/skills" "$HOME/.claude/skills"; do
      if [[ -f "$_DIR/$_SKILL/SKILL.md" ]]; then
        _SKILL_FILE="$_DIR/$_SKILL/SKILL.md"
        break
      fi
    done
    [[ -z "$_SKILL_FILE" ]] && continue

    # Extract YAML frontmatter
    _FM=$(sed -n '/^---$/,/^---$/p' "$_SKILL_FILE")
    echo "$_FM" | grep -q '^ *memory:' || continue

    # Parse memory.tags and memory.types from frontmatter
    _IN_MEM=false
    _IN_TAGS=false
    _IN_TYPES=false

    while IFS= read -r line; do
      if echo "$line" | grep -q '^ *memory:'; then
        _IN_MEM=true; continue
      fi
      if $_IN_MEM; then
        if echo "$line" | grep -qE '^[a-z]' || echo "$line" | grep -q '^---'; then
          _IN_MEM=false; _IN_TAGS=false; _IN_TYPES=false; continue
        fi
        if echo "$line" | grep -q '^ *tags:'; then
          _IN_TAGS=true; _IN_TYPES=false; continue
        fi
        if echo "$line" | grep -q '^ *types:'; then
          _IN_TYPES=true; _IN_TAGS=false; continue
        fi
        if $_IN_TAGS && echo "$line" | grep -q '^ *- '; then
          _TAG=$(echo "$line" | sed 's/^ *- *//' | tr -d '"' | tr -d "'")
          _ALL_SKILL_TAGS+=("$_TAG")
        fi
        if $_IN_TYPES && echo "$line" | grep -q '^ *- '; then
          _TYPE=$(echo "$line" | sed 's/^ *- *//' | tr -d '"' | tr -d "'")
          _ALL_SKILL_TYPES+=("$_TYPE")
        fi
      fi
    done <<< "$_FM"
  done

  # Resolve $tech_tags and deduplicate
  if [[ ${#_ALL_SKILL_TAGS[@]} -gt 0 || ${#_ALL_SKILL_TYPES[@]} -gt 0 ]]; then
    _RESOLVED_TAGS=()
    for _TAG in "${_ALL_SKILL_TAGS[@]}"; do
      if [[ "$_TAG" == '$tech_tags' || "$_TAG" == '${tech_tags}' ]]; then
        if [[ -n "$MEM_TECH_TAGS" ]]; then
          IFS=',' read -ra _TTAGS <<< "$MEM_TECH_TAGS"
          _RESOLVED_TAGS+=("${_TTAGS[@]}")
        fi
      else
        _RESOLVED_TAGS+=("$_TAG")
      fi
    done

    _UNIQUE_TAGS=($(printf '%s\n' "${_RESOLVED_TAGS[@]}" 2>/dev/null | sort -u))
    _UNIQUE_TYPES=($(printf '%s\n' "${_ALL_SKILL_TYPES[@]}" 2>/dev/null | sort -u))

    if [[ ${#_UNIQUE_TAGS[@]} -gt 0 ]]; then
      _TAGS_JSON=$(printf '%s\n' "${_UNIQUE_TAGS[@]}" | jq -R . | jq -s .)
      _TYPES_JSON="[]"
      if [[ ${#_UNIQUE_TYPES[@]} -gt 0 ]]; then
        _TYPES_JSON=$(printf '%s\n' "${_UNIQUE_TYPES[@]}" | jq -R . | jq -s .)
      fi

      _SKILL_BODY=$(jq -n \
        --arg project "$MEM_PROJECT" \
        --arg repo "$MEM_REPO" \
        --argjson tags "$_TAGS_JSON" \
        --argjson types "$_TYPES_JSON" \
        --argjson exclude_ids "$INIT_ENTRY_IDS" \
        '{
          project: $project,
          repo: $repo,
          tags: $tags,
          types: $types,
          exclude_ids: $exclude_ids
        }')

      _SKILL_RESULT=""
      if _SKILL_RESULT=$(mem_curl POST "/entries/by-skill" "$_SKILL_BODY" "pre_tool_use(Agent)"); then
        SKILL_ENTRIES=$(echo "$_SKILL_RESULT" | jq '.entries // []' 2>/dev/null || echo "[]")
        SKILL_COUNT=$(echo "$_SKILL_RESULT" | jq '.count // 0' 2>/dev/null || echo "0")
        mem_log INFO "skill entries: count=$SKILL_COUNT tags=${_UNIQUE_TAGS[*]} types=${_UNIQUE_TYPES[*]}"
      else
        mem_log WARN "entries/by-skill failed: $_SKILL_RESULT"
      fi
    fi
  fi
fi

# --- Merge skill entries into ALL_ENTRIES (session-init entries already loaded) ---
if [[ "$SKILL_COUNT" -gt 0 ]]; then
  ALL_ENTRIES=$(jq -s '
    [.[0] // [], .[1] // []] | add // [] |
    group_by(.id) | map(.[0])
  ' <(echo "$ALL_ENTRIES") <(echo "$SKILL_ENTRIES") 2>/dev/null || echo "$ALL_ENTRIES")
  DEDUPED_COUNT=$(echo "$ALL_ENTRIES" | jq 'length' 2>/dev/null || echo "0")
fi

if [[ "$DEDUPED_COUNT" -eq 0 ]]; then
  mem_log INFO "done (0 entries total)"
  echo '{}'
  exit 0
fi

FORMATTED=$(echo "$ALL_ENTRIES" | jq -r '
  .[] |
  "### [" + .type + "] " + .title + "\n" +
  "*Tags: " + (.tags | join(", ")) + "*\n\n" +
  .content + "\n"
' 2>/dev/null || echo "(formatting error)")

# Build context with skill summary if any skill entries were loaded
SKILL_NOTE=""
if [[ "$SKILL_COUNT" -gt 0 ]]; then
  SKILL_NOTE=" + $SKILL_COUNT by skills"
fi

CONTEXT="<autodev-memory-hook-result source=\"pre-agent\">
## Knowledge Base ($DEDUPED_COUNT entries for: ${MEM_TECH_TAGS}${SKILL_NOTE})

$FORMATTED
</autodev-memory-hook-result>"

OUTPUT=$(jq -n --arg context "$CONTEXT" '{hookSpecificOutput: {hookEventName: "PreToolUse", additionalContext: $context}}')
mem_log INFO "done entries=$DEDUPED_COUNT (session_init=$TOTAL_COUNT skill=$SKILL_COUNT)"
mem_log_output "$OUTPUT"
echo "$OUTPUT"

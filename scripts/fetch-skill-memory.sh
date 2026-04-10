#!/usr/bin/env bash
# =============================================================================
# fetch-skill-memory.sh — Fetch memory entries for skill-declared tags/types
# =============================================================================
#
# Reads SKILL.md frontmatter for memory declarations and calls the
# /entries/by-skill API endpoint to fetch matching entries.
#
# Usage:
#   ./scripts/fetch-skill-memory.sh review-python-standards review-patterns
#   ./scripts/fetch-skill-memory.sh --agent reviewer
#
# Modes:
#   skill names:  Read each skill's SKILL.md, merge tags/types
#   --agent NAME: Read agent .md, extract skills list, then read each skill
#
# Environment:
#   AUTODEV_MEMORY_API_URL   (default: http://localhost:8475)
#   AUTODEV_MEMORY_API_TOKEN (required)
#   MEM_PROJECT              (default: auto-detect from CLAUDE.md)
#   MEM_REPO                 (default: auto-detect from git remote)
#   MEM_TECH_TAGS            (comma-separated, for $tech_tags resolution)
#   MEM_EXCLUDE_IDS          (comma-separated UUIDs to exclude)
#
# Output: JSON response from /entries/by-skill
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILLS_DIR="${SCRIPT_DIR}/../skills"
AGENTS_DIR="${SCRIPT_DIR}/../agents"

MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"

if [[ -z "$MEM_TOKEN" ]]; then
  echo "ERROR: AUTODEV_MEMORY_API_TOKEN not set" >&2
  exit 1
fi

# --- Parse arguments ---
SKILL_NAMES=()
AGENT_NAME=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent)
      AGENT_NAME="$2"
      shift 2
      ;;
    *)
      SKILL_NAMES+=("$1")
      shift
      ;;
  esac
done

# --- If --agent, extract skill names from agent definition ---
if [[ -n "$AGENT_NAME" ]]; then
  AGENT_FILE="$AGENTS_DIR/${AGENT_NAME}.md"
  if [[ ! -f "$AGENT_FILE" ]]; then
    echo "ERROR: Agent file not found: $AGENT_FILE" >&2
    exit 1
  fi
  # Extract skills from YAML frontmatter (between --- lines)
  while IFS= read -r line; do
    SKILL_NAMES+=("$line")
  done < <(sed -n '/^---$/,/^---$/p' "$AGENT_FILE" | grep '^ *- ' | sed 's/^ *- //')
fi

if [[ ${#SKILL_NAMES[@]} -eq 0 ]]; then
  echo "Usage: $0 skill-name [skill-name ...] OR $0 --agent agent-name" >&2
  exit 1
fi

# --- Read skill frontmatter and merge memory declarations ---
ALL_TAGS=()
ALL_TYPES=()

for skill in "${SKILL_NAMES[@]}"; do
  SKILL_FILE="$SKILLS_DIR/$skill/SKILL.md"
  if [[ ! -f "$SKILL_FILE" ]]; then
    continue
  fi

  # Extract memory block from YAML frontmatter
  FRONTMATTER=$(sed -n '/^---$/,/^---$/p' "$SKILL_FILE")

  # Check if memory: block exists
  if ! echo "$FRONTMATTER" | grep -q '^ *memory:'; then
    continue
  fi

  # Extract tags (lines under memory.tags:)
  IN_MEMORY=false
  IN_TAGS=false
  IN_TYPES=false

  while IFS= read -r line; do
    if echo "$line" | grep -q '^ *memory:'; then
      IN_MEMORY=true
      continue
    fi

    if $IN_MEMORY; then
      # End of memory block if we hit a non-indented line
      if echo "$line" | grep -qE '^[a-z]' || echo "$line" | grep -q '^---'; then
        IN_MEMORY=false
        IN_TAGS=false
        IN_TYPES=false
        continue
      fi

      if echo "$line" | grep -q '^ *tags:'; then
        IN_TAGS=true
        IN_TYPES=false
        continue
      fi
      if echo "$line" | grep -q '^ *types:'; then
        IN_TYPES=true
        IN_TAGS=false
        continue
      fi

      if $IN_TAGS && echo "$line" | grep -q '^ *- '; then
        TAG=$(echo "$line" | sed 's/^ *- *//' | tr -d '"' | tr -d "'")
        ALL_TAGS+=("$TAG")
      fi
      if $IN_TYPES && echo "$line" | grep -q '^ *- '; then
        TYPE=$(echo "$line" | sed 's/^ *- *//' | tr -d '"' | tr -d "'")
        ALL_TYPES+=("$TYPE")
      fi
    fi
  done <<< "$FRONTMATTER"
done

if [[ ${#ALL_TAGS[@]} -eq 0 && ${#ALL_TYPES[@]} -eq 0 ]]; then
  echo '{"entries":[],"count":0}'
  exit 0
fi

# --- Resolve $tech_tags ---
TECH_TAGS="${MEM_TECH_TAGS:-}"
RESOLVED_TAGS=()
for tag in "${ALL_TAGS[@]}"; do
  if [[ "$tag" == '$tech_tags' || "$tag" == '${tech_tags}' ]]; then
    if [[ -n "$TECH_TAGS" ]]; then
      IFS=',' read -ra TTAGS <<< "$TECH_TAGS"
      RESOLVED_TAGS+=("${TTAGS[@]}")
    fi
  else
    RESOLVED_TAGS+=("$tag")
  fi
done

# --- Deduplicate ---
UNIQUE_TAGS=($(printf '%s\n' "${RESOLVED_TAGS[@]}" | sort -u))
UNIQUE_TYPES=($(printf '%s\n' "${ALL_TYPES[@]}" | sort -u))

# --- Build JSON request ---
TAGS_JSON=$(printf '%s\n' "${UNIQUE_TAGS[@]}" | jq -R . | jq -s .)
TYPES_JSON=$(printf '%s\n' "${UNIQUE_TYPES[@]}" | jq -R . | jq -s .)

PROJECT="${MEM_PROJECT:-}"
REPO="${MEM_REPO:-}"

# Build exclude_ids array
EXCLUDE_JSON="[]"
if [[ -n "${MEM_EXCLUDE_IDS:-}" ]]; then
  EXCLUDE_JSON=$(echo "$MEM_EXCLUDE_IDS" | tr ',' '\n' | jq -R . | jq -s .)
fi

BODY=$(jq -n \
  --arg project "$PROJECT" \
  --arg repo "$REPO" \
  --argjson tags "$TAGS_JSON" \
  --argjson types "$TYPES_JSON" \
  --argjson exclude_ids "$EXCLUDE_JSON" \
  '{
    project: $project,
    repo: (if $repo == "" then null else $repo end),
    tags: $tags,
    types: $types,
    exclude_ids: $exclude_ids
  }')

# --- Call API ---
RESULT=$(curl -sS --max-time 15 \
  -X POST \
  -H "Authorization: Bearer $MEM_TOKEN" \
  -H "Content-Type: application/json" \
  -d "$BODY" \
  "${MEM_URL}/entries/by-skill" 2>&1)

echo "$RESULT"

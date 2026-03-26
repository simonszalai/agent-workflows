#!/usr/bin/env bash
# Shared helper: parse mem identity from CLAUDE.md and validate config.
# Source this from hooks: source "$(dirname "$0")/mem-env.sh" "$INPUT"
# Sets: MEM_PROJECT, MEM_REPO, MEM_URL, MEM_TOKEN, MEM_TOPOLOGY
# On skip (no mem tag): sets MEM_ENV_SKIP=1, returns 0. Caller should exit 0.
# On error: writes to stderr, returns 1. Caller's mem-err-trap catches it.

_INPUT="${1:-}"

# --- Load env from dotfile if present ---
if [[ -f "$HOME/.config/autodev-memory/.env" ]]; then
  set -a
  source "$HOME/.config/autodev-memory/.env"
  set +a
fi

# --- CWD: different hook events use different schemas ---
_CWD=$(echo "$_INPUT" | jq -r '(.cwd // .session.cwd) // empty' 2>/dev/null)
if [[ -z "$_CWD" ]]; then
  echo "HOOK ERROR [mem-env]: no cwd found in hook input (tried .cwd and .session.cwd)" >&2
  return 1
fi

# --- Parse mem stub from CLAUDE.md ---
_CLAUDE_MD="$_CWD/CLAUDE.md"
if [[ ! -f "$_CLAUDE_MD" ]]; then
  MEM_ENV_SKIP=1
  return 0
fi

_MEM_LINE=$(grep -o '<!-- mem:project=[^ ]* repo=[^ ]* -->' "$_CLAUDE_MD" 2>/dev/null || true)
if [[ -z "$_MEM_LINE" ]]; then
  MEM_ENV_SKIP=1
  return 0
fi

MEM_PROJECT=$(echo "$_MEM_LINE" | sed 's/.*project=\([^ ]*\).*/\1/')
MEM_REPO=$(echo "$_MEM_LINE" | sed 's/.*repo=\([^ ]*\).*/\1/' | sed 's/ *-->//')
MEM_URL="${AUTODEV_MEMORY_API_URL:-http://localhost:8475}"
MEM_TOKEN="${AUTODEV_MEMORY_API_TOKEN:-}"

if [[ -z "$MEM_TOKEN" ]]; then
  echo "HOOK ERROR [mem-env]: AUTODEV_MEMORY_API_TOKEN not set" >&2
  return 1
fi

# --- Fetch topology (|| true prevents set -e from killing us before error check) ---
TOPO_RESPONSE=$(curl -sS --max-time 3 \
  -H "Authorization: Bearer $MEM_TOKEN" \
  "$MEM_URL/topology?project=$MEM_PROJECT" 2>&1) || true
TOPO_EXIT=${PIPESTATUS[0]:-$?}

# Check if curl failed (response will contain "curl:" error text)
if [[ "$TOPO_RESPONSE" == curl:* ]]; then
  echo "HOOK ERROR [mem-env]: memory API unreachable at $MEM_URL: $TOPO_RESPONSE" >&2
  return 1
fi

MEM_TOPOLOGY=$(echo "$TOPO_RESPONSE" | jq -r '
  "Project: " + .project + " — " + .project_description + "\nRepos:\n" +
  ([.repos[] | "  - " + .repo_name + ": " + .repo_description] | join("\n"))
' 2>/dev/null)

if [[ -z "$MEM_TOPOLOGY" ]]; then
  echo "HOOK ERROR [mem-env]: failed to parse topology response: $TOPO_RESPONSE" >&2
  return 1
fi

export MEM_PROJECT MEM_REPO MEM_URL MEM_TOKEN MEM_TOPOLOGY

#!/bin/bash
# claude-sync-hook — pre-commit hook
# Syncs user-level agents/skills/commands into .claude/ for cloud compatibility.
# Runs before the commit is created so synced files are staged naturally,
# avoiding the fragile post-commit --amend pattern that breaks rebases.
#
# Respects project-level items: if a name exists at project level and wasn't
# put there by this script, it's left alone.
#
# Marker convention:
#   Directories (skills): .claude/skills/my-skill/.synced-from-user
#   Files (agents):       .claude/agents/.synced-from-user.my-agent.md

set -euo pipefail

# Resolve shared config location: explicit env var, or follow ~/.claude symlinks
if [ -n "${CLAUDE_SHARED_CONFIG:-}" ]; then
  SHARED="$CLAUDE_SHARED_CONFIG"
elif [ -L "$HOME/.claude/agents" ]; then
  SHARED="$(dirname "$(readlink -f "$HOME/.claude/agents")")"
else
  # Fallback: nothing to sync
  exit 0
fi

[ -d "$SHARED" ] || exit 0

DIRS=("agents" "skills" "commands")
PROJECT_CLAUDE=".claude"
changed=false

for dir in "${DIRS[@]}"; do
  [ -d "$SHARED/$dir" ] || continue

  # Ensure we don't create empty dirs for no reason
  has_items=false
  for item in "$SHARED/$dir"/*; do
    [ -e "$item" ] && has_items=true && break
  done
  $has_items || continue

  mkdir -p "$PROJECT_CLAUDE/$dir"

  # --- Sync: shared → project ---
  for item in "$SHARED/$dir"/*; do
    [ -e "$item" ] || continue
    name=$(basename "$item")

    # Skip dotfiles / markers
    [[ "$name" == .synced-from-user* ]] && continue

    # Check if project already has this name
    if [ -e "$PROJECT_CLAUDE/$dir/$name" ]; then
      # Is it ours from a previous sync?
      is_ours=false
      if [ -d "$PROJECT_CLAUDE/$dir/$name" ] && [ -f "$PROJECT_CLAUDE/$dir/$name/.synced-from-user" ]; then
        is_ours=true
      elif [ -f "$PROJECT_CLAUDE/$dir/$name" ] && [ -f "$PROJECT_CLAUDE/$dir/.synced-from-user.$name" ]; then
        is_ours=true
      fi

      if ! $is_ours; then
        echo "[claude-sync] SKIP $dir/$name (project-level exists)"
        continue
      fi
    fi

    # Copy and mark
    if [ -d "$item" ]; then
      rm -rf "$PROJECT_CLAUDE/$dir/$name"
      cp -r "$item" "$PROJECT_CLAUDE/$dir/$name"
      touch "$PROJECT_CLAUDE/$dir/$name/.synced-from-user"
    else
      cp "$item" "$PROJECT_CLAUDE/$dir/$name"
      touch "$PROJECT_CLAUDE/$dir/.synced-from-user.$name"
    fi
    changed=true
  done

  # --- Cleanup: remove synced items that no longer exist in shared ---
  for item in "$PROJECT_CLAUDE/$dir"/*; do
    [ -e "$item" ] || continue
    name=$(basename "$item")
    [[ "$name" == .synced-from-user* ]] && continue

    is_ours=false
    if [ -d "$item" ] && [ -f "$item/.synced-from-user" ]; then
      is_ours=true
    elif [ -f "$item" ] && [ -f "$PROJECT_CLAUDE/$dir/.synced-from-user.$name" ]; then
      is_ours=true
    fi

    if $is_ours && [ ! -e "$SHARED/$dir/$name" ]; then
      if [ -d "$item" ]; then
        rm -rf "$item"
      else
        rm -f "$item" "$PROJECT_CLAUDE/$dir/.synced-from-user.$name"
      fi
      echo "[claude-sync] REMOVED stale $dir/$name"
      changed=true
    fi
  done
done

if $changed; then
  git add .claude/
  echo "[claude-sync] Staged synced user-level config into .claude/"
fi

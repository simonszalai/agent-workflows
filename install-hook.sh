#!/bin/bash
# install-hook.sh — Run from inside any project repo to install the sync hook.
# Usage:
#   /path/to/claude-shared-config/install-hook.sh          (from project root)
#   /path/to/claude-shared-config/install-hook.sh /my/repo  (target a specific repo)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOOK_SOURCE="$SCRIPT_DIR/sync-hook.sh"
TARGET_REPO="${1:-.}"

# Resolve git dir (supports worktrees)
GIT_DIR=$(git -C "$TARGET_REPO" rev-parse --git-dir 2>/dev/null) || {
  echo "Error: $TARGET_REPO is not a git repository" >&2
  exit 1
}
HOOKS_DIR="$GIT_DIR/hooks"
HOOK_TARGET="$HOOKS_DIR/post-commit"

mkdir -p "$HOOKS_DIR"

# If post-commit already exists, chain it
if [ -f "$HOOK_TARGET" ] && ! grep -q "claude-sync-hook" "$HOOK_TARGET"; then
  echo "[hook] Existing post-commit found, appending claude sync"
  cat >> "$HOOK_TARGET" <<EOF

# --- claude-sync-hook ---
CLAUDE_SHARED_CONFIG="$SCRIPT_DIR" bash "$HOOK_SOURCE"
EOF
else
  cat > "$HOOK_TARGET" <<EOF
#!/bin/bash
# --- claude-sync-hook ---
CLAUDE_SHARED_CONFIG="$SCRIPT_DIR" bash "$HOOK_SOURCE"
EOF
fi

chmod +x "$HOOK_TARGET"
echo "[ok] Post-commit hook installed in $GIT_DIR"
echo "     Syncs from: $SCRIPT_DIR"
echo "     On each commit, user-level agents/skills/commands → .claude/"

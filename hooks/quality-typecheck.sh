#!/usr/bin/env bash
# =============================================================================
# quality-typecheck.sh — Whole-project type checking hook (Stop event)
# =============================================================================
#
# Runs the project's type checker when Claude finishes responding. If errors
# are found, blocks Claude from stopping (exit 2) so it can fix them.
# Uses stop_hook_active to prevent infinite loops — only blocks once.
#
# Supported type checkers (detected automatically):
#   - TypeScript (tsc):  tsconfig.json in project root
#   - Pyrefly:           [tool.pyrefly] section in pyproject.toml
#   - Pyright:           pyright listed in project dependencies in pyproject.toml
#
# Performance notes:
#   - tsc --noEmit can be slow (10-30s on medium projects)
#   - If @typescript/native-preview is installed, tsgo is used instead (~3-5s)
#   - Python type checkers are generally fast
#
# Exit behavior:
#   - Exit 0: all checks pass, or stop_hook_active is true (prevent loop)
#   - Exit 2: type errors found — stderr is fed back to Claude, which will
#             continue working to fix them before stopping again
#
# =============================================================================
# SETUP — Register this hook in settings.json (user or project level):
#
#   "hooks": {
#     "Stop": [
#       {
#         "matcher": "",
#         "hooks": [
#           {
#             "type": "command",
#             "command": "~/.claude/hooks/quality-typecheck.sh",
#             "timeout": 120
#           }
#         ]
#       }
#     ]
#   }
#
# Same merge caveat as quality-lint.sh: if the project has its own hooks in
# .claude/settings.json, add this Stop entry there too.
# =============================================================================

set -uo pipefail
# Note: no set -e — we need to capture non-zero exits from type checkers

INPUT=$(cat)

# Requires jq for JSON parsing
if ! command -v jq &>/dev/null; then
  exit 0
fi

# Prevent infinite loops: if we already blocked once, let Claude stop
STOP_HOOK_ACTIVE=$(echo "$INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$STOP_HOOK_ACTIVE" = "true" ]; then
  exit 0
fi

# Use CLAUDE_PROJECT_DIR (primary project only), not cwd which may point to
# an additional directory with pre-existing errors unrelated to this session.
PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$PROJECT_ROOT" ]; then
  exit 0
fi

ERRORS=""

# --- TypeScript → tsgo (fast) or tsc (fallback) ---
# No explicit timeout here — the hook's "timeout" setting in settings.json handles it.
if [ -f "$PROJECT_ROOT/tsconfig.json" ]; then
  if [ -x "$PROJECT_ROOT/node_modules/.bin/tsgo" ]; then
    output=$(cd "$PROJECT_ROOT" && npx tsgo --noEmit 2>&1)
    rc=$?
  else
    output=$(cd "$PROJECT_ROOT" && npx tsc --noEmit 2>&1)
    rc=$?
  fi
  if [ $rc -ne 0 ]; then
    ERRORS="TypeScript type errors:\n$output"
  fi
fi

# --- Python → Pyrefly ---
if [ -f "$PROJECT_ROOT/pyproject.toml" ] && grep -q '\[tool\.pyrefly' "$PROJECT_ROOT/pyproject.toml"; then
  # No args = project mode, which honors project_excludes from config.
  output=$(cd "$PROJECT_ROOT" && uv run pyrefly check 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    ERRORS="${ERRORS:+$ERRORS\n\n}Pyrefly type errors:\n$output"
  fi
fi

# --- Python → Pyright (only if pyrefly not configured) ---
if [ -f "$PROJECT_ROOT/pyproject.toml" ] && ! grep -q '\[tool\.pyrefly' "$PROJECT_ROOT/pyproject.toml" \
   && grep -q 'pyright' "$PROJECT_ROOT/pyproject.toml"; then
  output=$(cd "$PROJECT_ROOT" && uv run pyright 2>&1)
  rc=$?
  if [ $rc -ne 0 ]; then
    ERRORS="${ERRORS:+$ERRORS\n\n}Pyright type errors:\n$output"
  fi
fi

if [ -n "$ERRORS" ]; then
  echo -e "$ERRORS" >&2
  exit 2
fi

exit 0

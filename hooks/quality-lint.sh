#!/usr/bin/env bash
# =============================================================================
# quality-lint.sh — Per-file linting hook (PostToolUse on Edit|Write)
# =============================================================================
#
# Runs the project's linter on the edited file immediately after each Edit/Write.
# Detects tooling from config files — never assumes a tool is present.
#
# Supported linters (detected automatically):
#   - Biome:  biome.json or biome.jsonc in project root
#   - Ruff:   [tool.ruff] section in pyproject.toml
#
# Exit behavior:
#   - Exit 0: file is clean or not a lintable type (no action)
#   - Exit 2: lint errors found — stderr is fed back to Claude, which will
#             attempt to fix the issues before continuing
#
# =============================================================================
# SETUP — Register this hook in settings.json (user or project level):
#
#   "hooks": {
#     "PostToolUse": [
#       {
#         "matcher": "Edit|Write",
#         "hooks": [
#           {
#             "type": "command",
#             "command": "~/.claude/hooks/quality-lint.sh",
#             "timeout": 30
#           }
#         ]
#       }
#     ]
#   }
#
# If the project already has hooks in .claude/settings.json, add the
# PostToolUse entry alongside existing hooks — hooks don't merge across
# levels, so user-level hooks are invisible when project-level hooks exist.
# =============================================================================

set -uo pipefail
# Note: no set -e — we need to capture non-zero exits from linters

# Skip when running inside a memory hook's claude -p subprocess
if [[ "${_MEM_HOOK_ACTIVE:-}" == "1" ]]; then
  exit 0
fi

INPUT=$(cat)

# Requires jq for JSON parsing
if ! command -v jq &>/dev/null; then
  exit 0
fi

FILE=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty' 2>/dev/null)
if [ -z "$FILE" ]; then
  exit 0
fi

# Resolve project root from the file's location (handles multi-project setups)
FILE_DIR=$(dirname "$FILE")
PROJECT_ROOT=$(cd "$FILE_DIR" 2>/dev/null && git rev-parse --show-toplevel 2>/dev/null) || true
if [ -z "$PROJECT_ROOT" ]; then
  exit 0
fi

ERRORS=""

# --- TypeScript / JavaScript → Biome ---
if [[ "$FILE" == *.ts ]] || [[ "$FILE" == *.tsx ]] || [[ "$FILE" == *.js ]] || [[ "$FILE" == *.jsx ]]; then
  if [ -f "$PROJECT_ROOT/biome.json" ] || [ -f "$PROJECT_ROOT/biome.jsonc" ]; then
    output=$(cd "$PROJECT_ROOT" && npx biome check "$FILE" 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
      ERRORS="Biome lint errors:\n$output"
    fi
  fi
fi

# --- Python → Ruff ---
if [[ "$FILE" == *.py ]]; then
  if [ -f "$PROJECT_ROOT/pyproject.toml" ] && grep -q '\[tool\.ruff' "$PROJECT_ROOT/pyproject.toml"; then
    output=$(cd "$PROJECT_ROOT" && uv run ruff check "$FILE" 2>&1)
    rc=$?
    if [ $rc -ne 0 ]; then
      ERRORS="Ruff lint errors:\n$output"
    fi
  fi
fi

if [ -n "$ERRORS" ]; then
  echo "$ERRORS" >&2
  exit 2
fi

exit 0

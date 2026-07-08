#!/usr/bin/env python3
"""PreToolUse guard on Bash: enforce the Conductor commit-all rule mechanically.

Session-audit finding #11: agents detect uncommitted changes in Conductor
workspaces and still push / open PRs without committing them, despite the
CLAUDE.md critical rule ("commit ALL outstanding changes"). Docs are not
enforcement — this hook is.

Blocks `git push` / `gh pr create` when the working tree is dirty, ONLY when:
  - cwd is under a Conductor workspace (~/conductor/workspaces/), and
  - the same command does not itself commit first (git add/commit chained).

Fail-open: any unexpected error exits 0 with no output (call proceeds normally).
"""
import json
import os
import subprocess
import sys

try:
    data = json.load(sys.stdin)
    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if "git push" not in cmd and "gh pr create" not in cmd:
        sys.exit(0)
    # Command commits as part of the same chain — status check would be stale.
    if "git commit" in cmd or "git add" in cmd:
        sys.exit(0)
    cwd = data.get("cwd") or os.getcwd()
    if "/conductor/workspaces/" not in cwd:
        sys.exit(0)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=cwd, capture_output=True, text=True, timeout=10,
    )
    dirty = result.stdout.strip()
    if result.returncode == 0 and dirty:
        reason = (
            "Conductor commit rule (CLAUDE.md, critical): the workspace has "
            "uncommitted changes and you are about to push / open a PR. Commit "
            "ALL outstanding changes first — including ones unrelated to the "
            "current task; Conductor workspaces are ephemeral and Conductor "
            "hides the merge button while anything is uncommitted. "
            "Dirty files:\n" + dirty[:1500] +
            "\nStage everything (git add -A), commit, then retry this command."
        )
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }))
except Exception:
    pass
sys.exit(0)

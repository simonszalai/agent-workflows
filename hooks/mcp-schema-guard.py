#!/usr/bin/env python3
"""PreToolUse guard for mcp__autodev-memory__search.

Session-audit finding #1 (highest recurrence): agents call search with a single
`query` string instead of the required `queries=[{keywords, text}]` array —
especially subagents, which never see the session-start memory hook output.
This hook denies the malformed call with a corrective message so the agent
self-corrects in one turn instead of retry-looping.

Fail-open: any unexpected error exits 0 with no output (call proceeds normally).
"""
import json
import sys

try:
    data = json.load(sys.stdin)
    tool_input = data.get("tool_input") or {}
    queries = tool_input.get("queries")
    ok = (
        isinstance(queries, list)
        and len(queries) > 0
        and all(isinstance(q, dict) for q in queries)
    )
    if not ok:
        reason = (
            "Malformed mcp__autodev-memory__search call. The tool takes "
            'queries=[{"keywords": ["<kw1>", "<kw2>"], "text": "<free text>"}] '
            "— a LIST of objects. There is no single `query` string parameter. "
            "Retry exactly like this:\n"
            'mcp__autodev-memory__search(queries=[{"keywords": ["<topic>", "<area>"], '
            '"text": "<what you are investigating>"}], project="<project>", limit=5)\n'
            "If this tool's schema was never loaded in this session, call "
            'ToolSearch("select:mcp__autodev-memory__search") first and follow the '
            "returned schema."
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

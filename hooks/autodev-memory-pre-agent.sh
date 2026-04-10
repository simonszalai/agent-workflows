#!/usr/bin/env bash
# Pre-agent hook disabled — additionalContext from PreToolUse goes to the parent
# model, not the spawned subagent. Subagents now bootstrap their own memory via
# active search (see autodev-search skill). Keeping the file so the hook config
# doesn't error; it just returns empty immediately.
echo '{}'
exit 0

---
name: tool-slack
description: Slack Web API reference via the slack-api CLI wrapper (the slack MCP server was retired). Reading channels/threads, searching, and sending messages.
---

# Slack CLI Reference

How to use Slack via the Web API. The slack MCP server was retired (2026-07-28) —
use `slack-api` (agent-workflows/bin, on PATH) through the Bash tool.

## The wrapper: `slack-api`

`slack-api <method> [key=value ...]` calls any Slack Web API method with the user
token injected silently per call (1Password service-account token; no Touch ID).
Output is the raw API JSON — **always check `.ok` and pipe through `jq`**; never dump
a raw response into context.

```bash
slack-api auth.test | jq '{ok, team, user}'          # sanity check
```

## Reading

```bash
# find a channel id (do this once; methods below need ids, not names)
slack-api conversations.list types=public_channel,private_channel limit=200 \
  | jq -r '.channels[] | select(.name=="ops-alerts") | .id'

# recent messages
slack-api conversations.history channel=C0123456789 limit=20 \
  | jq -r '.messages[] | "\(.ts) \(.user // .bot_id): \(.text[:200])"'

# a thread (thread_ts = ts of the parent message)
slack-api conversations.replies channel=C0123456789 ts=1753700000.123456 \
  | jq -r '.messages[] | "\(.user): \(.text[:200])"'

# search (user-token scoped)
slack-api search.messages query='deploy failed in:#ops-alerts' count=10 \
  | jq -r '.messages.matches[] | "\(.channel.name) \(.ts): \(.text[:150])"'

# user lookup
slack-api users.info user=U0123456789 | jq '{name: .user.name, real: .user.real_name}'
```

## Writing (outward-facing — needs explicit instruction or durable authorization)

```bash
slack-api chat.postMessage channel=C0123456789 text='message here'
slack-api chat.postMessage channel=C0123456789 thread_ts=1753700000.123456 text='reply in thread'
slack-api reactions.add channel=C0123456789 timestamp=1753700000.123456 name=white_check_mark
```

Sending a Slack message publishes it to humans immediately — same bar as any
outward-facing action: do it when asked or durably authorized, not speculatively.

## Rules

- Timestamps (`ts`) double as message ids; keep them verbatim (string, not float).
- `key=value` args are form-encoded; quote values with spaces (`text='two words'`).
- Rate limits: Slack returns `.ok=false, .error="ratelimited"` with a `Retry-After`
  header — back off, don't hammer.
- Never print the token; the wrapper never exposes it.
- Common channels (ts project): `#ops-alerts` (alerting), `#issue-updates`
  (ticket/PR traffic), `#all-ts-invest` (general).

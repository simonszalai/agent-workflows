# Hermes schedules

Canonical definitions of every scheduled agent run Hermes launches through the Conductor MCP
(`hermes/conductor/server.py`). Hermes cron reads `schedules.yaml`, creates a Conductor
workspace per the entry, sends the referenced prompt file's contents as the first session
message, polls the session, and posts the result to Slack.

Rules:

- **Prompts stay thin.** One skill invocation plus the scheduled marker. All logic, the
  unattended contract, and Slack report formatting live in the invoked skill, which is
  versioned in `skills/`. Never put procedural instructions in a prompt file.
- **Changes are PR-reviewed.** These files gate what runs autonomously against production
  data; edit them only through a reviewed agent-workflows PR, like every Hermes asset.
- **Unattended contract (every schedule inherits this):** no `op://*-sensitive` access, no
  operation that would raise a 1Password prompt (they hard-fail unattended), no production
  mutations of any kind. Production is read-only via `TS/PROD_POSTGRES_URL_RO`. Anything
  requiring prod-touch or human approval stops and reports to Slack instead of proceeding.
- An `enabled: false` entry is staged but not yet runnable — its `blocked_on` field says
  what must land first.

Slack destinations:

| Channel | Content |
|---|---|
| `#autodev-nightly` | verify/promote and dream results |
| `#autodev-health` | 6-hourly checks; a single ✅ line when green |
| `#autodev-incidents` | root-cause clusters needing a human decision |

Format everywhere: one-line summary in the channel, all detail in the thread.

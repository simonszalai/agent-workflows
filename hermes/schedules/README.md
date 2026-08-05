# Hermes schedules

Canonical definitions of every scheduled agent run Hermes launches through the Conductor MCP
(`hermes/conductor/server.py`). systemd timers (one per manifest entry, timezone
America/Vancouver) start `runner.py run <name>`, which reads `schedules.yaml`, creates a
Conductor workspace per the entry, sends the referenced prompt file's contents as the first
session message, polls the session with the entry's `max_runtime_minutes` cap, parses the
`SCHEDULED_RUN_RESULT` ending, and posts the result to Slack (normally one line in the channel
with detail in the thread; `health-6h` uses a parent bullet list plus one reply per issue;
FAIL/BLOCKED additionally routes one line to `#autodev-incidents`).

## Runner mechanics (`runner.py`, deployed to `/opt/hermes-schedules`)

- **Enabled gate.** `enabled: false` entries are skipped at runtime; timers are always
  installed, so activation is purely a reviewed manifest flip plus `hermes/install.sh`.
- **Overlap lock.** A per-schedule `flock` under `/var/lib/hermes-schedules` skips a firing
  while the previous run is still active. No queueing, no double workspaces.
- **Failure handling.** Poll timeout cancels the session and posts FAIL; an errored session
  or a run ending without a `SCHEDULED_RUN_RESULT` block is FAIL; there are no automatic
  retries. Runner crashes trigger `OnFailure=hermes-schedule-alert@%i.service`, which posts
  the unit failure to `#autodev-incidents`.
- **Watchdog.** `hermes-schedule-watchdog.timer` (every 30 min) alerts `#autodev-incidents`
  when an enabled schedule has not reported within its cron interval plus `max_runtime` plus
  an hour of grace — green runs post, so silence means the scheduler is broken.
- **Workspace retention.** The watchdog archives PASS workspaces after
  `runner.retention_days_pass` days; FAIL/BLOCKED workspaces are retained
  `runner.retention_days_fail` days for triage before archival.
- **Secret boundary.** The runner holds no Conductor credential (loopback MCP on 8794 owns
  it) and receives the Slack token only via systemd `LoadCredential`
  (`/etc/hermes-schedules/slack.token`, root-only 0400 — see `hermes/README.md`).

Rules:

- **Prompts stay thin.** One skill invocation plus the scheduled marker. All logic, the
  unattended contract, and Slack report formatting live in the invoked skill, which is
  versioned in `skills/`. Never put procedural instructions in a prompt file.
- **Health findings prove current ownership.** A stale row is not an issue until the verifier
  proves that a current producer still writes that exact state on the expected cadence. The
  canonical gate is `skills/references/scheduled-run.md` §2a.
- **Changes are PR-reviewed.** These files gate what runs autonomously against production
  data; edit them only through a reviewed agent-workflows PR, like every Hermes asset.
- **Unattended contract (every schedule inherits this):** no `op://*-sensitive` access, no
  operation that would raise a 1Password prompt (they hard-fail unattended), no production
  mutations of any kind. Production is read-only via `TS/PROD_POSTGRES_URL_RO`. Anything
  requiring prod-touch or human approval stops and reports to Slack instead of proceeding.
- An `enabled: false` entry is staged but not yet runnable — its `blocked_on` field says
  what must land first.
- The full unattended contract (mutation boundary, Slack report format, PASS/FAIL ending
  schema, `rc_fingerprint` dedup) is canonical in `skills/references/scheduled-run.md`.

Slack destinations:

| Channel | Content |
|---|---|
| `#autodev-nightly` | verify/promote and dream results |
| `#autodev-health` | 6-hourly checks; issue bullets + one reply each, or a single ✅ line when green |
| `#autodev-incidents` | root-cause clusters needing a human decision |

Default format: one-line summary in the channel, detail in the thread. Health failures use the
issue-oriented exception defined in `skills/references/scheduled-run.md` §2. Nightly dream uses a
count-rich parent plus one structured what/why/how reply; its raw result block is never posted.

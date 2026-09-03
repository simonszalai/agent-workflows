# Hermes schedules

Canonical definitions of every scheduled agent run Hermes launches through the Conductor MCP
(`hermes/conductor/server.py`). systemd timers (one per manifest entry, timezone
America/Vancouver) start the stable release launcher with `run <name>`. It resolves the current
immutable release, whose `runner.py` reads `schedules.yaml`, creates a
Conductor workspace per the entry, sends the referenced prompt file's contents as the first
session message, polls the session with the entry's `max_runtime_minutes` cap, parses the
`SCHEDULED_RUN_RESULT` ending, and posts the result to Slack (normally one line in the channel
with detail in the thread; `health-6h` uses a parent bullet list, launches one cloud
`/ticket-flow` workspace per issue, and posts one final issue/fix/verification message per issue;
FAIL/BLOCKED additionally routes one line to `#autodev-incidents`; NEEDS_MORE_TIME remains in the
schedule channel for automatic/next-run continuation).

## Runner mechanics (`runner.py`, deployed to `/opt/hermes-schedules`)

- **Automatic reviewed updates.** A root-owned 15-minute timer fetches public
  `agent-workflows/main`, exports only the runtime files in this directory, validates them as the
  unprivileged service account, and atomically activates a complete immutable release. Existing
  jobs remain pinned to their starting release; no service restart is required.
- **Deployment contract.** `deployment_contract_version` prevents code that needs new systemd,
  timer, or credential behavior from being activated by the limited automatic updater. Timer
  names and calendars must continue matching the installed reviewed units.

- **Enabled gate.** `enabled: false` entries are skipped at runtime; timers are always
  installed, so activation is purely a reviewed manifest flip plus `hermes/install.sh`.
- **Overlap lock.** A per-schedule `flock` under `/var/lib/hermes-schedules` skips a firing
  while the previous run is still active. No queueing, no double workspaces.
- **Health remediation.** `health-6h` first completes bounded triage and emits owning tickets. The
  runner then launches all per-ticket workspaces in parallel from `staging`, supervises them under
  `remediation_max_runtime_minutes`, and keeps the schedule lock until each child has produced a
  structured terminal result or been cancelled at the deadline.
- **Production approval.** Every staging-verified issue is its own top-level Slack message and
  approval thread. The operator replies there, tags Hermes, and clearly approves in their own
  words. The separate approval timer reads at most one 15-message Slack thread page per minute and
  accepts only a non-negated, non-conditional approval addressed to the manifest-pinned immutable
  Hermes user ID, written by a manifest-authorized immutable operator ID after staging verification.
  Ticket identity comes only from that one-issue thread, never from the prose. The runner re-checks
  the ticket and exact staging PASS artifact, then launches a fresh `/ticket-promote` session in
  that issue's workspace. Promotions are globally serialized.
  Success is posted only after the ticket re-reads as `completed` with a new exact production PASS
  artifact recorded after the Slack approval. Failed promotions reset later queued approvals.
- **Failure handling.** Poll timeout cancels the session and posts FAIL; an errored session
  or a run ending without a `SCHEDULED_RUN_RESULT` block is FAIL; there are no automatic
  retries. Runner crashes trigger a root-owned stable alert program outside the mutable
  release, which posts the unit failure to `#autodev-incidents`.
- **Watchdog.** `hermes-schedule-watchdog.timer` (every 30 min) alerts `#autodev-incidents`
  when an enabled schedule has not reported within its cron interval plus `max_runtime` plus
  an hour of grace — green runs post, so silence means the scheduler is broken.
- **Archive on completion.** A run whose final status is in `runner.archive_on_complete`
  (default `[PASS, FAIL, BLOCKED]`, i.e. every terminal status) has its Conductor workspace
  archived immediately by the runner; the Slack thread keeps the deep link and an archived
  workspace stays readable for triage. Failed health remediation workspaces are archived the
  same way. NEEDS_MORE_TIME must stay open for its continuation, and staging-verified
  remediation workspaces stay open until their production promotion has finished.
- **Workspace retention.** Every workspace is written to the schedule's history file as
  `RUNNING` the moment it is created, so a runner crash cannot leak it. The watchdog sweep
  retries any failed archive-on-complete on its next pass, archives `RUNNING` records older
  than `runner.retention_days_stale_run` (unless that schedule's overlap lock is still held),
  PASS records after `runner.retention_days_pass`, and everything else after
  `runner.retention_days_fail`. Workspaces waiting for or running an approved production
  promotion are never archived by retention.
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
- **Unattended contract (every schedule inherits this):** no `op://*-sensitive` access and no
  operation that would raise a 1Password prompt (they hard-fail unattended). Production data is
  read-only via `TS/PROD_POSTGRES_URL_RO`; `health-6h` has one reviewed production-side exception:
  append-only `ticket:<ID>` Prefect tags on explicitly verified failed/crashed runs. Per-issue
  ticket workspaces may land and verify staging only. Production remains human-invoked: the exact
  operator identity, Hermes mention, issue thread, and clear Slack approval are the bounded
  invocation transported by the deterministic approval bridge.
- An `enabled: false` entry is staged but not yet runnable — its `blocked_on` field says
  what must land first.
- The full unattended contract (mutation boundary, Slack report format, terminal-result ending
  schema, `rc_fingerprint` dedup) is canonical in `skills/references/scheduled-run.md`.

Slack destinations:

| Channel | Content |
|---|---|
| `#autodev-nightly` | verify/promote and dream results |
| `#autodev-health` | 6-hourly checks; issue bullets + one top-level result/approval thread per issue, or a single ✅ line when green |
| `#autodev-incidents` | root-cause clusters needing a human decision |

Default format: one-line summary in the channel, detail in the thread. Health failures use the
issue-oriented exception defined in `skills/references/scheduled-run.md` §2. Nightly dream uses a
count-rich parent plus one structured what/why/how reply; its raw result block is never posted.

For a staging-verified issue, reply to that issue's message, tag Hermes, and clearly approve in
your own words—for example, “@Hermes I approve this for production” or “@Hermes looks good, ship
it.” No ticket syntax is required because the thread itself binds the approval to exactly one
ticket. The bridge acknowledges acceptance, links the production Conductor session when it starts,
and posts the final issue/fix/production-evidence reply in the same thread. A different user,
missing Hermes mention, ambiguous/negated/conditional language, different thread, older message,
or expired approval window cannot authorize production.

`#autodev-health` must remain outside the generic Hermes gateway's `SLACK_ALLOWED_CHANNELS` and
`SLACK_FREE_RESPONSE_CHANNELS`. The bot mention is the human-facing approval affordance; this
deterministic bridge is the only component allowed to interpret it as production authorization.

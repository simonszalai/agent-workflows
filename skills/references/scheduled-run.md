# Scheduled-Run Convention

The shared contract for every unattended agent run Hermes launches from
`hermes/schedules/schedules.yaml` (nightly verify/promote, nightly dream, 6-hourly health).
Scheduled skill modes (ticket-verify `--scheduled`, night-dream, health-system scheduled mode)
reference this document instead of restating it. Prompts in `hermes/schedules/` stay thin: one
skill invocation plus the scheduled marker; all logic lives here and in the invoked skill.

A scheduled run never asks interactive questions. Anything that would require human input,
approval, or credentials it does not already hold is a stop-and-report, not a prompt.

## 1. Mutation boundary (unattended contract)

What a scheduled run may and may never touch:

- **Prod app DB: read-only, enforced by credential.** All production database access goes
  through the read-only credential `TS/PROD_POSTGRES_URL_RO`. Never connect to prod with a
  read-write credential from a scheduled context, even for a "safe" statement.
- **Autodev ticket/memory writes: allowed.** Creating/updating tickets, artifacts, and memory
  entries via the autodev-memory MCP is the intended dedup/state mechanism (see §4).
- **`graph_*` mutations: never.** No inserts/updates/deletes on graph tables in any
  environment. Graph maintenance is its own explicitly-approved workflow.
- **Git merges/pushes to long-lived branches: never.** No merging or pushing to `main` or
  `staging` from a scheduled run. For ts-prefect, merging to `main` IS a production deploy
  (flows git_clone at runtime) and merging to `staging` is a staging deploy. A scheduled run
  reports "promotion-ready" evidence; a human (or an explicitly human-invoked workflow)
  performs the merge.
- **Nothing that can raise a 1Password prompt.** No `op://*-sensitive` reads, no operation
  that triggers Touch ID or an authorization prompt. These hard-fail unattended (authorization
  timeout / agent-communication failure) and wedge the run.
- **Stop-and-report instead.** Any action outside this boundary — prod mutation, human
  approval, missing scope/credential — ends that item as BLOCKED with the exact command or
  manual action a human should run, posted to Slack per §2. Never improvise around the
  boundary.

## 2. Slack report format

The Hermes runner owns Slack delivery from the structured result. Scheduled agents do not post
to Slack themselves. Channel IDs are recorded in `hermes/schedules/schedules.yaml`; the runner
resolves the configured name to its ID.

- **Default format.** Post exactly one summary line to the schedule's channel, then attach detail
  in that message's thread.
- **`health-6h` issue format.** When issues exist, the parent message is a short header followed by
  one bullet per issue. Each bullet names the issue and its owning ticket. Post exactly one thread
  reply per issue containing its human-readable problem description and ticket ID. Do not add a
  generic result-dump reply. A green run remains one standalone ✅ line with no thread reply.
- **Green runs still post.** A healthy run posts its one ✅ line ("ran, nothing to report").
  Silence is indistinguishable from a broken scheduler.
- **FAIL routing.** When a run ends FAIL (or BLOCKED on something needing a human decision),
  additionally post a one-line summary to `#autodev-incidents` @-mentioning Simon
  (`<@U09T4LELYES>`), linking the original thread. Detail lives in the origin thread; the
  incidents channel carries only the routing line.
- Channel map: `#autodev-nightly` (verify/promote + dream results), `#autodev-health`
  (6-hourly checks), `#autodev-incidents` (FAIL routing / root-cause clusters needing a human
  decision).

## 3. Structured ending (PASS/FAIL schema)

Every scheduled run's final session message ends with a fenced block the Hermes runner parses:

```
SCHEDULED_RUN_RESULT
status: PASS | FAIL | BLOCKED
schedule: <schedules.yaml name>
summary: <one line, becomes the Slack channel line>
checks_total: <int>
checks_failed: <int>
tickets_touched: [<ticket ids, may be empty>]
rc_fingerprints: [<fingerprints emitted this run, may be empty>]
issues: [{"title":"<short issue name>","problem":"<what is wrong>","ticket_id":"<ID or null>"}]
blocked_on: <exact command or manual action a human must take; omit unless BLOCKED>
```

- `PASS`: everything in scope ran and is healthy.
- `FAIL`: at least one check found a real problem (routes to `#autodev-incidents` per §2).
- `BLOCKED`: the run could not complete an item without crossing the §1 boundary;
  `blocked_on` carries the exact resume command/action.
- `issues` is required for `health-6h`: one single-line JSON array entry per actionable issue,
  or `[]` on PASS. `ticket_id` is the open ticket that owns the root cause, not a fallback ticket
  used only to store occurrence evidence. Use `null` only when no owning ticket could be assigned.
  Keep `title` short enough for the parent bullet; put the explanation and evidence in `problem`.
- The block is the last thing in the message. Free-form detail goes above it, never below.

## 4. Dedup convention (`rc_fingerprint`)

Recurring findings must extend one ticket, not spawn a new ticket per run.

- For each root cause a run identifies, compute a stable **root-cause fingerprint**: a short
  slug of the failing subsystem plus the invariant error signature (e.g.
  `auth-scraper:datadome-403`, `atlas:reviewed-plan-drift`). Exclude volatile parts —
  timestamps, run ids, counts, record ids.
- Store it as a ticket tag: `rc_fingerprint: <slug>` via the autodev-memory MCP.
- Before creating a ticket, search open tickets for a matching `rc_fingerprint` tag.
  **Match → extend** that ticket (append evidence, bump last-seen in a comment/artifact);
  **no match → create** a new ticket carrying the tag.
- Tickets closed since the last occurrence count as no-match: a recurrence after a fix gets a
  fresh ticket (same fingerprint), which is itself signal that the fix did not hold.

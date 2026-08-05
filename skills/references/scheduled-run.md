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

- **Prod app DB: read-only, enforced by the project profile and CLI.** Production database access
  uses `psql-cli prod` only when the selected project registry exposes a non-sensitive read-only
  production profile. A missing profile is BLOCKED; never substitute a read-write credential,
  even for a "safe" statement.
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
- **`nightly-dream` format.** The parent line states whether any changes were applied and gives
  counts for memory actions, tickets consolidated, graph writes, and proposals. Its one thread
  reply uses named sections for what was done, why, how, applied actions, proposals, graph plan,
  bounded scope, and run details. Never expose the raw `SCHEDULED_RUN_RESULT` block in Slack.
- **FAIL routing.** When a run ends FAIL (or BLOCKED on something needing a human decision),
  additionally post a compact, human-readable alert to `#autodev-incidents` @-mentioning Simon
  (`<@U09T4LELYES>`). Give each issue its own bold title, followed by one indented block containing
  proof, a representative example, the next step, and its owning ticket. Separate issues with a
  blank line, then link the original thread. Keep every field to one plain sentence; full logs and
  exhaustive evidence stay in the origin thread.
- Channel map: `#autodev-nightly` (verify/promote + dream results), `#autodev-health`
  (6-hourly checks), `#autodev-incidents` (FAIL routing / root-cause clusters needing a human
  decision).

## 2a. Health finding ownership gate

Before a health finding affects status, enters `issues`, or creates/extends a ticket, prove that
the failing identifier is owned by a **current producer**:

1. Resolve the identifier against the checked-out code, deployment/config registry, and actual
   writer call sites. Classify it as a current writer, current but intentionally untracked
   provenance identifier, or retired/renamed/unowned state.
2. A stale database row, timestamp, version pointer, or registry entry is not failure evidence by
   itself. It is actionable only when the current producer still writes that exact state on a
   defined cadence and has missed that cadence.
3. Retired, renamed, or unowned rows are excluded from unhealthy counts and service-outage
   issues. Find the replacement producer and test its current flow/run plus output evidence. If
   the verifier itself still describes the retired writer as active, classify that as
   `verifier_defect`, not `code_defect` or a product outage.
4. Current but intentionally untracked identifiers use the producer's authoritative evidence
   source. Do not infer a missing execution from a table the producer does not write.
5. Queue and orphan verifiers separate queued, actively owned, and expired work using the
   workload's ownership or lease clock. Enqueue/discovery age plus a broad processing state is not
   proof that work is stuck. Require a confirming sample after one successful worker or cleanup
   cycle before emitting a red issue.

*Example (ts-prefect `health-6h` scraper depth):* `scraper_executions` contains execution writers,
not every active feed or record-provenance ID. Derive its expected rows from current
`update_execution` writer call sites/configs. Evaluate RSS and Reuters discovery through current
Prefect flows and `record.source_meta.scraper_id`; do not use a Reuters record-ID prefix because
the sitemap deliberately preserves the historical fusion prefix for deduplication. A Completed
all-config RSS run proves every selected RSS config passed acquisition/parsing/claim processing,
but does not prove every downstream article body scrape succeeded.

## 3. Structured ending (PASS/FAIL schema)

Every scheduled run's final session message ends with a fenced block the Hermes runner parses:

```
SCHEDULED_RUN_RESULT
status: PASS | FAIL | BLOCKED
schedule: <schedules.yaml name>
summary: <one-line outcome; becomes the Slack line except for specialized schedule renderers>
checks_total: <int>
checks_failed: <int>
tickets_touched: [<ticket ids, may be empty>]
rc_fingerprints: [<fingerprints emitted this run, may be empty>]
issues: <single-line JSON array using the issue object below>
blocked_on: <exact command or manual action a human must take; omit unless BLOCKED>
```

`nightly-dream` additionally requires a `dream_report: <JSON object>` line. The value must be
serialized on one line in the result block; expanded, its schema is:

```json
{
  "what": "<one sentence describing the completed work and outcome>",
  "why": "<one sentence explaining why actions were or were not applied>",
  "how": "<one sentence describing the evidence and safety method>",
  "memory_actions": ["<entry ID — action — reason>"],
  "ticket_consolidations": ["<ticket ID — consolidation — reason>"],
  "proposals": ["<proposal — reason it needs human review>"],
  "graph_plan": "<one-sentence graph audit/plan outcome>",
  "scope": ["<bounded ticket, memory, or graph scope>"]
}
```

All fields are required. Action and proposal arrays may be empty; `scope` may not. The runner
derives the main-message counts from the arrays, so each applied memory action, consolidated
ticket, and proposal must occupy exactly one item. The graph write count is always zero because
the scheduled graph lane is propose-only. The runner converts this object into human-readable
Slack sections and keeps the machine block in the Conductor transcript only.

Issue object:

```json
{
  "title": "<short name>",
  "concrete_proof": "<aggregate evidence>",
  "representative_example": "<one occurrence>",
  "next_step": "<specific action>",
  "owning_ticket_id": "<ID or null>"
}
```

Serialize the array on one line in the result block.
Scheduled-run producers emit only those canonical keys. For older or already-running sessions,
the Hermes runner also accepts `proof`, `example`, and `ticket_id` as input-only legacy aliases.
When both forms of a field are present they must have the same value; conflicting aliases are
rejected.

- `PASS`: everything in scope ran and is healthy.
- `FAIL`: at least one check found a real problem (routes to `#autodev-incidents` per §2).
- `BLOCKED`: the run could not complete an item without crossing the §1 boundary;
  `blocked_on` carries the exact resume command/action.
- `issues` is required for `health-6h`: one single-line JSON array entry per actionable issue,
  or `[]` on PASS. `owning_ticket_id` is the open ticket that owns the root cause, not a fallback
  ticket used only to store occurrence evidence. Use `null` only when no owning ticket could be
  assigned. Keep `title` short enough for the parent bullet. Keep `concrete_proof`,
  `representative_example`, and `next_step` to one concrete sentence each. `concrete_proof` states
  the aggregate evidence; `representative_example` names one representative occurrence rather than
  repeating the proof.
- `dream_report` is required for `nightly-dream`. Missing or malformed data makes the run FAIL
  rather than silently restoring the raw machine dump.
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

---
name: ticket-verify
description: Timer-friendly evidence collection for tickets or explicit epic/milestone gates in staging or production. Read-only while verifying; standalone staging PASS promotes unless disabled.
max_turns: 200
---

# Ticket Verify

Verify tickets, or an explicit epic/milestone gate, after code has landed and deployment has
completed. Use this instead of legacy `/auto-verify`.

## Usage

```text
/ticket-verify staging              # verify all standalone tickets in to_verify_staging
/ticket-verify production           # verify all standalone tickets in to_verify_prod
/ticket-verify staging F0123 B0042
/ticket-verify production F0123 --lookback 24h
/ticket-verify staging --no-promote # report staging PASS but do not call ticket-promote

/ticket-verify staging --epic E0007 --milestone M2 --no-promote
/ticket-verify production --epic E0007
/ticket-verify production --epic E0007 --milestone M2
```

First argument must be `staging`, `prod`, or `production`.

## Boundaries

- Verification evidence collection is read-only by default: no data mutation, no flow triggers, no deploys.
  Exception: if the selected scope's evidence contract/deployment guide explicitly requires a bounded on-demand canary/shadow run in the target environment, and the deployment is already registered with safe parameters (for example `enqueue_mode=off`, capped `max_items`, no schedule change), `/ticket-verify` may trigger exactly that on-demand run and then grade its durable outputs. Record the command, run id, parameters, and terminal state in the evidence artifact. Do not use this exception for backfills, unbounded/full enqueue, schedule creation, deploys, migrations, manual Render deploys, or external-service mutations.
- Treat local `.context` files as **temporary scratch only**, not as verification artifacts or
  durable evidence. The canonical verification report must be persisted to autodev as a ticket
  or epic artifact. After the artifact is created or updated, delete any local scratch files this
  verification run created under `.context` (logs, JSON dumps, markdown drafts, screenshots, temp
  artifact JSON files, etc.) unless the user explicitly asked to keep them.
- On standalone staging PASS, this skill invokes `/ticket-promote` for that ticket **only
  when the auto-promotion gate (§9b) passes** — low-risk scopes with a fully graded
  FINALIZED contract. Higher-risk scopes rest at `staging_verified` for an explicit human
  `/ticket-promote`. Promotion (landing on main + production deploy steps) is a separate
  step, not part of evidence collection.
- The verifier agents this skill spawns are strictly read-only. The two narrow mutations this
  skill allows — the bounded on-demand canary/shadow trigger and the deferred post-PASS
  cleanup command (§10) — are executed by the ORCHESTRATOR (the ticket-verify runner itself),
  never by a spawned verifier agent.
- In explicit `--epic`/`--milestone` mode, do **not** auto-promote. The parent `/epic-flow`
  controls milestone progression and production promotion.
- On production PASS, set standalone ticket status to `completed`. In epic mode, update the
  parent epic/milestone gate and included step tickets according to the epic lifecycle.
- On failure, set `verify_staging_failed` or `verify_prod_failed` on the standalone ticket, or
  record the failed epic/milestone gate and failed evidence rows for `/epic-flow`'s fix loop.
- Blocker metadata is **not** a skip signal. If a selected ticket/gate has an active blocker,
  first re-check the recorded blocking condition against source-of-truth systems. If the blocker
  has cleared, continue verification in the same run.
- Verification stays read-only except for two narrow cases: (1) the bounded on-demand canary/shadow run exception above, and (2) on **production PASS**, a ticket may carry a deferred post-verification cleanup that runs only after the PASS verdict is recorded (see §10).

## Process

### 1. Select scope

If `--epic` is provided:

1. Load `get_epic(project, epic_id)` with artifacts, milestones, step tickets, events, and
   blockers.
2. If `--milestone` is present, restrict verification to that milestone's step tickets and gate
   package. If not present, verify the final/current production gate for all completed milestones.
3. Include epic step tickets explicitly. The default queue skip for epic steps does not apply
   when the parent epic/milestone is the requested scope.

If explicit ticket IDs are provided, load those. Otherwise:

- `staging` -> `list_tickets(status="to_verify_staging")`
- `production` -> `list_tickets(status="to_verify_prod")`

For the default queue mode, skip `abandoned`, `completed`, source tickets, and epic step tickets
whose parent milestone owns verification.

Do **not** skip tickets merely because they have `blocked_at`, `blocked_by`, `blocked_reason`, or
`blocked_context` metadata. Blocked candidates stay in scope and go through the blocker re-check
in §3.

### 1a. Parallel verifier dispatch

Verification of independent scopes is parallel, not sequential:

- **Queue mode (multiple tickets):** spawn one `verifier` agent per selected ticket as a
  single foreground parallel batch (multiple Agent calls in one message; never
  `run_in_background`). Each agent gets its ticket's context, evidence contract, and
  activation boundary, and returns its evidence rows and per-row results.
- **Large epic/milestone gates:** split the gate's evidence rows by surface — database
  queries, service logs, flow/deployment health, browser/UI — and spawn one verifier per
  surface in parallel. The orchestrator merges the rows into the single gate verdict (§7–§8).
- The orchestrator consolidates all agent output, computes verdicts, writes artifacts, and
  performs status changes. Verifier agents never write artifacts or change statuses, and never
  execute the canary/cleanup mutations (see Boundaries).

### 2. Load context

For each standalone ticket, or for the epic/milestone gate as a unit:

- load ticket/epic artifacts and events;
- read source, plan, review notes, existing `verification_evidence` artifacts, and milestone acceptance criteria;
- read the **`deployment_guide` artifact** — its **Verification Evidence** section is the
  contract you grade against. Each row is one evidence item: a reproducible query/command, an
  expected good output, and a bad-output interpretation, listed per environment (staging / prod).
  Also read its **Activation boundary**. If the artifact is missing or its evidence rows are still
  `TBD`/empty, fall back to deriving evidence from source + plan acceptance criteria, and flag in
  the report that the work shipped without a finalized evidence contract — the best staging
  verdict such a scope can earn is `PASS (contract-missing)` (§8), which does not auto-promote.
  Exception — tickets tagged `cleanup=true`: the ticket's `deferred_cleanup.evidence_contract`
  IS the FINALIZED contract (§10/§10a); the contract-missing verdict cap does not apply and no
  `deployment_guide` is synthesized;
- find PR/commit/landing branch from events, tags, PR title, or git history;
- read `.claude/environments/{env}.md` when present.

### 3. Re-check active blockers from ground truth

Before skipping, delaying, or reporting a selected ticket/gate as blocked, prove whether each
recorded blocker is still true.

1. Read the ticket/epic blocker metadata (`blocked_at`, `blocked_by`, `blocked_reason`,
   `blocked_context`) plus the event that created the blocker.
2. Translate the blocker into concrete source-of-truth checks. Examples:
   - manual Render worker redeploy -> Render service/deploy status and deployed image/commit;
   - external repo deploy -> target branch commit containment, deployment logs, health endpoint;
   - Prefect deploy/schedule availability -> Prefect API deployment/work-pool state;
   - data/backfill availability -> read-only database query or flow-run evidence;
   - third-party outage/rate limit -> provider status/log/API evidence.
3. Run those checks directly against the authoritative system. A stale blocker flag, a human note,
   or the absence of a recent failure is not enough; include reproducible command/query output.
4. If **all** blocking conditions are resolved:
   - record the resolution evidence in the verification report;
   - clear or supersede stale blocker metadata using the ticket tool's supported blocker fields;
   - continue with normal activation-boundary and evidence collection in this same run.
5. If any blocking condition is still active:
   - verdict is `BLOCKED` for that scope, not `FAIL` and not a silent skip;
   - leave the lifecycle status unchanged (`to_verify_staging`, `to_verify_prod`, etc.);
   - update/preserve blocker metadata with the ground-truth evidence and the exact next condition
     to re-check;
   - do not promote, complete, or run deferred cleanup.

Ground-truth blocker checks must remain read-only except for the bounded on-demand canary/shadow run exception in §Boundaries. Do not perform a missing deploy, backfill, unbounded flow trigger, schedule change, or external manual action yourself unless another skill explicitly owns that step.

### 4. Determine activation boundary

Do not use naive wall-clock lookback when a commit boundary is available.

- Production: commit landed on `origin/main`.
- Staging: commit landed on `origin/staging`.
- Epic/milestone staging: use the latest included milestone step commit on the staging target and
  the deploy completion time from `/auto-deploy <EPIC_ID> staging`.
- Projects that pull code from git at runtime: activation may be the first run after git land;
  measure feature fill rates from the first post-land evidence row, not just merge time.
- If §3 cleared a blocker that delayed activation (for example a manual worker redeploy or an
  external service release), use the later of the code-deploy boundary and blocker-resolution
  evidence as the activation boundary for post-activation checks.

### 5a. Deployment precondition (check before grading runtime-evidence rows)

Before grading any evidence item that depends on runtime output from a deployed object (Prefect
deployment/flow, scheduler, worker, supervisor-managed flow, webhook, canary, on-demand
deployment, cron, queue consumer), confirm the producing object is actually live in the target
environment:

1. the producing deployment/object is **registered** in the target env (e.g.
   `prefect deployment ls` against the env's API, the cron is installed, the worker is up); and
2. for **on-demand / non-scheduled** deployments, either at least **one run exists after the activation
   boundary** or the verifier triggers the exact bounded canary/shadow run allowed by §Boundaries.
   A registered-but-never-triggered on-demand flow produces no rows on its own.

If the producing object is absent, the feature is **not deployed yet**. If an on-demand object has
never run post-activation and the bounded-run exception does not apply, do not grade its runtime
rows as "no data yet / wait" — that is a deploy-prerequisite gap. Stop collecting runtime evidence
for that scope and return `BLOCKED` (§8) with the exact unblock action. Common cause: an **epic
step** lands at `merged`, but its milestone staging deploy is owned by `/milestone-flow` and has not
run — so `prefect deploy` + trigger never happened. Standalone `/ticket-verify` of such a step is
premature; route to `/milestone-flow <EPIC_ID> <MILESTONE>` unless the already-registered bounded
on-demand canary/shadow exception applies.

Be precise about provenance: rows written by a **different** deployment (e.g. an M1 fixture
canary) are not evidence that **this** ticket's flow ran. Confirm the rows were produced by the
deployment under verification (matching deployment/run id, scraper id, or source marker) before
crediting them.

### 5. Collect evidence

Run **every** Verification Evidence item listed for the environment being verified (staging items
for staging, prod items for prod) — execute each item's query/command and compare against its
expected good output. Then supplement with read-only checks until the report proves the feature
and its edge cases work, not just one happy path:

- affected flows/jobs since activation;
- service logs since activation;
- database state and data quality using read-only queries;
- feature-specific success-path logs or rows;
- every edge case named in source, plan, build todos, review notes, bug hypotheses, and acceptance
  criteria;
- negative/regression checks that would have failed before the fix when applicable;
- bug hypothesis re-evaluation when investigation artifacts contain confirmed hypotheses.

For pollers, observers, schedulers, queue consumers, webhooks, scrapers, supervisor flows, or
any repeated writer that persists data, supplement the contract with storage-amplification
checks even if the deployment guide omitted them:

- compute observed rows/run and extrapolated rows/day, bytes/day, and index/WAL impact from
  the activation window;
- compare actual growth against the plan/deployment-guide volume budget;
- prove repeated unchanged source data is deduped or change-gated across runs, not merely
  unique within a fresh fetch/run id;
- distinguish canonical entities from append-only observations, snapshots, and logs;
- verify retention/TTL/partitioning exists for any intentional per-run history.

Never treat "rows exist" as PASS for a repeated writer if polling frequency is creating
redundant durable data. "Lossless" is not a waiver to save the same payload every interval.

Every claim must include a reproducible command/query, expected good output, actual observed
output, and bad-output interpretation. Record, per evidence item, whether it passed, failed, or
had no post-activation data yet. A single successful happy-path run is never sufficient evidence
for PASS when edge cases are in scope.

If you need intermediate files, put them in a single run-scoped scratch directory such as:

```text
.context/ticket-verify/<scope>-<env>-<YYYYMMDDTHHMMSSZ>/
```

Do not scatter verification files directly in `.context`. Before cleanup, fold the relevant
contents into the `verification_evidence` artifact: exact commands/queries, compact outputs,
summaries of long logs, artifact IDs/URLs, and the final verdict. The autodev artifact must be
self-contained enough that the local scratch directory can be deleted without losing the
verification record.

For any evidence item that verifies a visible surface (UI, rendered document, email preview,
chart, public page, browser-visible error/success state), open the actual target in a real browser
and save a screenshot only as temporary scratch. If the surface is behind authentication, get the
login method and credentials from the repo-specific `.claude/environments/{env}.md` (see §2) and
authenticate before capture; read secrets from the source it names (e.g. a 1Password-mounted env
file) at runtime and never print, echo, or persist them. Only if that env file is missing or does
not document a working login is a missing session a real capture blocker. If screenshots are material to the verdict,
persist the durable evidence in the autodev artifact (for example: the target URL, exact browser
actions, visible text/state asserted, and a concise screenshot description; or a durable uploaded
image URL if the workflow provides one). Do **not** leave screenshot files in `.context` after the
artifact is persisted unless the user explicitly asked to keep them. If browser capture is
impossible, mark the row `BLOCKED`/`FAIL` as appropriate and include the exact capture blocker.

### 6. Record the fixed Verification Evidence artifact

The collected evidence is a first-class artifact, separate from the `deployment_guide` contract:

- Artifact type: `verification_evidence`.
- Title: `Staging verification evidence — <scope>` or `Production verification evidence — <scope>`.
- Metadata must include at least:
  - `environment`: `staging` or `production`;
  - `verdict`: `PASS`, `FAIL`, `NEEDS_MORE_TIME`, or `BLOCKED`;
  - `activation_boundary`: the boundary from §4;
  - `evidence_count`: total executed rows/checks;
  - `edge_case_count`: total explicit edge cases checked;
  - `screenshot_count`: total screenshots captured;
  - `scope`: ticket id or epic/milestone gate id;
  - `generated_by`: `/ticket-verify`;
  - **staging runs only** — co-tenancy attribution (staging is shared, and this ticket's
    evidence was collected with other tickets' code present):
    - `staging_head_sha`: `git rev-parse origin/staging` at collection time;
    - `co_staged_tickets`: ticket IDs found in `git log origin/main..origin/staging`
      subjects (excluding this scope). `/ticket-promote` compares this against the set it
      actually promotes; a later prod regression can then distinguish "PASS was never
      attributable to this ticket alone" from a genuine environment difference.

Content must be the durable proof package: activation boundary, every evidence row with command or
query, expected good output, actual observed output, bad-output interpretation, screenshot paths,
edge-case coverage, failures/blockers, and final verdict. It should be strong enough that a future
reader does not need to re-think whether the problem is solved.

Staging evidence is optional in the lifecycle: absence of a staging `verification_evidence`
artifact must not by itself block production verification. If this command verifies staging,
however, write the staging evidence artifact. Production evidence is mandatory: a production run
must create/update the production `verification_evidence` artifact for every selected scope, and a
production PASS is invalid until that artifact exists and contains all executed evidence and edge
case coverage.

For standalone tickets, write the artifact on the ticket with `create_artifact` (or update the
latest matching environment artifact when repeating the same verification).

For explicit epic/milestone verification, evidence must be persisted in **all applicable scopes**:

1. **Canonical milestone/final gate artifact on the epic** — create/update a full
   `verification_evidence` epic artifact for the exact gate scope, for example
   `Staging milestone gate evidence — E0010/M2` or `Production final gate evidence — E0010`.
   This is the complete, self-contained proof package and is the source of truth for the
   milestone/final gate verdict. Metadata must include `scope`, `environment`, `verdict`,
   `activation_boundary`, `evidence_count`, `edge_case_count`, `screenshot_count`,
   `generated_by`, `step_ticket_ids`, and an `artifact_family` such as
   `epic-milestone-verification`. If this canonical artifact cannot be written, do not update
   milestone/step/epic statuses; production verdict is `BLOCKED`, and staging verdict must be
   reported without advancing statuses.
2. **Full ticket-level verification artifact on every included step ticket** — create/update a
   `verification_evidence` ticket artifact for each step ticket in the requested scope. This is
   more than a bare backlink: include the step's activation boundary, the evidence rows relevant
   to that step/contract edge, actual observed output summaries, verdict, status action, and a
   pointer to the canonical epic gate artifact. Shared cross-step evidence may be summarized instead
   of duplicated verbatim, but each step ticket page must be understandable without searching the
   epic first. Metadata must include `parent_scope`, `canonical_evidence_artifact_id`,
   `environment`, `verdict`, `step_ticket_id`, `repo`, `generated_by`, and
   `artifact_family=epic-step-verification`. If these ticket artifacts cannot be written, leave
   the corresponding step ticket statuses unchanged and report exactly which ticket artifact write
   failed.
3. **Compact epic-level verification summary** — create/update a separate concise epic artifact,
   for example `Epic verification summary — E0010`, after writing the gate and ticket artifacts.
   It should roll up all verified milestone/final gates, verdicts, canonical gate artifact ids,
   step ticket artifact ids, step statuses, remaining risks, and next action. This summary is not
   a substitute for the canonical gate artifact; it is the epic dashboard/readability index. Use
   `artifact_family=epic-verification-summary` in metadata and update the existing summary artifact
   if one exists.

### 7. Epic/milestone aggregation

In `--epic` mode, produce one gate verdict for the requested scope:

- include every evidence row from the milestone gate package or final epic deployment guide;
- for a non-first staging milestone, include an impact-based regression subset from earlier
  passed milestone gates so later work cannot silently break already-verified epic behavior;
- map each failed row to the most likely step ticket(s) and contract edge(s);
- prove every included step commit is present on the expected branch (`origin/staging` for
  staging, `origin/main` for production);
- do not pass the gate just because individual step tickets look healthy; the milestone's
  acceptance criteria and cross-step contracts must pass as a unit.

### 8. Verdict

The deployment_guide evidence contract is the gate — verdict is determined by the env's evidence
items:

- `PASS` — **every** evidence item for this environment passed, and no related failures surfaced;
- `PASS (contract-missing)` — every derived evidence item passed, but the deployment_guide
  evidence contract was missing/`TBD` and the items were derived from source/plan acceptance
  criteria. This is the **best possible verdict** for such a scope. On staging it sets
  `staging_verified` but does **not** auto-invoke `/ticket-promote`: promotion requires an
  explicit human go-ahead, or a regenerated FINALIZED deployment guide followed by a re-run
  that grades the real contract;
- `FAIL` — any evidence item shows broken behavior or expected-but-missing activity;
- `NEEDS_MORE_TIME` — the feature **is deployed and running** (its producing deployment is
  registered in the target env and, for scheduled/continuous flows, executing), but one or more
  evidence items have no post-activation data yet (and none have failed). Use this **only** when
  passive waiting will actually produce the missing evidence;
- `BLOCKED` — at least one of: (a) a selected ticket/gate had blocker metadata and §3 proved a
  blocking condition is still active; or (b) the **deployment precondition (§5a) is unmet** — a
  required producing deployment is not registered in the target environment, or an
  on-demand/non-scheduled deployment has never run since the activation boundary and the bounded
  on-demand canary/shadow run exception does not apply or failed to start. Case (b) is a
  deploy-prerequisite gap, **not** `NEEDS_MORE_TIME`: waiting alone will never produce evidence
  because nothing is scheduled to run. The reason must name the exact unblock action (run the
  milestone deploy via `/milestone-flow`, or `prefect deploy` + trigger the deployment). This is an
  explicit outcome, never an omitted row.

Never report `NEEDS_MORE_TIME` for a feature whose producing deployment is absent or has never
run — that misrepresents "nobody deployed/triggered it" as "wait for data." If §5a could not
confirm the producing object is live, the verdict is `BLOCKED`, not `NEEDS_MORE_TIME`.

**NEEDS_MORE_TIME cap.** `NEEDS_MORE_TIME` is not an indefinitely repeatable verdict. Record in
the scope's `verification_evidence` artifact metadata a `needs_more_time_count` and a
`needs_more_time_first_seen` timestamp, incrementing the counter on every `NEEDS_MORE_TIME`
run. After **3 NEEDS_MORE_TIME runs or 24 hours** since first seen (whichever comes first),
escalate: the verdict becomes `FAIL` — or `BLOCKED` when the producing deployment/object is
absent or has never run — and the report must name the exact evidence row(s) that never
produced post-activation data. Waiting that long without data means the evidence is not
coming on its own.

**Moving-target guard (scheduled-event waits).** When `NEEDS_MORE_TIME` waits on a scheduled event
(e.g. "the next due poll"), the re-run MUST verify the awaited condition actually *arrives*, not
just that time passed. Record the awaited timestamp (`scheduled_for` / `next_run_at` / due time)
and compare it across rechecks. If it keeps advancing faster than it is consumed — a producer
re-anchoring the schedule outruns the consumer, so the item is never actually due — that is a
**structural design flaw, not a timing wait**: two consecutive rechecks where the awaited condition
never became true (the due time moved forward again) ⇒ verdict `BLOCKED` with a design-flaw reason,
never another `NEEDS_MORE_TIME`. Waiting longer cannot fix a due time that recedes on every producer
tick (see review reference `data-integrity.md` §4b).

When the evidence contract was missing/`TBD` and you fell back to acceptance criteria, say so in
the report so the gap is visible rather than silently passing.

### 9. Status and promotion

Standalone ticket mode:

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | write optional staging `verification_evidence`; set status `staging_verified` (green "Ready for prod" flag), then apply the **auto-promotion gate (§9b)**: call `/ticket-promote <ID>` only if the gate passes and neither `--no-promote` nor a batch/epic hold applies; otherwise rest at `staging_verified` and report exactly which gate condition held promotion |
| staging | PASS (contract-missing) | write staging `verification_evidence` flagging the missing contract; set status `staging_verified`; do **not** call `/ticket-promote` — require a human go-ahead or a regenerated FINALIZED deployment guide first |
| staging | FAIL | write staging `verification_evidence`; status `verify_staging_failed` |
| staging | NEEDS_MORE_TIME | leave status unchanged |
| staging | BLOCKED | write/update staging `verification_evidence` with blocker ground-truth evidence; leave status unchanged; update/preserve blocker metadata |
| production | PASS | write mandatory production `verification_evidence`; materialize follow-ups (§10a); set status `completed` only after materialization succeeds; then run any same-cycle cleanup (§10) |
| production | FAIL | write mandatory production `verification_evidence`; status `verify_prod_failed` |
| production | NEEDS_MORE_TIME | leave status unchanged |
| production | BLOCKED | write/update mandatory production `verification_evidence` with blocker ground-truth evidence; leave status unchanged; update/preserve blocker metadata |

`staging_verified` is the resting "passed staging, ready for prod" state — the green-flag
counterpart of `verify_staging_failed`. Set it on every staging PASS, **including** tickets that
must NOT be promoted individually (e.g. ones held for a batched epic promotion, or a ticket whose
own artifacts forbid a solo cherry-pick): those rest in `staging_verified` rather than advancing.

Epic/milestone mode:

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | write canonical staging milestone gate `verification_evidence` on the epic; write full per-step ticket `verification_evidence` artifacts; update the compact epic verification summary; mark the milestone staging gate passed; set included step tickets to `staging_verified`/ready-for-parent-promotion when the lifecycle supports it; do **not** call `/ticket-promote` |
| staging | FAIL | write canonical staging gate `verification_evidence` plus per-step ticket artifacts for every included step, with failed evidence-to-step mapping on affected steps; update the epic summary; leave the milestone unpassed for `/epic-flow` fix loop |
| staging | NEEDS_MORE_TIME | write/update canonical staging gate `verification_evidence` plus per-step ticket artifacts for collected evidence; update the epic summary; leave milestone and step statuses unchanged |
| staging | BLOCKED | write/update canonical staging gate `verification_evidence` plus per-step ticket artifacts for every included step, with blocker ground-truth evidence on affected steps; update the epic summary; leave milestone and step statuses unchanged |
| production | PASS | write mandatory final production gate `verification_evidence` on the epic; write full per-step ticket `verification_evidence` artifacts; update the compact epic verification summary; mark included step tickets `completed` when their parent epic owns completion; mark epic complete only if all milestones are done |
| production | FAIL | write mandatory production gate `verification_evidence` plus per-step ticket artifacts for every included step; update the epic summary; mark epic/affected step production verification failed if supported, otherwise record blocker/failure metadata |
| production | NEEDS_MORE_TIME | write/update mandatory production gate `verification_evidence` plus per-step ticket artifacts for collected evidence; update the epic summary; leave statuses unchanged |
| production | BLOCKED | write/update mandatory production gate `verification_evidence` plus per-step ticket artifacts for every included step, with blocker ground-truth evidence on affected steps; update the epic summary; leave statuses unchanged; update/preserve blocker metadata |

When staging PASS then calls `/ticket-promote` in standalone mode, the status advances from
`staging_verified` to `to_verify_prod` once the promotion lands on `main` **and** the
production deploy steps complete (`/ticket-promote` runs both, then invokes
`/ticket-verify production <ID>`).

### 9a. Persist report before status changes and clean scratch

For every terminal verdict (`PASS`, `FAIL`, `BLOCKED`) and for `NEEDS_MORE_TIME` when evidence was
collected, first create or update all required evidence artifacts, then update ticket/epic status.
For epic/milestone gates the required order is: canonical gate artifact on the epic -> per-step
ticket evidence artifacts -> compact epic summary -> status changes. The `verification_evidence`
artifacts are the source of truth; local files are not.

After the autodev artifact write succeeds:

1. Verify the artifact ID is returned and the artifact content includes all evidence needed to
   understand the verdict without reading local files.
2. Delete the run-scoped `.context/ticket-verify/<...>/` scratch directory and any one-off
   `.context` files created by the verification run.
3. If cleanup fails, retry once. If it still fails, mention the leftover path in the final output
   with a cleanup command. Do not present leftover `.context` files as canonical evidence.

Do not delete pre-existing user/project `.context` files that this verification run did not
create.

### 9b. Auto-promotion gate (standalone staging PASS only)

A staging PASS is an LLM-graded verdict, and auto-invoking `/ticket-promote` chains it
straight into a production mutation (land on main + prod deploy steps) with no human in
between. That chain is earned only by low-risk, fully-graded scopes. Auto-invoke
`/ticket-promote <ID>` only when ALL of these hold:

1. **Contract graded, not derived** — the deployment_guide evidence contract was
   `FINALIZED` and every row for staging was executed (a `PASS (contract-missing)` never
   auto-promotes; that rule already exists in §8).
2. **Fresh evidence** — every evidence row passed on post-activation data; no row passed
   only on pre-existing/ambiguous-provenance data (§5a provenance).
3. **Low-risk diff** — the ticket's landed diff contains **no schema/migration, deploy-config,
   or auth/security/payment category**. Detect with the same path checks `/ticket-promote`'s
   schema gate and `landing-policy.md` use (`migrations/`, `alembic/`, `prisma/`, Atlas
   model/plan paths, deployment YAML/env config, auth paths). These are exactly the classes
   landing-policy routes staging-first *because* they are risky — the same risk reasoning
   applies to leaving staging.

If any condition fails: leave the ticket at `staging_verified` (the dashboard already shows
it as "Ready for prod"), and report which condition held promotion plus the exact next
command (`/ticket-promote <ID>`). This costs nothing on the common low-risk case and puts
the one human gate exactly where a false PASS would be amplified into production.

### 9c. Capture failure knowledge (FAIL verdicts, staging or production)

A FAIL verdict is the most informative event this system produces — a confident
plan/build/review met reality and lost. Do not let it rest only in the ticket: after
writing the `verification_evidence` artifact and setting the failed status, persist the
lesson to memory (same duplicate-check-then-store pattern as `/review` step 7):

```
# 1. Check for duplicates
mcp__autodev-memory__search(queries=[{"keywords": ["<feature area>"], "text": "<failure summary>"}], project=PROJECT)

# 2. If no duplicate, store
mcp__autodev-memory__create_entry(
  project=PROJECT,
  title="Verify failure: <1-sentence what broke>",
  content="Ticket <ID> (<env>). Evidence row that failed: <command + expected vs observed>.
           Cause (if known): <root cause or 'unknown — see verification_evidence <artifact id>'>.
           What planning/build should have done differently: <lesson>.",
  entry_type="gotcha",
  summary="<1-sentence summary>",
  tags=["verification", "<area>"],
  source="captured",
  caller_context={"skill": "ticket-verify", "reason": "verification FAIL — feed future planning priors",
                  "action_rationale": "New entry — no existing entry covers this failure",
                  "trigger": "verify FAIL <env>"}
)
```

This closes the loop that `/auto-plan`'s "Related past failures" prior search reads from.
If the MCP tool is unavailable, skip silently.

### 10. Deferred post-verification cleanup (production PASS only)

Some tickets carry a cleanup action that must run only once the fix is confirmed live in
production — never before. This is the single mutation ticket-verify may perform, and only after
a `PASS` verdict has been recorded for that ticket. Like the bounded canary trigger, it is
executed by the orchestrator itself — never delegated to a (read-only) verifier agent.

The generic contract is a **`deferred_cleanup` artifact**. (The old `flow-run-cleanup` artifact
name is retired; flow-run deletion is now just a `deferred_cleanup` with
`cleanup_kind="flow_run_cleanup"`.)

```json
{
  "cleanup_command": "<command; run with --artifact <temp-file> --fix-time <activation boundary §4> --execute plus any documented non-interactive flags (e.g. --yes)>",
  "scope_manifest": ["<exactly what the command may touch: tables, deployments, paths, ids>"],
  "reversibility": "reversible | destructive (missing/unknown => destructive)",
  "cleanup_kind": "<e.g. flow_run_cleanup, deployment_retirement, table_drop>",
  "trigger_condition": {"check_command": "<read-only; exit 0 = trigger true, non-zero = not yet>", "description": "<when this becomes safe>"},
  "soak_window": "<duration the effect must soak before final verification>",
  "evidence_contract": [{"command": "<read-only check>", "good": "<expected>", "bad-interpretation": "<what a bad output means>"}],
  "revert_ref": "<commit/artifact to restore>", "revert_command": "<optional explicit revert>"
}
```

Execution rules:

1. Fetch the artifact and write its JSON body to a temp file under the run-scoped scratch
   directory from §5; delete it as part of §9a cleanup.
2. Run `cleanup_command`, appending `--artifact <temp-file>`, `--fix-time <activation boundary
   from §4>`, `--execute`, and any documented non-interactive flags.
3. **Scope enforcement:** diff the command's dry-run/reported effects against `scope_manifest`.
   Anything out of scope → ABORT, capture the diff into `blocked_context`, and do not re-run.
4. Fold the command's reported counts into the verdict output.

**Same-cycle path:** no `trigger_condition` and `reversibility="reversible"` → the orchestrator
runs the cleanup immediately after the production PASS is recorded (preserving prior behavior).
Anything else is deferred to a cleanup ticket (§10a). A ticket without a `deferred_cleanup`
artifact has no cleanup step, and a non-PASS verdict never triggers one.

### 10a. Materialize follow-ups (production PASS only)

Every structured decommission/retirement follow-up identified during verification MUST become a
**child cleanup ticket**, not prose. Prose-only follow-ups in learning_reports are a violation.
§10a runs BEFORE the parent is set `completed`; if materialization fails, the parent stays
`to_verify_prod` with blocker metadata naming the materialization failure.

For each follow-up:

1. Dedup: skip if a child ticket already exists for (parent, `cleanup_kind`).
2. `create_ticket` in the parent's project, repo = the runtime surface being cleaned, tags
   `{"cleanup": "true"}`, related → parent.
3. Attach a `deferred_cleanup` artifact (schema above) to the child ticket.

Cleanup mini-lifecycle (existing statuses only; see `references/ticket-lifecycle.md`):

- Created at `backlog` with `blocked_by="trigger_condition"` (`blocked_context` holds the
  `check_command`); destructive cleanups instead/additionally carry `blocked_by="approval"`.
- An explicit `/ticket-verify production <cleanup-ticket>` evaluates the trigger. Trigger false:
  the §3 blocker-metadata refresh is the **only** permitted write.
- Trigger true + reversible: clear blocker → `in_progress` → run `cleanup_command` with scope
  enforcement (§10) → `to_verify_prod` with `blocked_by="soak"`,
  `blocked_context={"soak_until": ...}`.
- Destructive: `blocked_by="approval"` is an ABSOLUTE no-run gate regardless of trigger state.
  Approval = an operator clears the blocker (optionally recording
  `blocked_context.approved_by`).
- Post-soak verify grades the artifact's `evidence_contract` — it IS the FINALIZED contract
  (§2) → `completed` | `verify_prod_failed` (revert = `revert_ref`/`revert_command`). A verify
  before `soak_until` must refuse completion (`NEEDS_MORE_TIME`).

Periodic sweep/supervisor adoption of due cleanup tickets is a contract-consumer concern
(ts-prefect follow-up); this skill guarantees explicit-invocation evaluation only.

## Output

Report one table for all selected tickets or gate scopes:

```text
Scope            Env      Verdict          Action
F0123            staging  PASS             artifact <id>; scratch cleaned; promoted -> to_verify_prod
B0042            staging  NEEDS_MORE_TIME  left to_verify_staging
F0130            prod     BLOCKED          blocker still true; left to_verify_prod
E0007/M2         staging  PASS             gate artifact <id>; step artifacts F1:<id>, F2:<id>; epic summary <id>; held for epic promotion
E0007/final      prod     PASS             final gate artifact <id>; per-step evidence artifacts <ids>; epic summary <id>; epic completed
```

Also include any cleanup exception:

```text
Scratch cleanup: FAILED for .context/ticket-verify/F0123-staging-...; run `rm -rf ...`
```

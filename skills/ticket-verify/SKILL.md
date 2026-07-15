---
name: ticket-verify
description: >-
  Timer-friendly evidence collection for tickets and epic/milestone gates in staging or
  production. The default queue includes pending verification, failed verification, production
  cleanup holders, and pending epic gates. Read-only while verifying; standalone staging PASS
  promotes unless disabled.
max_turns: 200
---

# Ticket Verify

Follow `../references/execution-economy.md`; coalescing execution never coalesces lifecycle truth
or waives an evidence row.

Verify tickets, or an explicit epic/milestone gate, after code has landed and deployment has
completed. Use this instead of legacy `/auto-verify`.

## Usage

```text
/ticket-verify staging              # to_verify_staging + verify_staging_failed tickets, plus pending epic gates
/ticket-verify production           # to_verify_prod + verify_prod_failed tickets, plus pending epic gates
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
  A triggered canary is not free to leave behind: **any canary/shadow run this verification triggers must be cleaned up after it is graded.** That includes the canary flow run itself, any temporary deployment/schedule registered to produce it, and any throwaway rows/records it wrote purely to generate evidence. Real production data the canary happened to process is left alone — only the artifacts that exist *because* the canary ran are removed. Do the cleanup through the §10 `deferred_cleanup` path (record it as a `deferred_cleanup` on the item and run it once the PASS is recorded), or inline immediately after grading when the canary's output is trivially and fully reversible; either way record what was removed in the evidence artifact. A canary run left registered/running after verification (e.g. an orphaned Prefect deployment or flow run kept alive only for the check) is a defect, not a PASS.
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
- In `--epic`/`--milestone` mode — **including epics auto-included by the default queue (§1)** —
  do **not** auto-promote. The parent `/epic-flow` controls milestone progression and production
  promotion.
- On production PASS, set standalone ticket status to `completed`. In epic mode, update the
  parent epic/milestone gate and included step tickets according to the epic lifecycle.
- On failure, set `verify_staging_failed` or `verify_prod_failed` on the standalone ticket, or
  record the failed epic/milestone gate and failed evidence rows for `/epic-flow`'s fix loop.
- Blocker metadata is **not** a skip signal. If a selected ticket/gate has an active blocker,
  first re-check the recorded blocking condition against source-of-truth systems. If the blocker
  has cleared, continue verification in the same run.
- Verification stays read-only except for two narrow cases: (1) the bounded on-demand
  canary/shadow run exception above, and (2) on **production PASS**, a ticket may carry a deferred
  post-verification cleanup that runs only after the PASS verdict is recorded. Bounded
  noncritical cleanup may run automatically even when irreversible; critical/unknown destructive
  cleanup remains approval-gated (see §10).

## Process

### 1. Select scope

If explicit standalone ticket IDs are provided, load only those tickets. For default-queue mode,
`--epic`/`--milestone` mode, or any run with multiple scopes, load
`references/verify-scope-dispatch.md`. Epic/milestone runs must also load
`references/verify-epic-gates.md`.

Do **not** skip tickets merely because they have `blocked_at`, `blocked_by`, `blocked_reason`, or
`blocked_context` metadata. Blocked candidates stay in scope and go through the blocker re-check
in §3.

### 1a. Parallel verifier dispatch

Single-scope runs execute inline. Multi-scope/queue runs load and follow the parallel-dispatch
section of `references/verify-scope-dispatch.md`.

### 2. Load context

For each standalone ticket, or for the epic/milestone gate as a unit:

- begin with `detail="light", include_events=false` and cache the response's artifact IDs and
  `context_version` for the entire verification run;
- fetch `detail="full"` only for the artifact types the contract needs — normally `source`,
  `deployment_guide`, and the latest environment-matching `verification_evidence`; add `plan`,
  review notes, or milestone acceptance criteria only when the source/contract refers to them;
- do not call `get_ticket` again when `context_version` is unchanged; use `known_version` with the
  bulk context API when refreshing multiple tickets;
- read the **`deployment_guide` artifact** — its **Verification Evidence** section is the
  contract you grade against. Each row is one evidence item: a reproducible query/command, an
  expected good output, and a bad-output interpretation, listed per environment (staging / prod).
  Also read its **Activation boundary**. If the artifact is missing or its evidence rows are still
  `TBD`/empty, fall back to deriving evidence from source + plan acceptance criteria, and flag in
  the report that the work shipped without a finalized evidence contract — the best staging
  verdict such a scope can earn is `PASS (contract-missing)` (§8), which does not auto-promote.
  Exception — items in `prod_verified_needs_cleanup` (or legacy tickets tagged
  `cleanup=true`): the item's `deferred_cleanup.evidence_contract` IS the FINALIZED cleanup
  contract (§10/§10a); the contract-missing verdict cap does not apply and no
  `deployment_guide` is synthesized for cleanup-only verification;
- find PR/commit/landing branch from ticket tags and loaded artifacts first; request event history
  only when those bounded sources cannot establish the activation boundary;
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

### 5b. Visible-surface (UI) acceptance is graded on STAGING, never production

Load and follow `references/verify-visible-surfaces.md` only when acceptance includes a UI,
rendered document, email preview, chart, public page, or other browser-visible state.

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

Visible-surface evidence uses the screenshot and authentication rules in
`references/verify-visible-surfaces.md`.

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
latest matching environment artifact when repeating the same verdict). If the verdict changed,
create a new correctly titled artifact first, then mark the prior artifact `superseded` and link it
to the new artifact ID. Never overwrite a verdict-bearing title with contradictory metadata.

For explicit epic/milestone verification, evidence must be persisted across all applicable
scopes (canonical gate artifact on the epic, full per-step ticket artifacts, and a compact epic
summary). This is **only** relevant in `--epic`/`--milestone` mode — see the "§6 (epic/milestone)"
section of `references/verify-epic-gates.md`.

### 7. Epic/milestone aggregation

Epic/milestone aggregation produces one gate verdict for the requested scope. This is **only**
relevant in `--epic`/`--milestone` mode — see the "§7" section of
`references/verify-epic-gates.md`.

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
  on-demand canary/shadow run exception does not apply or failed to start; or (c) a UI/visible-surface
  scope's change is not deployed to **staging** (§5b), so its rendering cannot be graded — reason:
  **needs to be deployed to staging as well, not only main**. Cases (b) and (c) are
  deploy-prerequisite gaps, **not** `NEEDS_MORE_TIME`: waiting alone will never produce evidence
  because nothing is scheduled to run. The reason must name the exact unblock action (run the
  milestone deploy via `/milestone-flow`; `prefect deploy` + trigger the deployment; or land/deploy the
  UI change to staging then `/ticket-verify staging <scope>`). This is an explicit outcome, never an
  omitted row.

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

After computing the verdict, load `references/verify-lifecycle-actions.md` and apply only the row
for the current environment/mode. Epic/milestone mode instead uses the lifecycle section of
`references/verify-epic-gates.md`.

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

Load `references/verify-staging-promotion.md` only for a standalone staging PASS when
`--no-promote` and batch/epic holds do not already prohibit promotion.

### 9c. Capture failure knowledge (FAIL verdicts, staging or production)

Load `references/verify-failure-capture.md` only after a staging or production `FAIL`.

### 10 / 10a. Deferred post-verification cleanup (production PASS only)

Load `references/verify-deferred-cleanup.md` **only when a `deferred_cleanup` artifact exists**
on the ticket/epic being verified. It defines §10 (the `deferred_cleanup` contract, dry-run/scope
enforcement, same-cycle path) and §10a (the `prod_verified_needs_cleanup` holding status and
cleanup-holding lifecycle). A ticket/epic without a `deferred_cleanup` artifact has no cleanup
step, and a non-PASS verdict never triggers one.

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

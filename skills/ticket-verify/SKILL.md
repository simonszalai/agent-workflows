---
name: ticket-verify
description: >-
  Timer-friendly evidence collection for tickets and epic/milestone gates in staging or
  production. The default queue includes pending verification, failed verification, production
  cleanup holders, and pending epic gates. Read-only while verifying; standalone staging PASS
  promotes unless disabled.
max_turns: 30
---

# Ticket Verify

Verify tickets, or an explicit epic/milestone gate, after code has landed and deployment has
completed. Evidence collection never coalesces lifecycle truth or waives an evidence row.

## Usage

```text
/ticket-verify staging              # to_verify_staging + verify_staging_failed tickets, plus pending epic gates
/ticket-verify production           # to_verify_prod + verify_prod_failed tickets, plus pending epic gates
/ticket-verify staging F0123 B0042
/ticket-verify production F0123 --lookback 24h
/ticket-verify staging --no-promote # report staging PASS but do not promote
/ticket-verify staging F0123 --produce-evidence # run one bounded idle-staging producer if needed

/ticket-verify staging --epic E0007 --milestone M2 --no-promote
/ticket-verify production --epic E0007

/ticket-verify --scheduled            # unattended nightly: full default queue, staging AND production, verify-only
/ticket-verify staging --scheduled    # unattended, one environment
```

First argument must be `staging`, `prod`, or `production` — except with `--scheduled`, where
omitting the environment means both (staging first, then production).

`--produce-evidence` is staging-only and must be explicitly supplied by the user or a
human-authorized deploying workflow. It does not authorize production flow triggers.

## Boundaries

- Use only MCP tools injected into the current agent session. Never read a Codex/Conductor/browser
  Keychain or credential store, reuse browser/application cookies as bearer tokens, or construct a
  direct HTTP/custom MCP client to compensate for a stale tool catalog or missing authentication.
  `redacted-exec`, in-memory handling, and user-imported browser cookies do not permit this. If the
  required MCP tool is absent or unauthenticated, record the scope `BLOCKED` with the supported
  login/reconnect + fresh-session remedy; do not attempt credential recovery. See
  `../sensitive-vault-access/SKILL.md` § Client-managed MCP and OAuth credentials.
- Verification evidence collection is read-only by default: no data mutation, no flow triggers,
  no deploys. Exception: if the scope's evidence contract explicitly requires a bounded on-demand
  canary/shadow run, or staging `--produce-evidence` resolves one unambiguous bounded producer
  (§3a), and the deployment is already registered with safe parameters (e.g. `enqueue_mode=off`,
  capped `max_items`, no schedule change), trigger exactly that run and grade its durable outputs.
  Record command, run id, parameters, and terminal state in the evidence artifact. Never use this
  exception for backfills, unbounded enqueue, schedule creation, deploys, migrations, or
  external-service mutations.
- **Successful canary/shadow runs and their temporary artifacts must be cleaned up after
  grading**: the canary flow run itself, any temporary deployment/schedule registered to produce
  it, and throwaway rows written purely for evidence. Real data the canary happened to process is
  left alone. In staging, clean up inline before recording PASS; in production use the deferred
  cleanup path (§10) unless trivially reversible. A canary left registered or running after
  verification is a defect, not a PASS. On terminal failure, preserve the failed run history and
  logs for diagnosis and stop.
- Local `.context` files are temporary scratch only. The canonical verification report is
  persisted to autodev as a ticket or epic artifact; after it is written, delete the run's
  scratch files.
- On standalone staging PASS, promote **only when the auto-promotion gate (§9b) passes**.
  Higher-risk scopes rest at `staging_verified` for an explicit human promotion. Promotion
  (landing on main + production deploy steps) is a separate step, not evidence collection.
- Spawned verifier agents are strictly read-only. The two narrow mutations this skill allows —
  the bounded canary trigger and deferred post-PASS cleanup (§10) — are executed by the
  orchestrator itself, never a spawned agent.
- In `--epic`/`--milestone` mode — including epics auto-included by the default queue — do
  **not** auto-promote; the epic orchestration owns milestone progression and production
  promotion.
- On production PASS, set standalone ticket status to `completed`. In epic mode, update the
  parent epic/milestone gate and included step tickets per the epic lifecycle.
- On failure, set `verify_staging_failed` or `verify_prod_failed` (or record the failed gate),
  then root-cause it (§9d).
- Blocker metadata is **not** a skip signal: re-check the recorded blocking condition against
  source-of-truth systems first (§3).

## Scheduled mode (`--scheduled`)

Unattended nightly invocation (Hermes `hermes/schedules/nightly-verify-promote.md`). The run
inherits the full unattended contract in `../references/scheduled-run.md` — mutation boundary,
Slack one-line + thread format, `SCHEDULED_RUN_RESULT` ending, `rc_fingerprint` dedup.

- **Verify-only. §9b auto-promotion is SUPPRESSED — unconditionally**, in any mode, for any
  tier. Merging to `main` is a de-facto production deploy for ts-prefect (flows `git_clone` at
  runtime), so a scheduled run never merges or pushes to long-lived branches. A standalone
  staging PASS sets `staging_verified` and reports
  `promotion-ready — prod promotion awaiting Simon` with the exact `/ticket-promote <ID>`
  command; a human runs it.
- **No interactive questions.** Anything needing human input, approval, or an unheld credential
  ends that scope as `BLOCKED` with `blocked_on` naming the exact command or manual action.
- **Strictly read-only.** The canary exception and `--produce-evidence` are NOT available: no
  flow triggers in any environment. Scopes whose contract requires an on-demand producer end
  `BLOCKED` naming the bounded trigger a human should run. §10 deferred cleanup does not execute
  either — a production PASS holding cleanup rests at `prod_verified_needs_cleanup`.
- **Bounded queue.** Cap the default queue explicitly per run (scope limit or lookback window);
  report anything unprocessed as carried-over.
- **Prod DB reads only via `psql-cli prod`** when the project registry exposes a non-sensitive
  read-only production profile. Missing profile is BLOCKED; never substitute a read-write
  credential. Nothing may raise a Touch ID prompt (no `*-sensitive` reads).
- **Slack report to `#autodev-nightly`** (channel ID from `hermes/schedules/schedules.yaml`):
  one summary line, per-scope detail as thread replies; summary ends `all verified` or
  `promotion-ready — prod promotion awaiting Simon`. FAIL/BLOCKED routes to
  `#autodev-incidents` per scheduled-run.md §2; end with the `SCHEDULED_RUN_RESULT` block.

## Process

### 1. Select scope

Explicit ticket IDs load only those tickets. Default-queue mode selects the environment's
pending/failed tickets, production cleanup holders, and pending epic gates. Multi-scope runs may
verify scopes in parallel with read-only verifier agents, one scope each. Do **not** skip tickets
with blocker metadata — they go through §3.

### 2. Load context

Per standalone ticket or epic/milestone gate: start with `detail="light",
include_events=false`, cache artifact IDs and `context_version` for the run; fetch
`detail="full"` only for the artifact types needed — normally `source`, `deployment_guide`, and
the latest environment-matching `verification_evidence`. Read the **`deployment_guide`
Verification Evidence section — it is the contract you grade against**: each row is a
reproducible query/command, expected good output, and bad-output interpretation, per
environment. Also read its Activation boundary. If the contract is missing/`TBD`, derive
evidence from source + plan acceptance criteria and flag it: the best staging verdict is then
`PASS (contract-missing)` (§8), which does not auto-promote unless `tiny_safe` (§2a). For items
in `prod_verified_needs_cleanup`, the `deferred_cleanup.evidence_contract` IS the finalized
contract. Read `.claude/environments/{env}.md` when present.

### 2a. Risk tier (tiny/safe fast path)

Classify the scope's actual diff once per run as `risk_tier: tiny_safe | standard` and record
it with the diff SHA in the evidence artifact. `tiny_safe` requires ALL of: no schema/migration
or backfill; no prompt/LLM change; no auth/security/payment/deploy-config change; no cross-repo
contract; no user-visible multi-step workflow change; clean local tests/review; small, easily
reversible diff. For `tiny_safe`: run every contract (or derived) row once; the edge-case
battery and storage-amplification checks are required only when named or when the diff touches
a repeated writer; `PASS (contract-missing)` counts as `PASS` for §9b when every derived row
passed on fresh post-activation data. Any failed or doubtful condition means `standard`. The
tier never waives §3, §3a, §4a, §5a, or §5b.

### 3. Re-check active blockers from ground truth

Before skipping or reporting a blocked scope, prove each recorded blocker is still true:
translate `blocked_*` metadata into concrete source-of-truth checks (deploy status, commit
containment, Prefect API state, read-only DB query, provider status) and run them. A stale flag
or human note is not evidence. If all conditions resolved: record the evidence, clear the
blocker, continue verification in the same run. If still active: classify with
`staging-autonomy.md` in staging (a live operation/provider recovery with a healthy producer is
`external_wait` — run the deterministic waiter, not `BLOCKED`); verdict `BLOCKED` only when the
required action is human-required or agent-incapable; leave lifecycle status unchanged; update
blocker metadata with the ground-truth evidence and exact next re-check condition. In staging,
return a machine-readable repair packet (authoritative source, exact command when known,
rollback/cleanup, success predicate) so a deploying owner can fix it. Ground-truth checks stay
read-only except the bounded canary exception; never perform the missing deploy, fixture seed,
or manual action yourself.

### 3a. Produce evidence in an intentionally idle staging environment

Only when: staging + `--produce-evidence` + a required row lacks post-activation activity
because its producer is intentionally idle, and waiting cannot change that. Resolve the producer
from the deployment guide; infer a registered deployment only when scope, name, entrypoint, and
safe parameters identify exactly one candidate — ambiguity is `BLOCKED`, never a guessed
trigger.

**Boundedness is a mechanical precondition, not a prose claim.** Inspect the actual parameter
schema and entrypoint selection loop; require a code-enforced selector/cap (one explicit entity,
`max_items`, dry-run/shadow mode, or a fixed-inventory canary). Default-empty parameters,
full-table or due-work scans, and uncapped loops are unbounded even when on-demand. Record a
conservative maximum for units, external calls, writes, cost, and duration (fitting the
producer's timeout with headroom); unknown maxima are `BLOCKED` before triggering. Never run
first and infer boundedness afterwards.

Before triggering, prove: the deployment is registered in staging at the activated revision;
bounds are mechanically verified; it cannot alter schedules, backfill, deploy, migrate, enqueue
unbounded work, or mutate external production services; cleanup is defined. If the producer
fans out across units, first run one real unit through the exact final transport/parsing path
(same argv, credentials, timeout — a dry-run or health probe is insufficient); a failed
exact-path canary stops fan-out.

Trigger exactly once, capture run id and parameters, and wait with one bounded blocking call:

```text
wait-prefect-flow <run-id> --command-prefix '<project-approved prefect command>' --timeout 540
```

A `failure` terminal result makes the row and verdict `FAIL`. A timeout becomes
`NEEDS_MORE_TIME` only when the same run is `RUNNING` with a healthy worker and fresh progress
evidence. `PENDING`/`SCHEDULED` with a healthy queue is `external_wait`. A successful terminal
run is not itself a PASS: grade every durable output row after it completes.

### 4. Determine activation boundary

Never naive wall-clock lookback when a commit boundary exists. Production: commit landed on
`origin/main`. Staging: commit landed on `origin/staging`. Repos that pull code from git at
runtime: activation is the first run after land. If §3 cleared a blocker that delayed
activation, use the later of code-deploy and blocker-resolution evidence.

### 4a. Grade destructive-cutover runtime readiness

When the change removes/renames a schema or runtime object, schema truth alone is insufficient.
Before PASS: (1) inventory every long-lived reader/consumer/worker/job that can touch the
removed object, including cached-query and indirect config paths; (2) prove each restarted or
loaded post-cutover code after the activation boundary (instance/run/revision evidence, not
registration); (3) run or observe the guide's bounded real-input soak; (4) require zero new
undefined-object failures and zero new infrastructure quarantines in the soak window; (5) never
suppress, relabel, or delete failures to obtain a clean result. Missing inventory/activation
proof is `BLOCKED` before a destructive step and `FAIL` once active.

### 5a. Deployment precondition (check before grading runtime rows)

Before grading any evidence item that depends on runtime output of a deployed object, confirm
the producing object is live in the target env: it is **registered** (deployment listed, cron
installed, worker up), and for on-demand objects at least one post-activation run exists or the
bounded canary exception applies. If absent, the feature is **not deployed yet** — do not grade
its runtime rows as "no data yet": stop and return `BLOCKED` (§8) with the exact unblock action.
Be precise about provenance: rows written by a different deployment are not evidence this
ticket's flow ran — confirm matching deployment/run id or source marker before crediting them.

### 5b. Visible surfaces are staging-first

When acceptance includes a UI, rendered document, email preview, chart, or other
browser-visible state, grade it in a real browser session with screenshots (CLAUDE.md visible-
work rule) against **staging**. Production browser grading is allowed only when
`bin/environment-capability` confirms there is no staging, the acceptance contract is
explicitly production-only, and the user authorized it; anything else fails closed as
staging-first.

### 5. Collect evidence

First recheck each contract row's feasibility: declared maturity delay, sample size, and
acquisition time must fit the verification deadline
(`maturity_delay + acquisition_time <= deadline`; for natural traffic,
`acquisition >= ceil(sample_size / conservative_eligible_units_per_day * 86400)`), and failure
must demonstrate a defect controlled by the shipped change. A structurally infeasible or
non-causal row is `BLOCKED: invalid_evidence` routed to the contract owner — never executed,
never silently weakened or reclassified after seeing current output.

Run **every** contract row for the environment being verified, then supplement with read-only
checks until the report proves the feature and its edge cases work, not just one happy path:
affected flows/jobs since activation; service logs; database state via read-only queries;
every edge case named in source, plan, review notes, bug hypotheses, and acceptance criteria;
negative/regression checks that would have failed before the fix.

For pollers, schedulers, queue consumers, webhooks, scrapers, or any repeated writer,
supplement with storage-amplification checks even if the guide omitted them: observed rows/run
and extrapolated rows/day vs the volume budget; proof that unchanged source data is deduped or
change-gated across runs; retention/TTL for intentional per-run history. Never treat "rows
exist" as PASS for a repeated writer creating redundant durable data.

Every claim includes a reproducible command/query, expected good output, actual output, and
bad-output interpretation. Intermediate files go in one run-scoped
`.context/ticket-verify/<scope>-<env>-<stamp>/` directory, folded into the artifact before
cleanup.

**Evidence bound.** The evidence set is the contract rows, the named edge cases, and the
repeated-writer checks above — proved once each with the cheapest read that settles the row.
Within one scope: at most one triggered producer run (the §3a canary, when it applies) plus one
re-run only if the first ended in a non-terminal state; no manually dispatched CI/migration
workflows to observe a no-op (read the last run's result instead); no throwaway git worktrees
or hand-written oracle programs when the row can be graded with the deployed code's own
outputs and a read-only query; no service-log pulls beyond the activation window the row
names. A row that cannot be settled inside this bound is `BLOCKED: invalid_evidence` for the
contract owner, not a reason to widen the bound. A milestone gate (`--epic`) grades under the
same bound per included step; it is not a second code review.

### 6. Record the Verification Evidence artifact

Artifact type `verification_evidence`, title
`Staging|Production verification evidence — <scope>`. Metadata at minimum: `environment`,
`verdict`, `activation_boundary`, `evidence_count`, `edge_case_count`, `screenshot_count`,
`scope`, `generated_by`, `risk_tier`, `failure_classes` (row -> class for every non-PASS row),
and for staging runs the co-tenancy attribution: `staging_head_sha`
(`git rev-parse origin/staging`) and `co_staged_tickets` (ticket IDs in
`git log origin/main..origin/staging` subjects excluding this scope) — promotion compares this
against what it actually promotes. Content is the durable proof package: strong enough that a
future reader need not re-derive whether the problem is solved.

Production evidence is mandatory before any production PASS; staging evidence is written
whenever this command verifies staging, but its absence never blocks production verification.
If the verdict changed, create a new correctly titled artifact and mark the prior one
`superseded` — never overwrite a verdict-bearing title with contradictory metadata.

**FAIL→PASS supersession requires signature comparison (B0312/B0306):** before superseding a
FAIL with a PASS on "pre-existing failure / baseline noise" grounds, compare the failure
**diagnostic signature**, not just source/category/rate. If the baseline failed with a
specific, actionable error and post-activation failures show a different error for the same
source, that is a new regression that masks diagnostics — the FAIL stands.

Epic/milestone verification persists evidence in three places before status changes: the
canonical gate artifact on the epic, a `verification_evidence` artifact on every included step
ticket (with a pointer to the gate artifact), and a compact epic summary index
(see `../references/epic-lifecycle.md`).

### 8. Verdict

- `PASS` — every causal ship-gate row for this environment passed and no related causal failure
  surfaced. A failure is *related* only in a surface the diff touched or the contract names;
  a pre-existing failure with an identical diagnostic signature across the boundary is not.
- `PASS (contract-missing)` — every derived row passed but the contract was missing/`TBD`.
  Best possible verdict for such a scope; sets `staging_verified` without auto-promotion
  (exception: `tiny_safe`, §2a).
- `FAIL` — a causal row demonstrates related broken behavior or expected-but-missing activity.
- `NEEDS_MORE_TIME` — the producing deployment is registered and running, but rows have no
  post-activation data yet and none failed; use only when passive waiting will actually
  produce the evidence.
- `BLOCKED` — a concrete human-required or agent-incapable action remains: a still-true
  blocker (§3), an unmet deployment precondition (§5a), or an undeployed visible surface
  (§5b). These are deploy-prerequisite gaps, never `NEEDS_MORE_TIME`; name the exact unblock
  action.

Failed observation rows are recorded and routed but cannot fail an unrelated causal gate, and
cannot be relabeled causal after output is known. Thresholds remain the accepted contract.

**NEEDS_MORE_TIME cap.** Track per causal row from
`evidence_eligible_at = activation_boundary + maturity_delay`. After **3 eligible
NEEDS_MORE_TIME runs or 24h past eligibility** (whichever first), re-run feasibility: a feasible
live row still showing expected-but-missing activity becomes `FAIL`; an absent producer becomes
`BLOCKED: deployment_prerequisite`; structurally wrong timing math becomes
`BLOCKED: invalid_evidence`. A healthy `external_wait` with fresh progress is exempt until its
ETA/cadence is missed. **Moving-target guard:** when waiting on a scheduled event, verify the
awaited condition actually arrives; if the due time keeps advancing faster than it is consumed
(two consecutive rechecks where it never became true), that is a structural design flaw —
verdict `FAIL` with a repair packet, never another `NEEDS_MORE_TIME`.

### 9. Status, promotion, and failure handling

Persist all evidence artifacts **before** status changes, then delete the run's `.context`
scratch (retry once; report leftovers with a cleanup command).

Status actions: staging PASS -> `staging_verified` (then §9b); staging FAIL ->
`verify_staging_failed`; production PASS -> `completed`, or `prod_verified_needs_cleanup` when
deferred cleanup remains (§10); production FAIL -> `verify_prod_failed`; `NEEDS_MORE_TIME` and
`BLOCKED` leave the lifecycle status unchanged. Epic mode updates gates and step tickets per
`../references/epic-lifecycle.md` instead.

**9b. Auto-promotion gate (standalone staging PASS only).** Promote automatically only when ALL
hold: not `--scheduled`, not `--no-promote`, not epic mode; the contract was FINALIZED and fully
graded on fresh post-activation evidence (or `tiny_safe` per §2a); and the diff contains no
schema/migration, deploy-config, or auth/security category. Anything else rests at
`staging_verified` with the exact `/ticket-promote <ID>` command in the report.

**9c/9d. Every FAIL is root-caused before the run ends.** Run a bounded read-only investigation
per failure cluster; persist an `investigation` artifact with root-cause hypothesis, confidence,
and classification (`code_defect`, `environment`, `verifier_defect`, `invalid_evidence`); then
either hand a machine-readable repair packet to the active deploying owner (staging) or propose
2–4 ranked remediation routes. A `verifier_defect`/`invalid_evidence` classification also
records the contract-authoring lesson via `/compound`. Production or epic remediation that
changes product code/config/auth requires a new fix ticket or epic step — never an untracked
branch. This skill never mutates product code or environments; the FAIL verdict and evidence
artifacts are never rewritten.

### 10. Deferred post-verification cleanup (production PASS only)

When a `deferred_cleanup` artifact exists (or a production bug ticket structurally attributes
incident flow runs), grade its `evidence_contract` and execute the cleanup only after the PASS
verdict is recorded. Bounded noncritical destructive cleanup (including terminal Prefect
flow-run history) runs automatically; critical/unknown destructive cleanup is approval-gated —
the ticket rests at `prod_verified_needs_cleanup` with the pending command as blocker metadata
(see `../references/ticket-lifecycle.md`). Enforce the artifact's dry-run and scope bounds; a
non-PASS verdict never triggers cleanup.

## Output

Report truthfully: one large environment-specific banner (`## ✅ ...` only for a verdict that
was actually persisted and whose status action completed; production `completed` only after the
item re-reads as `completed`), then one table for all selected scopes:

```text
Scope            Env      Verdict          Action
F0123            staging  PASS             artifact <id>; scratch cleaned; promoted -> to_verify_prod
B0042            staging  NEEDS_MORE_TIME  left to_verify_staging
F0130            prod     BLOCKED          blocker still true; left to_verify_prod
E0007/M2         staging  PASS             gate artifact <id>; step artifacts <ids>; held for epic promotion
```

For every FAIL row, append the §9d result: investigation artifact ID, root-cause one-liner with
confidence, and the repair packet or top remediation route. Include any scratch-cleanup failure
with the exact cleanup command.

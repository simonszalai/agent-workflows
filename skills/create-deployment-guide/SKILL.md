---
name: create-deployment-guide
description: Create or finalize the deployment_guide ticket artifact — how to deploy (order, migrations, deploys, blocks) and what evidence proves it works in staging and prod.
skills:
  - review
  - autodev-search
---

# Create Deployment Guide Command

Produce the ticket's **`deployment_guide` artifact**: an explicit, queryable record of (a) **how
to deploy** this change — cross-repo order, migrations, code/service deploys, scheduler/worker
deploys, credential blocks, env vars — and (b) **what evidence proves it works** in staging and in
production.

This artifact is **stored in the MCP ticket system** (`artifact_type="deployment_guide"`), never as
a file on disk. Its downstream consumers (`/milestone-flow`, `/auto-deploy`, `/create-pr`,
`/ticket-verify`, `/ticket-promote`) all read it via `get_ticket`.

This skill is ticketed only. Ticketless ultra-light work (`/go-fable`) does not write a
deployment guide.


## The artifact is authored progressively

| Stage | Command | What it does to the artifact |
| ----- | ------- | ---------------------------- |
| Plan  | `/ticket-plan` | Creates a **DRAFT** — deploy *shape* + first-cut evidence contract, from architecture only |
| Build-todos | `/create-build-todos` | **Finalizes mechanics** — concrete migration revision/file, exact commands, block names, env vars, cross-repo order |
| Post-build | `/create-deployment-guide` | **Reconciles against the real diff** — what was actually changed, fills any gaps, marks FINALIZED |

So this command usually **updates** an existing draft, not creates from scratch. If no draft
exists (e.g. ticket skipped `/ticket-plan`), create one.

## Usage

```
/create-deployment-guide F007                    # Finalize/refresh guide for feature F007
/create-deployment-guide 009                     # Bug fix 009
/create-deployment-guide F007 --minimal          # Skip optional sections
```

## When to Run

- After `/resolve-review` completes (code is final)
- Automatically as part of `/ticket-flow` / `/ticket-build` when deploy shape is non-trivial
- Before `/milestone-flow` deploys/verifies a milestone, or before standalone `/auto-deploy` /
  `/ticket-verify`

## Prerequisites

- Code changes are complete and reviewed
- A `plan` artifact exists (read via `get_ticket`)
- A draft `deployment_guide` artifact usually exists from `/ticket-plan` (update it; create if absent)

## Process

### 1. Load the ticket and existing artifacts

```
ticket = mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  detail="full",
  artifact_types=["plan", "build_todo", "review_todo", "deployment_guide"],
  include_events=false
)
```

Read: `plan`, all `build_todo`s, `review_todo`s (deployment-relevant findings), and the existing
`deployment_guide` draft if present.

### 2. Analyze the real diff for deployment impact

`git diff origin/main...` (or the target branch). Categorize every change — do not rely on the
plan's predictions, grade them against what was actually built:

| Change Type            | Deployment Requirement                          |
| ---------------------- | ----------------------------------------------- |
| Database schema changes | Schema apply/migration must run before code that reads it |
| New/changed models     | Use repo active schema system (ts-prefect Atlas after E0017; Prisma/Alembic migrations elsewhere) |
| New services/jobs      | Service deploy + schedule registration          |
| Scheduler/worker/cron  | Deploy + (re)register the schedule               |
| Runtime canary/observer evidence | Flow/CLI/deployment that produces the evidence rows |
| Secrets/credential cfg | Provision the block/secret before first run     |
| Config / env vars      | Set in each environment before deploy            |
| Cross-repo contracts   | Producer deploys before consumer (or vice versa)|
| Dashboard/frontend     | Frontend redeploy                                |

### 3. Discover PROJECT-SPECIFIC deploy mechanics (CRITICAL)

This skill is project-agnostic. The *actual* deploy mechanism for this repo lives in project
instructions — **discover it, do not assume**:

1. Read the project `CLAUDE.md` / `AGENTS.md` for the deployment model (e.g. does code deploy via
   runtime git-pull, or a service build/redeploy? is there a scheduler/worker deploy? are there
   credential/secret "blocks" to provision? a DAG/pipeline sync step? CI auto-migration on merge?).
2. Search memory for deploy gotchas:
   ```
   mcp__autodev-memory__search(project=PROJECT, queries=[
     {"keywords": ["deploy", "migration", "rollback"], "text": "deployment order gotchas"},
     {"keywords": ["<project deploy primitives>"], "text": "deploy steps blocks scheduler"}
   ])
   ```
3. Encode what you learn into the Deployment Steps. Name the **real** commands/objects for this
   project, not generic placeholders.
4. Load and reconcile the planning-time inventory from
   `../references/deployment-ownership.md`. For every environment key/action record its
   classification (`non_secret_config`, `secret_value`, or `manual_gate`), source/owner,
   destination, application route, safe-state handling, and verification evidence. Missing config
   is not evidence that a token/secret should be invented. Validate the completed inventory with
   `bin/deployment-ownership-contract`.

### 4. Define the Verification Evidence contract (CRITICAL)

This is the part `/ticket-verify` grades against.

**Before writing or finalizing any contract row, search memory for this app's contract-authoring
lessons** — every past `verifier_defect`/`invalid_evidence` FAIL compounds one (tag
`verifier-contract`, written by ticket-verify's failure investigation):

```text
mcp__autodev-memory__search(project=PROJECT, repo=REPO, detail="compact", queries=[
  {"keywords": ["verifier-contract"], "text": "verifier evidence contract authoring rules <feature area>"}
])
```

Apply every returned rule that touches a surface this contract uses (e.g. squash-safe ancestry
checks, controller shell-decoding constraints, timing feasibility) and note the applied entry IDs
in the artifact. If the memory tool is unavailable, proceed and say so in the artifact.

For **each** of staging and production, list the
evidence that proves the change works. Every evidence item MUST be:

- a **reproducible** query or command (copy-pasteable, read-only),
- with an **expected good output**, and
- a **bad-output interpretation** (what a failure looks like and what it means),
- `gate_class: causal_ship_gate | observation`,
- `acceptance_source.kind: source_criterion | explicit_user_decision |
  measured_production_baseline | invariant` plus the exact source reference, and
- the bounded failure class used for routing if the row fails.

Before classifying a row as `causal_ship_gate`, apply the **release-gate minimality test**:

1. Name the shipped defect the row distinguishes.
2. State why failure proves the shipped behavior is broken, rather than merely leaving confidence
   incomplete.
3. Name the smallest sufficient evidence for that defect.
4. Explain why deterministic checks, one exact-path live case, or a bounded replay are insufficient
   if the row asks for more.
5. Identify whether the threshold came from a source criterion or was added by the agent.

If failure would only leave confidence incomplete, or a smaller proof distinguishes the same
defect, the row is an `observation`. Core behavior stays causal, but its evidence mechanism must be
the smallest adequate one. Do not remove a real behavior gate merely because a cheaper bounded
replay or exact-path case can replace a broad natural cohort.

Every row also carries machine-readable feasibility fields: `sample_size`,
`minimum_sufficient_evidence`, `distinguishes_defect`, `failure_class_on_failure`, and
`evidence_timing`. Timing declares the source (`immediate`, `bounded_producer`, or
`natural_traffic`), maturity delay, conservative acquisition time, and verification deadline.
Natural-traffic rows additionally declare a measured conservative eligible-units/day rate.

For every causal row, prove mechanically:

```text
maturity_delay_seconds + acquisition_time_seconds <= verification_deadline_seconds
```

For natural traffic, `acquisition_time_seconds` must be at least
`ceil(sample_size / conservative_eligible_units_per_day * 86400)`. If either inequality fails,
classify the row as a longitudinal `observation` or keep the guide DRAFT when the source explicitly
requires it. Never deploy first and discover that the release evidence needs days or weeks longer
than the verification lifecycle.

High-N/statistical rows are incomplete unless they state the pre-change baseline, why that sample
size can distinguish the named defect, and the finite units/time/cost budget. They must reference
an earlier one-unit exact-path canary for the same defect. Missing provenance, a missing canary, or
a threshold selected after current output keeps the guide DRAFT; it never becomes a tailored PASS.

Provider success is not evidence of non-empty business yield unless an API contract or measured
baseline guarantees non-empty output. Likewise, a soak or orphan/stranded-record metric is causal
only when the shipped change controls it and the ticket explicitly promises it. Valid empty
provider results, rare calendar states, and noisy recovery metrics default to observations unless
the acceptance source proves otherwise.

Generic acceptance ("it works") is not evidence. "Row count in table X for records landed after
the activation commit is > 0, and `status='ok'` for all of them" is evidence. The contract must
cover every edge case named in the source, plan, acceptance criteria, build todos, review notes,
and bug hypotheses; one happy-path row is not enough.

**First use of a transport or protocol is its own evidence item.** If the diff introduces the
repo's *first* call site for a wire mechanism — SSE/streaming, websockets, HTTP/2 push, gRPC,
long-polling, chunked upload, a new SDK client mode, a new content encoding — grep to confirm it is
genuinely the first (`rg` the SDK method / scheme repo-wide) and then require a **standalone
transport smoke check** that exercises that mechanism alone, through the real deployed network path
including every proxy, gateway, or rewritten `base_url` the runtime actually uses. It must run
before, and independently of, the feature's own evidence, and its bad-output interpretation is
"this transport does not survive our network path — the feature built on it cannot ship". A
mechanism that works against the vendor directly proves nothing about a path that rewrites the
endpoint: E0027/F0296 shipped the repo's only `messages.stream` call through a decrypt proxy that
does not relay SSE in order, and it failed deterministically on record 1 of every staging run.

For pollers, observers, schedulers, queue consumers, webhooks, scrapers, supervisor flows, or
any repeated writer that persists data, the evidence contract must also prove storage shape:

- expected rows/run, rows/day, bytes/day, index/WAL impact, and retention/TTL;
- a read-only duplicate/unchanged-source check showing repeated identical polls do not create
  redundant business rows unless explicitly required;
- a query that distinguishes canonical rows from append-only observations/snapshots/logs;
- the named downstream consumer for any per-poll append-only history.

Do not let "rows exist" be the only success criterion for a repeated writer. A feature can be
functionally alive and still fail verification because polling frequency is multiplying
redundant storage.

For any **producer/consumer** feature (a producer schedules work a separate consumer performs),
the **staging** contract MUST include one row that observes the **terminal artifact end-to-end** —
seed a real input, then confirm the consumer actually ran and produced its output row (e.g. a
`pacer_poll_events` row for a followed case), not merely that a schedule/queue row exists. "A
schedule row is present" or "the deployment is live" is NOT proof the work happens. If the terminal
table stays empty in staging because the feature was never exercised with real seed data, the
staging gate is **BLOCKED**, not PASS-with-caveat — an unexercised producer/consumer path is exactly
where scheduler/cadence starvation hides (see review reference `data-integrity.md` §4b).

Also record the **activation boundary**: how a verifier knows the new code is actually live
(commit landed on `origin/main` / `origin/staging`; or, for runtime-git-pull projects, the first
flow/job run that started after the land — measure fill rates from the first post-land row, not
from merge time).

For any permitted **destructive schema cutover** (drop/rename of a table, column, view, function,
queue, topic, or other runtime object), static schema truth is insufficient runtime-readiness
evidence. The guide must sequence the compatibility-code activation and all reader restarts before
the destructive step, then require all of this evidence:

1. a complete inventory of every long-lived reader, consumer, worker, scheduler, and job that can
   touch the removed object, including indirectly through cached queries or configuration;
2. per-reader proof that the process restarted or otherwise loaded the post-cutover code/config,
   tied to an instance/run/revision and later than the activation boundary;
3. a bounded representative real-input soak after the destructive cutover is active, with the
   input mix, duration or run cap, and observation window recorded;
4. zero new undefined-object failures and zero new infrastructure quarantines during that soak,
   measured from a pre-cutover baseline and checked in both runtime failures and quarantine stores;
5. explicit preservation of intentional FAILED-state observability: do not catch, suppress, delete,
   or relabel failures to make the cutover pass.

If any reader cannot be inventoried, activated, or observed, the destructive step is not permitted.
An Atlas/schema-truth no-op or matching database fingerprint proves only schema state; it never
proves that long-lived runtime readers loaded compatible code.

If any evidence row expects runtime behavior (canary run, observer, flow, deployment, stored rows,
polling, scheduler, worker, Prefect, supervisor, webhook, or live readback), the guide must name
the producing deploy object/command in the Deployment Steps. Do not leave a guide FINALIZED when
verification expects rows/logs from a flow that the diff did not add or an existing deployment
cannot produce. Either add the producing flow/YAML/supervisor/CLI step, or revise the evidence
contract to a different proof mechanism before deploy.

If the named producer is a **canary/shadow run triggered solely to generate evidence** (a bounded
on-demand flow, a temporary deployment/schedule, throwaway records) rather than the feature's real
production path, the guide must also carry its **cleanup**: record a `deferred_cleanup` (or an
inline reversible teardown) that removes the canary flow run, any temporary deployment/schedule
registered for it, and any rows it wrote purely as evidence. A canary is not FINALIZED-ready until
its teardown is specified — leaving one registered/running after `/ticket-verify` is a defect.

The guide must prove "bounded" from the producer's actual parameter schema and entrypoint, not from
phrases such as "one run" or "on-demand." For every trigger-only evidence producer, record the exact
code-enforced selector/cap and conservative maxima for selected units, external calls, durable
writes, estimated cost, and wall-clock duration (including retry/provider worst cases). The maximum
duration must fit within the outer flow/job timeout with headroom. Default-empty parameters,
full-table or due-work scans, dynamic backlog consumers, and uncapped sequential loops are not
canaries. If any maximum depends on live database cardinality or cannot be established before the
trigger, keep the guide unfinalized and require a bounded parameter or dedicated canary instead.

For a **bug ticket created from Prefect failures**, also inspect the ticket's structured triage
context. When it attributes original incident runs by ticket tag/cluster or explicit labeled run IDs,
the guide must require a parent `deferred_cleanup` with `cleanup_kind="flow_run_cleanup"`. It runs
only after production behavior PASS and deletes only terminal pre-fix flow-run history selected by
the ticket attribution. It must exclude verification/canary runs, post-fix failures, deployments,
schedules, task runs, blocks, and application rows. Do not finalize a guide that would leave known
resolved incident runs on the failure board without a safe cleanup contract.

### 5. Write/update the artifact

Before marking or persisting a guide as FINALIZED, compile it into this machine contract and run
`deployment-guide-contract <absolute-contract-path>`:

```json
{
  "schema_version": 2,
  "status": "FINALIZED",
  "activation_boundary": "exact branch/run/revision boundary",
  "environments": {
    "staging": {
      "rows": [{
        "id": "staging-1",
        "exact_command": "read-only command",
        "expected_result": "concrete good result",
        "bad_interpretation": "specific defect and failure meaning",
        "gate_class": "causal_ship_gate",
        "acceptance_source": {
          "kind": "source_criterion",
          "reference": "ticket acceptance criterion 1"
        },
        "sample_size": 1,
        "minimum_sufficient_evidence": "one exact-path post-activation result",
        "distinguishes_defect": "the shipped behavior is absent",
        "causal_failure_meaning": "the activated revision does not implement criterion 1",
        "failure_class_on_failure": "code_defect",
        "exact_path_canary": false,
        "canary_row_id": null,
        "evidence_timing": {
          "source": "immediate",
          "maturity_delay_seconds": 0,
          "acquisition_time_seconds": 60,
          "verification_deadline_seconds": 3600
        },
        "bounded_producer": {"status": "N/A", "justification": "read-only evidence"},
        "cleanup": {"status": "N/A", "justification": "no temporary producer"}
      }]
    },
    "production": {
      "status": "N/A",
      "justification": "staging-only ticket with no production delivery"
    }
  }
}
```

Both environment keys are mandatory. Each applicable environment has at least one causal row. Each
row carries the command, expected/bad results, acceptance source, minimum sufficient evidence,
defect, failure class, sample/canary fields, timing feasibility, bounded producer, and cleanup.
Any `N/A` must use the object form above with a non-empty justification. Validation must pass
before the artifact update/create call. A failed contract remains DRAFT; do not repair it after
deployment or other remote mutation.

Find the existing draft in the `get_ticket` response (the artifact with
`artifact_type="deployment_guide"`). If found, **update by its `artifact_id`** (preserve plan
intent, finalize mechanics, mark FINALIZED):

```
mcp__autodev-memory__update_artifact(
  project=PROJECT,
  artifact_id="<deployment_guide artifact id from get_ticket>",
  content="<filled template>",
  command="/create-deployment-guide"
)
```

If none exists (ticket skipped `/ticket-plan`), create it:

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="deployment_guide",
  content="<filled template>",
  command="/create-deployment-guide"
)
```

## Template: deployment_guide artifact

````markdown
# Deployment & Verification Guide: {ticket-id}

**Status:** DRAFT (from /ticket-plan) | FINALIZED
**Feature/Fix:** {title}
**Branch:** {branch}
**Repos touched:** {repo-a, repo-b, ...}
**Date:** {YYYY-MM-DD}

## Deployment / Configuration Ownership

| Key / action | Type | Source / owner | Destination | Application route | Safe-state handling | Verification evidence |
| ------------ | ---- | -------------- | ----------- | ----------------- | ------------------- | --------------------- |
| {name} | {non_secret_config / secret_value / manual_gate} | {repo/team/source} | {repo/env} | {exact route} | {unset/rollback behavior} | {read-only proof} |

## Summary

{1-2 sentences: what is being deployed.}

## Deployment

### Cross-Repo Order

Ordered list of repos/components to deploy and **why** this order (which contract or dependency
forces it). If single-repo, state "Single repo — no cross-repo ordering."

1. {repo/component} — {reason it goes first, e.g. "produces the field repo-b reads"}
2. {repo/component} — {reason}

### Steps (in order)

Include only the categories that apply. Use the **project's real** commands/objects (discovered in
Process step 3), not placeholders.

| # | Step | Command / object | Expected result |
| - | ---- | ---------------- | --------------- |
| 1 | {e.g. run migration} | {real command, or "CI auto-migrates on merge"} | {what success looks like} |
| 2 | {e.g. deploy code}   | {runtime git-pull / service redeploy / …}      | {…} |
| 3 | {e.g. provision block/secret} | {block/secret name + how}             | {…} |
| 4 | {e.g. deploy scheduler/worker, register schedule} | {…}              | {…} |
| 5 | {e.g. set env var}   | {VAR + value/where}                            | {…} |
| 6 | {e.g. DAG/pipeline sync} | {…}                                        | {…} |
| 7 | {e.g. run bounded canary that writes verification rows} | {real deployment/CLI command} | {durable evidence exists for `/ticket-verify`} |

### Pre-Deployment Checklist

- [ ] Tests + type check pass
- [ ] Branch rebased on target (linear history; avoids migration-graph conflicts)
- [ ] Migration is order-independent / idempotent (if any)
- [ ] First-use-of-a-transport smoke check passed through the real proxy/gateway path (if any new
      wire mechanism — streaming/SSE, websockets, gRPC, new SDK client mode, new encoding)
- [ ] Destructive cutover reader inventory, activation/restart proofs, and post-cutover soak are
      defined (if any object is removed)
- [ ] {change-type-specific checks}

### Rollback

- Reversible? {Yes / Partial / No} — {why}
- Steps: {how to roll back, including whether the migration is safe to leave in place}

## Verification Evidence

What proves this works. `/ticket-verify` grades **every** item in the relevant environment and
writes the actual observations to the fixed `verification_evidence` artifact slot. Every row has
one gate class and one acceptance source:

- `causal_ship_gate` — fail closed when the shipped revision does not satisfy a source criterion,
  explicit user decision, measured production baseline, or invariant;
- `observation` — useful telemetry that is not causally required to ship. Its failure routes to
  its owner but cannot fail an unrelated causal ship gate.

Record the exact source reference; "best practice" or current output is not an acceptance source.
Any statistical threshold or sample size greater than one additionally records its pre-change
baseline, sample-size rationale, finite resource budget, and the defect it distinguishes. Never
tune a threshold after seeing current output. Put the smallest single-unit exact-path canary before
the high-N row and name that canary from the high-N row.

Before FINALIZED, run the release-gate minimality test and evidence-feasibility inequality from
Process step 4 for every row. A natural cohort that cannot mature and accumulate within its
deadline is longitudinal monitoring, not a release blocker. A provider call that validly permits
empty results cannot use non-empty output as a routing gate. A soak measuring a documented
non-goal cannot be causal.

### Activation boundary

{How to know the new code is live: commit on origin/{main|staging}; or first flow/job run after
the land for runtime-git-pull projects. Measure from the first post-land evidence row.}

### Destructive cutover runtime readiness (if applicable)

- Removed object(s): {exact names}
- Reader inventory: {reader/consumer/job -> deployment/process identity}
- Activation proof: {reader -> restarted/reloaded revision and timestamp/run id}
- Representative soak: {real inputs, fixed duration/run cap, post-cutover observation window}
- Failure predicates: zero new undefined-object failures; zero new infrastructure quarantines
- Observability: preserve intentional FAILED states and failure history
- Schema truth: {schema evidence}, explicitly recorded as insufficient without the runtime proofs

### Staging

| # | Gate class | Acceptance source + reference | Evidence (reproducible query/command) | Expected good output | Bad output means |
| - | ---------- | ----------------------------- | ------------------------------------- | -------------------- | ---------------- |
| 1 | {causal_ship_gate / observation} | {source criterion / explicit user decision / measured production baseline / invariant}: {exact reference} | {read-only query/command} | {concrete expected} | {defect + failure class} |

### Production

| # | Gate class | Acceptance source + reference | Evidence (reproducible query/command) | Expected good output | Bad output means |
| - | ---------- | ----------------------------- | ------------------------------------- | -------------------- | ---------------- |
| 1 | {causal_ship_gate / observation} | {source criterion / explicit user decision / measured production baseline / invariant}: {exact reference} | {read-only query/command} | {concrete expected} | {defect + failure class} |

### Statistical / high-N rows (only when applicable)

| Evidence row | Baseline | Sample-size rationale | Resource budget | Defect distinguished | Exact-path canary row |
| ------------ | -------- | --------------------- | --------------- | -------------------- | --------------------- |
| {row #} | {measured pre-change value/reference} | {why N is discriminating} | {units/time/cost cap} | {specific defect} | {earlier single-unit row #} |

### Evidence feasibility

| Evidence row | Source | Sample | Maturity seconds | Acquisition seconds | Deadline seconds | Conservative eligible units/day | Minimum sufficient evidence | Causal failure meaning |
| ------------ | ------ | ------ | ---------------- | ------------------- | ---------------- | ------------------------------- | --------------------------- | ---------------------- |
| {row #} | {immediate / bounded_producer / natural_traffic} | {N} | {seconds} | {seconds} | {seconds} | {rate or N/A} | {smallest proof} | {why failure proves shipped behavior broken, or N/A for observation} |

## Services / Env / Dependencies (if applicable)

| Service   | Change Required | Notes        |
| --------- | --------------- | ------------ |
| {name}    | {Yes/No}        | {details}    |

| Env Var | Environment | Value/Description |
| ------- | ----------- | ----------------- |
| {VAR}   | {where}     | {description}     |

- External dependencies: {list or "none"}

---

**Generated by:** /create-deployment-guide — verify before deploying.
````

## Section Guidelines

| Section                  | Always | If Applicable |
| ------------------------ | ------ | ------------- |
| Summary                  | Yes    |               |
| Deployment → Cross-Repo Order | Yes |             |
| Deployment → Steps       | Yes    |               |
| Pre-Deployment Checklist | Yes    |               |
| Rollback                 | Yes    |               |
| Verification Evidence (staging + prod) | Yes |    |
| Services / Env / Deps    |        | Multi-service / new vars / external deps |

### What NOT to Include

- Implementation details (those live in build_todos)
- Historical context (that lives in plan)

### Minimal Mode (`--minimal`)

Skip Services/Env/Dependencies when empty. **Never** skip Deployment Steps or Verification
Evidence — those are the point of the artifact.

## Output

After writing/updating the artifact, tell the user:

```
deployment_guide artifact {created|updated} for {ID} (status: FINALIZED).
- Deploy steps: {N} (cross-repo order: {…})
- Verification evidence: {S} staging item(s), {P} prod item(s)

Next: deploy, then /ticket-verify staging (grades against the evidence contract).
```

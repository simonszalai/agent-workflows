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

## Ticketless mode (lfg)

When invoked with **no ticket** (i.e. from `/lfg`), write the filled template to
`.context/deployment-guide.md` instead of the MCP artifact, and skip every
`get_ticket`/`create_artifact`/`update_artifact` call (read the plan and todos from
`.context/ticket-plan.md` and `.context/build_todos/` instead). This is the sanctioned lfg exception
to the File Storage Rules — lfg has no ticket to write to. Everything else in this skill
(diff analysis, project-specific deploy mechanics, the evidence contract, the template)
applies unchanged. Ticketed behavior is unchanged.

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
- Automatically as part of `/ticket-flow` and `/lfg` (ticketless mode)
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

### 4. Define the Verification Evidence contract (CRITICAL)

This is the part `/ticket-verify` grades against. For **each** of staging and production, list the
evidence that proves the change works. Every evidence item MUST be:

- a **reproducible** query or command (copy-pasteable, read-only),
- with an **expected good output**, and
- a **bad-output interpretation** (what a failure looks like and what it means).

Generic acceptance ("it works") is not evidence. "Row count in table X for records landed after
the activation commit is > 0, and `status='ok'` for all of them" is evidence. The contract must
cover every edge case named in the source, plan, acceptance criteria, build todos, review notes,
and bug hypotheses; one happy-path row is not enough.

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
- [ ] {change-type-specific checks}

### Rollback

- Reversible? {Yes / Partial / No} — {why}
- Steps: {how to roll back, including whether the migration is safe to leave in place}

## Verification Evidence

What proves this works. `/ticket-verify` grades **every** item in the relevant environment and
writes the actual observations to the fixed `verification_evidence` artifact slot; the verdict is
PASS only if all rows and all listed edge cases pass.

### Activation boundary

{How to know the new code is live: commit on origin/{main|staging}; or first flow/job run after
the land for runtime-git-pull projects. Measure from the first post-land evidence row.}

### Staging

| # | Evidence (reproducible query/command) | Expected good output | Bad output means |
| - | ------------------------------------- | -------------------- | ---------------- |
| 1 | {read-only query/command}             | {concrete expected}  | {what failure looks like + interpretation} |

### Production

| # | Evidence (reproducible query/command) | Expected good output | Bad output means |
| - | ------------------------------------- | -------------------- | ---------------- |
| 1 | {read-only query/command}             | {concrete expected}  | {what failure looks like + interpretation} |

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

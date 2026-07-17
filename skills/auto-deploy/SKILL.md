---
name: auto-deploy
description: Autonomous deployment. Deploys PR to staging or production, runs migrations/blocks/deploys, updates ticket status.
max_turns: 100
---

# Auto-Deploy Command

Follow `../references/execution-economy.md` for bounded output, run-local caching, batching, and
non-model-driven waits. Its economy rules never relax deployment or fail-loud gates below.
Also follow `../references/ci-self-heal.md`: routine CI failures are repaired autonomously rather
than returned as terminal deploy failures.

Autonomous deployment that picks up a unit ready to deploy, deploys its PR to the target
environment, and advances its status. **Both standalone tickets and epics can use the staging
segment** (per-ticket staging statuses were added in migration 025): a unit at
`ready_to_deploy_staging` deploys to staging and advances to `to_verify_staging`. Production
deploys are not picked up from a status: they are invoked explicitly by `/ticket-flow` (the
direct-production route, target argument `production`) or handled by `/ticket-promote`
(post-staging landing + deploy). Epic **members** are still carried by the epic — they reach
`merged` and are not deployed individually by a scheduled pickup. The milestone gate is owned
by `/milestone-flow`: after each milestone's member steps are merged, it invokes this skill
for the parent epic's staging deploy, then invokes the explicit epic/milestone verifier. After
all milestone staging gates pass, `/epic-flow` uses `/ticket-promote --epic` for the ordered
production promotion/deploy path.

Auto-deploy is also the canonical place to record deployment blockers. "Blocked" is not a
ticket lifecycle status: a ticket can be blocked in any column. If an automatable deployment
finishes but a known external/manual dependency remains, advance the ticket to the correct next
verification status and set the independent blocker metadata (`blocked_at`, `blocked_by`,
`blocked_reason`, `blocked_context`) so the dashboard can show the red blocker indicator.

## Usage

```
/auto-deploy F007                   # Deploy feature F007 (target from ticket status)
/auto-deploy F007 staging           # Deploy to staging (overrides ticket status detection)
/auto-deploy F007 production        # Deploy to production (overrides ticket status detection)
/auto-deploy B003                   # Deploy bug fix B003
/auto-deploy                        # (scheduled) Pick up next ready_to_deploy_staging unit
```

## When to Use

- From `/ticket-flow`, after the ticket has been planned, built, reviewed, and locally verified;
  ticket-flow chooses `staging` vs `production` up front and invokes this skill for the deploy
  (production deploys always arrive via this explicit target argument, never a status pickup)
- For an epic staging gate: after milestone members are `merged`, when called by
  `/milestone-flow` (deploys the parent epic to staging)
- For epic or post-staging production promotion/deploy: use `/ticket-promote`, which owns the
  ordered verified-work landing + production deploy path
- Scheduled agent picks up standalone or epic units at `ready_to_deploy_staging` automatically
- Manual trigger when you want to deploy a specific ticket or epic

## Prerequisites

- A standalone ticket or epic at `ready_to_deploy_staging`, or an explicit target argument
  supplied by the caller
- Feature branch must exist on remote (created + pushed by the `/ticket-flow` build phase)
- A PR is NOT required upfront — this skill creates the PR as its first action if one
  does not already exist for the branch
- CI checks must be passing on the PR after it exists

## Target Environment

The target environment is determined by **argument override first**, then ticket status:

1. If a second argument is provided (`staging` or `production`), use that directly
2. Otherwise, infer from ticket status:

| Status                       | Applies to  | Deploy Target | Next Status          |
| ---------------------------- | ----------- | ------------- | -------------------- |
| `ready_to_deploy_staging`    | Ticket/Epic | Staging       | `to_verify_staging`  |

There is no production pickup status: a production deploy requires the explicit `production`
target argument (from `/ticket-flow`'s direct-production route). Post-staging production work
goes through `/ticket-promote` instead. A production deploy advances the unit to
`to_verify_prod`.

For a standalone ticket the next status is written on the ticket (`update_ticket`); for an epic
it is written on the epic (`update_epic`, an `epic_status`). When the target is overridden via
argument, the status check is relaxed — the
unit must exist but can be in any active status (not `completed` or `abandoned`).

## Process Overview

```
1.  Validate       -> Check ticket exists, determine target environment
2.  Find or Create PR -> Locate existing PR; if none, create it via /create-pr
3.  Load Deploy    -> Read project-specific /deploy command (if exists)
4.  Check CI       -> Verify CI checks are passing
5.  Update branch  -> Rebase PR onto target branch when the repository permits it
6.  Detect Changes -> Analyze what changed for deployment decisions
7.  Merge PR       -> Merge PR to target branch
8.  Deploy Steps   -> Run project-specific deployment steps for target environment
9.  Verify         -> Confirm each deployment step succeeded
10. Set Status + Blockers -> Update next status and independent blocker metadata
```

**PR creation happens here, not in the build phase.** The `/ticket-flow` build phase pushes a
feature branch without opening a PR. Auto-deploy creates the PR as its first action (Phase 2)
so the PR reflects the final state of the branch at deploy time.

## Detailed Process

### Phase 1: Validate Ticket

```
ticket = mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  detail="full",
  artifact_types=[
    "plan", "build_todo", "review_todo", "deployment_guide",
    "verification_evidence", "deferred_cleanup"
  ],
  include_events=false
)
```

This is the retrieval owner for the whole auto-deploy run. Cache the response and its
`context_version` in run-local state; do not call `get_ticket` again unless an external writer
changes a relevant artifact. If Phase 2 invokes `/create-pr`, pass this cached response through its
`--context-file` input rather than letting create-pr reload the same ticket. The file is an ephemeral
0600 OS-temp cache (for example `${TMPDIR:-/tmp}/agent-workflows/<run-id>/ticket.json`), not a
durable ticket artifact; delete it at the end of the run and never place it in `.context/`.

- If not found: STOP - "Ticket not found"
- Parse arguments: if second arg is `staging` or `production`, use as target override
- If no override: check ticket status is `ready_to_deploy_staging`
- If override provided: accept any non-terminal ticket status
- Determine target environment and corresponding deploy config

### Phase 2: Find or Create PR

Find the PR by ticket ID (branch naming is not assumed):

```bash
gh pr list --search "{ticket-id} in:title,body" \
  --state all --json number,url,headRefName,state
```

- **PR found, open:** continue to Phase 3
- **PR found, already merged:** skip the merge phase (Phase 7), continue to deploy steps
- **No PR found:** fall back to the current branch — if the current branch is a pushed
  feature branch for this ticket (not `main`/`staging`), use it as the PR head; then run
  `/create-pr {ticket-id} --context-file <run-local-cached-ticket>` internally to:
  1. Reuse the ticket artifacts already loaded in Phase 1
  2. Generate the PR summary from those artifacts + test results
  3. Create the PR against the target branch with the generated body

  Output the PR URL.

If no PR matches the ticket ID and the current branch is not a usable feature branch for this
ticket: STOP and report - "No PR or feature branch found for this ticket."

### Phase 3: Load Project-Specific Deploy Command

Check if a project-specific `/deploy` command exists:

```bash
ls .claude/commands/deploy.md 2>/dev/null
```

If it exists, **read it** to understand the full deployment process for this
project. The project-specific deploy command defines:

- What change categories to detect (migrations, config, dependencies, etc.)
- What deployment steps to run and in what order
- What verification to perform
- What manual steps to flag to the user
- **Environment-specific commands** for staging vs production

Use this as the authoritative guide for Phases 6-9. The phases below describe
the generic process; the project-specific command overrides where it differs.

### Phase 4: Check CI

```bash
bin/wait-ci {pr_number} --timeout 540
```

- Invoke that as one blocking foreground tool call with an outer timeout above 540 seconds; consume
  its one JSON result. Do not background it and poll process output from model turns.
- If checks fail: wait for the check set to become terminal, inspect the failed GitHub Actions logs,
  and run the `ci-self-heal.md` loop. Mechanical failures are fixed, locally verified, reviewed,
  committed, pushed, and waited on again. Resume Phase 5 only after the current tree is green.
- Stop only when CI repair reaches `ci-self-heal.md`'s human-judgment gate. Record the exact failed
  check, evidence, and decision needed; do not label an ordinary red unit/dependency/lint check as
  a deploy blocker.
- If still pending at the cap: STOP - report pending checks and the returned `resume_command`
- If PR already merged: skip CI check (already passed)

### Phase 5: Update the PR onto Target Branch (CRITICAL)

Determine the target branch based on environment:
- **Staging**: rebase onto `staging`
- **Production**: rebase onto `main`

Use the repository's documented branch-update policy to bring the PR branch onto the target. The
default is rebase; do not use it when the repository requires another strategy. Database schema
changes depend on the repo's active migration system. For
ts-prefect after E0017, that system is Atlas reviewed-plan/additive-only gates, not Alembic;
for legacy migration repos, merging a PR whose base is behind the target can still cause
migration graph conflicts.

```bash
# Fetch latest target branch
git fetch origin {target_branch}

# Check if PR branch is behind
gh api repos/{owner}/{repo}/compare/{target_branch}...{branch} \
  --jq '.behind_by'
```

If behind_by > 0:

```bash
# Rebase the PR branch onto target
git checkout {branch}
git rebase origin/{target_branch}
git push --force-with-lease
```

Wait for CI to re-run after rebase (checks must pass again) with one new
`bin/wait-ci {pr_number} --timeout 540` invocation. Repair mechanical failures through the same CI
self-heal loop. If it times out, return its resume command; never turn GitHub polling into repeated
model turns.

If the repository-approved branch update has conflicts: STOP and report the exact conflict.

### Phase 6: Detect Changes

Before merging, analyze what changed to determine which deployment steps
are needed. This MUST happen before merge (pushing advances the target branch).

```bash
# Check for each change category
git diff origin/{target_branch}..{branch} --name-only
```

**Generic detection categories:**

| Category     | Detect                                              |
| ------------ | --------------------------------------------------- |
| Schema       | ts-prefect Atlas paths (`ts_schemas/models/`, `atlas.hcl`, `atlas/plans/`, `cli_tools/atlas/`, `migrations/db_object_manifest.py`) or legacy migration dirs (`alembic/`, `migrations/versions/`, Prisma migrations) |
| Config       | Deployment config files (YAML, env, etc.)           |
| Dependencies | Package manifests, lockfiles, `Dockerfile`, and requirements files |

**Project-specific categories** (from `/deploy` command if loaded):

The project-specific deploy command may define additional categories like
blocks, Prefect config, DAG nodes, etc. Detect all categories it specifies.

Store detection results for use in Phase 8.

Also compare the deployment guide / milestone gate evidence contract against the detected diff.
If any verification row expects runtime behavior from a Prefect flow, scheduler, worker,
supervisor-managed deployment, webhook, canary, stored-row observer, or live deployment, prove
that one of these is true before merging:

- the diff adds/changes the producing flow entrypoint plus the relevant deployment config
  (`prefect.*.yaml`, supervisor registration, worker/schedule config, etc.);
- the deployment guide names an existing deployed object that will produce the evidence, and
  `prefect deployment ls` / the authoritative deploy system confirms it exists in the target
  environment; or
- the deployment guide names an explicit deploy-owned canary/CLI command that will be run in
  Phase 8 and leave durable evidence for `/ticket-verify`.

If the evidence contract expects runtime rows/logs but the diff is only schema/parser/model code
and no existing deploy object/command can produce the rows, STOP as a scope mismatch. Do not
silently skip Prefect deploy merely because `prefect.staging.yaml` / `prefect.prod.yaml` is
unchanged; report that planning/splitting missed the runtime surface required by the gate.

Also detect **external/manual deploy blockers**. These do not prevent advancing the ticket to the
next verification status after all automatable deploy work is complete, but they must be recorded
as blocker metadata before returning.

Detect project-specific manual-deploy blockers from the project's own context — search project
memory and read the project `CLAUDE.md` / `AGENTS.md` / deployment guide for any repo or service
that a specific person must deploy by hand. Detect via: the ticket's primary repo; the ticket
artifacts/deployment guide; coordinated changes in the dependency repo's diff/PR; or an explicit
project-memory note. When one applies, record blocker metadata (`blocked_by`, `blocked_reason`,
`blocked_context`) before returning, and never deploy that service yourself.

*Example (ts-prefect):* `ts-decrypt-proxy` production deployment is **Thomas-only** (project memory
entry `216431b0`). Set `blocked_by="Thomas"`,
`blocked_reason="Waiting for Thomas to deploy ts-decrypt-proxy to production"`,
`blocked_context={"repo":"ts-decrypt-proxy","target":"production","manual_deploy_owner":"Thomas"}`,
and do not deploy `ts-decrypt-proxy` production yourself.

### Phase 6b: Preflight every deploy command before merge

Build the exact ordered command table for Phase 8 while the PR can still be stopped safely. Every
row must have a preflight result:

- validate script/module imports and CLI argument shape (`--help`, compile/import, config parse, or
  the project's non-mutating plan/dry-run command);
- when the project documents a safe idempotent staging mirror, execute the same command shape there
  with **staging credentials only** and verify its postcondition;
- when no staging mirror exists, use a non-mutating production plan/readiness check — never invent a
  fake dry-run flag and never perform the production mutation as the preflight.

Record `command`, `target`, `preflight`, and `expected postcondition`. A missing/failed preflight is
a STOP before merge. The preflight does not replace the real deploy or its verification; it catches
bad imports, stale flags, wrong YAML/entrypoints, and environment selection before production code
lands.

### Phase 7: Merge PR

```bash
gh pr merge {pr_number} {repository-approved merge flag}
```

Determine the merge flag from the repository's authoritative instructions and GitHub merge-policy
settings. Use `--rebase` only when rebase merges are permitted; use `--squash` for squash-only
repositories. Never guess a disallowed merge strategy.

Note: If the PR is already merged, skip this phase entirely.

### Phase 8: Run Deployment Steps

If a project-specific `/deploy` command was loaded in Phase 3, follow its
deployment steps **in order**, using the change detection from Phase 6 to
determine which steps to run.

**CRITICAL: Use the correct environment-specific commands.** The `/deploy`
command documents commands for each environment (staging vs production) with
different env files, Prefect API URLs, and YAML files. Match the commands to
the target environment determined in Phase 1.

**Generic fallback** (when no project-specific deploy exists):

1. **Migrations**: If migration files detected, rely on CI auto-migration
   (most projects run `migrate.yml` on push to main/staging)
2. **Dependencies**: If dependency files changed, flag to user that a
   service redeploy may be needed

**Execution rules:**

- **EXECUTE every automatable step directly** — do NOT just print the
  commands or tell the user to run them. The whole point of auto-deploy
  is autonomous execution. If the project deploy command provides a bash
  command for a step (migrations, blocks, Prefect deploy, DAG sync, etc.),
  run it yourself.
- Skip the project deploy command's "Confirm with User" phase — the ticket
  being at `ready_to_deploy` status IS the confirmation (or the user
  explicitly passed a target override, which is also confirmation).
- Run steps in the order specified by the project deploy command
- Each step depends on the previous one succeeding
- If a step fails: STOP, do not continue, revert ticket status
- Log output of each step for verification
- For production, prefer audited MCP/server-side mutations. Direct local production DB writes are
  prohibited. Any other authenticated production CLI step with no remote route must run as
  `bin/redacted-exec -- <documented command>`; never inspect the auth profile or write raw output to
  a compact-exec log.
- Only flag steps to the user that are **genuinely manual** and cannot be
  run from the CLI (e.g., clicking "Deploy" in a web dashboard). Steps
  that have CLI commands are not manual — run them.

**Deployment-guide reconciliation (MANDATORY, after the detected categories run).** The
project `/deploy` command is the per-repo source of truth for *how* standard categories
deploy — but the ticket's **`deployment_guide` artifact** (finalized by
`/create-build-todos`) is where *ticket-specific one-off steps* live: a new secret/
credential block, a new env var, a pre-enable backfill, a cross-repo ordering constraint.
Those exist in no generic category and are silently skipped unless reconciled here. After
executing the detected categories:

1. Read the guide's **Steps** section for the target environment (the artifact is already
   loaded from Phase 6's evidence-contract check).
2. For each guide step, classify and report it: `covered` (the project deploy command
   already ran it), `executed-now` (you ran it in this reconciliation), or `blocked`
   (genuinely manual — record blocker metadata per Phase 6).
3. A guide step that cannot be mapped to anything run, executed, or blocked is a **STOP
   condition**, not a skip — report it as a guide/deploy mismatch. Do not advance the
   ticket to a verification status with an unexecuted, unaccounted-for deploy step,
   because `/ticket-verify` will then fail (or worse, falsely pass) on an environment the
   guide says is incomplete.

Include the per-step reconciliation table in the Phase 9 verification checklist output.

If the diff removes or retires a route, writer, trigger, queue consumer, deployment, flag, or other
runtime surface, Phase 9 must also close the negative inventory recorded by the plan/deployment
guide: code/config search shows each old item absent, authoritative live inventory shows retired
registrations absent, and the surviving route is exercised. An unexplained legacy item is a failed
deploy verification.

### Phase 9: Verify Deployment

After all deployment steps complete, verify each one succeeded:

**Generic verification:**

| What              | How to Verify                           |
| ----------------- | --------------------------------------- |
| Code pushed       | `git log origin/{target} -1` matches merge |
| Migrations        | CI workflow completed successfully       |
| Service health    | No new errors in logs since merge       |
| Activation/content gates | If the deploy activates a DB-stored artifact (prompt version, feature flag, config row), **read the live row back and assert it equals the intended pinned value** — never assume the step set it, and never trust "latest". A project gate command (if any) must report the actual value, not the planned one |

**Bounded log reads (always):** never pull full unbounded logs into context. Constrain every
log read to the time window since the deploy AND a generous tail cap (e.g. the last 2000
lines). If the windowed log is still larger than that, spawn a haiku subagent with
`fork_turns: "none"` and only the log path, time window, feature terms, and output cap; work from
its relevant excerpts (errors and feature-specific lines).

**Project-specific verification** (from `/deploy` command):

Follow any post-deployment verification steps defined in the project
deploy command.

**Verification checklist (log each):**

```
Deployment verification:
  Target:            {staging|production}
  Code pushed:       [yes/no]
  Migrations:        [ran/skipped/CI-handled] - [verified/pending]
  Config deploys:    [ran/skipped] - [verified/pending]
  Dependencies:      [unchanged/flagged-for-redeploy]
  Project-specific:  [list each step and result]
```

### Phase 10: Set Status + Blockers

Set status based on the target environment. Use `update_ticket` for a standalone ticket and
`update_epic` for an epic — both staging and prod verification statuses now exist on each enum:

```
# Staging deploy — standalone ticket:
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="to_verify_staging",
  command="/auto-deploy"
)
# Staging deploy — epic (to_verify_staging is also an epic_status):
mcp__autodev-memory__update_epic(
  project=PROJECT, epic_id=EPIC_ID,
  status="to_verify_staging",
  command="/auto-deploy"
)

# Production deploy — standalone ticket (or update_epic for the epic itself):
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="to_verify_prod",
  command="/auto-deploy"
)
```

If a blocker was detected, set the status **and** blocker metadata in the same final update when
the MCP surface supports it:

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="to_verify_prod",
  blocked=True,
  blocked_by="Thomas",
  blocked_reason="Waiting for Thomas to deploy ts-decrypt-proxy to production",
  blocked_context={
    "repo": "ts-decrypt-proxy",
    "target": "production",
    "manual_deploy_owner": "Thomas"
  },
  command="/auto-deploy"
)
```

If the MCP tool schema in the current session has not yet refreshed to expose blocker fields,
do not fall back to a fake `blocked` status and do not hide the blocker in `tags`. Instead:

1. set the lifecycle status normally (`to_verify_prod` / `to_verify_staging`);
2. add/log a ticket event or comment with the blocker details if available;
3. explicitly report that blocker metadata could not be written because the MCP schema is stale
   or the autodev-memory blocker migration/API is not deployed.

When blocker metadata is written successfully, the dashboard should show the ticket in its normal
status column with a red blocker indicator/hover card.

## On Failure — Revert Status

If deploy fails at any phase, revert status to what it was before — on the same unit that was
being deployed (branch on unit type, mirroring Phase 10):

```
# Standalone ticket deploy:
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="{original_status}",
  command="/auto-deploy"
)

# Epic deploy (staging or prod) — original_status may be an epic-only value:
mcp__autodev-memory__update_epic(
  project=PROJECT, epic_id=EPIC_ID,
  status="{original_status}",
  command="/auto-deploy"
)
```

## Error Handling

| Phase          | Error                | Action                              |
| -------------- | -------------------- | ----------------------------------- |
| Validate       | Ticket not found     | STOP, report                        |
| Validate       | Wrong status         | STOP, report                        |
| Find PR        | No PR found          | STOP, report                        |
| Check CI       | Checks failing       | Self-heal; STOP only at human-judgment gate |
| Rebase         | Conflicts            | STOP, report (manual resolution)    |
| Rebase         | CI fails after rebase| Self-heal; STOP only at human-judgment gate |
| Detect         | Detection error      | STOP, report                        |
| Merge          | Merge failure        | STOP, report (don't change status)  |
| Deploy Steps   | Step failure         | STOP at failed step, report         |
| Deploy Steps   | Manual step needed   | Flag to user, wait for confirmation |
| Verify         | Verification failure | STOP, revert status to what it was before auto-deploy started, report |

Auto-deploy never sets `verify_staging_failed` / `verify_prod_failed` — those verdicts belong
to `/ticket-verify` after behavior/evidence verification.

## Output

### On Success

```
Auto-deploy complete for {ID}: {title}

Target: {staging|production}
PR #{pr_number} rebased and merged to {target_branch}.

Deployment steps:
  Code pushed:    yes
  Migrations:     {ran/skipped}
  {project-specific steps...}
  Dependencies:   {unchanged/flagged}

Verification: all steps confirmed

Status: {to_verify_staging|to_verify_prod} (ready for verification)

Next: /ticket-verify {staging|production} {ID} (verify behavior/evidence)
```

### On Failure

```
Auto-deploy failed for {ID} at: {phase}

Reason: {error description}

Status reverted to: {original_status}
```

## Relation to Other Commands

| Command        | When to Use                                          |
| -------------- | ---------------------------------------------------- |
| `/ticket-flow` | Orchestrates the full standalone ticket path (its build phase pushes the branch, no PR) and invokes `/auto-deploy` for staging-first or direct-production deployment |
| `/auto-deploy` | This command — creates PR, rebases, merges, deploys, verifies deployment mechanics |
| `/ticket-verify` | Next step — verifies feature behavior/evidence in staging or production |
| `/ticket-promote` | Post-staging path — lands staging-verified work on main and runs prod deploy steps |
| `/milestone-flow` | Parent orchestrator for milestone-by-milestone epic staging deploy/verify gates |
| `/epic-flow` | Sequences milestone-flow runs and owns final production promotion/verification |
| `/deploy`      | Project-specific deployment (consumed by auto-deploy)|

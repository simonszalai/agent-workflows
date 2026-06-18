---
name: auto-deploy
description: Autonomous deployment. Deploys PR to staging or production, runs migrations/blocks/deploys, updates ticket status.
max_turns: 100
---

# Auto-Deploy Command

Autonomous deployment that picks up a unit ready to deploy, deploys its PR to the target
environment, and advances its status. **Both standalone tickets and epics can use the staging
segment** (per-ticket staging statuses were added in migration 025): a unit at
`ready_to_deploy_staging` deploys to staging and advances to `to_verify_staging`; a unit at
`ready_to_deploy_production` deploys to prod and advances to `to_verify_prod`. A standalone
ticket may be landed straight to prod or routed through staging first, depending on its target.
Epic **members** are still carried by the epic — they reach `merged` and are not deployed
individually by a scheduled pickup. The ordered epic walk is owned by `/epic-flow --full-auto`:
after each milestone it invokes this skill for the parent epic's staging deploy, then invokes the
explicit epic/milestone verifier. After all milestone staging gates pass, `/epic-flow` uses
`/promote-to-production --epic` for the ordered production promotion/deploy path.

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
/auto-deploy                        # (scheduled) Pick up next standalone ticket at ready_to_deploy_production, or epic at ready_to_deploy_staging
```

## When to Use

- After `/auto-build` completes for a standalone ticket (deploys to production)
- For an epic staging gate: after milestone members are `merged`, when called by `/epic-flow`
  (deploys the parent epic to staging)
- For epic production promotion/deploy: prefer `/promote-to-production --epic`, which owns the
  ordered verified-step promotion path
- Scheduled agent picks up standalone `ready_to_deploy_production` tickets and
  `ready_to_deploy_staging` epics automatically
- Manual trigger when you want to deploy a specific ticket or epic

## Prerequisites

- A standalone ticket at `ready_to_deploy_production`, or an epic at
  `ready_to_deploy_staging` / `ready_to_deploy_production` (unless target is overridden via
  argument)
- Feature branch must exist on remote (created + pushed by `/auto-build`)
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
| `ready_to_deploy_production` | Ticket/Epic | Production    | `to_verify_prod`     |

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
5.  Rebase         -> Rebase PR onto target branch (linear history, avoid conflicts)
6.  Detect Changes -> Analyze what changed for deployment decisions
7.  Merge PR       -> Merge PR to target branch
8.  Deploy Steps   -> Run project-specific deployment steps for target environment
9.  Verify         -> Confirm each deployment step succeeded
10. Set Status + Blockers -> Update next status and independent blocker metadata
```

**PR creation moved here from auto-build.** Auto-build now pushes a feature branch
without opening a PR. Auto-deploy creates the PR as its first action (Phase 2) so the
PR reflects the final state after any auto-polish iterations on the branch.

## Detailed Process

### Phase 1: Validate Ticket

```
ticket = mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO
)
```

- If not found: STOP - "Ticket not found"
- Parse arguments: if second arg is `staging` or `production`, use as target override
- If no override: check ticket status is `ready_to_deploy_staging` or `ready_to_deploy_production`
- If override provided: accept any non-terminal ticket status
- Determine target environment and corresponding deploy config

### Phase 2: Find or Create PR

```bash
gh pr list --search "auto-build/{ticket-id} OR lfg/{ticket-id}" \
  --state all --json number,url,headRefName,state
```

- **PR found, open:** continue to Phase 3
- **PR found, already merged:** skip the merge phase (Phase 7), continue to deploy steps
- **No PR found:** verify the feature branch exists on remote; then run
  `/create-pr {ticket-id}` internally to:
  1. Collect all ticket artifacts (plan, build_todos, review_todos, polish_report,
     deployment_guide) via `get_ticket`
  2. Generate the PR summary from those artifacts + test results
  3. Create the PR against the target branch with the generated body

  Output the PR URL.

If the branch is not found on remote either: STOP - "No feature branch or PR for this
ticket. Run /auto-build first."

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
gh pr checks {pr_number}
```

- If checks failing: STOP - "CI checks failing, cannot deploy"
- If checks pending: Wait up to 10 minutes, then STOP if still pending
- If PR already merged: skip CI check (already passed)

### Phase 5: Rebase onto Target Branch (CRITICAL)

Determine the target branch based on environment:
- **Staging**: rebase onto `staging`
- **Production**: rebase onto `main`

Rebase the PR branch onto the target to ensure linear history and avoid migration
conflicts. Database migrations depend on sequential ordering — merging a PR
whose base is behind the target can cause migration graph conflicts.

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

Wait for CI to re-run after rebase (checks must pass again).

If rebase has conflicts: STOP - "Rebase conflicts, manual resolution needed"

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
| Migrations   | Files in `alembic/versions/`, `migrations/`         |
| Config       | Deployment config files (YAML, env, etc.)           |
| Dependencies | `pyproject.toml`, `Dockerfile`, `requirements.txt`  |

**Project-specific categories** (from `/deploy` command if loaded):

The project-specific deploy command may define additional categories like
blocks, Prefect config, DAG nodes, etc. Detect all categories it specifies.

Store detection results for use in Phase 8.

Also detect **external/manual deploy blockers**. These do not prevent advancing the ticket to the
next verification status after all automatable deploy work is complete, but they must be recorded
as blocker metadata before returning.

Known blocker rules:

| Condition | Blocker metadata |
| --------- | ---------------- |
| Ticket changes or depends on `ts-decrypt-proxy` production deployment | `blocked_by="Thomas"`, `blocked_reason="Waiting for Thomas to deploy ts-decrypt-proxy to production"`, `blocked_context={"repo":"ts-decrypt-proxy","target":"production","manual_deploy_owner":"Thomas"}` |

How to detect the `ts-decrypt-proxy` blocker:

- the ticket's primary repo is `ts-decrypt-proxy`; or
- the ticket artifacts/deployment guide mention `ts-decrypt-proxy` production deployment; or
- the diff/PR includes coordinated changes in `ts-decrypt-proxy`; or
- the user/project memory says this ticket is waiting on a decrypt-proxy deploy.

Operational memory to load when in doubt: "ts-decrypt-proxy production deployment is
Thomas-only". Do not attempt to deploy `ts-decrypt-proxy` production yourself.

### Phase 7: Merge PR

```bash
gh pr merge {pr_number} --rebase
```

Using `--rebase` for linear history (no merge commits).

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
- Only flag steps to the user that are **genuinely manual** and cannot be
  run from the CLI (e.g., clicking "Deploy" in a web dashboard). Steps
  that have CLI commands are not manual — run them.

### Phase 9: Verify Deployment

After all deployment steps complete, verify each one succeeded:

**Generic verification:**

| What              | How to Verify                           |
| ----------------- | --------------------------------------- |
| Code pushed       | `git log origin/{target} -1` matches merge |
| Migrations        | CI workflow completed successfully       |
| Service health    | No new errors in logs since merge       |
| Activation/content gates | If the deploy activates a DB-stored artifact (prompt version, feature flag, config row), **read the live row back and assert it equals the intended pinned value** — never assume the step set it, and never trust "latest". A project gate command (if any) must report the actual value, not the planned one |

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
| Check CI       | Checks failing       | STOP, report (don't change status)  |
| Rebase         | Conflicts            | STOP, report (manual resolution)    |
| Rebase         | CI fails after rebase| STOP, report                        |
| Detect         | Detection error      | STOP, report                        |
| Merge          | Merge failure        | STOP, report (don't change status)  |
| Deploy Steps   | Step failure         | STOP at failed step, report         |
| Deploy Steps   | Manual step needed   | Flag to user, wait for confirmation |
| Verify         | Verification failure | Set verify_staging_failed (epic) / verify_prod_failed (ticket or epic), report |

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
| `/auto-build`  | Previous step — pushes branch (no PR); sets merged (member) / ready_to_deploy_production (standalone) |
| `/auto-deploy` | This command — creates PR, rebases, merges, deploys, verifies deployment mechanics |
| `/ticket-verify` | Next step — verifies feature behavior/evidence in staging or production |
| `/epic-flow` | Parent orchestrator for milestone-by-milestone epic deploy/verify gates |
| `/deploy`      | Project-specific deployment (consumed by auto-deploy)|

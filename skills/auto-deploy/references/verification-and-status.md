# Deployment verification, lifecycle status, and output

Load this reference only when executing P9 or P10, or when reverting after a failed phase.

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
lines). Filter with grep for errors and feature terms rather than reading the tail whole. Only
when the windowed log is genuinely too large to filter down (roughly >5k lines after grep) is it
worth a haiku subagent with `fork_turns: "none"` and only the log path, time window, feature
terms, and output cap; work from its relevant excerpts.

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
  Staging back-sync: [n/a (staging target)/already-synced/synced @ <sha>/blocked: <reason>]
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
| Deploy Steps   | Step failure         | Production: STOP; staging: apply staging-autonomy repair lane, then stop only at its boundary |
| Deploy Steps   | Manual step needed   | Prove no callable route; staging-safe work executes instead of waiting for confirmation |
| Verify         | Verification failure | STOP, revert status to what it was before auto-deploy started, report |

Auto-deploy never sets `verify_staging_failed` / `verify_prod_failed` — those verdicts belong
to `/ticket-verify` after behavior/evidence verification.

## Output

Before emitting either terminal report, load and apply
`skills/references/terminal-outcomes.md`. When `/auto-deploy` was invoked directly, run its
post-check after the final deploy/status action and put the environment-specific deploy
success/failure banner and confirmation block before the existing details. When a parent workflow
invoked it, report the deploy result and let the parent own the post-check and outer banner.
A successful deploy is not final ticket closure: its closeout result stays
`NOT READY` until `/ticket-verify` proves behavior and cleanup.

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

# Auto-deploy lifecycle

Load this reference only when executing P1, P2, P4, P5, or P7 from the phase manifest.
The compact skill owns routing and the literal Conductor wait recipe.

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


### Phase 4: Check CI

```bash
wait-ci {pr_number} --timeout 540
```

- Under Conductor, dispatch that exact deterministic command immediately to one fresh
  `fork_turns: "none"` leaf and block once for its compact terminal result. The parent must not
  start the wait, poll the leaf or a resumable parent process, substitute `gh ... --watch`, or use
  repeated GitHub status reads. Outside Conductor, invoke it as one blocking foreground tool call
  with an outer timeout above 540 seconds and consume its one JSON result.
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
`wait-ci {pr_number} --timeout 540` invocation, using one new no-history waiter leaf under
Conductor. Repair mechanical failures through the same CI
self-heal loop. If it times out, return its resume command; never turn GitHub polling into repeated
model turns.

If the repository-approved branch update has conflicts: STOP and report the exact conflict.


### Phase 7: Merge PR

```bash
gh pr merge {pr_number} {repository-approved merge flag}
```

Determine the merge flag from the repository's authoritative instructions and GitHub merge-policy
settings. Use `--rebase` only when rebase merges are permitted; use `--squash` for squash-only
repositories. Never guess a disallowed merge strategy.

Confirm the PR state is `MERGED`. When this invocation merged the PR whose head is the current
Conductor workspace branch, classify that head using the repository's branch policy. For a
throwaway feature head, delete only its remote branch and run:

```bash
align-merged-pr-workspace {pr_number}
```

It must report `aligned` or `already_aligned` before Phase 8. Do not use a normal post-merge rebase:
multi-commit squash merges can replay or conflict. Do not delete or align `main`, `staging`, or any
other repository-defined long-lived head. If the PR was already merged before this invocation, skip
both the merge and current-workspace cleanup.


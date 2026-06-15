---
name: auto-build
description: Autonomous build from approved plan. Builds on the current branch, reviews, resolves, verifies, and pushes. Does NOT create a branch (the Conductor workspace already provides one) and does NOT create the PR — that is the first action of /auto-deploy.
max_turns: 200
---

# Auto-Build Command

Fully autonomous build workflow that runs after plan approval. Runs on the **current branch**
(provided by the Conductor workspace or cloud session — auto-build does not create one),
executes all build steps, runs reviews, resolves findings, verifies locally, and pushes the
branch. PR creation is deferred to `/auto-deploy`.

## Usage

```
/auto-build F007                    # Auto-build feature F007
/auto-build 009                     # Auto-build bug fix 009
/auto-build F007 --skip-verify      # Skip local verification step
/auto-build F007 --review-pause     # Pause after review for user decision
```

## When to Use

- **From Claude Code on the web**: Send `& /auto-build F007` to run autonomously in cloud
- **From terminal**: Use when you've approved a plan and want hands-off execution
- **Best for**: Well-defined features with clear acceptance criteria

## Prerequisites

- A `plan` artifact must exist on the ticket (read via `get_ticket`)
- Must be on a feature branch — **not** `main` or `staging`. Conductor workspaces always
  start on a dedicated branch; cloud sessions are similarly pre-branched. Auto-build will
  refuse to run on `main` or `staging` and will NOT create a new branch on its own.
- For cloud: SessionStart hook configures environment automatically

## Process Overview

```
1.  Validate     -> Check ticket exists, plan artifact is present, on a feature branch
2.  Setup        -> Set status to "in_progress", verify environment (branch already exists)
3.  Build Todos  -> /create-build-todos (deep research)
4.  Build        -> /build (implement each step)
5.  Write Tests  -> /write-tests (test coverage for new code)
6.  Review       -> /review mode:cross (Claude + Codex + Grok, merged)  ┐ cross-review
7.  Resolve      -> Claude fixes actionable findings; re-review         ┘ loop, ≤3 rounds
8.  Compound     -> /compound (learn from review, apply improvements)
9.  Deploy Guide -> /create-deployment-guide (deployment instructions)
10. Push Branch  -> Push the current branch to remote (NO PR created here)
11. Set Status   -> epic member -> "merged"; standalone ticket -> "ready_to_deploy_production"
```

**This skill does NOT create a PR.** PR creation is the first action of `/auto-deploy`.
UI polish (`/auto-polish-web`) runs as a separate sibling step orchestrated by
`/auto-flow`, after auto-build and before auto-deploy.

## Unrelated errors → fix them, in a separate commit

While building, the type checker, linter, and reviewers will sometimes surface
errors that are **not caused by this work** — pre-existing problems in files the
ticket never touched, latent type errors, lint violations, dead imports, broken
references, etc.

Do not ignore them, and do not fold them into the feature/fix work. Instead:

1. **Fix them** when the fix is clear and low-risk: a few lines, an obvious
   correction, no behavior change to unrelated features.
2. **Keep them out of the main diff.** Commit the unrelated fixes **separately**
   from the ticket's work (its own commit, before the push in Phase 9), with their
   own conventional message:
   ```
   fix: resolve pre-existing lint/type errors surfaced during /auto-build
   ```
   List the files and the specific errors fixed in the body.
3. **Don't balloon scope.** If an unrelated error needs a real change (a risky
   refactor, ambiguous intent, or it touches a feature you can't verify), do
   **not** fix it — note it in the ticket and the final report as a follow-up.

Track unrelated errors and their fixes as you encounter them across the build and
review phases so Phase 9 can commit them as one clean, independently reviewable
unit. This applies to `/auto-flow` too, since it delegates building to this skill.

## Detailed Process

### Phase 1: Validate and Setup

1. **Validate ticket:**
   - Load ticket: `mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)`
   - Check plan artifact exists — if not: STOP - "Plan artifact not found"

2. **Validate branch:**
   - Run `git rev-parse --abbrev-ref HEAD` to get current branch
   - If on `main` or `staging`: STOP — "auto-build must run on a feature branch. Start a
     Conductor workspace (or check out a branch) before running /auto-build."
   - **Do NOT create a branch.** The Conductor workspace (or cloud session) already
     provides a dedicated branch; creating another one branches off mid-flow and causes
     confusion.

3. **Set status to in_progress:**
   ```
   mcp__autodev-memory__update_ticket(
     project=PROJECT, ticket_id=ID, repo=REPO,
     status="in_progress",
     command="/auto-build"
   )
   ```

4. **Verify environment:**
   - Check required services are running
   - Check database connectivity
   - If cloud (`CLAUDE_CODE_REMOTE=true`): Environment already set up by hook

### Phase 2: Create Build Todos

Run `/create-build-todos` internally:

- Spawns `build-planner` agent for deep research
- Creates build_todo artifacts with detailed implementation steps
- Each step includes discovered patterns and conventions

**On failure:** Log error, report to user, do not continue.

### Phase 4: Build

Run `/build` internally for each build todo:

- Execute steps in dependency order
- Run tests after each step
- Run type checker
- Run linter

**On test failure:**

1. Attempt automatic fix (up to 2 retries)
2. If still failing: Log details, continue to write tests phase
3. Review will flag remaining issues

**On unrelated type/lint errors** (pre-existing failures in files this ticket
didn't touch): fix the clear, low-risk ones and track them for the separate
commit in Phase 9; defer the risky/ambiguous ones to a follow-up note on the
ticket. See [Unrelated errors → fix them, in a separate commit](#unrelated-errors--fix-them-in-a-separate-commit).

### Phase 4: Write Tests

Run `/write-tests {work-item-id}` internally:

1. Analyze all code changes from the build phase
2. Classify changed code: pure logic, DB operations, API routes, user flows
3. Write tests at the appropriate level:
   - **Unit tests** (vitest) for data transformations, business logic, validators
   - **Integration tests** (vitest + DB) for model functions with query logic
   - **E2E tests** (playwright) for multi-step user flows
4. Run all new tests to verify they pass
5. Run full test suite to verify no regressions

**Test scope:** Only test code written in Phase 3. Don't test unrelated code.

**On failure:** Log details, continue to review phase. Review will catch test gaps.

### Phase 5–6: Cross-Review Iteration Loop (review + resolve)

Run the **Cross-Review Iteration Loop** from the `review` skill instead of a single
review-then-resolve pass. Each round:

1. Run `/review mode:cross` — Claude's native reviewers (quality/YAGNI/patterns;
   architecture/security/performance; data if DB changes) **plus** external Codex and Grok
   reviewers, each run inside an `external-reviewer` subagent (which calls the `external-agent`
   adapter) in the same parallel batch. All findings merge
   through one synthesis with a cross-provider confidence boost, and store as review_todo
   artifacts.
2. Resolve the actionable findings (Claude fixes — `safe_auto` inline, `gated_auto`/`manual`
   via `/resolve-review` logic), re-run affected tests, run the type checker.

Repeat up to **3 rounds**, or stop earlier when the merged result has no actionable
(`safe_auto`/`gated_auto`/`manual`) findings. `advisory` and gate-suppressed nits do not
re-trigger a round. After round 3, surface any remaining `gated_auto`/`manual` findings.

**If `--review-pause`:** stop after the first round's review, notify the user, wait for
decisions.

Reviewers may also flag problems that are **unrelated** to this work (pre-existing issues in
untouched code). Fix the clear, low-risk ones and track them for the separate Phase 9 commit;
defer the rest as a follow-up note on the ticket. See
[Unrelated errors → fix them, in a separate commit](#unrelated-errors--fix-them-in-a-separate-commit).

### Phase 7: Compound Learnings

Run `/compound` in **autonomous mode** to learn from the build and review process.

1. Analyze resolved review findings for upstream gaps
2. Identify improvements to memory entries, skills, and workflows
3. Auto-apply all improvements (no user approval needed in auto-build)
4. Store all learnings in memory service (critical for cloud persistence)
5. Report what was changed

**Cloud note:** In cloud environments, file-based changes from /compound are ephemeral.
Memory service saves are the **persistent** knowledge channel. The compound skill
handles this automatically via its "Store in Memory Service" step.

**On no findings:** Skip this phase (nothing to learn from).

**On error:** Log details, continue to deployment guide (non-blocking).

### Phase 8: Create Deployment Guide

Run `/create-deployment-guide` internally:

1. **Analyze changes for deployment impact:**
   - Database migrations
   - New services/jobs
   - Configuration changes
   - Multi-service dependencies

2. **Generate deployment-guide.md:**
   - Pre-deployment checklist
   - Deployment steps in order
   - Post-deployment verification queries/commands
   - Rollback plan
   - Monitoring requirements

3. **Check for special requirements:**
   - Schema changes -> migration steps
   - Multi-service -> coordination requirements

**Output:** `deployment-guide.md` in work item folder.

**On trivial changes:** May skip if changes don't require deployment steps (e.g., doc-only).

**On error:** Log details, continue to verification (non-blocking).

### Phase 9: Commit and Push Branch

Commit any remaining staged changes and push the **current** branch to the remote. **Do NOT
create a PR here** — PR creation is the first action of `/auto-deploy`.

First, if any **unrelated** lint/type/review fixes were made during the build (see
[Unrelated errors → fix them, in a separate commit](#unrelated-errors--fix-them-in-a-separate-commit)),
commit just those files **on their own**, so the cleanup stays separate from the
feature/fix diff and is independently reviewable/revertable:

```bash
# only if unrelated fixes exist — stage just those files explicitly
git add <unrelated-files...>
git commit -m "fix: resolve pre-existing lint/type errors surfaced during /auto-build"
```

Then commit the ticket's own outstanding changes and push:

```bash
git add -A
git commit -m "<descriptive message for any outstanding changes>" || true  # ok if nothing to commit
BRANCH=$(git rev-parse --abbrev-ref HEAD)
git push -u origin "$BRANCH"
```

Reasons the PR is deferred to auto-deploy:

- Lets `/auto-polish-web` iterate on the branch between build and deploy without generating
  PR-update noise for every polish commit
- Keeps the PR summary fresh — it's generated at deploy time from the final ticket
  artifacts (plan, build_todos, review_todos, polish_report, deployment_guide)
- Aligns the PR lifecycle with the deploy lifecycle — one PR, one merge, one deploy

### Phase 10: Set Status (member vs standalone)

Branch on epic membership — a ticket is an **epic member** iff its `epic_id` is set (check
the `get_ticket` response from Phase 1):

```
# Epic member: the epic owns staging/prod, so the member stops at `merged`.
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="merged",
  command="/auto-build"
)

# Standalone ticket: goes straight to the prod deploy queue (no staging segment).
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="ready_to_deploy_production",
  command="/auto-build"
)
```

## On Failure — Revert Status

If the build fails at any phase, revert status to the prior status the ticket had when
auto-build started (typically `planned`):

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="<prior_status>",
  command="/auto-build"
)
```

## Error Handling

| Phase        | Error                    | Action                                  |
| ------------ | ------------------------ | --------------------------------------- |
| Setup        | On main/staging branch   | STOP, instruct user to use a workspace  |
| Build Todos  | Agent failure            | STOP, report                            |
| Build        | Test failure             | Retry 2x, then continue                 |
| Build        | Type error               | Attempt fix, continue                   |
| Build/Resolve| Unrelated error, clear   | Fix it; commit separately in Phase 9    |
| Build/Resolve| Unrelated error, risky   | Don't fix; note on ticket as follow-up  |
| Write Tests  | Test creation fails      | Log, continue to review (non-blocking)  |
| Write Tests  | New tests fail           | Fix tests, retry once, then continue    |
| Review       | Agent failure            | Log, continue with partial review       |
| Resolve      | Fix introduces new error | Revert fix, mark as deferred            |
| Compound     | Analysis failure         | Log, continue (non-blocking)            |
| Compound     | Improvement write fails  | Log, continue (non-blocking)            |
| Deploy Guide | Generation failure       | Log, continue (non-blocking)            |
| Push Branch  | Push failure             | Report, provide manual instructions     |

## Cloud vs Local Differences

| Aspect            | Cloud                       | Local (Conductor workspace) |
| ----------------- | --------------------------- | --------------------------- |
| Environment setup | SessionStart hook           | Workspace setup             |
| Database          | Pre-configured              | Must be running             |
| Services          | Started by hook             | Must be running             |
| Branch            | Provided by session         | Provided by workspace       |
| User interaction  | Async notifications         | Real-time in terminal       |

In both cases, **auto-build does not create a branch** — it uses whatever branch is already
checked out.

## Output

### On Success

```
Auto-build complete!

Branch: {current branch} (pushed to origin, no PR yet)

Summary:
- Implemented {feature description}
- Tests: 15 passing / 15 total (8 unit, 5 integration, 2 e2e)
- Verification: PASS
- Review: 4 findings resolved
- Unrelated fixes: 1 pre-existing lint error in untouched code (separate commit)

Ticket: F0007 (status: merged [epic member] | ready_to_deploy_production [standalone])

Next: /auto-polish-web {ID} (UI polish, optional) then /auto-deploy {ID} (creates PR + deploys)
```

### On Partial Success

```
Auto-build needs attention!

Branch: {current branch} (pushed)

Summary:
- Implemented {feature description}
- Tests: 14 passing / 15 total
- Verification: FAIL (1 scenario)
- Review: 3 findings resolved, 1 P3 remaining

Ticket: F0007

Next: Fix attention items, then /auto-polish-web or /auto-deploy
```

### On Failure

```
Auto-build failed at: {phase}

Reason: {error description}

Ticket: F0007
See ticket F0007 for partial progress
```

## Work Log Entry

Progress is tracked via ticket status changes and artifacts (build_todos, review_todos,
deployment_guide) in the MCP ticket system — the `update_ticket` status transitions are
themselves logged as ticket events. No `plan.md` work-log file is written.

## Relation to Other Commands

| Command                | When to Use                                          |
| ---------------------- | ---------------------------------------------------- |
| `/auto-plan`           | Previous step — creates plan, sets status to planned |
| `/auto-build`          | This command — picks up `planned`, builds + pushes branch (no PR) |
| `/auto-polish-web`     | Next step (sibling) — UI polish on the pushed branch before deploy |
| `/auto-deploy`         | Next step — creates PR, deploys, sets to_verify_prod  |
| `/auto-verify`         | After deploy — observes staging/prod, collects evidence |
| `/build`               | For manual step-by-step building                     |
| `/review`              | For manual review (auto-build includes this)         |

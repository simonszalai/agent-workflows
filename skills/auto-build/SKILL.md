---
name: auto-build
description: Autonomous build from approved plan. Creates branch, builds, reviews, resolves, verifies, and creates PR.
max_turns: 200
---

# Auto-Build Command

Fully autonomous build workflow that runs after plan approval. Creates a feature branch, executes
all build steps, runs reviews, resolves findings, verifies locally, and produces a PR with a
summary report.

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

- `plan.md` must exist and be **approved** (user reviewed and accepted)
- For cloud: SessionStart hook configures environment automatically
- For local: Must be in a git worktree (not main branch)

## Process Overview

```
1.  Validate     -> Check ticket exists, status is approved
2.  Setup        -> Set status to "building", create branch, verify environment
3.  Build Todos  -> /create-build-todos (deep research)
4.  Build        -> /build (implement each step)
5.  Write Tests  -> /write-tests (test coverage for new code)
6.  Review       -> /review (parallel review agents)
7.  Resolve      -> Auto-resolve p1/p2 findings
8.  Compound     -> /compound (learn from review, apply improvements)
9.  Deploy Guide -> /create-deployment-guide (deployment instructions)
10. Verify       -> /verify local (test execution)
11. Create PR    -> /create-pr (summary + PR + link)
12. Set Status   -> Update to "ready_to_deploy"
```

## Detailed Process

### Phase 1: Validate and Setup

1. **Validate ticket status:**
   - Load ticket: `mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)`
   - If status is not `approved`: STOP and report "Ticket status is {status}, expected approved"
   - Check plan artifact exists — if not: STOP - "Plan artifact not found"

2. **Set status to building:**
   ```
   mcp__autodev-memory__update_ticket(
     project=PROJECT, ticket_id=ID, repo=REPO,
     status="building",
     command="/auto-build"
   )
   ```

3. **Create feature branch:**

   ```bash
   git checkout -b auto-build/{work-item-id}
   ```

3. **Verify environment:**
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

### Phase 5: Review

Run `/review` internally:

- Spawn review agents in parallel:
  - `reviewer` (quality, YAGNI, patterns)
  - `reviewer` (architecture, security, performance)
  - `reviewer` (data — if database changes)
- Store findings as review_todo artifacts

**If `--review-pause`:** Stop here, notify user, wait for decisions.

### Phase 6: Resolve Review Findings

For each finding in `review_todos/`:

| Priority        | Action                                 |
| --------------- | -------------------------------------- |
| p1 (critical)   | Auto-fix, these are clear bugs         |
| p2 (important)  | Auto-fix, these improve quality        |
| p3 (suggestion) | Auto-fix, these are worth implementing |

- Run `/resolve-review` logic
- Re-run affected tests
- Run type checker

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

### Phase 9: Local Verification

**Unless `--skip-verify`:**

Run `/verify local` internally:

1. Apply migrations
2. Seed test data
3. Execute tests with mocked external services
4. Verify expected outcomes
5. Generate verification report

**On verification failure:**

1. Log detailed failure info
2. Include in final report
3. PR will be marked as "needs attention"

### Phase 10: Create PR

Run `/create-pr {work-item-id}` internally:

1. Collects all ticket artifacts via `get_ticket` (plan, build_todos, review_todos,
   deployment_guide, etc.)
2. Runs tests and collects results
3. Generates standardized summary with:
   - What was done (implementation details)
   - Test results (counts by type, pass/fail)
   - Verification status
   - Review findings resolved
   - Deployment notes
   - Files changed
4. Commits all changes
5. Pushes to `auto-build/{work-item-id}` branch
6. Creates PR with summary as body
7. Outputs the PR link

### Phase 12: Set Status to Ready to Deploy

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="ready_to_deploy",
  command="/auto-build"
)
```

## On Failure — Revert Status

If the build fails at any phase, revert status to `approved`:

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="approved",
  command="/auto-build"
)
```

## Error Handling

| Phase        | Error                    | Action                                  |
| ------------ | ------------------------ | --------------------------------------- |
| Setup        | Plan not approved        | STOP, report                            |
| Setup        | Not in worktree (local)  | STOP, instruct user                     |
| Build Todos  | Agent failure            | STOP, report                            |
| Build        | Test failure             | Retry 2x, then continue                 |
| Build        | Type error               | Attempt fix, continue                   |
| Write Tests  | Test creation fails      | Log, continue to review (non-blocking)  |
| Write Tests  | New tests fail           | Fix tests, retry once, then continue    |
| Review       | Agent failure            | Log, continue with partial review       |
| Resolve      | Fix introduces new error | Revert fix, mark as deferred            |
| Compound     | Analysis failure         | Log, continue (non-blocking)            |
| Compound     | Improvement write fails  | Log, continue (non-blocking)            |
| Deploy Guide | Generation failure       | Log, continue (non-blocking)            |
| Verify       | Test failure             | Log details, mark PR as needs attention |
| PR           | Push failure             | Report, provide manual instructions     |

## Cloud vs Local Differences

| Aspect            | Cloud               | Local                 |
| ----------------- | ------------------- | --------------------- |
| Environment setup | SessionStart hook   | Manual / worktree     |
| Database          | Pre-configured      | Must be running       |
| Services          | Started by hook     | Must be running       |
| Branch creation   | Automatic           | Automatic             |
| PR creation       | `gh` CLI            | `gh` CLI              |
| User interaction  | Async notifications | Real-time in terminal |

## Output

### On Success

```
Auto-build complete!

PR: https://github.com/org/repo/pull/456

Summary:
- Implemented {feature description}
- Tests: 15 passing / 15 total (8 unit, 5 integration, 2 e2e)
- Verification: PASS
- Review: 4 findings resolved

Ticket: F0007
```

### On Partial Success

```
Auto-build needs attention!

PR: https://github.com/org/repo/pull/456 (marked needs attention)

Summary:
- Implemented {feature description}
- Tests: 14 passing / 15 total
- Verification: FAIL (1 scenario)
- Review: 3 findings resolved, 1 P3 remaining

Ticket: F0007
```

### On Failure

```
Auto-build failed at: {phase}

Reason: {error description}

Ticket: F0007
See ticket F0007 for partial progress
```

## Work Log Entry

After completion, adds to `plan.md`:

```markdown
| YYYY-MM-DD | auto-build | Autonomous build complete | PR: {url}, Status: {status} |
```

## Relation to Other Commands

| Command                | When to Use                                          |
| ---------------------- | ---------------------------------------------------- |
| `/auto-plan`           | Previous step — creates plan, sets status to planned |
| `/auto-build`          | This command — picks up approved, builds + PR        |
| `/auto-deploy`         | Next step — deploys PR, sets to_verify_staging       |
| `/auto-verify`         | After deploy — verifies staging, merges to main      |
| `/build`               | For manual step-by-step building                     |
| `/review`              | For manual review (auto-build includes this)         |
| `/verify local`        | For manual verification (auto-build includes this)   |

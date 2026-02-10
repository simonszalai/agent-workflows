---
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
1. Setup        -> Create branch, verify environment
2. Build Todos  -> /create-build-todos (deep research)
3. Build        -> /build (implement each step)
4. Review       -> /review (parallel review agents)
5. Resolve      -> Auto-resolve p1/p2 findings
6. Learn        -> Analyze findings, apply workflow improvements
7. Deploy Guide -> /create-deployment-guide (deployment instructions)
8. Verify       -> /verify-local (test execution)
9. Report       -> Generate summary, create PR
```

## Detailed Process

### Phase 1: Setup

1. **Verify plan is approved:**
   - Read `plan.md`
   - Check for approval indicator (user sign-off in work log or explicit approval)
   - If not approved: STOP and report "Plan needs approval first"

2. **Create feature branch:**

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
- Creates `build_todos/` with detailed implementation steps
- Each step includes discovered patterns and conventions

**On failure:** Log error, report to user, do not continue.

### Phase 3: Build

Run `/build` internally for each build todo:

- Execute steps in dependency order
- Run tests after each step
- Run type checker
- Run linter

**On test failure:**

1. Attempt automatic fix (up to 2 retries)
2. If still failing: Log details, continue to review phase
3. Review will flag remaining issues

### Phase 4: Review

Run `/review` internally:

- Spawn review agents in parallel:
  - `reviewer-code` (quality, YAGNI, patterns)
  - `reviewer-system` (architecture, security, performance)
  - `reviewer-data` (if database changes)
- Collect findings into `review_todos/`

**If `--review-pause`:** Stop here, notify user, wait for decisions.

### Phase 5: Resolve Review Findings

For each finding in `review_todos/`:

| Priority        | Action                                 |
| --------------- | -------------------------------------- |
| p1 (critical)   | Auto-fix, these are clear bugs         |
| p2 (important)  | Auto-fix, these improve quality        |
| p3 (suggestion) | Auto-fix, these are worth implementing |

- Run `/resolve-review` logic
- Re-run affected tests
- Run type checker

### Phase 6: Learn from Review

Analyze resolved findings to prevent recurrence and improve the workflow.

**Load skill:** `.claude/skills/learn-from-review/SKILL.md`

1. **Gather resolved findings:**
   - Read all files in `review_todos/` with status: resolved
   - Analyze all priorities (p1, p2, p3)

2. **Analyze each finding for upstream gaps:**

   | Gap Type          | Question                                      | Fix Target                          |
   | ----------------- | --------------------------------------------- | ----------------------------------- |
   | Knowledge Gap     | Should this have been a documented gotcha?    | `.claude/knowledge/gotchas/`        |
   | Plan Gap          | Should plan have identified this constraint?  | `.claude/skills/plan-methodology/`  |
   | Build Todos Gap   | Should build todos have referenced a pattern? | `.claude/skills/build-plan-method/` |
   | Review Prompt Gap | Should a review skill check for this?         | `.claude/skills/review-*/`          |
   | Implementation    | One-off mistake? (no systemic fix needed)     | None                                |

3. **Prioritize improvements:**
   - P1: 3+ findings from same gap, or security/data integrity
   - P2: 2 findings from same gap, or significant time wasted
   - P3: Single finding, low impact (document but defer)

4. **Apply improvements:**
   - Create knowledge docs with proper YAML frontmatter
   - Update skill checklists and research requirements
   - Add rules to AGENTS.md only for repeated violations

5. **Generate learning report:**
   - Create `learning-report.md` in work item folder
   - Summarize gaps found and improvements applied

**On no findings:** Skip this phase (nothing to learn from).

**On error:** Log details, continue to verification (non-blocking).

### Phase 7: Create Deployment Guide

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

### Phase 8: Local Verification

**Unless `--skip-verify`:**

Run `/verify-local` internally:

1. Apply migrations
2. Seed test data
3. Execute tests with mocked external services
4. Verify expected outcomes
5. Generate verification report

**On verification failure:**

1. Log detailed failure info
2. Include in final report
3. PR will be marked as "needs attention"

### Phase 9: Report and PR

1. **Generate summary report** (`auto-build-report.md`):

   ```markdown
   # Auto-Build Report: {work-item-id}

   **Branch:** auto-build/{work-item-id}
   **Status:** {COMPLETE|NEEDS_ATTENTION}
   **Date:** YYYY-MM-DD

   ## Build Summary

   - Build todos completed: N/N
   - Tests passing: X/Y
   - Type check: PASS/FAIL

   ## Review Summary

   - Findings: N total (X p1, Y p2, Z p3)
   - Auto-resolved: N
   - Deferred: N

   ## Learning Summary

   - Findings analyzed: N
   - Workflow improvements: N
   - Knowledge docs created: N
   - [Link to learning-report.md]

   ## Deployment Guide

   - Status: GENERATED/SKIPPED
   - [Link to deployment-guide.md]
   - Key steps: {summary of deployment steps}

   ## Verification Summary

   - Status: PASS/FAIL/SKIPPED
   - Scenarios tested: N
   - [Link to verification-report.md]

   ## Files Changed

   | File            | Change      |
   | --------------- | ----------- |
   | path/to/file.py | description |

   ## Issues Requiring Attention

   - [List any unresolved issues]

   ## Next Steps

   - [ ] Review PR
   - [ ] Merge to main
   - [ ] Deploy and verify in production
   ```

2. **Commit all changes:**

   ```bash
   git add -A
   git commit -m "Auto-build {work-item-id}: {title}

   - Completed N build steps
   - Resolved N review findings
   - Local verification: {status}

   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
   ```

3. **Push and create PR:**

   ```bash
   git push -u origin auto-build/{work-item-id}
   ```

   Create PR with:

   ```
   gh pr create --title "{work-item-id}: {title}" --body "$(cat auto-build-report.md)"
   ```

## Error Handling

| Phase        | Error                    | Action                                  |
| ------------ | ------------------------ | --------------------------------------- |
| Setup        | Plan not approved        | STOP, report                            |
| Setup        | Not in worktree (local)  | STOP, instruct user                     |
| Build Todos  | Agent failure            | STOP, report                            |
| Build        | Test failure             | Retry 2x, then continue                 |
| Build        | Type error               | Attempt fix, continue                   |
| Review       | Agent failure            | Log, continue with partial review       |
| Resolve      | Fix introduces new error | Revert fix, mark as deferred            |
| Learn        | Analysis failure         | Log, continue (non-blocking)            |
| Learn        | Improvement write fails  | Log, continue (non-blocking)            |
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

- Feature branch with all changes
- `auto-build-report.md` in work item folder
- `deployment-guide.md` in work item folder
- `verification-report.md` (unless skipped)
- PR ready for review
- Notification: "Auto-build complete for {id}. PR: {url}"

### On Partial Success

- Branch with partial changes
- Report documenting what succeeded/failed
- PR marked "needs attention"
- Notification: "Auto-build needs attention: {issues}"

### On Failure

- No PR created
- Detailed error report
- Notification: "Auto-build failed: {reason}"

## Work Log Entry

After completion, adds to `plan.md`:

```markdown
| YYYY-MM-DD | auto-build | Autonomous build complete | PR: {url}, Status: {status} |
```

## Relation to Other Commands

| Command         | When to Use                                        |
| --------------- | -------------------------------------------------- |
| `/plan`         | Before auto-build, to create plan                  |
| `/auto-build`   | After plan approved, for hands-off execution       |
| `/build`        | For manual step-by-step building                   |
| `/review`       | For manual review (auto-build includes this)       |
| `/verify-local` | For manual verification (auto-build includes this) |

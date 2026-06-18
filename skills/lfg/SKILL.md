---
name: lfg
description: Let's Fucking Go - Autonomous end-to-end workflow on the current branch from a GitHub issue, error report, or conversation. Commits before and after; never opens PRs.
max_turns: 300
---

# LFG Command

Let's Fucking Go. Autonomous workflow that takes a GitHub issue, error report,
**or conversation context** and delivers the work as commits on the **current
branch** of whichever repo(s) are touched. Handles features and bugs (including
production incidents with hypothesis-driven root cause analysis).

LFG operates **without the ticket system** — no tickets are created, no status
is tracked, no artifacts are stored in MCP. All coordination uses the
filesystem (`.context/` directory). For the ticket-tracked version, use
`/auto-flow`.

## What LFG does NOT do

These are hard rules. Never violate them:

- **Never open a pull request.** Not one, not many. The user opens PRs themselves
  when they're ready. Do not run `gh pr create` under any circumstances.
- **Never create a new branch.** Work happens on whatever branch is currently
  checked out. Do not run `git checkout -b`, `git switch -c`, or `git branch
  <new>`.
- **Never push.** Pushing is the user's call. Do not run `git push` (with or
  without `-u`, `-f`, etc.).
- **Never fan out across repos with separate branches/PRs.** If the task spans
  multiple repos (rare), commit on each repo's current branch in place. No
  branches, no PRs, no cross-repo coordination beyond the commits themselves.

If you find yourself reaching for any of those, stop and report back instead.

## Unrelated errors → fix them, in a separate commit

While building, the type checker, linter, and reviewers will sometimes surface
errors that are **not caused by this work** — pre-existing problems in files the
task never touched, latent type errors, lint violations, dead imports, broken
references, etc.

Do not ignore them, and do not fold them into the main feature/fix commit. Instead:

1. **Fix them** when the fix is clear and low-risk: a few lines, an obvious
   correction, no behavior change to unrelated features.
2. **Keep them out of the main diff.** Stage and commit the unrelated fixes
   **separately** from the work commit, with their own conventional message:
   ```
   fix: resolve pre-existing lint/type errors surfaced during /lfg
   ```
   List the files and the specific errors fixed in the body.
3. **Don't balloon scope.** If an unrelated error needs a real change (a risky
   refactor, ambiguous intent, or it touches a feature you can't verify), do
   **not** fix it — note it in the final report as a follow-up instead.

The result is up to three independently reviewable commits: the Phase 0
checkpoint (if any), the unrelated-fixes commit (if any), and the main work
commit. Track unrelated errors and their fixes in `.context/unrelated-fixes.md`
as you encounter them across phases.

## Usage

```
/lfg #123                    # GitHub issue number
/lfg 123                     # Same thing
/lfg https://github.com/org/repo/issues/123   # Full URL
/lfg                         # Use current conversation as input
/lfg --skip-verify           # Skip local verification step
```

## When to Use

- Quick autonomous execution without ticket overhead
- One-off fixes or features that don't need formal tracking
- Triggered from a GitHub issue or conversation thread
- Requirements are clear and you trust the workflow to make decisions

## Relation to /auto-flow

| Aspect      | `/lfg`                                     | `/auto-flow`                          |
| ----------- | ------------------------------------------ | ------------------------------------- |
| Ticket      | No ticket created                          | Creates and manages ticket lifecycle  |
| Status      | No status tracking                         | backlog -> in_progress -> planned -> ... |
| Artifacts   | Filesystem only (.context/)                | Stored in ticket system via MCP       |
| Resume      | Cannot resume from ticket                  | Resume via BNNN/FNNN                  |
| Branches    | Current branch only — no new branches      | May create branches                   |
| PRs         | Never opens a PR                           | Opens PR via `/auto-deploy`           |
| Pushing     | Never pushes                               | Pushes when needed                    |

## Input Detection

LFG detects its input source automatically:

| Invocation             | Input Source  | Behavior                            |
| ---------------------- | ------------- | ----------------------------------- |
| `/lfg #123` or number  | GitHub issue  | Fetch issue, extract requirements   |
| `/lfg` (no args)       | Conversation  | Extract requirements from thread    |

## Process Overview

```
0.  Pre-work checkpoint -> Commit any uncommitted state on the current branch as a checkpoint
1.  Parse Input         -> Extract type (bug/feature), requirements from issue OR conversation
2.  Research            -> Codebase research (features) or investigation (bugs)
3.  Plan                -> Spawn planner agent, write .context/plan.md
4.  Build Todos         -> /create-build-todos (deep research into implementation steps)
5.  Build               -> /build (implement each step)
6.  Write Tests         -> /write-tests (test coverage for new code)
7.  Review              -> /review mode:cross (runner + two peers, merged)     ┐ cross-review
8.  Resolve             -> runner fixes actionable findings; re-review         ┘ loop, ≤3 rounds
9.  Compound            -> /compound (learn from review, apply improvements)
10. Deploy Guide        -> /create-deployment-guide
11. Final commit        -> Commit the LFG work on the current branch (no push, no PR)
                           + a separate commit for any unrelated lint/type/review fixes
```

Throughout the build/review phases, unrelated errors surfaced by the type
checker, linter, or reviewers are fixed and tracked for their **own** commit —
see [Unrelated errors → fix them, in a separate commit](#unrelated-errors--fix-them-in-a-separate-commit).

## Detailed Process

### Phase 0: Pre-work checkpoint

Before doing anything else, capture the working tree as a checkpoint commit so
the LFG work has a clean starting point and is reviewable as a discrete diff.

For each repo that LFG will touch:

1. Confirm a branch is checked out (`git rev-parse --abbrev-ref HEAD`). If
   detached HEAD, STOP and ask the user to check out a branch.
2. Run `git status --porcelain`.
3. If there are any uncommitted modifications or untracked files that are not
   gitignored, stage them (`git add -A`) and create a checkpoint commit:
   ```
   chore: checkpoint before /lfg
   ```
   Include a one-line subject only. The user's pending work is preserved as a
   discrete commit, separable from LFG's output.
4. If the working tree is clean, no checkpoint commit is needed.

Do **not** create a branch. Do **not** push. Stay on whatever branch is
currently checked out.

### Phase 1: Parse Input

Determine input source and extract requirements.

**Source A: GitHub Issue** (when invoked with issue number/URL)

1. **Fetch issue details:**

   ```bash
   gh issue view {issue_number} --json title,body,labels,author
   ```

2. **Determine issue type:**

   | Labels/Keywords           | Type    |
   | ------------------------- | ------- |
   | `bug`, `fix`, `error`     | Bug     |
   | `feature`, `enhancement`  | Feature |
   | `refactor`, `improvement` | Feature |
   | (no clear signal)         | Feature |

3. **Extract requirements:**
   - Title -> work item title
   - Body -> acceptance criteria, context
   - Labels -> tags

**Source B: Conversation** (when invoked without args)

1. **Extract from conversation thread:**
   - Scan the full conversation history for the user's request
   - Identify: what they want built/fixed, any constraints, acceptance criteria
   - Determine type: bug (error reports, "fix this") vs feature (new functionality)

2. **Determine issue type:**

   | Conversation signals                          | Type    |
   | --------------------------------------------- | ------- |
   | Error reports, "fix", "broken", "not working" | Bug     |
   | Service failures, OOM, crashes, timeouts      | Bug     |
   | "Add", "build", "create", "implement"         | Feature |
   | Refactoring, cleanup, improvement              | Feature |
   | (ambiguous)                                    | Feature |

3. **For bugs — extract error context** (when available):
   - **Service name** — which service failed
   - **Error type** — crash, timeout, OOM, validation error
   - **Timestamp** — when it failed (UTC)
   - **Error message** — actual error text if available
   - **User hints** — additional context from the triggering comment

4. **Extract requirements:**
   - Synthesize a clear title from the conversation
   - Collect all stated requirements and constraints
   - Infer acceptance criteria from the discussion

5. **If context is insufficient:**

   For features:

   ```markdown
   I need more detail to proceed. Please provide:

   - What should be built or fixed
   - Expected behavior / acceptance criteria
   - Any constraints or preferences
   ```

   For bugs:

   ```markdown
   I need more detail to proceed. Please provide:

   - Service name
   - Approximate time of failure (e.g., "around 2pm UTC")
   - Error type or message if known
   ```

   Then STOP and wait for user response before continuing.

### Phase 2: Research / Investigate

Write the parsed requirements to `.context/source.md` for reference by later phases.

**For features:**
- Spawn `researcher` agent to analyze codebase patterns, integration points, similar implementations
- Write findings to `.context/research.md`

**For bugs:**
- Spawn `investigator` agent (or `hypothesis-evaluator` for production incidents)
- Investigate root causes, check logs, analyze code paths
- Write findings to `.context/investigation.md`

### Phase 3: Plan

Spawn `planner` agent with all gathered context (source + research/investigation).

The plan must answer three questions clearly:

1. **What** will be done (high-level, 2-3 sentences)
2. **How** it will be done (approach, key decisions)
3. **Why** this approach (tradeoffs, alternatives considered)

Also include:
- Verification strategy (how to know it works)
- Risks and mitigations
- Side effects

Write the plan to `.context/plan.md`.

**In LFG mode, the plan is auto-approved** — proceed immediately to build.

**On failure:** STOP, report error.

### Phase 4: Build Todos

Run `/create-build-todos` internally:

- Spawns `build-planner` agent for deep research
- Creates build_todo files with detailed implementation steps
- Each step includes discovered patterns and conventions

**On failure:** STOP, report error.

### Phase 5: Build

Run `/build` internally for each build todo:

- Execute steps in dependency order
- Run tests after each step
- Run type checker
- Run linter

**On test failure:**
1. Attempt automatic fix (up to 2 retries)
2. If still failing: Log details, continue to write tests phase
3. Review will flag remaining issues

**On unrelated type/lint errors** (pre-existing failures in files this work
didn't touch): fix the clear, low-risk ones and record them in
`.context/unrelated-fixes.md` for the separate commit in Phase 11. Leave the
risky/ambiguous ones for the follow-up report. See
[Unrelated errors → fix them, in a separate commit](#unrelated-errors--fix-them-in-a-separate-commit).

### Phase 6: Write Tests

Run `/write-tests` internally:

1. Analyze all code changes from the build phase
2. Write tests at the appropriate level (unit, integration, e2e)
3. Run all new tests to verify they pass
4. Run full test suite to verify no regressions

**On failure:** Log details, continue to review phase (non-blocking).

### Phase 7–8: Cross-Review Iteration Loop (review + resolve)

Run the **Cross-Review Iteration Loop** from the `review` skill. Each round:

1. Run `/review mode:cross` — the current runner's native/self-review **plus** the other two
   providers via `external-agent`, all merged through one synthesis with a cross-provider
   confidence boost. Store findings in `.context/review_todos/`.

   **Cross-coverage gate — a round where only one provider ran is a failed round.** Before
   treating the round as done, confirm the two `.context/review/<provider>.json` files for peer
   providers exist (a failed provider still writes a valid empty envelope with a `residual_risks`
   note — that counts; a *missing* file means peer dispatch was never spawned). If either is
   absent, spawn the missing peer provider(s) and fold its envelope into synthesis before
   continuing — do not skip peer providers and proceed.
2. Resolve the actionable findings (runner fixes — `safe_auto` inline, `gated_auto`/`manual`
   via `/resolve-review` logic), re-run affected tests, run the type checker.

Repeat up to **3 rounds**, or stop earlier when no actionable
(`safe_auto`/`gated_auto`/`manual`) findings remain. `advisory` and gate-suppressed nits do
not re-trigger a round. After round 3, record any remaining `gated_auto`/`manual` findings in
the follow-up report.

Reviewers may also flag problems that are **unrelated** to this work (pre-existing
issues in untouched code). Fix the clear, low-risk ones and record them in
`.context/unrelated-fixes.md` for the separate Phase 11 commit; defer the rest to
the follow-up report. See
[Unrelated errors → fix them, in a separate commit](#unrelated-errors--fix-them-in-a-separate-commit).

### Phase 9: Compound Learnings

Run `/compound` in **autonomous mode** to learn from the build and review process.

1. Analyze resolved review findings for upstream gaps
2. Identify improvements to memory entries, skills, and workflows
3. Auto-apply all improvements
4. Report what was changed

**On error:** Log details, continue (non-blocking).

### Phase 10: Create Deployment Guide

Run `/create-deployment-guide` internally:

1. Analyze changes for deployment impact (migrations, services, config)
2. Generate deployment guide
3. Check for special requirements

**On trivial changes:** Skip if no deployment steps needed.

**On error:** Log details, continue (non-blocking).

### Phase 11: Final commit

Commit the LFG output on the current branch — same branch the user was on
when they invoked `/lfg`. **Do not** create a branch, push, or open a PR.

For each repo that LFG touched:

1. Confirm still on the same branch as Phase 0.
2. **Commit unrelated fixes first, separately.** If
   `.context/unrelated-fixes.md` recorded any pre-existing lint/type/review
   fixes, stage just those files and commit them on their own:
   ```
   fix: resolve pre-existing lint/type errors surfaced during /lfg
   ```
   List the files and specific errors in the body. This keeps the feature diff
   clean and the cleanup independently reviewable/revertable. Skip this commit
   if there were no unrelated fixes.
3. Stage only the files LFG changed for the feature/fix itself (be specific —
   avoid `git add -A` so unrelated working-tree state isn't swept in). If the
   user had pre-existing uncommitted changes, those are already in the Phase 0
   checkpoint commit.
4. Create the final work commit. Subject is a one-line conventional summary; the
   body describes what was done and (briefly) why. Do not include a "Test
   plan" or PR-style sections — this is a commit, not a PR.

If multiple repos were touched, repeat per repo. Each repo gets its own
checkpoint + final commit on its current branch. No cross-repo PRs.

Report back with:
- Each repo's branch name and the SHAs of the checkpoint + unrelated-fixes +
  final commits (whichever were made)
- A short summary of what was done
- Any unrelated errors that were fixed (and which were deferred as too risky)
- Any follow-ups the user may want to handle (uncommitted state, separate cleanup)

## Error Handling

| Phase           | Error                  | Action                                  |
| --------------- | ---------------------- | --------------------------------------- |
| Pre-work        | Detached HEAD          | STOP, ask user to check out a branch    |
| Pre-work        | Commit fails           | STOP, report error                      |
| Parse Input     | Can't fetch issue      | STOP, report error                      |
| Parse Input     | Insufficient context   | Ask user for details, then STOP         |
| Research        | Agent failure          | Log, attempt plan with less context     |
| Plan            | Planner failure        | STOP, report error                      |
| Build Todos     | Agent failure          | STOP, report error                      |
| Build           | Test failure           | Retry 2x, then continue                 |
| Write Tests     | Test creation fails    | Log, continue to review (non-blocking)  |
| Review          | Agent failure          | Log, continue with partial review       |
| Resolve         | Fix introduces error   | Revert fix, mark as deferred            |
| Build/Resolve   | Unrelated error, risky | Don't fix; record as a follow-up        |
| Compound        | Analysis failure       | Log, continue (non-blocking)            |
| Deploy Guide    | Generation failure     | Log, continue (non-blocking)            |
| Final commit    | Commit fails           | Report; leave changes staged            |

## Filesystem Artifacts

All artifacts live in `.context/` (gitignored), not the ticket system:

| File                        | Created By      | Content                          |
| --------------------------- | --------------- | -------------------------------- |
| `.context/source.md`        | Phase 1         | Parsed requirements              |
| `.context/research.md`      | Phase 2         | Research findings (features)     |
| `.context/investigation.md` | Phase 2         | Investigation findings (bugs)    |
| `.context/plan.md`          | Phase 3         | Implementation plan              |
| `.context/build_todos/`     | Phase 4         | Build steps                      |
| `.context/review_todos/`    | Phase 7         | Review findings                  |
| `.context/unrelated-fixes.md` | Phases 5/8    | Pre-existing errors fixed → separate commit |
| `.context/deployment-guide.md` | Phase 10     | Deployment instructions          |

## Output

### On Success

```
LFG complete!

Branch: feature/whatever-was-checked-out
Commits:
  abc1234 chore: checkpoint before /lfg                        # if Phase 0 made one
  bcd2345 fix: resolve pre-existing lint/type errors ...       # if any unrelated fixes
  def5678 fix: <one-line summary of LFG work>

Summary:
- Implemented user dashboard feature
- Tests: 12 passing / 12 total (4 unit, 6 integration, 2 e2e)
- Review: 3 iterations, all P1/P2 resolved
- Unrelated fixes: 2 pre-existing type errors in untouched files (separate commit)

Next: review the diff, then push and open a PR when you're ready.
```

### On Partial Success

```
LFG needs attention!

Branch: feature/whatever-was-checked-out
Commits:
  abc1234 chore: checkpoint before /lfg
  def5678 fix: <one-line summary>

Summary:
- Implemented user dashboard feature
- Tests: 11 passing / 12 total (1 flaky e2e)
- 2 P3 findings remain (not blocking)
```

### On Failure

```
LFG failed at: {phase}

Branch: feature/whatever-was-checked-out
Reason: {error description}
```

## Differences from Running Steps Manually

| Aspect          | Manual steps          | /lfg                                  |
| --------------- | --------------------- | ------------------------------------- |
| Trigger         | You run each command  | One command does everything           |
| Plan approval   | You review plan first | Auto-approved                         |
| Review handling | You decide on findings| Loop until no P1/P2                   |
| Scope           | You pick the work     | Extracts from issue/conversation      |
| Stops at        | Wherever you stop     | Final commit on the current branch    |
| Branch / push   | Up to you             | Stays on current branch; never pushes |
| PR              | Up to you             | Never opens a PR                      |

## Example Flows

### Example A: From GitHub Issue

**GitHub Issue #123:**

```
Title: Add user activity dashboard
Labels: feature, enhancement
Body:
Users should be able to see their recent activity including:
- Documents created in last 30 days
- Recent edits
- Pending approvals

Should integrate with existing analytics.
```

**LFG execution:**

1. Phase 0: working tree clean → no checkpoint commit
2. Parse: source=github, type=feature, title="Add user activity dashboard"
3. Research: analyze existing analytics, dashboard patterns
4. Plan: write `.context/plan.md`
5. Build todos + build + tests + review + resolve
6. Phase 11: stage LFG-touched files, commit on the current branch

**Output:**

```
LFG complete!

Branch: feature/activity-dashboard
Commits:
  def5678 feat: add user activity dashboard

Summary:
- Implemented user activity dashboard
- Tests: 12 passing / 12 total
- Review: 3 iterations, all P1/P2 resolved

Next: review the diff, then push and open a PR when you're ready.
```

### Example B: From Conversation

**Conversation:**

```
User: "I want to add a bulk export button to the invoices list. It should let
users select multiple invoices and download them as a single ZIP of PDFs. Only
finalized invoices should be exportable."
```

**LFG execution:**

1. Phase 0: working tree had pending edits → `chore: checkpoint before /lfg`
2. Parse: source=conversation, type=feature, title="Bulk invoice PDF export"
3. Research: analyze invoice list code, export patterns
4. Plan: write `.context/plan.md`
5. Build todos + build + tests + review + resolve
6. Phase 11: stage LFG-touched files, commit on the current branch

**Output:**

```
LFG complete!

Branch: invoices-work
Commits:
  abc1234 chore: checkpoint before /lfg
  def5678 feat: bulk invoice PDF export

Summary:
- Implemented bulk invoice PDF export
- Tests: 6 passing / 6 total (2 unit, 3 integration, 1 e2e)
- Review: 2 iterations, all P1/P2 resolved
```

### Example C: Bug Fix from Error Report

**Conversation:**

```
User: "Fix this - seeing OOM on large batches lately. Service main-processor
failed at 14:23 UTC with exit code -9"
```

**LFG execution:**

1. Phase 0: clean working tree → no checkpoint commit
2. Parse: source=conversation, type=bug, service=main-processor, error=OOM
3. Investigate: hypotheses + evaluation
4. Plan: write `.context/plan.md`
5. Build todos + build + tests + review + resolve
6. Phase 11: commit on the current branch

**Output:**

```
LFG complete!

Branch: hotfix-batch-oom
Commits:
  def5678 fix: cap main-processor batch size to prevent OOM

Root cause: Memory exhaustion on large batches (>500 items)
Fix: Added batch size limit of 200 items with chunked processing
Tests: 5 passing / 5 total
Review: No critical findings
```

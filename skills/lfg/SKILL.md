---
name: lfg
description: Let's Fucking Go - Autonomous end-to-end workflow from GitHub issue, error report, or conversation to PR. No ticket tracking.
max_turns: 300
---

# LFG Command

Let's Fucking Go. The ultimate autonomous workflow that takes a GitHub issue, error report,
**or conversation context** and delivers a complete PR. Handles both features and bugs
(including production incidents with hypothesis-driven root cause analysis).

LFG operates **without the ticket system** — no tickets are created, no status is tracked,
no artifacts are stored in MCP. All coordination uses the filesystem (`.context/` directory).
For the ticket-tracked version, use `/auto-flow`.

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

| Aspect      | `/lfg`                         | `/auto-flow`                          |
| ----------- | ------------------------------ | ------------------------------------- |
| Ticket      | No ticket created              | Creates and manages ticket lifecycle  |
| Status      | No status tracking             | backlog -> planning -> planned -> ... |
| Artifacts   | Filesystem only (.context/)    | Stored in ticket system via MCP       |
| Resume      | Cannot resume from ticket      | Resume via BNNN/FNNN                  |
| Deployment  | PR only                        | PR + `/auto-deploy` + `/auto-verify`  |

## Input Detection

LFG detects its input source automatically:

| Invocation             | Input Source  | Behavior                            |
| ---------------------- | ------------- | ----------------------------------- |
| `/lfg #123` or number  | GitHub issue  | Fetch issue, extract requirements   |
| `/lfg` (no args)       | Conversation  | Extract requirements from thread    |

## Process Overview

```
1.  Parse Input       -> Extract type (bug/feature), requirements from issue OR conversation
2.  Research          -> Codebase research (features) or investigation (bugs)
3.  Plan              -> Spawn planner agent, write .context/plan.md
4.  Build Todos       -> /create-build-todos (deep research into implementation steps)
5.  Build             -> /build (implement each step)
6.  Write Tests       -> /write-tests (test coverage for new code)
7.  Review            -> /review (parallel review agents)
8.  Resolve           -> /resolve-review (auto-fix p1/p2/p3 findings)
9.  Compound          -> /compound (learn from review, apply improvements)
10. Deploy Guide      -> /create-deployment-guide
11. Verify            -> /verify local (unless --skip-verify)
12. Create PR         -> Commit, push, create PR with summary
```

## Detailed Process

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

### Phase 6: Write Tests

Run `/write-tests` internally:

1. Analyze all code changes from the build phase
2. Write tests at the appropriate level (unit, integration, e2e)
3. Run all new tests to verify they pass
4. Run full test suite to verify no regressions

**On failure:** Log details, continue to review phase (non-blocking).

### Phase 7: Review

Run `/review` internally:

- Spawn review agents in parallel:
  - `reviewer` (quality, YAGNI, patterns)
  - `reviewer` (architecture, security, performance)
  - `reviewer` (data — if database changes)
- Store findings in `.context/review_todos/`

### Phase 8: Resolve Review Findings

Run `/resolve-review` internally:

| Priority        | Action                                 |
| --------------- | -------------------------------------- |
| p1 (critical)   | Auto-fix, these are clear bugs         |
| p2 (important)  | Auto-fix, these improve quality        |
| p3 (suggestion) | Auto-fix, these are worth implementing |

- Re-run affected tests after fixes
- Run type checker

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

### Phase 11: Local Verification

**Unless `--skip-verify`:**

Run `/verify local` internally:

1. Apply migrations
2. Seed test data
3. Execute tests
4. Verify expected outcomes
5. Generate verification report

**On failure:** Log details, mark PR as needs attention.

### Phase 12: Create PR

1. Collect all context from `.context/` (plan, build_todos, review_todos, deployment guide)
2. Run tests and collect results
3. Generate standardized summary with:
   - What was done (implementation details)
   - Test results (counts by type, pass/fail)
   - Verification status
   - Review findings resolved
   - Deployment notes
   - Files changed
4. Commit all changes
5. Push branch
6. Create PR with summary as body
7. Output the PR link

## Error Handling

| Phase        | Error                  | Action                                  |
| ------------ | ---------------------- | --------------------------------------- |
| Parse Input  | Can't fetch issue      | STOP, report error                      |
| Parse Input  | Insufficient context   | Ask user for details, then STOP         |
| Research     | Agent failure          | Log, attempt plan with less context     |
| Plan         | Planner failure        | STOP, report error                      |
| Build Todos  | Agent failure          | STOP, report error                      |
| Build        | Test failure           | Retry 2x, then continue                 |
| Write Tests  | Test creation fails    | Log, continue to review (non-blocking)  |
| Review       | Agent failure          | Log, continue with partial review       |
| Resolve      | Fix introduces error   | Revert fix, mark as deferred            |
| Compound     | Analysis failure       | Log, continue (non-blocking)            |
| Deploy Guide | Generation failure     | Log, continue (non-blocking)            |
| Verify       | Test failure           | Log details, mark PR as needs attention |
| PR           | Push failure           | Report, provide manual instructions     |

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
| `.context/deployment-guide.md` | Phase 10     | Deployment instructions          |

## Output

### On Success

```
LFG complete!

PR: https://github.com/org/repo/pull/456
Issue: #123                              # Only shown if source was GitHub issue

Summary:
- Implemented user dashboard feature
- Tests: 12 passing / 12 total (4 unit, 6 integration, 2 e2e)
- Review: 3 iterations, all P1/P2 resolved
```

### On Partial Success

```
LFG needs attention!

PR: https://github.com/org/repo/pull/456 (marked needs attention)
Issue: #123                              # Only shown if source was GitHub issue

Summary:
- Implemented user dashboard feature
- Tests: 11 passing / 12 total (1 flaky e2e)
- 2 P3 findings remain (not blocking)
```

### On Failure

```
LFG failed at: {phase}

Issue: #123                              # Only shown if source was GitHub issue
Reason: {error description}
```

## Differences from Running Steps Manually

| Aspect          | Manual steps          | /lfg                                  |
| --------------- | --------------------- | ------------------------------------- |
| Trigger         | You run each command  | One command does everything            |
| Plan approval   | You review plan first | Auto-approved                         |
| Review handling | You decide on findings| Loop until no P1/P2                   |
| Scope           | You pick the work     | Extracts from issue/conversation       |
| Stops at        | Wherever you stop     | PR created                            |

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

1. Parse: source=github, type=feature, title="Add user activity dashboard"
2. Research: analyze existing analytics, dashboard patterns
3. Plan: write `.context/plan.md`
4. Build todos + build + tests + review + resolve + verify + PR

**Output:**

```
LFG complete!

PR: https://github.com/org/repo/pull/456
Issue: #123

Summary:
- Implemented user activity dashboard
- Tests: 12 passing / 12 total
- Review: 3 iterations, all P1/P2 resolved
```

### Example B: From Conversation

**Conversation:**

```
User: "I want to add a bulk export button to the invoices list. It should let
users select multiple invoices and download them as a single ZIP of PDFs. Only
finalized invoices should be exportable."
```

**LFG execution:**

1. Parse: source=conversation, type=feature, title="Bulk invoice PDF export"
2. Research: analyze invoice list code, export patterns
3. Plan: write `.context/plan.md`
4. Build todos + build + tests + review + resolve + verify + PR

**Output:**

```
LFG complete!

PR: https://github.com/org/repo/pull/790

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

1. Parse: source=conversation, type=bug, service=main-processor, error=OOM
2. Investigate: hypotheses + evaluation
3. Plan: write `.context/plan.md`
4. Build todos + build + tests + review + resolve + verify + PR

**Output:**

```
LFG complete!

PR: https://github.com/org/repo/pull/456

Root cause: Memory exhaustion on large batches (>500 items)
Fix: Added batch size limit of 200 items with chunked processing
Tests: 5 passing / 5 total
Review: No critical findings
```

---
description: Let's Fucking Go - Autonomous end-to-end workflow from GitHub issue, error report, or conversation to PR.
max_turns: 300
---

# LFG Command

Let's Fucking Go. The ultimate autonomous workflow that takes a GitHub issue, error report,
**or conversation context** and delivers a complete PR. Handles both features and bugs
(including production incidents with hypothesis-driven root cause analysis).

## Usage

```
/lfg #123                    # GitHub issue number
/lfg 123                     # Same thing
/lfg https://github.com/org/repo/issues/123   # Full URL
/lfg                         # Use current conversation as input
/lfg B001                    # Resume existing bug work item
/lfg --skip-verify           # Skip local verification step
```

## When to Use

- Triggered from a GitHub issue (via Claude Code web or CLI)
- Triggered from a conversation thread where the user describes what they want
- Triggered from an error report or production incident
- You want fully autonomous end-to-end execution
- Requirements are clear (from issue or conversation)
- You trust the workflow to make decisions

## Input Detection

LFG detects its input source automatically:

| Invocation             | Input Source  | Behavior                            |
| ---------------------- | ------------- | ----------------------------------- |
| `/lfg #123` or number  | GitHub issue  | Fetch issue, extract requirements   |
| `/lfg B001`            | Existing bug  | Resume existing BNNN work item      |
| `/lfg` (no args)       | Conversation  | Extract requirements from thread    |

## Process Overview

```
1.  Parse Input          -> Extract type (bug/feature), requirements from issue OR conversation
2.  Create Work Item     -> Feature (FNNN) or Bug (BNNN) folder
3.  Research/Investigate -> /research for features, /investigate for bugs
4.  Plan                 -> /plan creates plan.md with approach
5.  Build Todos          -> /create-build-todos for detailed steps
6.  Build                -> /build implements each step
7.  Write Tests          -> /write-tests (MANDATORY — never skip)
8.  Review Loop          -> /review + /resolve-review until no P1/P2
9.  Compound             -> /compound in autonomous mode (learn + apply improvements)
10. Create PR            -> /create-pr (summary + PR + link)
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

   | Labels/Keywords           | Type    | Command        |
   | ------------------------- | ------- | -------------- |
   | `bug`, `fix`, `error`     | Bug     | `/investigate` |
   | `feature`, `enhancement`  | Feature | `/research`    |
   | `refactor`, `improvement` | Feature | `/research`    |
   | (no clear signal)         | Feature | `/research`    |

3. **Extract requirements:**
   - Title -> work item title
   - Body -> acceptance criteria, context
   - Labels -> tags for work item

**Source B: Conversation** (when invoked without args)

1. **Extract from conversation thread:**
   - Scan the full conversation history for the user's request
   - Identify: what they want built/fixed, any constraints, acceptance criteria
   - Determine type: bug (error reports, "fix this") vs feature (new functionality)

2. **Determine issue type:**

   | Conversation signals                          | Type    | Command        |
   | --------------------------------------------- | ------- | -------------- |
   | Error reports, "fix", "broken", "not working" | Bug     | `/investigate` |
   | Service failures, OOM, crashes, timeouts      | Bug     | `/investigate` |
   | "Add", "build", "create", "implement"         | Feature | `/research`    |
   | Refactoring, cleanup, improvement              | Feature | `/research`    |
   | (ambiguous)                                    | Feature | `/research`    |

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

**Source C: Resume existing ticket** (when invoked with BNNN)

1. Load the existing ticket:
   ```
   ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
   ```
2. Read the source artifact for context
3. Check which artifact types already exist (investigation, plan, build_todo, etc.)
4. Resume from the next incomplete phase

### Phase 2: Create Ticket

Resolve project and repo from CLAUDE.md (`<!-- mem:project=X -->`) and git remote.

**Create a ticket via MCP:**

```
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="<synthesized title>",
  type="bug" | "feature",
  description="<formatted description — see below>",
  status="active",
  tags={"github_issue": issue_number, "source": "conversation"},  # as applicable
  command="/lfg"
)
# ticket_id is auto-generated (e.g., F0043, B0012)
```

**Description content by input source:**

**For GitHub issue input:**
Include issue number, author, labels, body, and extracted acceptance criteria.

**For conversation input (features):**
Include context summary, requirements, and acceptance criteria.

**For conversation input (bugs):**
Include service name, error time, error type, error message, and user context.

### Phase 3: Research or Investigate

**For Features (type: feature):**

Run `/research` internally:

- Find existing patterns in codebase
- Understand architecture for the feature area
- Identify files that will need changes
- Document findings in work item

**For Bugs (type: bug):**

Run `/investigate` internally with hypothesis generation enabled:

1. **Select agents** based on error type (when error context is available):

   | Error Type | Primary Agents                        |
   | ---------- | ------------------------------------- |
   | OOM/Crash  | Infrastructure agent + Service agent  |
   | Timeout    | Infrastructure agent + Database agent |
   | Data error | Database agent + researcher           |
   | Unknown    | All available investigator agents     |

2. **Spawn agents in parallel**

3. **Synthesize findings** into `investigation.md` with root causes, evidence, and
   hypotheses table

Then evaluate hypotheses:

1. Spawn `hypothesis-evaluator` agent for each hypothesis
2. Collect verdicts: CONFIRMED | REFUTED | INCONCLUSIVE
3. Create `hypothesis-evaluation/` folder with evaluation documents

**Decision logic:**

| Scenario           | Action                                |
| ------------------ | ------------------------------------- |
| One CONFIRMED      | Use as root cause for plan            |
| Multiple CONFIRMED | Prioritize by severity, document all  |
| None CONFIRMED     | Use highest-confidence INCONCLUSIVE   |
| All REFUTED        | Return to investigation, expand scope |

**On failure:** Log error, continue to planning with available info.

**Memory service save:** Store key research findings (root causes, architecture patterns found)
via the memory service store API (see compound-methodology skill for full API details).

### Phase 4: Plan

Run `/plan` internally:

1. Read research/investigation artifacts from `get_ticket` response
2. Design implementation approach
3. Store plan as artifact:
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="plan", content="<plan content>",
     command="/lfg"
   )
   ```

**Plan is auto-approved** in LFG mode (no user confirmation needed).

### Phase 5: Create Build Todos

Run `/create-build-todos` internally:

- Spawns `build-planner` agent for deep research
- Creates `build_todo` artifacts with detailed implementation steps
- Each step includes discovered patterns and conventions

**On failure:** STOP, report error.

### Phase 6: Build

1. **Set ticket status to building:**
   ```
   mcp__autodev-memory__update_ticket(
     project=PROJECT, ticket_id=ID, repo=REPO,
     status="building",
     command="/lfg"
   )
   ```

2. **Create branch:**

   ```bash
   git checkout -b lfg/{work-item-id}
   ```

3. Run `/build` internally:
   - Execute steps in dependency order
   - Run tests after each step
   - Run type checker
   - Run linter

**On test failure:**

1. Attempt automatic fix (up to 2 retries)
2. If still failing: Log details, continue to review phase

### Phase 7: Write Tests (MANDATORY - NEVER SKIP)

**This phase is NON-NEGOTIABLE.** Every LFG run MUST write tests for new code paths before
proceeding to review. Skipping this phase means bugs ship untested. The review loop (Phase 8)
does NOT substitute for tests — reviewers check code quality, not runtime behavior.

Run `/write-tests {work-item-id}` internally:

1. Analyze all code changes from the build phase
2. Classify changed code: pure logic, DB operations, API routes, user flows
3. Write tests at the appropriate level:
   - **Unit tests** for data transformations, business logic, validators, mappings
   - **Integration tests** (DB) for model functions with query logic, new DB methods
   - **E2E tests** for multi-step user flows
4. Run all new tests to verify they pass
5. Run full test suite to verify no regressions

**Test scope:** Only test code written in Phase 6. Don't test unrelated code.

**Minimum bar:** At least one test per new public function/method. New constants and mappings
that affect control flow deserve tests. Result handlers that write to DB deserve tests
(mock the DB, verify call args and return values).

**On failure:** Fix tests, retry once, then continue to review loop.

### Phase 8: Review Loop

This phase loops until there are no P1 or P2 findings remaining.

**Loop iteration:**

1. **Run `/review` internally:**
   - Spawn review agents in parallel
   - Collect findings into `review_todos/`

2. **Check for P1/P2 findings:**

   Check the ticket's review_todo artifacts for unresolved P1/P2 findings:
   ```
   ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
   # Filter artifacts where type="review_todo" and status != "resolved"
   # and content contains "priority: p1" or "priority: p2"
   ```

3. **If P1/P2 exist:**
   - Run `/resolve-review` internally
   - Auto-accept all resolutions (no user confirmation)
   - Re-run tests and type checker
   - Loop back to step 1

4. **If no P1/P2:**
   - Exit loop
   - P3 findings remain as documented but not blocking

**Loop safeguard:** Maximum 5 iterations. If still P1/P2 after 5 loops, continue anyway
with findings documented.

### Phase 9: Compound Learnings

Run `/compound` in **autonomous mode**:

1. Analyze the build and review process for upstream gaps
2. Identify improvements to memory entries, skills, and workflows
3. Auto-apply all improvements (no user approval needed in lfg)
4. Store all learnings in memory service (critical for cloud persistence)
5. Report what was changed

**Cloud note:** In cloud environments, file-based changes from /compound are ephemeral.
Memory service saves are the **persistent** knowledge channel. The compound-methodology skill
handles this automatically via its "Store in Memory Service" step.

### Phase 10: Create PR

**For GitHub issue input:**

Run `/create-pr {work-item-id} --issue {issue_number}` internally.

**For conversation input:**

Run `/create-pr {work-item-id}` internally (no issue to link).

Steps:

1. Collects all ticket artifacts via `get_ticket` (source, plan, build_todos,
   review_todos, investigation, learning_report, etc.)
2. Runs tests and collects results
3. Generates standardized summary with:
   - What was done (research/investigation + implementation)
   - Root cause analysis and hypothesis verdicts (for bugs)
   - Test results (counts by type, pass/fail)
   - Verification status
   - Review iterations and findings resolved
   - Learnings captured
   - Files changed
4. Commits all changes
5. Pushes to `lfg/{work-item-id}` branch
6. Creates PR with summary as body
7. Links PR to GitHub issue (if source was a GitHub issue)
8. Outputs the PR link

## Error Handling

| Phase        | Error                  | Action                          |
| ------------ | ---------------------- | ------------------------------- |
| Parse Input  | Can't fetch issue      | STOP, report error              |
| Parse Input  | Insufficient context   | Ask user for details, then STOP |
| Work Item    | Creation fails         | STOP, report error              |
| Research/Inv | Partial failure        | Continue with available info    |
| Hypothesis   | No data available      | Mark INCONCLUSIVE               |
| Plan         | Agent failure          | STOP, report error              |
| Build Todos  | Agent failure          | STOP, report error              |
| Build        | Test failure           | Retry 2x, continue to review   |
| Write Tests  | Test creation fails    | Log, continue to review loop   |
| Write Tests  | New tests fail         | Fix tests, retry once, continue |
| Review Loop  | Max iterations reached | Continue, document in report    |
| Resolve      | Fix causes new error   | Revert, mark needs attention    |
| Compound     | Write failure          | Log, continue (non-blocking)    |
| PR           | Push fails             | Report, provide manual steps    |

## Differences from /auto-build

| Aspect          | /auto-build           | /lfg                                  |
| --------------- | --------------------- | ------------------------------------- |
| Trigger         | Plan approval         | GitHub issue, error report, or convo  |
| Starting point  | Existing plan.md      | No artifacts exist                    |
| Research phase  | None                  | Full research/investigation           |
| Plan approval   | Required              | Auto-approved                         |
| Review handling | Single pass + resolve | Loop until no P1/P2                   |
| Compound        | Not included          | Autonomous mode                       |
| Scope           | Features with plans   | Any issue or request (bug or feature) |

## Ticket Artifacts

All artifacts are stored in the MCP ticket system, not on the filesystem.

**For features (e.g., F0042):**

| Artifact Type | Purpose |
|---|---|
| `source` | Issue or conversation context (auto-created) |
| `investigation` | Codebase research findings |
| `plan` | Implementation approach |
| `build_todo` (seq 1-N) | Implementation steps |
| `review_todo` (seq 1-N) | Review findings |
| `learning_report` | Final summary for PR |

**For bugs (e.g., B0001):**

| Artifact Type | Purpose |
|---|---|
| `source` | Error context + details (auto-created) |
| `investigation` | Root cause analysis + hypotheses |
| `plan` | Fix architecture |
| `build_todo` (seq 1-N) | Implementation steps |
| `review_todo` (seq 1-N) | Review findings |
| `learning_report` | Workflow gap analysis |

## Output

### On Success

```
LFG complete!

PR: https://github.com/org/repo/pull/456
Issue: #123                              # Only shown if source was GitHub issue

Summary:
- Implemented user dashboard feature
- Tests: 12 passing / 12 total (4 unit, 6 integration, 2 e2e)
- Verification: PASS
- 3 review iterations, all P1/P2 resolved

Ticket: F0042
```

### On Partial Success

```
LFG needs attention!

PR: https://github.com/org/repo/pull/456 (marked needs attention)
Issue: #123                              # Only shown if source was GitHub issue

Summary:
- Implemented user dashboard feature
- Tests: 11 passing / 12 total (1 flaky e2e)
- Verification: SKIPPED
- 2 P3 findings remain (not blocking)

Ticket: F0042
```

### On Failure

```
LFG failed at: {phase}

Issue: #123                              # Only shown if source was GitHub issue
Reason: {error description}

Ticket created: F0042
See ticket F0042 for partial progress
```

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
2. Create: `ticket F0042 via MCP`
3. Research: Find analytics patterns, component structure
4. Plan: Dashboard component + API routes + DB queries
5. Build todos: 6 steps identified
6. Build: Implement all steps
7. Review loop:
   - Iteration 1: 2 P1, 3 P2, 4 P3 -> resolve
   - Iteration 2: 0 P1, 1 P2, 4 P3 -> resolve
   - Iteration 3: 0 P1, 0 P2, 4 P3 -> exit loop
8. Compound: Created gotcha about analytics caching
9. PR: Created with full report, linked to #123

### Example B: From Conversation

**Conversation:**

```
User: "I want to add a bulk export button to the invoices list. It should let
users select multiple invoices and download them as a single ZIP of PDFs. Only
finalized invoices should be exportable."
```

**LFG execution:**

1. Parse: source=conversation, type=feature, title="Bulk invoice PDF export"
2. Create: `ticket F0043 via MCP`
3. Research: Find invoice list patterns, PDF generation, ZIP utilities
4. Plan: Selection UI + export API route + ZIP generation
5. Build todos: 5 steps identified
6. Build: Implement all steps
7. Review loop: 2 iterations, all resolved
8. Compound: Noted pattern for bulk operations
9. PR: Created with full report (no issue link)

**Output:**

```
LFG complete!

PR: https://github.com/org/repo/pull/790

Summary:
- Implemented bulk invoice PDF export
- Tests: 6 passing / 6 total (2 unit, 3 integration, 1 e2e)
- Verification: PASS
- 2 review iterations, all P1/P2 resolved

Ticket: F0043
```

### Example C: Bug Fix from Error Report

**Conversation:**

```
User: "Fix this - seeing OOM on large batches lately. Service main-processor
failed at 14:23 UTC with exit code -9"
```

**LFG execution:**

1. Parse: source=conversation, type=bug, service=main-processor, error=OOM
2. Create: `ticket B0001 via MCP`
3. Investigate: Finds memory spike at 14:23, batch had 650 items
4. Hypotheses:
   - H1: Memory exhaustion on batches >500 items (High confidence)
   - H2: Memory leak in client (Medium confidence)
5. Evaluate: H1 CONFIRMED, H2 REFUTED
6. Plan: Add batch size limit of 200 with chunked processing
7. Build: Implement limit + chunking
8. Write tests: Verify chunking logic + large batch handling
9. Review loop: No critical findings
10. Compound: Added gotcha about batch sizing
11. PR: Created with root cause report

**Output:**

```
LFG complete!

PR: https://github.com/org/repo/pull/456

Root cause: Memory exhaustion on large batches (>500 items)
Fix: Added batch size limit of 200 items with chunked processing
Tests: 5 passing / 5 total
Verification: PASS

Ticket: B0001
```

---
description: Autonomous bug-fix from error reports. Investigates, evaluates hypotheses, fixes, reviews, and creates PR.
max_turns: 200
---

# Auto-Fix Command

Fully autonomous bug-fix workflow triggered from error reports. Runs investigation with
hypothesis testing, implements fix, reviews, compounds learnings, and creates a PR with a full
report.

## Usage

```
/auto-fix                                    # Parses error context from conversation
/auto-fix "Service OOM at 14:23 UTC"         # Direct error description
/auto-fix B001                               # Resume existing BNNN work item
/auto-fix --skip-verify                      # Skip local verification step
```

## Trigger Flow

```
1. Service fails -> Existing notification posts error to channel
2. User mentions Claude with context/hints: "Fix this - looks like timeout"
3. Claude receives thread context (parent error + user comment)
4. Claude runs /auto-fix workflow
5. On completion, Claude replies to thread with PR link
```

## Differences from /auto-build

| Aspect            | /auto-build        | /auto-fix                      |
| ----------------- | ------------------ | ------------------------------ |
| Trigger           | Plan approval      | Error report                   |
| Starting artifact | plan.md exists     | Creates source.md from context |
| Investigation     | None (features)    | Deep with hypothesis testing   |
| Work item prefix  | F or NNN           | BNNN                           |
| Execution         | Worktree or branch | Branch only (cloud)            |

## Process Overview

```
1. Parse Context     -> Extract error details from conversation
2. Create Work Item  -> BNNN folder with source.md
3. Investigate       -> Root cause analysis + hypothesis generation
4. Evaluate          -> Experimental verification of hypotheses
5. Plan              -> Design fix based on confirmed root cause
6. Build Todos       -> Detailed implementation steps
7. Build             -> Implement fix (branch-based)
8. Review            -> Parallel review agents
9. Resolve           -> Auto-resolve findings
10. Learn            -> Compound workflow improvements
11. Verify           -> Local verification (optional)
12. Report & PR      -> Create PR with summary
```

## Detailed Process

### Phase 1: Parse Context

Extract from message thread or conversation:

1. **Service name** - Which service failed
2. **Error type** - Crash, timeout, OOM, validation error
3. **Timestamp** - When it failed (UTC)
4. **Error message** - Actual error text if available
5. **User hints** - Additional context from the triggering comment

**If context is insufficient:**

```markdown
Unable to parse error context. Please provide:

- Service name
- Approximate time of failure (e.g., "around 2pm UTC")
- Error type or message if known
```

### Phase 2: Create Work Item

1. **Find next B number:**

   ```bash
   find work_items -maxdepth 2 -type d -name "B[0-9][0-9][0-9]-*" | \
     sed 's/.*B\([0-9]*\).*/\1/' | sort -n | tail -1
   # Add 1, pad to 3 digits
   ```

2. **Create folder:** `work_items/active/BNNN-slug/`

3. **Create source.md:**

   ```markdown
   ---
   type: bugfix
   source: auto-fix
   created: YYYY-MM-DD
   service: [service name]
   error_time: [timestamp]
   ---

   # [Service Name] - [Error Type]

   ## Error Context

   **Service:** [name]
   **Time:** [timestamp]
   **Error Type:** [crash/timeout/OOM/etc.]

   ## Error Message
   ```

   [Error text from notification]

   ```

   ## User Context

   [Any hints or context from the user's comment]

   ## Thread Context

   - Parent message: [error notification summary]
   - Trigger comment: [user's comment]
   ```

### Phase 3: Investigation

Run `/investigate` internally with hypothesis generation enabled:

1. **Select agents** based on error type:

   | Error Type | Primary Agents                        |
   | ---------- | ------------------------------------- |
   | OOM/Crash  | Infrastructure agent + Service agent  |
   | Timeout    | Infrastructure agent + Database agent |
   | Data error | Database agent + researcher           |
   | Unknown    | All available investigator agents     |

2. **Spawn agents in parallel**

3. **Synthesize findings** into `investigation.md` with:
   - Root causes identified
   - Evidence from each source
   - **Hypotheses table** with testable predictions

**On failure:** Log error details, continue with partial investigation if possible.

### Phase 4: Hypothesis Evaluation

For each hypothesis in `investigation.md`:

1. **Spawn hypothesis-evaluator agent** with hypothesis details

2. **Agent performs verification:**
   - Data queries (Database MCP)
   - Metrics analysis (Infrastructure MCP)
   - Service inspection (CLI)

3. **Collect verdicts:** CONFIRMED | REFUTED | INCONCLUSIVE

4. **Create evaluation documents:**
   - `hypothesis-evaluation/hypothesis-01-name.md`
   - Use template: `.claude/skills/hypothesis-testing/templates/evaluation.md`

**Decision logic:**

| Scenario           | Action                                |
| ------------------ | ------------------------------------- |
| One CONFIRMED      | Use as root cause for plan            |
| Multiple CONFIRMED | Prioritize by severity, document all  |
| None CONFIRMED     | Use highest-confidence INCONCLUSIVE   |
| All REFUTED        | Return to investigation, expand scope |

### Phase 5: Plan

Run `/plan` internally:

1. **Read confirmed hypothesis** for root cause
2. **Design fix** based on verified cause
3. **Create plan.md** with:
   - Root cause summary (from confirmed hypothesis)
   - Fix approach
   - Files to change
   - Testing strategy

**On no confirmed hypothesis:** Use highest-confidence hypothesis, note uncertainty in plan.

### Phase 6: Create Build Todos

Run `/create-build-todos` internally:

- Spawns `build-planner` agent for deep research
- Creates `build_todos/` with detailed implementation steps
- Each step includes discovered patterns and conventions

**On failure:** STOP, report error.

### Phase 7: Build

Run `/build` internally in **branch mode**:

1. **Create branch:** `git checkout -b auto-fix/BNNN`
2. **Execute steps** in dependency order
3. **Run tests** after each step
4. **Run type checker**
5. **Run linter**

**On test failure:**

1. Attempt automatic fix (up to 2 retries)
2. If still failing: Log details, continue to review phase

### Phase 8: Review

Run `/review` internally:

- Spawn review agents in parallel:
  - `reviewer-code` (quality, YAGNI, patterns)
  - `reviewer-system` (architecture, security, performance)
  - `reviewer-data` (if database changes)
- Collect findings into `review_todos/`

### Phase 9: Resolve Review Findings

For each finding in `review_todos/`:

| Priority        | Action   |
| --------------- | -------- |
| p1 (critical)   | Auto-fix |
| p2 (important)  | Auto-fix |
| p3 (suggestion) | Auto-fix |

- Run `/resolve-review` logic
- Re-run affected tests
- Run type checker

**On fix causing new error:** Revert fix, mark as deferred.

### Phase 10: Learn from Review

Run `/learn-from-review` internally:

1. **Analyze resolved findings** for upstream gaps
2. **Apply improvements** to workflow:
   - Knowledge docs (gotchas, references)
   - Skill updates (checklists, research requirements)
   - AGENTS.md rules (if repeatedly violated)
3. **Create learning-report.md**

**On error:** Log details, continue (non-blocking).

### Phase 11: Local Verification (Optional)

**Unless `--skip-verify`:**

Run `/verify-local` internally:

1. Apply migrations (if any)
2. Seed test data
3. Execute tests with mocked external services
4. Verify expected outcomes
5. Generate verification report

**On verification failure:**

1. Log detailed failure info
2. Include in final report
3. PR will be marked as "needs attention"

### Phase 12: Report and PR

1. **Generate auto-fix-report.md:**

   ```markdown
   # Auto-Fix Report: BNNN - {Title}

   **Branch:** auto-fix/BNNN
   **Status:** COMPLETE | NEEDS_ATTENTION | PARTIAL
   **Date:** YYYY-MM-DD

   ## Root Cause Analysis

   | ID  | Hypothesis | Verdict   | Confidence |
   | --- | ---------- | --------- | ---------- |
   | H1  | [Name]     | CONFIRMED | High       |
   | H2  | [Name]     | REFUTED   | Medium     |

   **Confirmed Root Cause:**
   [Summary of what was confirmed and evidence]

   ## Changes Made

   | File            | Change              |
   | --------------- | ------------------- |
   | path/to/file.py | [brief description] |

   **Fix Approach:**
   [Summary of how the fix addresses the root cause]

   ## Verification

   **Status:** PASS | FAIL | SKIPPED
   [Evidence or reason]

   ## Learnings Captured

   - Knowledge docs created: N
   - Workflow improvements: N
   - [Link to learning-report.md]

   ## Next Steps

   - [ ] Review PR
   - [ ] Merge to main
   - [ ] Monitor in production
   ```

2. **Commit all changes:**

   ```bash
   git add -A
   git commit -m "Auto-fix BNNN: {title}

   Root cause: {confirmed hypothesis}
   Fix: {brief description}

   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
   ```

3. **Push and create PR:**

   ```bash
   git push -u origin auto-fix/BNNN

   gh pr create --title "Auto-fix BNNN: {title}" --body "$(cat auto-fix-report.md)"
   ```

4. **Reply format** (depends on outcome):

   **Success:**

   ```
   Fixed! PR: https://github.com/.../pull/123

   **Root cause:** {confirmed hypothesis summary}
   **Fix:** {what the fix does}

   Work item: BNNN-slug
   ```

   **Needs attention:**

   ```
   Partial fix ready: https://github.com/.../pull/123

   **Root cause:** {confirmed or best hypothesis}
   **Fix:** {what was implemented}
   **Attention needed:** {what needs manual review}

   Work item: BNNN-slug
   ```

   **Failed:**

   ```
   Could not auto-fix this issue.

   **Investigation:** {summary of findings}
   **Blocking issue:** {what prevented the fix}

   Work item: BNNN-slug (investigation.md has details)
   ```

## Error Handling

| Phase         | Error                   | Action                         |
| ------------- | ----------------------- | ------------------------------ |
| Parse Context | Can't extract error     | STOP, report "Unable to parse" |
| Investigation | Agent failure           | Continue with partial data     |
| Hypothesis    | No data available       | Mark INCONCLUSIVE              |
| Plan          | No confirmed hypothesis | Use highest-confidence         |
| Build Todos   | Agent failure           | STOP, report                   |
| Build         | Test failure            | Retry 2x, continue to review   |
| Review        | Agent failure           | Continue with partial review   |
| Resolve       | Fix causes new error    | Revert, mark needs attention   |
| Learn         | Write fails             | Log, continue (non-blocking)   |
| Verify        | Failure                 | Log, mark PR needs attention   |
| PR            | Push fails              | Report, provide manual steps   |

## Work Item Structure

```
work_items/active/B001-service-oom/
  source.md                    # Error context + details
  investigation.md             # Root cause analysis + hypotheses
  hypothesis-evaluation/       # Experimental verification
    hypothesis-01-memory.md    # Verdict: CONFIRMED
    hypothesis-02-timeout.md   # Verdict: REFUTED
  plan.md                      # Fix architecture
  build_todos/                 # Implementation steps
    01-add-batch-limit.md
    02-add-chunking.md
  review_todos/                # Review findings
    01-finding.md
  learning-report.md           # Workflow gap analysis
  auto-fix-report.md           # Summary for PR
  conclusion.md                # Created on verification pass
```

## Relation to Other Commands

| Command              | Relation to /auto-fix                        |
| -------------------- | -------------------------------------------- |
| `/investigate`       | Called internally with hypothesis generation |
| `/plan`              | Called internally, uses confirmed hypothesis |
| `/build`             | Called internally in branch mode             |
| `/review`            | Called internally after build                |
| `/resolve-review`    | Called internally for all findings           |
| `/learn-from-review` | Called internally for workflow improvements  |
| `/verify-local`      | Called internally (optional)                 |
| `/auto-build`        | Sibling command for features (not bugs)      |

## Example Workflow

**Notification:**

```
Service failed: main-processor
Time: 2026-01-27 14:23 UTC
Error: Process killed (exit code -9)
```

**User comment:**

```
@Claude Fix this - seeing OOM on large batches lately
```

**Claude runs /auto-fix:**

1. Parses: service=main-processor, time=14:23 UTC, type=OOM, hint="large batches"
2. Creates: `work_items/active/B001-processor-oom/`
3. Investigates: Finds memory spike at 14:23, batch had 650 items
4. Hypotheses:
   - H1: Memory exhaustion on batches >500 items (High confidence)
   - H2: Memory leak in client (Medium confidence)
5. Evaluates: H1 CONFIRMED (memory graph shows spike), H2 REFUTED
6. Plans: Add batch size limit of 200 with chunked processing
7. Builds: Implements limit + chunking
8. Reviews: No critical findings
9. Learns: Added gotcha about batch sizing
10. Verifies: Local test passes with large batch
11. Creates PR with report

**Claude replies:**

```
Fixed! PR: https://github.com/org/repo/pull/456

**Root cause:** Memory exhaustion on large batches (>500 items)
**Fix:** Added batch size limit of 200 items with chunked processing

Work item: B001-processor-oom
```

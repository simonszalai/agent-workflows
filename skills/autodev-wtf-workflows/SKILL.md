---
name: autodev-wtf-workflows
description: Investigate which agent workflow stage failed to catch a bug before production. Traces plan, build, review, test, verify pipeline to find the gap.
---

# WTF Workflows

Analyze the agent workflow pipeline to find which stage should have caught a bug that
reached production, then propose concrete fixes to the workflow so it can't happen again.

**Scope:** One bug, one pipeline trace, one set of fixes. This traces the agent workflow
(plan -> build -> review -> test -> verify) for a specific failure. This is NOT a memory
system investigation (use `/autodev-wtf-memory` for that) and NOT a bug root cause
investigation (use `/investigate` for that). This answers: "which workflow stage should
have caught this, and why didn't it?"

## Usage

```
/autodev-wtf-workflows "Bug description: items missing associations"
/autodev-wtf-workflows B0009                    # Bug ticket B0009
/autodev-wtf-workflows F0076                    # Feature F0076 (scope dropped?)
/autodev-wtf-workflows "F076 didn't implement inline vision"
```

## When to Use

| Trigger | Example |
|---|---|
| Bug reached production | Code does the wrong thing in prod |
| Planned scope silently dropped | Source lists 5 items, only 3 implemented |
| Feature marked complete but partial | Some sub-items done, others silently dropped |
| Plan drift without discussion | Implementation diverged from plan |

## When NOT to Use

| Situation | Use Instead |
|---|---|
| Memory system didn't surface knowledge | `/autodev-wtf-memory` |
| Need to find the bug's root cause | `/investigate` |
| Broad system audit | `/consolidate` |
| Learning moment after correction | `/compound` |
| Bug not yet in production | Fix directly |

## Failure Types

### Production Bugs
A bug reached production. The code does the wrong thing.

### Agent Workflow Failures
The agent pipeline failed to deliver what was specified:
- **Silent scope reduction** — Source lists N items, implementation does N-K, marked complete
- **Plan drift** — Implementation diverges from plan without updating the plan
- **Partial completion** — Some sub-items done, others silently dropped
- **Wrong abstraction** — Plan specified approach A, implementation used approach B

## Process — Two Steps

### STEP 1: Investigate and Propose (read-only)

Gather evidence, analyze gaps, propose fixes. Do NOT edit any files.

#### 1a. Gather Context

1. **Load ticket** (if ID given):
   ```
   mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
   ```
   Or search: `mcp__autodev-memory__search_tickets(project=PROJECT, query="<desc>")`

2. **Get git history** for related commits
3. **Read the bug report**, incident description, or feature source document
4. **Check production state** if tools available (DB, logs, metrics)
5. **For workflow failures:** Read the source.md/plan to identify what was planned,
   then diff against what was actually implemented

#### 1b. Analyze Each Workflow Stage

Examine each stage in reverse order (closest to production first):

| Stage                   | Artifact               | Key Questions                                |
| ----------------------- | ---------------------- | -------------------------------------------- |
| Production Verification | verification-report.md | Did we verify the right scenarios?            |
| Local Verification      | (test output)          | Were integration tests sufficient?            |
| Tests                   | test files             | What test scenario is missing?                |
| Review                  | review_todos/          | Did reviewers check the right dimensions?     |
| Implementation          | git diff, code         | Did code match plan? Was scope fully covered? |
| Build Todos             | build_todos/           | Were implementation steps complete?           |
| Plan                    | plan.md                | Did plan identify edge cases/constraints?     |
| Source                  | source.md              | Was the scope clearly defined?                |
| Investigation (bugs)    | investigation.md       | Was root cause analysis thorough?             |

For each stage, determine:
- **Exists?** — Was this artifact created?
- **Covers failure area?** — Does it mention the code/scenario that failed?
- **Should have caught?** — Would proper execution have prevented the failure?

#### 1c. Identify Test Gap

For every failure, answer:
- What test (unit, integration, e2e) would have caught this?
- Does that test type exist for this area?
- If tests exist, why didn't they cover this scenario?

#### 1d. Spawn Deeper Analysis (if needed)

**For complex code analysis:** Spawn `researcher` agent:
```
Agent(subagent_type="researcher", prompt="
Research the codebase for: [bug/failure area]
Find:
1. When was the buggy code introduced? (git blame)
2. What commits relate to this area?
3. Are there similar patterns that handle this correctly?
For workflow failures: compare source.md/plan scope against
what was actually committed.
")
```

**For disputed root cause:** Spawn `hypothesis-evaluator` agent:
```
Agent(subagent_type="hypothesis-evaluator", prompt="
Post-mortem hypothesis: [suspected root cause]
Evidence so far: [what we know]
Verify using production data, metrics, and logs.
Return: CONFIRMED | REFUTED | INCONCLUSIVE with evidence.
")
```

#### 1e. Present Findings

Present to the user:
1. **What happened** — Clear description of the failure
2. **Primary gap** — The main workflow stage that should have caught this
3. **Secondary gaps** — Contributing factors
4. **Test gap** — What test would have caught this?
5. **Proposed fixes** — Concrete changes to prevent recurrence

**STOP HERE. Do not proceed to Step 2 until the user approves.**

### STEP 2: Apply Approved Fixes (only after user approval)

For each approved fix, apply it:

| Gap Found | Fix Target |
|---|---|
| Rule violated repeatedly | `AGENTS.md` |
| Plan didn't research area | `skills/plan/SKILL.md` |
| Build todos missed pattern | `skills/create-build-todos/SKILL.md` |
| Review didn't catch | `skills/review-*/SKILL.md` |
| Test missing | Test scenario documented for implementation |
| Verification missed | Verify skill or verification docs |
| Workflow step missing | Relevant skill's `SKILL.md` |

Then write the retrospective artifact:
```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="retrospective",
  content="<retrospective content>",
  command="/autodev-wtf-workflows"
)
```

## Gap Categories

### 1. Source/Plan Gap
- Source didn't clearly enumerate all scope items
- Plan didn't identify the constraint that caused the failure
- Plan didn't research relevant existing patterns

### 2. Build Todos Gap
- Build todos didn't cover all planned items
- Missing verification steps in build todos
- No 1:1 mapping to source scope items

### 3. Implementation Gap
- Code doesn't match what plan/build_todos specified
- Scope items silently dropped without discussion
- Missing error handling, edge case handling

### 4. Review Gap
- Reviewers didn't flag the missing scope
- Wrong review dimensions applied
- Review didn't diff source against implementation for completeness

### 5. Test Gap
- Happy path tested, edge case not
- Integration tests missing
- Test data didn't match production scenarios

### 6. Verification Gap
- Bug occurred after verification passed
- Verification didn't check the failing scenario
- Didn't wait for enough data to flow through

## Gap Severity Levels

| Severity  | Definition                                               |
| --------- | -------------------------------------------------------- |
| PRIMARY   | This gap directly caused the failure to escape detection |
| SECONDARY | This gap contributed but wasn't the main cause           |
| N/A       | This stage wouldn't have caught this type of failure     |

## Common Patterns

**"No plan" pattern:**
- Work was done ad-hoc without /plan
- Fix: Enforce planning for non-trivial changes

**"Silent scope reduction" pattern:**
- Agent implemented some items, silently dropped others, marked complete
- Fix: Review must diff source scope against implementation

**"Untested edge case" pattern:**
- Happy path tested, edge case not
- Fix: Add edge case checklist to verification

**"Rushed review" pattern:**
- Review done but not thorough
- Fix: Ensure right review dimensions applied

## Output Format

Use this structure for findings:

```markdown
## WTF Workflows Analysis

### What Happened
[2-3 sentence description of the failure]

### Primary Gap
**Stage:** [source | plan | build_todos | implementation | review | tests | verification]
**Severity:** PRIMARY
**What was missing:** [Specific description]
**Evidence:** [What artifact was checked and what it lacked]

### Secondary Gaps
| Stage | What was missing | Severity |
|---|---|---|
| [stage] | [description] | SECONDARY |

### Test Gap
**Missing test type:** [unit | integration | e2e]
**What should be tested:** [Specific scenario]
**Where to add:** [File path or area]

### Recommended Fixes

#### Fix 1: [Brief title]
**Target:** [file path]
**Type:** [new_file | add_content | update_content]
**Content:** [Exact content to add]
**Why:** [How this prevents recurrence]
```

## Evidence Quality

**Strong evidence for workflow gap:**
- Artifact exists but doesn't mention the failure area at all
- Step that should have verification was skipped
- Clear mismatch between plan and implementation
- Source lists N items, implementation covers N-K with no discussion

**Weak evidence (need more investigation):**
- Artifact partially covers the area
- Hard to say if verification would have caught it
- Edge case that's genuinely hard to predict

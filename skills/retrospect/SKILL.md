---
name: retrospect
description: Production incident post-mortem. Identifies workflow and test gaps, then fixes them.
---

# Retrospect

A bug reached production. Analyze the entire workflow pipeline to find which stage failed, then
actually fix the workflows, knowledge, and tests so it can't happen again. This is NOT a
reporting tool - it applies changes.

## Usage

```
/retrospect "Bug description: items missing associations"
/retrospect B0009                              # Bug ticket B0009
/retrospect 009                              # Bug/incident #009 (NNN format)
/retrospect F003                             # Feature F003 (FNNN format)
```

## When to Use

| Situation | Use `/retrospect`? | Instead Use |
|---|---|---|
| Bug reached production | Yes | - |
| Want to prevent similar bugs | Yes | - |
| Incident post-mortem | Yes | - |
| User correction or learning moment | **No** | `/compound` |
| Bug not yet in production | **No** | Fix directly |
| After review findings resolved | **No** | `/compound` |

**Key difference from `/compound`:** Retrospect examines the ENTIRE pipeline (plan -> build ->
review -> test -> verify -> deploy) for a specific production failure. Compound is lighter and
broader, triggered after any learning moment.

## Ticket Lookup

**If ticket ID given** (e.g., `B0003`, `F0009`):

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

**If only description given:** Search for related tickets or create a new one:

```
# Search first
results = mcp__autodev-memory__search_tickets(project=PROJECT, query="<description>")

# If no match, create new ticket
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="Retrospect: <slug>",
  type="bug", description="<description>",
  status="active", command="/retrospect"
)
```

## Process

### Phase 1: Gather Context

1. Load ticket with all artifacts via `get_ticket`
2. Get git history for related commits
3. Read the bug report or incident description
4. Check production state if tools available (DB, logs, metrics)

### Phase 2: Spawn Analysis Agents

Spawn agents in parallel based on what's needed:

**Always spawn:** `retrospector` agent with full context:

```
Task(subagent_type="retrospector", prompt="
Bug description: [description]

Work item (if found): [path or 'none']

Context from conversation: [any additional context]

Analyze which workflow stage should have caught this bug.
Identify specific gaps in workflows, knowledge, and tests.
Return analysis following the retrospect methodology template.
")
```

**Optional - deeper code analysis:** Spawn `researcher` agent in parallel:

```
Task(subagent_type="researcher", prompt="
Research the codebase for: [bug area]

Find:
1. When was the buggy code introduced? (git blame)
2. What commits relate to this area?
3. Are there similar patterns that handle this correctly?
4. Any memory entries that mention this area?
")
```

**Optional - verify suspected root cause:** When the root cause is disputed or unclear, spawn
`hypothesis-evaluator` agent in parallel to verify against production data:

```
Task(subagent_type="hypothesis-evaluator", prompt="
Post-mortem hypothesis evaluation for: [bug description]

Hypothesis: [suspected root cause from bug report or Phase 1 context]
Evidence so far: [what we know from the incident]
Testable prediction: [what production data should show if this is the cause]

Work item: [path]

Verify this root cause hypothesis using production data, metrics, and logs.
Return verdict: CONFIRMED | REFUTED | INCONCLUSIVE with evidence.
")
```

**When to include hypothesis-evaluator:**

| Situation | Include? | Why |
|---|---|---|
| Root cause is uncertain or debated | **Yes** | Evidence-backed conclusions |
| Multiple possible root causes | **Yes** | Disambiguate before applying fixes |
| Root cause is obvious (stack trace, clear error) | No | Don't over-verify the obvious |
| Production data/logs are unavailable | No | Agent can't verify without data |

### Phase 3: Synthesize Analysis

From the agent results, identify:

1. **Primary gap** - The main workflow stage that should have caught this
2. **Secondary gaps** - Contributing factors
3. **Test gap** - What test would have caught this before production?

### Phase 4: Apply Fixes

This is where retrospect differs from the old version. Don't just write a report - actually
fix things.

For each identified gap, apply the appropriate fix:

| Gap Type | Fix Action |
|---|---|
| Missing knowledge | Store via `mcp__autodev-memory__add_entry` (see below) |
| Missing AGENTS.md rule | Add rule to `AGENTS.md` |
| Plan didn't research this | Add research requirement to `plan` skill |
| Build todos missed pattern | Add pattern search to `create-build-todos` skill |
| Review didn't catch this | Add checklist item to appropriate `review-*` skill |
| Test didn't cover this | Add test scenario to testing strategy documentation |
| Verification missed scenario | Add verification step to `verify` skill docs |
| Workflow step missing | Add step to relevant skill |

**Present each proposed fix to the user for approval before applying.** Unlike `/compound`
in autonomous mode, retrospect always confirms - production incidents deserve careful attention.

### Phase 5: Write Retrospective

Store as retrospective artifact:

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="retrospective",
  content="<retrospective content>",
  command="/retrospect"
)
```

Content format:

```markdown
# Retrospective: [Work Item ID]

**Date:** YYYY-MM-DD
**Bug:** [Brief description]
**Impact:** [What happened in production]

## Root Cause

[What caused the bug]

## Primary Gap

**Stage:** [Which workflow stage failed]
**What was missing:** [Specific gap]
**Evidence:** [Why we know this stage should have caught it]

## Secondary Gaps

- [Contributing factor 1]
- [Contributing factor 2]

## Test Gap

**What test would have caught this:**
[Specific test scenario description]

## Fixes Applied

| Target | Change |
|---|---|
| [file path] | [what was added/changed] |

## Prevention

This bug cannot recur because:
- [Specific workflow improvement 1]
- [Specific knowledge addition 1]
- [Specific test addition 1]
```

## Knowledge Capture via MCP

For "Missing knowledge" gaps, store findings in the memory service:

```
# 1. Search for duplicates first
mcp__autodev-memory__search(
  queries=["<root cause keywords>"],
  project="<from <!-- mem:project=X --> in CLAUDE.md>"
)

# 2. If no duplicate, store the finding
mcp__autodev-memory__add_entry(
  project="<from <!-- mem:project=X --> in CLAUDE.md>",
  title="<1-sentence root cause / gotcha summary>",
  content="<Full explanation: what happened, why, how to prevent. 200-800 tokens.>",
  entry_type="gotcha",  # or "solution" or "pattern" as appropriate
  summary="<1-sentence summary>",
  tags=["retrospect", "<area>", "<technology>"],
  source="captured",
  caller_context={
    "skill": "retrospect",
    "reason": "<why this is worth persisting>",
    "action_rationale": "New entry — production incident revealed undocumented gotcha",
    "trigger": "retrospective knowledge gap"
  }
)
```

If the MCP tool is unavailable, skip this step silently.

## Output

- Retrospective artifact stored on ticket (always created)
- Memory service entries created/updated (if knowledge gap found)
- Skill files updated (if workflow gap found)
- Test scenarios documented (if test gap found)

Each retrospective results in at least one concrete change to prevent recurrence.

---

# Retrospect Methodology

Standards for conducting post-incident retrospectives that identify gaps in the development
workflow AND apply concrete fixes. This is not a reporting methodology - it produces actionable
fix recommendations.

## Purpose

When a bug reaches production, the goal is NOT just to fix it, but to:

1. **Where the workflow failed** - Which stage should have caught this?
2. **Why it failed** - What was missing from that stage?
3. **What test was missing** - What test would have caught this before production?
4. **Fix the workflow** - Apply concrete changes so this can't happen again

## Workflow Stages to Analyze

Examine each stage in reverse order (closest to production first):

| Stage                   | Artifact               | Key Questions                               |
| ----------------------- | ---------------------- | ------------------------------------------- |
| Production Verification | verification-report.md | Did we verify the right scenarios?          |
| Local Verification      | (test output)          | Were integration tests sufficient?          |
| Tests                   | test files             | What test scenario is missing?              |
| Review                  | review_todos/          | Did reviewers check the right dimensions?   |
| Implementation          | git diff, code         | Did code match plan? Quality issues?        |
| Build Todos             | build_todos/           | Were implementation steps complete?         |
| Plan                    | plan.md                | Did plan identify edge cases/constraints?   |
| Investigation (bugs)    | investigation.md       | Was root cause analysis thorough?           |
| Knowledge               | Memory service (MCP)   | Should there be a gotcha/reference/pattern? |

## Gap Categories

### 1. Plan Gap

**Symptoms:**

- Plan didn't identify the constraint that caused the bug
- Plan didn't research relevant existing patterns
- Plan missed important edge cases or scenarios

**Questions:**

- Was there a plan.md? If not, that's the gap
- Did the plan mention the area where the bug occurred?
- Did the plan research similar implementations?
- Were there edge cases the plan should have identified?

### 2. Build Todos Gap

**Symptoms:**

- Build todos didn't specify how to handle the failing case
- Missing verification steps in build todos
- No reference to relevant knowledge/gotchas

**Questions:**

- Were there build_todos? If not, that's the gap
- Did build todos include verification steps?
- Did build todos reference similar patterns in codebase?
- Should there have been a specific step for the bug area?

### 3. Implementation Gap

**Symptoms:**

- Code doesn't match what plan/build_todos specified
- Missing error handling, edge case handling
- Tests missing or inadequate

**Questions:**

- Did implementation follow the plan?
- Are there obvious code quality issues?
- Are tests present and covering the right scenarios?
- Did the implementer skip or misunderstand a build todo?

### 4. Review Gap

**Symptoms:**

- Reviewers didn't flag the issue
- Wrong review dimensions applied
- Review coverage incomplete

**Questions:**

- Was there a /review? If not, that's the gap
- Did review_todos exist for the affected area?
- Which review dimension should have caught this?
- Was reviewer context incomplete?

### 5. Local Verification Gap

**Symptoms:**

- Bug would have been caught with proper local testing
- Integration tests missing
- Test data didn't match production scenarios

**Questions:**

- Was local testing done before deployment?
- Were integration tests run?
- Did test data cover the failing scenario?
- Was verifier used?

### 6. Production Verification Gap

**Symptoms:**

- Bug occurred after `/verify prod` passed
- Verification didn't check the failing scenario
- Verification criteria incomplete

**Questions:**

- Was `/verify prod` run? If not, that's the gap
- Did verification-report.md cover the bug area?
- What verification step would have caught this?
- Was monitoring/alerting set up?

### 7. Knowledge Gap

**Symptoms:**

- A gotcha that should have been documented
- A pattern that wasn't in references
- A solution to a known issue that wasn't captured

**Questions:**

- Is this a recurring issue? - Add gotcha
- Is this a pattern others should know? - Add reference
- Is this a solution worth capturing? - Add solution

## Analysis Process

1. **Gather context**
   - Find the work item (if exists)
   - Read all artifacts: plan.md, build_todos/, review_todos/, etc.
   - Get git history for related commits
   - Read the bug report or incident description

2. **Trace the bug**
   - What is the bug? Be specific
   - When was it introduced? (git blame)
   - What feature/change introduced it?

3. **Analyze each stage**
   - For each stage, ask: "Should this stage have prevented the bug?"
   - If yes, identify specifically what was missing
   - Rate the gap severity: primary (main cause), contributing, or not applicable

4. **Identify root cause gap**
   - Usually ONE stage is the primary failure point
   - Other gaps may be contributing factors
   - Focus recommendations on the primary gap

5. **Identify test gap**
   - What test (unit, integration, e2e) would have caught this?
   - Does that test type exist for this area?
   - What specific scenario is missing?

6. **Produce fix recommendations**
   - Each fix must be concrete: specific file, specific content to add
   - The orchestrator will apply these fixes with user approval

## Fix Recommendation Format

Each recommended fix must be actionable by the orchestrator:

```markdown
#### Fix: [Brief title]
**Target:** [file path]
**Type:** [new_file | add_content | update_content]
**Content:**
[Exact content to add or create]
**Why:** [How this prevents recurrence]
```

## Fix Target Reference

| Gap Found | Fix Target |
|---|---|
| Missing knowledge | Memory service via `mcp__autodev-memory__add_entry` |
| Rule violated repeatedly | `AGENTS.md` |
| Plan didn't research | `skills/plan/SKILL.md` |
| Build todos missed pattern | `skills/create-build-todos/SKILL.md` |
| Review didn't catch | `skills/review-*/SKILL.md` |
| Test missing | Test scenario documented for implementation |
| Verification missed | Verify skill or verification docs |
| Workflow step missing | Relevant skill's `SKILL.md` |

## Output Template

Use the template at `templates/retrospective.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Evidence Quality

**Strong evidence for workflow gap:**

- Artifact exists but doesn't mention the bug area at all
- Step that should have verification was skipped
- Known pattern not applied despite documentation existing
- Clear mismatch between plan and implementation

**Weak evidence (need more investigation):**

- Artifact partially covers the area
- Hard to say if verification would have caught it
- Edge case that's genuinely hard to predict

## Gap Severity Levels

| Severity  | Definition                                           |
| --------- | ---------------------------------------------------- |
| PRIMARY   | This gap directly caused the bug to escape detection |
| SECONDARY | This gap contributed but wasn't the main cause       |
| N/A       | This stage wouldn't have caught this type of bug     |

## Common Patterns

**"No plan" pattern:**

- Work was done ad-hoc without /plan
- Fix: Enforce planning for non-trivial changes

**"Untested edge case" pattern:**

- Happy path tested, edge case not
- Fix: Add edge case checklist to verification

**"Misunderstood requirement" pattern:**

- Plan captured wrong understanding
- Fix: Better requirement clarification in source.md

**"Rushed review" pattern:**

- Review done but not thorough
- Fix: Ensure right review dimensions applied

**"Missing gotcha" pattern:**

- Known pitfall not documented
- Fix: Store via `mcp__autodev-memory__add_entry` as type `gotcha`

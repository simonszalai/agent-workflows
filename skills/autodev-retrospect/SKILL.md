---
name: autodev-retrospect
description: Investigate agent workflow failures and production incidents. Proposes fixes — never implements without approval.
---

# Retrospect

Analyze the entire workflow pipeline to find which stage failed, then propose concrete fixes.
This is a TWO-STEP process: investigate first, implement only after user approval.

## Scope

This skill covers TWO categories of failure:

1. **Production incidents** — bugs that reached production
2. **Agent workflow failures** — planned scope silently dropped during implementation,
   plan/build deviations, features marked complete but partially implemented

Both follow the same analysis process: trace what was planned, compare to what was delivered,
identify the gap.

## Usage

```
/autodev-retrospect "Bug description: items missing associations"
/autodev-retrospect B0009                   # Bug ticket B0009
/autodev-retrospect F0076                   # Feature F0076 (scope dropped?)
/autodev-retrospect "F076 didn't implement inline vision from F0064"
```

## When to Use

| Situation | Use it? | Instead Use |
|---|---|---|
| Bug reached production | Yes | - |
| Planned scope silently dropped | Yes | - |
| Feature marked complete but partially done | Yes | - |
| Want to prevent similar failures | Yes | - |
| Incident post-mortem | Yes | - |
| User correction or learning moment | **No** | `/compound` |
| Bug not yet in production | **No** | Fix directly |
| After review findings resolved | **No** | `/compound` |

**Key difference from `/compound`:** Retrospect examines the ENTIRE pipeline (plan -> build ->
review -> test -> verify -> deploy) for a specific failure. Compound is lighter and broader,
triggered after any learning moment.

## Ticket Lookup

**If ticket ID given** (e.g., `B0003`, `F0076`):

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
  status="active", command="/autodev-retrospect"
)
```

## Process — Two Steps

### STEP 1: Investigate and Propose (no edits)

This step is read-only. Gather evidence, analyze gaps, propose fixes. Do NOT edit any files.

#### 1a. Gather Context

1. Load ticket with all artifacts via `get_ticket`
2. Get git history for related commits
3. Read the bug report, incident description, or feature source document
4. Check production state if tools available (DB, logs, metrics)
5. **For workflow failures:** Read the source.md/plan to identify what was planned,
   then diff against what was actually implemented in the merged commits

#### 1b. Spawn Analysis Agents

Spawn agents in parallel based on what's needed:

**Always spawn:** `retrospector` agent with full context:

```
Agent(subagent_type="retrospector", prompt="
Bug/failure description: [description]

Work item (if found): [ticket content or 'none']

Context from conversation: [any additional context]

Analyze which workflow stage should have caught this.
Identify specific gaps in workflows, knowledge, and tests.
Return analysis following the retrospect methodology template.

IMPORTANT: For workflow failures (scope dropped, partial implementation),
compare what was planned (source.md, plan.md) against what was delivered
(git diff, merged code). The gap is in the stage that should have
verified completeness.
")
```

**Optional — deeper code analysis:** Spawn `researcher` agent in parallel:

```
Agent(subagent_type="researcher", prompt="
Research the codebase for: [bug/failure area]

Find:
1. When was the buggy code introduced? (git blame)
2. What commits relate to this area?
3. Are there similar patterns that handle this correctly?
4. Any memory entries that mention this area?

For workflow failures: compare the source.md/plan scope against
what was actually committed. List each planned item and whether
it was implemented.
")
```

**Optional — verify suspected root cause:** When the root cause is disputed or
unclear, spawn `hypothesis-evaluator` agent in parallel:

```
Agent(subagent_type="hypothesis-evaluator", prompt="
Post-mortem hypothesis evaluation for: [description]

Hypothesis: [suspected root cause]
Evidence so far: [what we know]
Testable prediction: [what production data should show if correct]

Work item: [ticket ID]

Verify this root cause hypothesis using production data, metrics, and logs.
Return verdict: CONFIRMED | REFUTED | INCONCLUSIVE with evidence.
")
```

**When to include hypothesis-evaluator:**

| Situation | Include? | Why |
|---|---|---|
| Root cause is uncertain or debated | **Yes** | Evidence-backed conclusions |
| Multiple possible root causes | **Yes** | Disambiguate before fixing |
| Root cause is obvious (stack trace, clear error) | No | Don't over-verify the obvious |
| Production data/logs are unavailable | No | Agent can't verify without data |

#### 1c. Synthesize and Present Findings

From the agent results, present to the user:

1. **What happened** — Clear description of the failure
2. **Primary gap** — The main workflow stage that should have caught this
3. **Secondary gaps** — Contributing factors
4. **Test gap** — What test would have caught this?
5. **Proposed fixes** — Concrete changes to prevent recurrence (see fix format below)

**STOP HERE. Present findings and proposed fixes to the user. Do not proceed to
Step 2 until the user approves.**

### STEP 2: Apply Approved Fixes (only after user approval)

For each fix the user approves, apply it:

| Gap Type | Fix Action |
|---|---|
| Missing knowledge | Store via `mcp__autodev-memory__create_entry` (see below) |
| Missing AGENTS.md rule | Add rule to `AGENTS.md` |
| Plan didn't research this | Add research requirement to `plan` skill |
| Build todos missed pattern | Add pattern search to `create-build-todos` skill |
| Review didn't catch this | Add checklist item to appropriate `review-*` skill |
| Test didn't cover this | Add test scenario to testing strategy documentation |
| Verification missed scenario | Add verification step to `verify` skill docs |
| Workflow step missing | Add step to relevant skill |

Then write the retrospective artifact:

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="retrospective",
  content="<retrospective content>",
  command="/autodev-retrospect"
)
```

Content format:

```markdown
# Retrospective: [Work Item ID]

**Date:** YYYY-MM-DD
**Failure type:** [production bug | workflow failure (scope dropped) | ...]
**Impact:** [What happened — bug in prod, wasted cost, missing feature, etc.]

## Root Cause

[What caused the failure]

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

This failure cannot recur because:
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
mcp__autodev-memory__create_entry(
  project="<from <!-- mem:project=X --> in CLAUDE.md>",
  title="<1-sentence root cause / gotcha summary>",
  content="<Full explanation: what happened, why, how to prevent. 200-800 tokens.>",
  entry_type="gotcha",  # or "solution" or "pattern" as appropriate
  summary="<1-sentence summary>",
  tags=["retrospect", "<area>", "<technology>"],
  source="captured",
  caller_context={
    "skill": "autodev-retrospect",
    "reason": "<why this is worth persisting>",
    "action_rationale": "New entry — failure revealed undocumented gotcha",
    "trigger": "retrospective knowledge gap"
  }
)
```

If the MCP tool is unavailable, skip this step silently.

## Fix Recommendation Format

Each recommended fix must be concrete enough to apply directly:

```markdown
#### Fix: [Brief title]
**Target:** [file path]
**Type:** [new_file | add_content | update_content | memory_entry]
**Content:**
[Exact content to add or create]
**Why:** [How this prevents recurrence]
```

## Output

- Findings and proposed fixes presented to user (Step 1 — always)
- Retrospective artifact stored on ticket (Step 2 — after approval)
- Memory service entries created/updated (Step 2 — if knowledge gap found)
- Skill files updated (Step 2 — if workflow gap found)
- Test scenarios documented (Step 2 — if test gap found)

Each retrospective results in at least one concrete change to prevent recurrence.

---

# Retrospect Methodology

Standards for conducting retrospectives that identify gaps in the development workflow AND
produce concrete fix recommendations. Step 1 is analysis-only; Step 2 is implementation.

## Purpose

When a failure occurs (production bug OR agent workflow failure), the goal is:

1. **Where the workflow failed** — Which stage should have caught this?
2. **Why it failed** — What was missing from that stage?
3. **What test was missing** — What test would have caught this?
4. **Propose fixes** — Concrete changes so this can't happen again
5. **Apply fixes** — Only after user approval

## Failure Types

### Production Bugs

A bug reached production. The code does the wrong thing.

### Agent Workflow Failures

The agent pipeline (plan -> build -> review -> verify) failed to deliver what was
specified. Common patterns:

- **Silent scope reduction** — Feature source lists 5 items, implementation does 3,
  marked as complete. No one noticed the missing 2.
- **Plan drift** — Implementation diverges from plan without updating the plan.
- **Partial completion** — Some sub-items done, others silently dropped.
- **Wrong abstraction** — Plan specified approach A, implementation used approach B
  without discussion.

For these failures, the "bug" is the gap between what was planned and what was
delivered. Trace it the same way: which stage should have verified completeness?

## Workflow Stages to Analyze

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
| Knowledge               | Memory service (MCP)   | Should there be a gotcha/reference/pattern?   |

## Gap Categories

### 1. Source/Plan Gap

**Symptoms:**

- Source didn't clearly enumerate all scope items
- Plan didn't identify the constraint that caused the failure
- Plan didn't research relevant existing patterns
- Plan missed important edge cases or scenarios

**Questions:**

- Was there a source.md / plan.md? If not, that's the gap
- Did the plan mention the area where the failure occurred?
- Was the scope clearly enumerable (checklist, not prose)?
- Did the plan research similar implementations?

### 2. Build Todos Gap

**Symptoms:**

- Build todos didn't cover all planned items
- Missing verification steps in build todos
- No reference to relevant knowledge/gotchas

**Questions:**

- Were there build_todos? If not, that's the gap
- Did build todos include verification steps?
- Did build todos have a 1:1 mapping to planned scope items?
- Should there have been a specific step for the failed area?

### 3. Implementation Gap

**Symptoms:**

- Code doesn't match what plan/build_todos specified
- Scope items silently dropped without discussion
- Missing error handling, edge case handling

**Questions:**

- Did implementation follow the plan?
- Were all build todo items completed?
- Did the implementer skip or misunderstand a build todo?
- Was the scope reduction discussed or just silently dropped?

### 4. Review Gap

**Symptoms:**

- Reviewers didn't flag the missing scope
- Wrong review dimensions applied
- Review coverage incomplete

**Questions:**

- Was there a /review? If not, that's the gap
- Did review check plan/source against implementation for completeness?
- Which review dimension should have caught this?

### 5. Local Verification Gap

**Symptoms:**

- Bug would have been caught with proper local testing
- Integration tests missing
- Test data didn't match production scenarios

**Questions:**

- Was local testing done before deployment?
- Were integration tests run?
- Did test data cover the failing scenario?

### 6. Production Verification Gap

**Symptoms:**

- Bug occurred after `/verify prod` passed
- Verification didn't check the failing scenario

**Questions:**

- Was `/verify prod` run? If not, that's the gap
- Did verification-report.md cover the failure area?
- What verification step would have caught this?

### 7. Knowledge Gap

**Symptoms:**

- A gotcha that should have been documented
- A pattern that wasn't in references
- A solution to a known issue that wasn't captured

**Questions:**

- Is this a recurring issue? -> Add gotcha
- Is this a pattern others should know? -> Add reference
- Is this a solution worth capturing? -> Add solution

## Analysis Process

1. **Gather context**
   - Find the work item (if exists)
   - Read all artifacts: source.md, plan.md, build_todos/, review_todos/, etc.
   - Get git history for related commits
   - Read the bug report or incident description

2. **Trace the failure**
   - What is the failure? Be specific
   - When was it introduced? (git blame for bugs, commit history for scope drops)
   - What feature/change introduced it?
   - For workflow failures: enumerate what was planned vs what was delivered

3. **Analyze each stage**
   - For each stage, ask: "Should this stage have prevented the failure?"
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
   - Present to user for approval — do NOT apply yet

## Fix Target Reference

| Gap Found | Fix Target |
|---|---|
| Missing knowledge | Memory service via `mcp__autodev-memory__create_entry` |
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

- Artifact exists but doesn't mention the failure area at all
- Step that should have verification was skipped
- Known pattern not applied despite documentation existing
- Clear mismatch between plan and implementation
- Source lists N items, implementation covers N-K with no discussion

**Weak evidence (need more investigation):**

- Artifact partially covers the area
- Hard to say if verification would have caught it
- Edge case that's genuinely hard to predict

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

- Combined ticket (e.g., F0076 = F0032 + F0064 + F0069 + F0071 + F0072)
- Agent implemented some items, silently dropped others, marked complete
- Fix: Review must diff source scope against implementation; build todos must
  have 1:1 mapping to source scope items

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
- Fix: Store via `mcp__autodev-memory__create_entry` as type `gotcha`

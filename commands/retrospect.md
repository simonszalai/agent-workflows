---
description: Production incident post-mortem. Identifies workflow and test gaps, then fixes them.
---

# Retrospect Command

A bug reached production. Analyze the entire workflow pipeline to find which stage failed, then
actually fix the workflows, knowledge, and tests so it can't happen again. This is NOT a
reporting tool - it applies changes.

## Usage

```
/retrospect "Bug description: items missing associations"
/retrospect work_items/active/009-missing-data
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

**Key difference from `/compound`:** Retrospect examines the ENTIRE pipeline (plan → build →
review → test → verify → deploy) for a specific production failure. Compound is lighter and
broader, triggered after any learning moment.

## Work Item Lookup

**If work item path given:** Use that folder as context.

**If number given (009 or F003):** Search for existing work item:

```bash
find work_items -maxdepth 2 -type d -name "*{id}*"
```

**If only description given:** Search for related work items by keyword, or create a new
incident work item in `work_items/active/NNN-retrospect-slug/`.

## Process

### Phase 1: Gather Context

1. Find and read all work item artifacts (plan.md, build_todos/, review_todos/, etc.)
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
Return analysis following the retrospect-methodology template.
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
| Plan didn't research this | Add research requirement to `plan-methodology` skill |
| Build todos missed pattern | Add pattern search to `build-plan-methodology` skill |
| Review didn't catch this | Add checklist item to appropriate `review-*` skill |
| Test didn't cover this | Add test scenario to testing strategy documentation |
| Verification missed scenario | Add verification step to `verify-local` or `verify-prod` docs |
| Workflow step missing | Add step to relevant command |

**Present each proposed fix to the user for approval before applying.** Unlike `/compound`
in autonomous mode, retrospect always confirms - production incidents deserve careful attention.

### Phase 5: Write Retrospective

Write `retrospective.md` to the work item folder with:

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

## Analysis Stages

The retrospective examines each workflow stage in reverse order (closest to production first):

| Stage | Artifact | Key Question |
|---|---|---|
| Production Verification | verification-report.md | Did we verify the right scenarios? |
| Local Verification | test output | Were integration tests sufficient? |
| Review | review_todos/ | Did reviewers check the right dimensions? |
| Implementation | git diff, code | Did code match plan? Quality issues? |
| Build Todos | build_todos/ | Were implementation steps complete? |
| Plan | plan.md | Did plan identify the constraint/edge case? |
| Investigation (bugs) | investigation.md | Was root cause analysis thorough? |
| Knowledge | Memory service (MCP) | Should there be a gotcha/reference? |
| Tests | test files | What test scenario is missing? |

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

- `retrospective.md` in work item folder (always created)
- Memory service entries created/updated (if knowledge gap found)
- Skill files updated (if workflow gap found)
- Command files updated (if process gap found)
- Test scenarios documented (if test gap found)

Each retrospective results in at least one concrete change to prevent recurrence.

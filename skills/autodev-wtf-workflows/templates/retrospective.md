---
title: "Retrospective: [Issue Title]"
date: YYYY-MM-DD
status: complete
work_item: [NNN or FNNN]
failure_type: [production_bug | workflow_failure]
bug_introduced_by: [commit hash or "unknown"]
---

# Retrospective: [Issue Title]

## Summary

[2-3 sentence description of what happened and why it matters]

## The Failure

**What happened:**
[Specific description of the bug behavior or scope gap]

**Failure type:**
[production bug | workflow failure (scope dropped) | workflow failure (plan drift) | ...]

**Impact:**
[User/system impact, data affected, duration, wasted cost]

**When introduced:**
[Commit, date, or change that introduced it]

**Related work item:**
[Link to original feature/bug work item, or "ad-hoc change"]

## Workflow Gap Analysis

### Primary Gap: [Stage Name]

**Severity:** PRIMARY

**What should have existed:**
[Specific artifact, step, or check that should have been present]

**What actually existed:**
[What was there, or "nothing"]

**Why this would have caught the failure:**
[Specific explanation of how this gap relates to the failure]

### Secondary Gaps

| Stage   | Severity  | Gap Identified                              |
| ------- | --------- | ------------------------------------------- |
| [Stage] | SECONDARY | [Brief description]                         |
| [Stage] | N/A       | [Why this stage wouldn't have caught it]    |

## Evidence

### Work Item Artifacts

| Artifact            | Status      | Notes                                  |
| ------------------- | ----------- | -------------------------------------- |
| source.md           | exists/none | [Quality assessment]                   |
| plan.md             | exists/none | [Did it cover the failure area?]       |
| investigation.md    | exists/none | [N/A for features]                     |
| build_todos/        | exists/none | [Did todos cover the failing case?]    |
| review_todos/       | exists/none | [Did reviewers flag it?]               |
| verification-report | exists/none | [Did verification cover the scenario?] |

### Git History

**Relevant commits:**

- `abc1234` - [commit message] - [how it relates to failure]

**Code blame:**

- Bug in `file.py:NN` introduced by commit `xyz5678` on YYYY-MM-DD

### Scope Comparison (workflow failures only)

**Planned items (from source.md):**

- [ ] Item 1 — implemented
- [ ] Item 2 — implemented
- [ ] Item 3 — **NOT implemented, silently dropped**

## Recommendations

### Immediate: Fix the Workflow Artifact

**What to add:**
[Specific addition to plan checklist, build todo template, review dimension, etc.]

**Where to add it:**
[File path or location]

**Proposed text:**

```markdown
[Exact text to add]
```

### Knowledge Documentation

**Type:** gotcha | reference | solution | none needed

**If memory entry needed:**

- **Type:** gotcha | pattern | solution
- **Title:** [Proposed title]
- **Key content:** [What it should capture]
- **Action:** Store via `mcp__autodev-memory__create_entry`

### Process Change (if recurring pattern)

**Pattern identified:** [Name of pattern, e.g., "silent scope reduction"]

**Suggested process change:**
[What to change in the workflow to prevent recurrence]

## Action Items

- [ ] [Specific action to fix primary gap]
- [ ] [Create knowledge doc if needed]
- [ ] [Update affected artifact template if needed]
- [ ] [Optional: process change if pattern is recurring]

## Lessons Learned

**What we learned:**
[Key insight from this retrospective]

**Applies to:**
[When this lesson is relevant for future work]

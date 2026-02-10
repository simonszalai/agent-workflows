---
title: "Learning Report: [Work Item ID]"
date: YYYY-MM-DD
status: complete
work_item: [NNN or FNNN]
findings_analyzed: N
workflow_gaps_found: N
mitigations_applied: N
---

# Learning Report: [Work Item ID]

## Summary

[1-2 sentence summary of what workflow gaps were discovered and how they were addressed]

## Findings Analyzed

| Category           | Count | Primary Gap |
| ------------------ | ----- | ----------- |
| Code quality       | N     | [gap type]  |
| Logic errors       | N     | [gap type]  |
| Missing cases      | N     | [gap type]  |
| Pattern violations | N     | [gap type]  |
| Security/perf      | N     | [gap type]  |
| **Total**          | N     |             |

---

## Workflow Gaps Discovered

This section documents what was lacking in the workflow that allowed issues to reach review.

### Gap 1: [Gap Type] - [Brief Title]

**Stage that failed:** [Plan | Build Todos | Implementation | Review Prompt | Knowledge Base]

**What was lacking:**
[Specific description of what was missing - e.g., "No checklist item to verify error handling for external APIs"]

**Evidence from findings:**

- Finding: "[finding title]" - [how it relates to this gap]
- Finding: "[finding title]" - [how it relates to this gap]

**Root cause:**
[Why this gap existed - missing checklist item, undocumented pattern, incomplete research, etc.]

### Gap 2: [Gap Type] - [Brief Title]

[Repeat structure for additional gaps]

### Secondary Gaps

| Gap Type   | Findings | What Was Lacking                |
| ---------- | -------- | ------------------------------- |
| [gap type] | N        | [brief description of the lack] |
| [gap type] | N        | [brief description of the lack] |

---

## Mitigations Applied

This section documents how each workflow gap was addressed to prevent recurrence.

### Mitigation 1: [Brief Title]

**Gap addressed:** [Reference to gap above]

**File changed:** `[path/to/file.md]`

**What was added:**

```markdown
[Exact content added to the file]
```

**Why this prevents recurrence:**
[How this change closes the gap]

### Mitigation 2: [Brief Title]

[Repeat structure for additional mitigations]

### Summary of Changes

| Target File                                 | Change Type     | Summary                |
| ------------------------------------------- | --------------- | ---------------------- |
| `.claude/knowledge/gotchas/[name].md`       | New document    | [what it documents]    |
| `.claude/knowledge/references/[name].md`    | New document    | [what it documents]    |
| `.claude/skills/plan-methodology/SKILL.md`  | Added content   | [research requirement] |
| `.claude/skills/build-plan-methodology/...` | Added content   | [pattern search]       |
| `.claude/skills/review-[type]/SKILL.md`     | Added checklist | [checklist item]       |
| `AGENTS.md`                                 | Added rule      | [rule added]           |

### No Mitigation Needed

| Finding         | Reason                           |
| --------------- | -------------------------------- |
| [finding title] | One-off mistake, not systemic    |
| [finding title] | Already documented in [location] |

---

## Patterns Observed

### Recurring Theme: [Pattern Name]

**Description:**
[What pattern emerged across multiple findings]

**Implication:**
[What this suggests about the workflow or codebase]

**Future attention:**
[What to watch for in future work items]

---

## Metrics

| Metric                 | Value |
| ---------------------- | ----- |
| Findings analyzed      | N     |
| Workflow gaps found    | N     |
| Mitigations applied    | N     |
| Knowledge docs created | N     |
| Workflow files updated | N     |
| No-action findings     | N     |

## Lessons for Future Work

**Key insight:**
[Most important learning from this analysis]

**Applies to:**
[When this lesson is relevant for future work items]

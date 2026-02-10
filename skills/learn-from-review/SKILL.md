---
name: learn-from-review
description: Root cause analysis for review findings. Identifies workflow gaps and applies targeted improvements.
---

# Learn from Review Methodology

Systematic analysis of review findings to prevent recurrence. Applied after resolve-review to turn
fixes into lasting improvements.

## Purpose

When reviewers catch issues, the goal is NOT just to fix them, but to understand:

1. **Which upstream stage failed** - Where should this have been caught earlier?
2. **Why it failed** - What was missing from that stage?
3. **How to prevent recurrence** - What to add to workflows, knowledge, or prompts?

## When to Use

- After `/resolve-review` completes (integrated into auto-build)
- When review findings reveal systemic issues
- To close the learning loop and make the workflow self-improving

## Gap Categories

Review findings typically stem from one of these upstream gaps:

### 1. Knowledge Gap

**Symptoms:**

- Finding involves a gotcha that should have been documented
- Pattern exists elsewhere in codebase but wasn't followed
- Solution to known issue wasn't captured

**Fix targets:**

- `.claude/knowledge/gotchas/` - Document the pitfall
- `.claude/knowledge/references/` - Document the pattern
- `AGENTS.md` - Add rule if repeatedly violated

### 2. Plan Gap

**Symptoms:**

- Requirement was ambiguous or incomplete
- Edge case wasn't identified during planning
- Constraint wasn't researched

**Fix targets:**

- `.claude/skills/plan-methodology/SKILL.md` - Add research requirement
- `.claude/knowledge/gotchas/` - Document the missed constraint

### 3. Build Todos Gap

**Symptoms:**

- Implementation step was missing or unclear
- Should have referenced existing pattern
- Verification step wasn't included

**Fix targets:**

- `.claude/skills/build-plan-methodology/SKILL.md` - Add research step
- `.claude/knowledge/references/` - Document the pattern to reference

### 4. Review Prompt Gap

**Symptoms:**

- Issue should have been caught by a specific review dimension
- Review skill doesn't check for this type of issue
- Review checklist is incomplete

**Fix targets:**

- `.claude/skills/review-*/SKILL.md` - Add checklist item
- `.claude/skills/review/SKILL.md` - Add new review dimension

### 5. Implementation Gap (Not Systemic)

**Symptoms:**

- One-off mistake, not a pattern
- Clear code quality issue
- Already well-documented but not followed

**Fix targets:**

- None (the fix itself is sufficient)
- Consider AGENTS.md rule if pattern repeats

## Analysis Process

### Step 1: Gather Resolved Findings

Read all files in `review_todos/` that have status: resolved or status: skipped.

Categorize by:

- **Fixed issues** (status: resolved) - These reveal what went wrong
- **Skipped issues** (status: skipped) - Note patterns but don't analyze deeply

### Step 2: Analyze Each Fixed Finding

For each resolved finding, determine:

1. **What type of issue?**
   - Code quality (style, naming, structure)
   - Logic error (wrong behavior)
   - Missing case (edge case, error handling)
   - Pattern violation (didn't follow existing conventions)
   - Security/performance (vulnerability, inefficiency)

2. **Which upstream gap?**
   - Could plan have identified this? - Plan Gap
   - Should build todos have specified this? - Build Todos Gap
   - Is this a known gotcha? - Knowledge Gap
   - Should review prompt check for this? - Review Prompt Gap
   - One-off mistake? - Implementation Gap (no systemic fix)

3. **What's the fix target?**
   - Identify specific file and section to update
   - Draft the addition (checklist item, gotcha doc, etc.)

### Step 3: Aggregate and Deduplicate

Multiple findings may point to the same gap. Consolidate:

- Group findings by gap category
- Identify root cause patterns
- Create single improvement for related findings

### Step 4: Prioritize Improvements

| Priority | Criteria                   | Action                |
| -------- | -------------------------- | --------------------- |
| **P1**   | 3+ findings from same gap  | Implement immediately |
| **P1**   | Security or data integrity | Implement immediately |
| **P2**   | 2 findings from same gap   | Implement             |
| **P2**   | Significant time wasted    | Implement             |
| **P3**   | Single finding, low impact | Document for future   |

### Step 5: Apply Improvements

For each prioritized improvement:

1. **Knowledge docs** - Use `/compound` pattern with YAML frontmatter
2. **Skill updates** - Add to checklist or research requirements
3. **AGENTS.md rules** - Only for repeatedly violated simple rules
4. **Review prompts** - Add specific checks to review skills

## Output

### Required: Save Learning Report

**CRITICAL**: Always save `learning-report.md` in the work item folder.

```
work_items/active/[work-item-id]/learning-report.md
```

Use the template at `templates/learning-report.md`.

The report MUST document:

1. **What was lacking in the workflow** - Which upstream stage failed and why
2. **How it was mitigated** - Specific files changed and what was added

### Learning Report Sections

1. **Findings Summary** - Count by category
2. **Gap Analysis** - Primary gaps identified with evidence (what was lacking)
3. **Improvements Applied** - What was changed and where (how it was mitigated)
4. **Patterns Observed** - Recurring themes for future attention

## Integration with Auto-Build

This methodology runs as Phase 5.5 in auto-build:

```
5. Resolve      - Auto-resolve p1/p2 findings
5.5 Learn      - Analyze findings, apply improvements
6. Verify      - /verify-local
```

## Improvement Templates

### Adding to Knowledge (Gotcha)

```markdown
---
title: [Pitfall discovered from review]
created: YYYY-MM-DD
tags: [area, discovered-from-review]
source: review-learning
---

# [Pitfall Title]

## The Gotcha

[What the review caught]

## Why It Happens

[Root cause from analysis]

## The Fix

[How to handle correctly]

## Prevention

[What was added to prevent recurrence]
```

### Adding to Review Skill

```markdown
## [Existing Section]

- [ ] [New check based on review finding]
```

### Adding to Plan Methodology

```markdown
## Research Requirements

- **[Area]**: [New research step based on what plan should have caught]
```

### Adding to Build Plan Methodology

```markdown
## Pattern Research

- Before implementing [area], search for: [specific patterns to find]
```

## Quality Checks

Before finalizing improvements:

- [ ] No duplicate knowledge docs (search existing)
- [ ] Improvement is specific and actionable
- [ ] Targets the root cause, not the symptom
- [ ] Written concisely (one-liners preferred for checklists)

## Example Analysis

**Finding:** "Missing error handling for API timeout"

**Analysis:**

- Type: Missing case (error handling)
- Upstream gap: Plan Gap - plan didn't identify API reliability constraints
- Also: Knowledge Gap - no gotcha for this API's timeout behavior

**Improvements:**

1. Add to plan-methodology: "When planning external API integrations, research
   timeout/retry requirements"
2. Create gotcha: `api-timeout-handling-YYYYMMDD.md`

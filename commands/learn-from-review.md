---
description: Analyze review findings to identify workflow gaps and apply improvements.
skills:
  - learn-from-review
  - compound
  - research-knowledge-base
---

# Learn from Review Command

Analyze resolved review findings to prevent recurrence. Creates knowledge docs and updates workflows
based on root cause analysis.

## Usage

```
/learn-from-review 009                              # Bug/incident #009 (NNN format)
/learn-from-review F001                             # Feature F001 (FNNN format)
/learn-from-review work_items/active/009-fix-timeout  # Use explicit path
```

## Prerequisites

- `review_todos/` exists with resolved findings
- At least one finding with status: resolved

## Process

1. **Load methodology:**
   - Read `.claude/skills/learn-from-review/SKILL.md`

2. **Gather resolved findings:**
   - Read all files in `review_todos/` with status: resolved
   - Analyze all priorities (p1, p2, p3) for systemic patterns

3. **Analyze each finding:**
   - Determine issue type (code quality, logic error, missing case, pattern violation)
   - Identify upstream gap (knowledge, plan, build todos, review prompt, implementation)
   - Draft improvement if systemic

4. **Aggregate improvements:**
   - Group findings by gap category
   - Deduplicate similar improvements
   - Prioritize by frequency and impact

5. **Apply improvements:**

   | Priority | Criteria                   | Action                |
   | -------- | -------------------------- | --------------------- |
   | P1       | 3+ findings from same gap  | Implement immediately |
   | P1       | Security or data integrity | Implement immediately |
   | P2       | 2 findings from same gap   | Implement             |
   | P3       | Single finding, low impact | Document but defer    |

6. **Create artifacts:**

   **Knowledge docs** (via `/compound` pattern):
   - Gotchas in `.claude/knowledge/gotchas/`
   - References in `.claude/knowledge/references/`
   - Rules in `AGENTS.md` (only for repeated violations)

   **Workflow updates:**
   - `.claude/skills/plan-methodology/SKILL.md` - Research requirements
   - `.claude/skills/build-plan-methodology/SKILL.md` - Pattern searches
   - `.claude/skills/review-*/SKILL.md` - Checklist items
   - `.claude/commands/build.md` - Verification steps

7. **Generate and save learning report:**
   - **REQUIRED**: Create `learning-report.md` in work item folder
   - Use template from `.claude/skills/learn-from-review/templates/`
   - Document all workflow gaps discovered and how they were mitigated
   - Include specific file paths and content for all changes made

8. **Update plan.md:**

   Add to Work Log:

   ```
   | YYYY-MM-DD | learn-from-review | Analyzed N findings | M improvements applied |
   ```

## Output

**Primary output: `learning-report.md`** in work item folder containing:

- Workflow gaps discovered (what was lacking in each workflow stage)
- Mitigations applied (how each gap was addressed with file paths and content)
- Patterns observed for future attention

**Secondary outputs:**

- Knowledge docs created (if any)
- Workflow updates applied (if any)
- Updated `plan.md` work log

## Example

**Input:** 5 review findings resolved for F007

**Analysis:**

- 3 findings related to missing error handling -> Knowledge Gap
- 1 finding about unused import -> Implementation Gap (no systemic fix)
- 1 finding about naming convention -> Plan Gap

**Output:**

- Created `.claude/knowledge/gotchas/api-error-handling-patterns-20260125.md`
- Updated `.claude/skills/plan-methodology/SKILL.md` with error handling research
- Created `learning-report.md` with full analysis

## Relation to Other Commands

| Command              | When to Use                                 |
| -------------------- | ------------------------------------------- |
| `/review`            | Run reviews, creates review_todos/          |
| `/resolve-review`    | Fix findings, marks status: resolved        |
| `/learn-from-review` | Analyze resolved findings, improve workflow |
| `/compound`          | Create knowledge docs (used internally)     |
| `/retrospect`        | Analyze production bugs (different focus)   |

## Auto-Build Integration

This command runs automatically as Phase 5.5 in `/auto-build`. Manual invocation is useful when:

- Running reviews manually (not via auto-build)
- Re-analyzing after more context is available
- Focusing specifically on workflow improvement

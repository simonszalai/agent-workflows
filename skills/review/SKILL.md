---
name: review
description: Review output format, priority levels, and synthesis methodology. Used by all reviewer agents.
---

# Review Methodology

Standards for conducting code reviews and producing review_todo files.

## Output Template

Use the template at `templates/review-todo.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Priority Levels

| Priority | Meaning                                          | Examples                               |
| -------- | ------------------------------------------------ | -------------------------------------- |
| **p1**   | Must fix - correctness, security, data integrity | Bugs, vulnerabilities, data loss risk  |
| **p2**   | Should fix - maintainability, performance        | YAGNI violations, complexity, patterns |
| **p3**   | Nice to have - style, minor improvements         | Naming, documentation, clarity         |

## Synthesis Methodology

When reviewing code changes:

1. **Understand intent** - Read plan.md and build_todos to know what was intended
2. **Check completeness** - Verify implementation matches the plan
3. **Apply skill checklists** - Systematically check each dimension
4. **Prioritize findings** - Critical issues first, style last
5. **Provide actionable fixes** - Show current code vs suggested fix

## Finding Quality

**Strong findings:**

- Specific file:line references
- Clear explanation of the issue
- Concrete suggested fix
- Impact assessment (complexity/performance/maintainability)

**Weak findings (improve before reporting):**

- Vague "could be better" without specifics
- Style preferences without justification
- Findings without suggested fixes

## Review Process

1. **Load context** - Read plan.md and changed files
2. **Apply checklists** - Use loaded skill checklists systematically
3. **Format findings** - Structure findings per template format
4. **Assess impact** - Evaluate complexity/performance/maintainability effects
5. **Prioritize** - Assign p1/p2/p3 based on severity

## Output Format

**For agents:** Return findings grouped by dimension. DO NOT write files - the orchestrator
consolidates findings from all agents and creates `review_todos/` files to avoid duplicates.

```markdown
## [Dimension] Findings

- [p2] src/path/file.py:45 - Issue description
- [p3] src/path/file.py:78 - Another issue
```

**For orchestrator:** After collecting agent outputs, create one `review_todos/NN-finding.md`
file per unique finding using the template at `templates/review-todo.md`.

**Numbering:** Before creating files, check existing `review_todos/` for highest index:
- List existing files matching `NN-*.md` pattern
- Extract index numbers and find the maximum
- Start new findings at `max_index + 1` (or 01 if directory is empty)

---
name: research-knowledge-base
description: Methodology for searching project knowledge base (references, gotchas, solutions). Portable to projects with .claude/knowledge/ folder.
---

# Knowledge Base Research Methodology

How to search and use a project's knowledge base for investigation.

## Knowledge Base Structure

```
.claude/knowledge/
├── references/    # Architecture, patterns, standards
├── gotchas/       # Known pitfalls and their solutions
└── solutions/     # Problem resolutions and fixes
```

## Search Patterns

**Find relevant references:**

```bash
# List all reference docs
ls .claude/knowledge/references/

# Search for topic in references
grep -r "topic" .claude/knowledge/references/
```

**Check for known gotchas:**

```bash
# List gotchas
ls .claude/knowledge/gotchas/

# Search gotchas for error pattern
grep -r "ErrorName" .claude/knowledge/gotchas/
```

**Find past solutions:**

```bash
# List solutions
ls .claude/knowledge/solutions/

# Search for similar problem
grep -r "keyword" .claude/knowledge/solutions/
```

## When to Use

**Before investigating:**

- Check if problem matches a known gotcha
- Look for past solutions to similar issues

**During investigation:**

- Reference architecture docs for context
- Check coding standards for expected patterns

**After finding root cause:**

- See if solution already documented
- Check gotchas for warnings about the fix

## Document Types

**References (`.claude/knowledge/references/`):**

- Architecture decisions
- Coding standards
- Deployment guides
- Pattern documentation

**Gotchas (`.claude/knowledge/gotchas/`):**

- Known pitfalls with specific technologies
- Edge cases that cause issues
- "Don't do X because Y" warnings

**Solutions (`.claude/knowledge/solutions/`):**

- Past problem resolutions
- Step-by-step fix documentation
- Workarounds and their rationale

## Output

When knowledge base findings are relevant:

```markdown
## Knowledge Base

**Relevant gotcha:** `.claude/knowledge/gotchas/connection-pooling.md`

- [Summary of gotcha and how it applies]

**Related solution:** `.claude/knowledge/solutions/oom-fix-20260110.md`

- [Summary of past fix and whether it applies]
```

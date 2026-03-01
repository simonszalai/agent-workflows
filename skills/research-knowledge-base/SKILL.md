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

## OpenMemory Search (Complementary)

In addition to file-based knowledge search, search OpenMemory for accumulated learnings.
OpenMemory captures cross-session insights, user preferences, and learnings that may not
have been written into knowledge files.

**Search project knowledge:**

```
search-memory(query="<topic> gotchas pitfalls", project_id="<from CLAUDE.md>")
search-memory(query="<topic> architecture patterns", project_id="<from CLAUDE.md>")
```

**Search user preferences:**

```
search-memory(query="<topic> debugging investigation preferences", user_preference=true)
```

**When to use OpenMemory vs file-based:**

- File-based: Structured, curated knowledge with YAML frontmatter (deterministic grep)
- OpenMemory: Semantic discovery, cross-session insights, user preferences
- **Always search both** - they capture different types of knowledge

If OpenMemory MCP is unavailable, mention once and continue with file-based search only.

## Output

When knowledge base findings are relevant:

```markdown
## Knowledge Base

**Relevant gotcha:** `.claude/knowledge/gotchas/connection-pooling.md`

- [Summary of gotcha and how it applies]

**Related solution:** `.claude/knowledge/solutions/oom-fix-20260110.md`

- [Summary of past fix and whether it applies]

**From OpenMemory:**

- [Memory title]: [How it applies to current investigation]
```

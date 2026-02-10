---
description: Audit knowledge organization, resolve contradictions, and ensure consistency.
---

# Heal Knowledge Base Command

Audit the knowledge base (`.claude/knowledge/`) for organization, contradictions, outdated content,
and consistency. Ensures knowledge is discoverable and accurate.

## Usage

```
/heal-knowledge-base                    # Full audit of knowledge base
/heal-knowledge-base gotchas            # Audit gotchas only
/heal-knowledge-base references         # Audit references only
/heal-knowledge-base solutions          # Audit solutions only
/heal-knowledge-base --fix              # Auto-fix issues (with confirmation)
```

## What This Command Audits

### 1. Frontmatter Validation

```yaml
---
title: Required
created: YYYY-MM-DD
tags: [required, array]
---
```

Checks:

- [ ] All files have valid YAML frontmatter
- [ ] Title field exists and is descriptive
- [ ] Created date is valid ISO format
- [ ] Tags array exists and is non-empty
- [ ] No duplicate titles across files

### 2. Organization Validation

```
.claude/knowledge/
  gotchas/       # Common pitfalls
  references/    # Architecture, patterns
  solutions/     # Problem resolutions
```

Checks:

- [ ] Files are in correct directory for their type
- [ ] File naming follows convention: `topic-YYYYMMDD.md`
- [ ] No duplicate content across files
- [ ] Appropriate file sizes (not too long, not too short)

### 3. Content Quality

Checks:

- [ ] No broken internal links/references
- [ ] Code examples are valid (no syntax errors)
- [ ] No outdated information (stale dates, deprecated patterns)
- [ ] Consistent formatting across files

### 4. Contradiction Detection

Checks:

- [ ] No conflicting advice between documents
- [ ] AGENTS.md rules don't contradict knowledge docs
- [ ] CLAUDE.md rules align with knowledge docs
- [ ] No duplicate gotchas with different solutions

## Process

### Phase 1: Collect Inventory

```bash
# Collect all knowledge files
find .claude/knowledge -name "*.md" -type f
```

### Phase 2: Parse and Validate

For each file:

1. Parse YAML frontmatter
2. Validate required fields
3. Check file naming convention
4. Extract key concepts and recommendations

### Phase 3: Cross-Reference Check

1. Build concept index from all files
2. Identify overlapping topics
3. Detect potential contradictions
4. Flag stale content (>6 months old)

### Phase 4: AGENTS.md Consistency

Compare knowledge docs to AGENTS.md rules:

1. Extract rules from AGENTS.md
2. Find related knowledge docs
3. Check for contradictions
4. Ensure Tier 1 rules have Tier 2 elaboration

### Phase 5: Report Issues

```markdown
## Knowledge Base Health Report

**Date:** YYYY-MM-DD
**Scope:** [all | gotchas | references | solutions]

### Summary

| Category   | Total | Valid | Issues |
| ---------- | ----- | ----- | ------ |
| Gotchas    | 15    | 14    | 1      |
| References | 8     | 8     | 0      |
| Solutions  | 12    | 10    | 2      |

### Issues Found

#### Critical (contradictions/errors)

1. **Contradicting advice**
   - Files: `gotchas/api-timeout-20260101.md` vs `gotchas/api-retry-20260115.md`
   - Issue: Different timeout recommendations (30s vs 60s)
   - Fix: Consolidate into single authoritative doc

#### Warning (organization/quality)

2. **Missing frontmatter**
   - File: `.claude/knowledge/solutions/quick-fix.md`
   - Issue: No YAML frontmatter
   - Fix: Add frontmatter with title, created, tags

3. **Stale content**
   - File: `.claude/knowledge/references/old-api-20250501.md`
   - Issue: Created > 6 months ago, may be outdated
   - Fix: Review and update or archive

#### Info (style/consistency)

4. **Non-standard naming**
   - File: `.claude/knowledge/gotchas/timeout_issue.md`
   - Issue: Uses underscores, missing date
   - Fix: Rename to `timeout-issue-YYYYMMDD.md`

### Tag Coverage

| Tag       | Count | Files           |
| --------- | ----- | --------------- |
| database  | 5     | [list of files] |
| api       | 3     | [list of files] |
| migration | 2     | [list of files] |
| (no tags) | 1     | quick-fix.md    |

### Recommendations

1. Consolidate duplicate timeout gotchas
2. Add tags to untagged files
3. Archive or update stale content
```

### Phase 6: Auto-Fix (if --fix)

For each fixable issue:

1. Show proposed fix
2. Ask for confirmation
3. Apply fix
4. Log change

Fixable issues:

- Missing frontmatter (add template)
- File naming (suggest rename)
- Missing tags (suggest based on content)

Non-fixable issues (require human decision):

- Contradictions between files
- Stale content review
- Content consolidation

## Common Issues

| Issue                     | Severity | Auto-Fix?   |
| ------------------------- | -------- | ----------- |
| Missing frontmatter       | Warning  | Yes         |
| Missing required field    | Warning  | Yes         |
| Non-standard naming       | Info     | Yes         |
| Stale content (>6 months) | Warning  | No (review) |
| Contradicting advice      | Critical | No (merge)  |
| Duplicate content         | Warning  | No (merge)  |
| Empty tags array          | Info     | Suggest     |

## Output

### Report File

Creates: `.claude/reports/knowledge-health-YYYYMMDD.md`

### Console Summary

```
Knowledge Base Health Check Complete

Critical: 1 (contradiction found)
Warning: 2
Info: 3

Run `/heal-knowledge-base --fix` to address fixable issues.
Full report: .claude/reports/knowledge-health-20260201.md
```

## Stale Content Criteria

Content is considered potentially stale if:

- Created date > 6 months ago
- References deprecated tools/APIs
- Mentions outdated patterns
- Links to non-existent files

## When to Run

- After bulk knowledge additions
- When getting unexpected behavior
- Quarterly maintenance
- Before major feature work (ensure knowledge is current)

## Related Commands

| Command                | Purpose                      |
| ---------------------- | ---------------------------- |
| `/heal-workflows`      | Audit workflow components    |
| `/heal-knowledge-base` | Audit knowledge organization |
| `/heal-work-items`     | Audit work item consistency  |
| `/compound`            | Add new knowledge docs       |

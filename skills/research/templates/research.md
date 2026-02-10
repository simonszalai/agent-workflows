---
title: "Research: [Topic]"
status: complete
created: YYYY-MM-DD
zones_searched: 5
total_files: 0
files_with_matches: 0
patterns_found: 0
inconsistencies: 0
---

# Research: [Topic]

> **Scope:** This document catalogs how [topic] is implemented across the codebase.
> For fixing issues, create a work item and use `/plan`.

## Executive Summary

[2-4 sentences: What patterns were found? Are they consistent? Key recommendations?]

**Coverage:** Searched {X} files across {Y} zones. {Z} files contained relevant patterns.

---

## Pattern Catalog

### Pattern 1: [Name]

**Usage:** {count} occurrences across {zones}
**Description:** [How this pattern works]

```typescript
// Canonical example from {file_path}
{code}
```

**Locations:**
- `{file_path}:{line}` - {brief note}
- `{file_path}:{line}` - {brief note}

---

### Pattern 2: [Name]

**Usage:** {count} occurrences across {zones}
**Description:** [How this pattern works]

```typescript
// Canonical example from {file_path}
{code}
```

**Locations:**
- `{file_path}:{line}` - {brief note}

---

## Zone Findings

### Routes (`app/routes/`)

**Files searched:** {count}
**Matches found:** {count}

| File | Line | Pattern | Notes |
| ---- | ---- | ------- | ----- |
| {file} | {line} | {pattern} | {notes} |

**Zone summary:** [Key observations for this zone]

---

### Components (`app/components/`)

**Files searched:** {count}
**Matches found:** {count}

| File | Line | Pattern | Notes |
| ---- | ---- | ------- | ----- |
| {file} | {line} | {pattern} | {notes} |

**Zone summary:** [Key observations for this zone]

---

### Models (`app/models/`)

**Files searched:** {count}
**Matches found:** {count}

| File | Line | Pattern | Notes |
| ---- | ---- | ------- | ----- |
| {file} | {line} | {pattern} | {notes} |

**Zone summary:** [Key observations for this zone]

---

### Core (`app/lib/`, `app/hooks/`, `app/types/`)

**Files searched:** {count}
**Matches found:** {count}

| File | Line | Pattern | Notes |
| ---- | ---- | ------- | ----- |
| {file} | {line} | {pattern} | {notes} |

**Zone summary:** [Key observations for this zone]

---

### Config (root, `prisma/`, `.claude/`)

**Files searched:** {count}
**Matches found:** {count}

| File | Line | Pattern | Notes |
| ---- | ---- | ------- | ----- |
| {file} | {line} | {pattern} | {notes} |

**Zone summary:** [Key observations for this zone]

---

## Inconsistencies

| #   | Issue | Severity | Locations | Impact |
| --- | ----- | -------- | --------- | ------ |
| 1   | [Description] | HIGH | {files} | [What could go wrong] |
| 2   | [Description] | MEDIUM | {files} | [Why it matters] |
| 3   | [Description] | LOW | {files} | [Minor concern] |

### 1. [Inconsistency Name]

**Severity:** HIGH | MEDIUM | LOW
**Pattern A:** [Description]
```typescript
// From {file_path}
{code}
```

**Pattern B:** [Description]
```typescript
// From {file_path}
{code}
```

**Impact:** [Why this inconsistency matters]
**Recommendation:** [Which pattern to standardize on and why]

---

## Recommendations

### Standardization Opportunities

1. **[Recommendation]**
   - Current state: [What's inconsistent]
   - Recommended pattern: [Which approach to adopt]
   - Files to update: {count}
   - Risk: Low | Medium | High

2. **[Recommendation]**
   - Current state: [What's inconsistent]
   - Recommended pattern: [Which approach to adopt]
   - Files to update: {count}
   - Risk: Low | Medium | High

### Missing Patterns

[Areas where the pattern should exist but doesn't]

- `{file_path}` - [What's missing]

---

## Metrics

| Metric | Value |
| ------ | ----- |
| Total files searched | {X} |
| Files with pattern | {X} |
| Unique pattern variants | {X} |
| HIGH severity issues | {X} |
| MEDIUM severity issues | {X} |
| LOW severity issues | {X} |

---

## Next Steps

- [ ] Review findings with team
- [ ] Decide on standardization approach
- [ ] Create work items for fixes (if needed)

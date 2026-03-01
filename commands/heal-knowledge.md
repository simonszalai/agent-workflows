---
description: Audit, consolidate, and reorganize the knowledge base.
max_turns: 100
---

# Heal Knowledge Command

Full knowledge base maintenance: audit for quality issues, group related files, merge duplicates,
and identify content that belongs elsewhere (skills, agents, CLAUDE.md, or AGENTS.md).

## Usage

```
/heal-knowledge                   # Full audit and consolidation
/heal-knowledge gotchas           # Scope to gotchas only
/heal-knowledge references        # Scope to references only
/heal-knowledge solutions         # Scope to solutions only
```

## When to Use

| Situation                                          | Use This? |
| -------------------------------------------------- | --------- |
| Knowledge base has grown organically, feels messy  | Yes       |
| Multiple docs cover the same topic                 | Yes       |
| Knowledge should be a skill or AGENTS.md rule      | Yes       |
| Suspect stale or contradictory docs                | Yes       |
| Adding new knowledge                               | No - /compound |

## Process

### Phase 1: Inventory and Read Everything

Read every file in `.claude/knowledge/` (all subdirectories). For each file, extract:

- Title, tags, created date from frontmatter
- Core topic and key concepts
- Actionable rules vs reference material vs troubleshooting steps
- Size and depth of content

Also read:

- `AGENTS.md` - current project-specific rules
- `CLAUDE.md` - current universal rules
- Skim `skills/*/SKILL.md` names and descriptions (frontmatter only)

### Phase 2: Audit Quality

Validate every file against these checks:

**Frontmatter:**

- [ ] Valid YAML frontmatter with title, created (YYYY-MM-DD), tags (non-empty array)
- [ ] No duplicate titles across files
- [ ] File naming follows `topic-YYYYMMDD.md` convention

**Content:**

- [ ] No broken internal links or references
- [ ] Code examples have no syntax errors
- [ ] No outdated information (stale dates, deprecated patterns)
- [ ] Consistent formatting

**Staleness:**

- [ ] Created date > 6 months ago → flag for review
- [ ] References deprecated tools/APIs
- [ ] Links to non-existent files

Collect all issues. Present fixable ones (missing frontmatter, naming) and offer to auto-fix.
Non-fixable ones (stale content, broken references) are flagged for user decision.

### Phase 3: Build Topic Map

Group all knowledge files by topic similarity. For each cluster:

1. **Identify the core topic** (e.g., "database migrations", "API error handling")
2. **List all files** that touch this topic
3. **Flag overlaps** - files that say the same thing differently
4. **Flag contradictions** - files that give conflicting advice
5. **Flag stragglers** - files that don't belong to any natural cluster

Present the topic map:

```
## Topic Map

### 1. Database Migrations (3 files)
- gotchas/migration-ordering-20260101.md - Migration ordering pitfalls
- solutions/migration-rollback-20260115.md - How to rollback migrations
- references/migration-patterns-20260120.md - Migration best practices
  **Overlap:** ordering gotcha duplicates content from patterns reference
  **Suggestion:** Merge into single reference, extract gotcha as short entry

### 2. API Timeout Handling (2 files)
- gotchas/api-timeout-20260105.md - Timeout defaults
- gotchas/api-retry-20260110.md - Retry strategies
  **Contradiction:** Different timeout values (30s vs 60s)
  **Suggestion:** Consolidate into one gotcha with correct values

### 3. Orphaned (1 file)
- solutions/quick-fix-20260103.md - One-off fix for deploy issue
  **Suggestion:** Archive or delete (one-time fix, no reuse value)
```

Wait for user to review the topic map before proceeding.

### Phase 4: Identify Promotions and Relocations

For each knowledge file, evaluate whether it belongs somewhere else:

| Signal                                              | Move To                |
| --------------------------------------------------- | ---------------------- |
| Short rule that agents keep violating               | AGENTS.md (Tier 1)     |
| Universal rule applying to all projects             | CLAUDE.md              |
| Detailed methodology with steps and checklists      | Skill (new or existing)|
| Project-specific patterns used during builds        | AGENTS.md              |
| Reusable across 2+ projects, not project-specific   | User-level skill       |

Present relocation proposals:

```
## Proposed Relocations

### 1. Promote to AGENTS.md
- gotchas/always-use-text-columns.md
  → Already a CLAUDE.md rule. Knowledge doc is redundant. **Delete.**

### 2. Convert to Skill
- references/react-performance-patterns.md
  → Detailed checklist with 15+ items. Better as a review skill.
  → Suggested: merge into skills/review-react-performance/SKILL.md

### 3. Move to CLAUDE.md
- gotchas/never-use-any-types.md
  → Universal rule, already partially in CLAUDE.md. **Delete duplicate.**

### 4. Keep in Knowledge Base
- solutions/postgres-deadlock-resolution.md
  → Good standalone solution doc. No changes needed.
```

Wait for user approval on each relocation.

### Phase 5: Execute Changes

For each approved action, execute in order:

1. **Auto-fixes first** - Fix frontmatter, naming conventions, missing tags
2. **Merges second** - Combine duplicate/overlapping files into consolidated docs
   - Preserve the best content from each source
   - Use the most recent date as the created date
   - Union all tags
   - Delete the source files after merge
3. **Promotions third** - Move content to skills/AGENTS.md/CLAUDE.md
   - For skill promotions: append to existing skill or propose new skill structure
   - For AGENTS.md/CLAUDE.md: append rule to appropriate section
   - Delete the knowledge file after promotion
4. **Deletions fourth** - Remove redundant/stale files user approved for deletion
5. **Reorganize survivors** - Ensure remaining files are in the right subdirectory
   - gotchas/ for pitfalls and their fixes
   - solutions/ for problem resolutions
   - references/ for patterns and guides

### Phase 6: Report

```
## Knowledge Base Health Report

**Date:** YYYY-MM-DD
**Scope:** [all | gotchas | references | solutions]

### Quality Fixes

| Issue              | Count | Auto-Fixed? |
| ------------------ | ----- | ----------- |
| Missing frontmatter| 2     | Yes         |
| Non-standard naming| 1     | Yes         |
| Stale content      | 1     | Flagged     |

### Consolidation

| Action      | Count | Details                               |
| ----------- | ----- | ------------------------------------- |
| Merged      | 3     | 7 files → 3 consolidated docs        |
| Promoted    | 2     | 1 to AGENTS.md, 1 to skill           |
| Deleted     | 1     | Redundant duplicate                   |
| Reorganized | 1     | Moved from solutions/ to gotchas/     |
| Unchanged   | 4     | Already well-organized                |

### Before/After

Before: 14 files across 3 directories
After: 8 files across 3 directories

### Tag Coverage

| Tag       | Count |
| --------- | ----- |
| database  | 5     |
| api       | 3     |
| migration | 2     |
```

## Key Principles

1. **Always ask before destructive actions** - Never delete or merge without explicit user approval
2. **Preserve information** - When merging, keep all unique content from each source
3. **Respect the tier system** - Short critical rules go to Tier 1, detailed docs stay Tier 2
4. **Skill detection** - If a knowledge doc looks like a checklist or methodology, it's a skill
5. **Less is more** - Fewer, better-organized docs beat many scattered ones

## Edge Cases

| Situation                                 | Action                                           |
| ----------------------------------------- | ------------------------------------------------ |
| Knowledge base is empty                   | Report "nothing to heal" and exit                |
| Only 1-2 files exist                      | Quick quality check and relocation scan, no merge|
| File references code that no longer exists | Flag for user decision (update or delete)        |
| Conflicting advice between files          | Present both versions, ask user which is correct |
| File is used by a skill's search pattern  | Warn before moving/renaming                      |

## Related Commands

| Command            | Purpose                           |
| ------------------ | --------------------------------- |
| `/compound`        | Add new knowledge docs            |
| `/heal-knowledge`  | Audit, consolidate, reorganize    |
| `/heal-workflows`  | Audit skills, agents, commands    |
| `/heal-work-items` | Audit work item consistency       |

---
description: Audit work items for naming, status, frontmatter consistency.
---

# Heal Work Items Command

Audit work items for consistent naming, status, frontmatter, and lifecycle compliance.
Ensures work items follow conventions and are in the correct state.

## Usage

```
/heal-work-items                    # Full audit of all work items
/heal-work-items active             # Audit active items only
/heal-work-items closed             # Audit closed items only
/heal-work-items backlog            # Audit backlog items only
/heal-work-items to_verify          # Audit items awaiting verification
/heal-work-items --fix              # Auto-fix issues (with confirmation)
```

## What This Command Audits

### 1. Naming Convention Validation

```
work_items/
  active/
    NNN-slug/           # Bug/incident (e.g., 009-timeout-fix)
    FNNN-slug/          # Feature (e.g., F001-new-feature)
    BNNN-slug/          # Auto-fix bug (e.g., B001-oom-fix)
  backlog/
  closed/
  completed/            # (Legacy folder - some projects use this)
  to_verify/
```

Checks:

- [ ] Folder names follow `NNN-slug`, `FNNN-slug`, or `BNNN-slug` pattern
- [ ] Slugs are kebab-case
- [ ] Numbers are properly padded (3 digits minimum)
- [ ] **No duplicate IDs across ANY folder** (CRITICAL - check all states)
- [ ] No items at root work_items/ level (should be in state folder)

### 2. CRITICAL: Duplicate ID Detection

**This is the most important check.** Scan ALL locations for ID conflicts:

```bash
# Check for duplicate bug numbers
find work_items -type d -name "[0-9]*-*" | \
  sed 's/.*\///; s/-.*//' | sort | uniq -d

# Check for duplicate feature numbers
find work_items -type d -name "F[0-9]*-*" | \
  sed 's/.*\///; s/F//; s/-.*//' | sort | uniq -d

# Check for duplicate auto-fix bug numbers
find work_items -type d -name "B[0-9]*-*" | \
  sed 's/.*\///; s/B//; s/-.*//' | sort | uniq -d
```

If any duplicates are found, this is a **CRITICAL** issue that blocks workflow.

### 3. Required Files Validation

**All work items must have:**

```
source.md              # Required: problem/feature description
```

**Work items in progress should have (based on stage):**

```
investigation.md       # For bugs after /investigate
plan.md                # After /plan
build_todos/           # After /create-build-todos
review_todos/          # After /review
deployment-guide.md    # After /create-deployment-guide
verification-report.md # After /verify-local
conclusion.md          # In closed/ items
```

### 4. Frontmatter Validation

**source.md frontmatter:**

```yaml
---
type: feature | bugfix | incident | research
created: YYYY-MM-DD
status: active | on_hold | blocked
---
```

**plan.md frontmatter:**

```yaml
---
status: draft | approved | in_progress | complete
created: YYYY-MM-DD
---
```

**conclusion.md frontmatter (closed items):**

```yaml
---
status: closed
closed: YYYY-MM-DD
outcome: completed | wont_fix | duplicate
---
```

### 5. Lifecycle Consistency

Checks:

- [ ] Items in `active/` have active work (recent commits or logs)
- [ ] Items in `closed/` have conclusion.md
- [ ] Items in `to_verify/` have verification pending
- [ ] Items in `backlog/` don't have active work started
- [ ] Stale items flagged (no activity for 14+ days)

### 6. Cross-Reference Validation

Checks:

- [ ] work_items/active/ items have corresponding branches
- [ ] PRs reference work item IDs
- [ ] Conclusion.md references PR (if applicable)

## Process

### Phase 1: Collect Inventory

```bash
# Collect all work items (including legacy locations)
find work_items -type d \( -name "[0-9]*-*" -o -name "F[0-9]*-*" -o -name "B[0-9]*-*" \)
```

### Phase 2: Check for Duplicates FIRST

This is the most critical check - do it before anything else:

```bash
# Extract all IDs and check for duplicates
find work_items -type d -name "[0-9]*-*" | sed 's/.*\///; s/-.*//' | sort | uniq -d
find work_items -type d -name "F[0-9]*-*" | sed 's/.*\///; s/F//; s/-.*//' | sort | uniq -d
find work_items -type d -name "B[0-9]*-*" | sed 's/.*\///; s/B//; s/-.*//' | sort | uniq -d
```

If duplicates found, report them immediately as CRITICAL.

### Phase 3: Validate Each Item

For each work item:

1. Check folder naming convention
2. Verify required files exist
3. Parse and validate frontmatter
4. Check lifecycle state consistency

### Phase 4: Report Issues

```markdown
## Work Items Health Report

**Date:** YYYY-MM-DD
**Scope:** [all | active | closed | backlog | to_verify]

### Summary

| Folder    | Total | Valid | Issues |
| --------- | ----- | ----- | ------ |
| active    | 5     | 4     | 1      |
| backlog   | 12    | 12    | 0      |
| closed    | 45    | 43    | 2      |
| to_verify | 2     | 2     | 0      |

### Issues Found

#### Critical (blocks workflow)

1. **DUPLICATE ID DETECTED**
   - ID: `031`
   - Locations:
     - `work_items/completed/031-stage1-score-saving/`
     - `work_items/completed/031-adr-currency-mismatch-multiples/`
   - Fix: Renumber one of these items to the next available number

2. **Missing source.md**
   - Path: `work_items/active/F015-new-feature/`
   - Issue: No source.md found
   - Fix: Create source.md with feature description

#### Warning (incomplete state)

3. **Stale active item**
   - Path: `work_items/active/009-old-bug/`
   - Issue: No activity for 21 days
   - Fix: Move to backlog or continue work

4. **Missing conclusion.md**
   - Path: `work_items/closed/F010-completed/`
   - Issue: Closed item without conclusion
   - Fix: Add conclusion.md documenting outcome

#### Info (naming/consistency)

5. **Non-standard naming**
   - Path: `work_items/active/feature-12-something/`
   - Issue: Doesn't follow FNNN-slug pattern
   - Fix: Rename to F012-something

6. **Item in wrong location**
   - Path: `work_items/F001-authenticated-scraping/`
   - Issue: Item at root level, not in state folder
   - Fix: Move to appropriate state folder (active/backlog/closed)

### Work Item Status

| ID   | Title       | Folder | Days Since Activity |
| ---- | ----------- | ------ | ------------------- |
| F015 | New Feature | active | 2                   |
| 009  | Old Bug     | active | 21 (stale)          |
| F010 | Completed   | closed | 45                  |

### Recommendations

1. **URGENT:** Fix duplicate IDs before any new work items are created
2. Move stale items to backlog or close
3. Add missing conclusion.md to closed items
4. Fix non-standard naming for 2 items
5. Move items from root to proper state folders
```

### Phase 5: Auto-Fix (if --fix)

For each fixable issue:

1. Show proposed fix
2. Ask for confirmation
3. Apply fix
4. Log change

Fixable issues:

- Missing frontmatter (add template)
- Non-standard naming (rename folder)
- Missing conclusion.md (create from git history)
- Items at root level (move to appropriate state folder)

Non-fixable issues (require human decision):

- **Duplicate IDs** - which one to renumber?
- Missing source.md (need human to describe)
- Stale items (need decision: continue or close)

## Common Issues

| Issue                  | Severity | Auto-Fix? |
| ---------------------- | -------- | --------- |
| Duplicate ID           | Critical | No        |
| Missing source.md      | Critical | No        |
| Item at root level     | Warning  | Yes       |
| Missing frontmatter    | Warning  | Yes       |
| Non-standard naming    | Info     | Yes       |
| Stale item (14+ days)  | Warning  | No        |
| Missing conclusion.md  | Warning  | Partial   |
| Wrong folder for state | Warning  | Yes       |

## Stale Item Criteria

An item is considered stale if:

- In `active/` with no git commits for 14+ days
- In `active/` with no work log entries for 14+ days
- In `to_verify/` for 7+ days without verification
- In `backlog/` but has active branches

## Output

### Report File

Creates: `.claude/reports/work-items-health-YYYYMMDD.md`

### Console Summary

```
Work Items Health Check Complete

Critical: 2 (duplicate IDs, missing source.md)
Warning: 3 (stale items, items at root)
Info: 2 (naming)

Run `/heal-work-items --fix` to address fixable issues.
Full report: .claude/reports/work-items-health-20260201.md
```

## Folder Lifecycle

```
backlog/     -> Queued work, not started
     |
     v (when /plan or /investigate starts)
active/      -> Work in progress
     |
     v (when deployed)
to_verify/   -> Deployed, awaiting verification
     |
     v (when verification passes)
closed/      -> Complete with conclusion.md
```

## When to Run

- **Before creating any new work item** (to catch existing duplicates)
- Weekly maintenance
- Before sprint planning
- When work items seem disorganized
- After bulk operations on work items

## Related Commands

| Command                | Purpose                      |
| ---------------------- | ---------------------------- |
| `/heal-workflows`      | Audit workflow components    |
| `/heal-knowledge-base` | Audit knowledge organization |
| `/heal-work-items`     | Audit work item consistency  |

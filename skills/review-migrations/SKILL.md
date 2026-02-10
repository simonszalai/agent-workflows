---
name: review-migrations
description: Data migration safety and ID mapping validation. Used by data-migration-expert agent. Portable to Cursor.
---

# Migration Review Standards

Standards for reviewing data migrations, backfills, and data transformations. Apply these to prevent data corruption.

## Core Principle

**Never trust fixtures or assumptions** - verify mappings match production data.

## Review Checklist

### 1. Understand the Real Data

- [ ] What tables/rows does the migration touch? List explicitly.
- [ ] What are the **actual** values in production? Document SQL to verify.
- [ ] If mappings/IDs/enums involved, paste assumed vs live mapping side-by-side.
- [ ] Never trust fixtures - they often have different IDs than production.

### 2. Validate Migration Code

- [ ] Are `up` and `down` reversible or documented as irreversible?
- [ ] Does migration run in chunks, batched transactions, or with throttling?
- [ ] Are `UPDATE ... WHERE ...` clauses scoped narrowly?
- [ ] Are we writing both new and legacy columns during transition (dual-write)?
- [ ] Are there foreign keys or indexes that need updating?

### 2a. Constraint Naming (Critical)

**All constraints MUST have explicit names.** Check for:

- [ ] No `None` in `op.drop_constraint()` calls in downgrade
- [ ] All `op.create_foreign_key()` have first param as explicit name
- [ ] All `op.create_unique_constraint()` have explicit names
- [ ] All `op.create_check_constraint()` have explicit names

**Naming convention:**

| Type   | Pattern                        | Example               |
| ------ | ------------------------------ | --------------------- |
| FK     | `fk_{table}_{ref_table}_{col}` | `fk_alert_company_id` |
| Unique | `uq_{table}_{cols}`            | `uq_user_email`       |
| Check  | `ck_{table}_{desc}`            | `ck_score_range`      |

See `.claude/knowledge/gotchas/migration-downgrade-named-constraints-*.md`

### 3. Verify Mapping/Transformation Logic

- [ ] For each CASE/IF mapping, confirm source data covers every branch (no silent NULL)
- [ ] If constants are hard-coded, compare against production query output
- [ ] Watch for copy/paste mappings that silently swap IDs
- [ ] If data depends on time windows, ensure timestamps/zones align with production

### 4. Check Observability & Detection

- [ ] What metrics/logs/SQL will run immediately after deploy?
- [ ] Are there alarms watching impacted entities (counts, nulls, duplicates)?
- [ ] Can we dry-run in staging with anonymized prod data?

### 5. Validate Rollback & Guardrails

- [ ] Is code path behind a feature flag or environment variable?
- [ ] How do we restore data if we need to revert?
- [ ] Are manual scripts idempotent with SELECT verification?

### 6. Structural Refactors & Code Search

- [ ] Search for every reference to removed columns/tables/associations
- [ ] Check background jobs, admin pages, rake tasks for deleted associations
- [ ] Do any serializers, APIs, or analytics jobs expect old columns?
- [ ] Document exact search commands for future reviewers

## Quick Reference SQL

```sql
-- Check legacy → new value mapping
SELECT legacy_column, new_column, COUNT(*)
FROM <table_name>
GROUP BY legacy_column, new_column
ORDER BY legacy_column;

-- Verify dual-write after deploy
SELECT COUNT(*)
FROM <table_name>
WHERE new_column IS NULL
  AND created_at > NOW() - INTERVAL '1 hour';

-- Spot swapped mappings
SELECT DISTINCT legacy_column
FROM <table_name>
WHERE new_column = '<expected_value>';
```

## Common Bugs to Catch

1. **Swapped IDs** - `1 => TypeA, 2 => TypeB` in code but `1 => TypeB, 2 => TypeA` in production
2. **Missing error handling** - `.fetch(id)` crashes on unexpected values
3. **Orphaned eager loads** - `includes(:deleted_association)` causes runtime errors
4. **Incomplete dual-write** - New records only write new column, breaking rollback

## Issue Reporting Format

For each issue:

- **File:Line** - Exact location
- **Issue** - What's wrong
- **Blast Radius** - How many records/users affected
- **Fix** - Specific code change needed

**Refuse approval until there is a written verification + rollback plan.**

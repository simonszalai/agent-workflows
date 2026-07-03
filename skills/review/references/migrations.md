# Migration Review Standards

Standards for reviewing data migrations, backfills, and data transformations. Apply these to prevent data corruption.

Output contract: structured findings JSON per `findings-schema.json` (severity p1/p2/p3) —
no other format.

## Core Principle

**Never trust fixtures or assumptions** - verify mappings match production data.

## Review Checklist

### 1. Understand the Real Data

- [ ] What tables/rows does the migration touch? List explicitly.
- [ ] What are the **actual** values in production? Document SQL to verify.
- [ ] If mappings/IDs/enums involved, paste assumed vs live mapping side-by-side.
- [ ] Never trust fixtures - they often have different IDs than production.


## ts-prefect exception — Atlas after E0017

ts-prefect no longer uses Alembic for application schema migrations. If reviewing ts-prefect:

- Do **not** ask for `alembic revision`, `alembic heads`, `alembic merge`, or
  `migrations/versions/**`. Those files were decommissioned in E0017/M3.
- Review SQLModel/Atlas changes instead: `ts_schemas/models/**`, `atlas.hcl`, `atlas/plans/**`,
  `cli_tools/atlas/**`, and `migrations/db_object_manifest.py`.
- Required evidence is Atlas additive-only safety, reviewed committed prod plan match/no-op for
  production, DB-only hook success, and `verify_schema_truth.py`.
- A diff that reintroduces Alembic config/versions in ts-prefect is a blocker.

The Alembic checklist below remains valid for repos that still actively use Alembic.

### 2. Validate Migration Code

- [ ] **Correct module prefix**: `sa.Column()` not `op.Column()` — `alembic.op` has no
  `Column` attribute. Same for `sa.Text()`, `sa.Integer()`, etc. The `op` module provides
  DDL operations only (`add_column`, `create_table`), NOT type constructors.
- [ ] Are `up` and `down` reversible or documented as irreversible?
- [ ] Does migration run in chunks, batched transactions, or with throttling?
- [ ] Are `UPDATE ... WHERE ...` clauses scoped narrowly?
- [ ] Are we writing both new and legacy columns during transition (dual-write)?
- [ ] Are there foreign keys or indexes that need updating?
- [ ] **Lock contention**: Does DDL (`DROP COLUMN`, `RENAME COLUMN`, `ALTER TYPE`) target
  tables with active workloads? These require `AccessExclusiveLock` and can deadlock with
  running queries. `ADD COLUMN` (nullable) is safe. Flag high-traffic tables.

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

See memory entry: "migration downgrade named constraints" (search memory service if not auto-injected)

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
- [ ] If scripts/tools were moved or renamed, grep `.github/workflows/` for old paths — including cross-branch steps that checkout `origin/main`
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

**File a p1 `manual` finding if no written verification + rollback plan exists.**


### Post-Merge Head Check (Branch Merges)

For repos that still use Alembic, when merging main into a feature branch (or vice versa), both branches may have added
migrations, creating multiple Alembic heads. CI will fail with "Multiple heads are present".

- [ ] After `git merge origin/main`, run `alembic heads` — must show exactly 1 head
- [ ] If multiple heads: `alembic merge heads -m "merge <branch1> and <branch2>"`
- [ ] Verify single head before pushing: `alembic heads` shows 1 result

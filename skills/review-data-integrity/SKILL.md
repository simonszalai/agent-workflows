---
name: review-data-integrity
description: Data integrity and migration safety checklist. Used by data-integrity-guardian agent. Portable to Cursor.
---

# Data Integrity Review Standards

Standards for data integrity review. Apply these when reviewing database migrations, data models, or code that manipulates persistent data.

## Core Review Areas

### 1. Database Migration Analysis

- Check for reversibility and rollback safety
- Identify potential data loss scenarios
- Verify handling of NULL values and defaults
- Assess impact on existing data and indexes
- Ensure migrations are idempotent when possible
- Check for long-running operations that could lock tables

### 2. Model Compliance with Coding Standards

When reviewing features that use database models (new OR existing):

- **TEXT vs VARCHAR**: Verify all string fields use TEXT, not VARCHAR with `max_length`
  - Check for `max_length=` in Field() definitions - these create VARCHAR columns
  - Correct pattern: `Field(description="...")` without max_length
  - If existing models have `max_length`, flag for remediation
- **Timestamps**: Verify `server_default=text("CURRENT_TIMESTAMP")` on timestamp columns
- **Pydantic models**: Ensure return types are Pydantic models, not dicts
- **Repository registration**: New repositories MUST be registered in `DatabaseResource`
  - Check: `grep "self.foo = FooRepository" src/resources/database/database.py`
  - If code uses `DatabaseBase()` directly instead of `DatabaseResource()`, flag as p1

This check applies to ALL models in the feature's data path, not just newly created models.

### 3. Data Constraints Validation

- Verify appropriate validations at model and database levels
- Check for race conditions in uniqueness constraints
- Ensure foreign key relationships are properly defined
- Validate business rules are enforced consistently
- Identify missing NOT NULL constraints

### 4. Transaction Boundary Review

- Ensure atomic operations are wrapped in transactions
- Check for proper isolation levels
- Identify potential deadlock scenarios
- Verify rollback handling for failed operations
- Assess transaction scope for performance impact

### 5. Impossible State Detection

For pipeline features with multi-step flows, identify **impossible database states** that
indicate control flow bugs:

- Combinations of column values that should never coexist (e.g., `is_new_development=False`
  with `impact_score IS NOT NULL` -- a score requires novelty assessment which requires
  `is_new_development=True`)
- Records marked as failed/incomplete that have fields only set on success
- Status flags that contradict timestamps or related records

**During review:** Ask "what database state would result if step N fails after step N-1
succeeds?" For each multi-step operation, verify the exception handler produces consistent
database state.

**During verification:** Include queries that check for impossible states:

```sql
-- Example: entries should not have impact_score unless they're novel
SELECT count(*) FROM macro_story_entries
WHERE is_new_development = false AND impact_score IS NOT NULL;
-- Expected: 0
```

### 6. Referential Integrity Preservation

- Check cascade behaviors on deletions
- Verify orphaned record prevention
- Ensure proper handling of dependent associations
- Validate polymorphic associations maintain integrity
- Check for dangling references

### 7. Privacy Compliance

- Identify personally identifiable information (PII)
- Verify data encryption for sensitive fields
- Check for proper data retention policies
- Ensure audit trails for data access
- Validate data anonymization procedures
- Check for GDPR right-to-deletion compliance

## Analysis Approach

1. Start with high-level assessment of data flow and storage
2. Identify critical data integrity risks first
3. Provide specific examples of potential data corruption scenarios
4. Suggest concrete improvements with code examples
5. Consider both immediate and long-term implications

## Issue Reporting Format

When identifying issues:

- Explain the specific risk to data integrity
- Provide clear example of how data could be corrupted
- Offer safe alternative implementation
- Include migration strategies for fixing existing data

## Priority Order

1. Data safety and integrity above all else
2. Zero data loss during migrations
3. Maintaining consistency across related data
4. Compliance with privacy regulations
5. Performance impact on production databases

## Reminder

In production, data integrity issues can be catastrophic. Be thorough, be cautious, and always consider the worst-case scenario.

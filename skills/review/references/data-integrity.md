# Data Integrity Review Standards

Standards for data integrity review. Apply these when reviewing database migrations, data models, or code that manipulates persistent data.

## Core Review Areas

### 1. Database Migration Analysis

- **Schema-deploy sync (CRITICAL):** If the schema file was modified (schema.prisma,
  models.py/SQLModel, Atlas HCL/plans, etc.), verify the repo's active schema deploy path covers
  ALL schema changes. For Prisma/Alembic repos this usually means a new migration exists. For
  ts-prefect after E0017, this means Atlas additive-only safety, reviewed committed prod plan
  match/no-op when production is affected, DB-only hook success, and `verify_schema_truth.py`;
  do **not** request Alembic revisions there. Tools like `prisma db push` or `prisma generate`
  sync the local dev DB/client only. Flag as **p1** if schema changes lack their repo-specific
  deploy/apply evidence.
- **Multi-DB/client rollout sync (CRITICAL):** If an app uses a derived ORM/client schema
  against multiple runtime databases (for example `autodev-dashboard` Prisma generated from
  `autodev-memory` Alembic-owned DBs), verifying that the migration/schema apply file exists is not enough.
  Verify the schema change is applied to every configured runtime DB before the generated client or
  app code expects the new scalar column. A lagging DB still crashes `findMany`/default selects
  with `P2022 column does not exist`. Flag as **p1** if a generated client/schema selects a
  new column before all target DBs are at the required schema version/head or the deployment plan
  explicitly gates code rollout after DB rollout.
- **Raw SQL column validation (CRITICAL):** For every `$queryRaw` / raw SQL query, verify that
  ALL referenced columns exist in the current schema. Raw SQL bypasses ORM type safety entirely
  — a typo or reference to a not-yet-migrated column compiles fine but crashes at runtime with
  "column X does not exist". Cross-reference column names against schema.prisma / models.
  Flag as **p1** if raw SQL references columns not in the schema.
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

### 4a. Repeated Writer / Polling Storage Amplification

For any poller, observer, scheduler, queue consumer, webhook, scraper, supervisor flow, or
other repeated writer that persists data:

- **Lossless is not duplicate-retentive by default.** Preserve the source facts/events that
  consumers need; do not save the same unchanged payload or item every interval just because
  the design says "lossless".
- **Check the multiplier:** calculate `sources × polls/day × items/response × rows/item`
  and estimate row bytes, index bytes, WAL, and retention horizon. If the reviewer cannot
  derive a bounded daily/weekly write rate from the plan/diff, flag it.
- **Inspect dedupe keys:** if uniqueness includes only a fresh `fetch_id`, `run_id`, or
  timestamp, it dedupes within a run but not across repeated polls. That is a red flag for
  unchanged-source duplication.
- **Prefer canonical/delta storage:** canonical entity upsert + `first_seen_at`,
  `last_seen_at`, and `seen_count` is usually enough for "actual entries and timestamps".
  Store append-only per-poll history only when a named downstream consumer requires it.
- **Require a bound for history:** intentional per-run observations need retention/TTL or
  partitioning, a deletion/backfill story, and verification queries for growth rate.

Flag unbounded redundant per-poll persistence as **p1** unless the diff proves it is
required, bounded, and covered by verification.

### 4b. External Data Cache Temporal Finality

For provider-backed data, shared caches, market/reference data, prompt-context enrichment,
evaluation labels, or ground-truth outcome tables, review the **semantic lifecycle** of the
stored value, not only the endpoint name or table name:

- **Classify rows:** every cached value must be `live`, `provisional`, or `final`. If the
  schema cannot represent that distinction, readers must not mix lifecycles.
- **Inventory writers/readers:** identify every writer and reader of the cache/table. Prompt
  context, alert-time fetches, backfills, CLIs, scheduled outcome jobs, and dashboards often
  have different freshness needs.
- **Provider names are not guarantees:** names like "EOD", "historical", or "latest" do not
  prove the value is final. Check provider semantics, source timestamp, exchange/calendar,
  timezone, and validity window.
- **First-write-wins is dangerous:** `ON CONFLICT DO NOTHING` is a p1 risk for mutable or
  provisional provider data unless the diff proves the fact is immutable. Require a safe
  upsert/refresh/repair path.
- **Cache-hit tests are mandatory:** tests must cover an already-present stale/provisional row
  before the finalizing job runs. Provider-miss tests alone do not prove correctness.
- **Separate semantic lifecycles:** live/tweet-time/current-session prices or snapshots must
  not be stored in the same final EOD / ground-truth-label table unless lifecycle state is
  encoded and enforced by readers.

Flag any path where provisional/live provider data can poison final labels or ground-truth
outcomes as **p1**.

### 4c. Producer/Consumer Schedule Starvation

For any pair of independently-scheduled flows that share a `scheduled_for` / `next_run_at` /
`due_at` row — a **producer** that periodically (re)writes the due time, and a separate
**consumer**/poller that claims rows `WHERE scheduled_for <= now()`:

- **Anchor check (CRITICAL):** the producer MUST compute the next due time from a fact that does
  not move every producer run — the last consumption/event/attempt, or the existing
  `scheduled_for` — **never from the producer's own run-time `now()`**. `scheduled_for = now() +
  interval` re-anchors on every producer tick, so an item that hasn't been consumed keeps getting
  pushed into the future and the consumer never sees it due. Flag `now() + interval` (or
  equivalent) as **p1**.
- **Upsert must not push a pending due time out:** on the producer's UPSERT, use
  `LEAST(existing, new)` / `WHERE new < existing`, so a row that is already due-but-unconsumed is
  not shoved forward. A blind `DO UPDATE SET scheduled_for = excluded.scheduled_for` is a red flag.
- **Cadence invariant:** confirm the consumer's poll window (its interval + any grace) comfortably
  exceeds the window the producer leaves open. When the interval is clamped at or below the
  producer's own cadence, the due window can collapse to ~1 tick and a producer/consumer dead-heat
  hides the row — the consumer reads the freshly-pushed future value and finds nothing due. Add a
  grace (`scheduled_for <= now() + grace`, grace ≥ producer interval) or anchor correctly.
- **Never-consumed starvation:** ask "if this item is never successfully consumed, does it stay
  claimable, or does the producer keep deferring it forever?" A freshly-created item that is
  perpetually re-scheduled is effectively never processed.

This is the timing/cadence sibling of §4a (the storage axis for the same family). `now() + interval`
in an isolated schedule-generation function looks correct — the defect only emerges from the
producer↔consumer interaction, so review the interaction, not just the hunk. Incident: E0014 M3
followed-pacer-poller — `court-pacer-policy` (15-min) rewrote `scheduled_for = now + ~14min` every
run while the 5-min poller kept losing the ~1-min due-window race, so a followed case was
structurally never polled.

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

### 3a. Upsert Staleness Check

For any `ON CONFLICT DO NOTHING` or partial `ON CONFLICT DO UPDATE`:

- **Is the data code-synced?** If code defines the values (tag descriptions, schema metadata,
  child key lists) and they could change across deployments, `DO NOTHING` causes stale data.
  Flag as **p1** — should use `DO UPDATE` with all evolving columns.
- **Litmus test:** "If someone changes the Python/TS code that defines this value and the
  task/service runs again, should the DB reflect the new value?" If yes → needs `DO UPDATE`.
- **Partial update trap:** `DO UPDATE` that only syncs some columns (e.g., `tag_hint` but not
  `attrs`) leaves other columns stale. Verify ALL code-defined columns are in the `set_` dict.

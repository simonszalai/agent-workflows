---
name: tool-postgres
description: Project-aware Postgres investigation through the shared read-only psql-cli wrapper.
---

# Postgres Access Reference

How to query project databases during investigation.

Also follow `../references/execution-economy.md` for run-local caching and bounded output.

**Important:** `psql-cli` has no mutation mode. Every connection is constrained by a
read-only transaction, a read-only session default, and a 30-second statement timeout. Schema and
data changes belong in each repository's approved application/migration workflow.

## Primary interface: `psql-cli`

Postgres MCP is retired. `psql-cli` is the canonical agent-investigation interface; use the
shared, project-aware CLI through the Bash tool:

```bash
psql-cli context [tier]                     # credential-free profile/tier check
psql-cli <tier> "<SQL>"                     # run one read-only query (CSV)
psql-cli <tier> search "<term>"              # find schema objects
```

`psql-cli` resolves the exact Git `origin` through `config/project-tools.json`. There is no
default or fuzzy project/tier selection. Only tiers explicitly configured with canonical,
non-sensitive `op://.../value` references are available; a project or tier without a profile
fails closed. For deliberate work outside the registered repository, both `--project <id>` and
`--allow-cross-project` are required.

Credentials resolve lazily through the selected project's service-account environment/Keychain
profile and the audited `bin/op` shim. The DSN is injected only as `PGDATABASE` into `psql`; it is
never put in argv, a file, or logs. Output defaults to a 50 KiB cap and carries an explicit
`TRUNCATED` marker. Add a tighter `LIMIT`; do not rerun an unbounded query.

If `psql` is missing, install the PostgreSQL client (`brew install libpq` on macOS or the
platform's PostgreSQL client package on Linux).

**CRITICAL:** Pass the requested tier exactly. Never substitute `prod` for staging/dev or another
available tier for one that is unavailable. Direct SQL is unavailable when the registry has no
Postgres profile; use the project's supported application/API interface instead.

## Mandatory query and payload bounds

Every SQL call must be bounded before execution. Read-only access does not make an
unbounded read safe or token-efficient.

- Select named columns; do not start with `SELECT *`.
- Add a justified time/key predicate unless the table is provably tiny.
- Multi-row queries need deterministic `ORDER BY` and `LIMIT`. Start at 20 rows;
  the first-pass hard maximum is 100.
- Keep returned payload at or below 64 KiB. Omit large JSON/text/blob columns or
  return a bounded preview plus the original byte length.
- Start with counts, existence checks, grouped aggregates, or min/max boundaries;
  fetch the smallest sample that can decide the question afterward.
- Bound JSON/array aggregates through a limited subquery; one aggregate cell must
  not hide an unbounded result.
- Save verbose results to run-local scratch and return only a compact summary.

If an exact full export is required, use a project-approved file/object-store export
path rather than routing it through MCP or model context.

Everything is plain SQL through the wrapper — the recipes below cover what the old
dedicated MCP tools used to do.

## Data Investigation Patterns

**Recent records:**

```sql
SELECT id, status, created_at
FROM schema.table
WHERE created_at >= NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC, id DESC
LIMIT 20;
```

**Count in time range:**

```sql
SELECT COUNT(*) FROM schema.table
WHERE created_at > NOW() - INTERVAL '1 hour';
```

**Group by status/state:**

```sql
SELECT status, COUNT(*) FROM schema.table
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY status
ORDER BY COUNT(*) DESC
LIMIT 100;
```

**Find gaps in data:**

```sql
SELECT date_trunc('hour', created_at) as hour, COUNT(*)
FROM schema.table
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour
LIMIT 100;
```

## Performance Investigation (SQL recipes)

**Find slow queries** (needs `pg_stat_statements`; note it omits queries that error every
time — "0 calls" can mean always-failing, not never-ran):

```sql
SELECT queryid, calls, mean_exec_time, total_exec_time, rows, query
FROM pg_stat_statements ORDER BY mean_exec_time DESC LIMIT 10;
-- resource-intensive: ORDER BY total_exec_time DESC (or shared_blks_read DESC)
```

**Analyze a specific query:**

```sql
EXPLAIN (ANALYZE, BUFFERS) SELECT ...;
-- read-only sources allow EXPLAIN; use plain EXPLAIN (no ANALYZE) for write statements
```

## Health Investigation (SQL recipes)

**Cache hit rate (want >95%):**

```sql
SELECT sum(heap_blks_hit) / NULLIF(sum(heap_blks_hit) + sum(heap_blks_read), 0) AS heap_hit_rate
FROM pg_statio_user_tables;
```

**Connection utilization:**

```sql
SELECT count(*) AS conns, (SELECT setting::int FROM pg_settings WHERE name='max_connections') AS max
FROM pg_stat_activity;
-- long-running holders: SELECT pid, state, now()-query_start AS age, left(query,80)
-- FROM pg_stat_activity WHERE state <> 'idle' ORDER BY age DESC;
```

**Vacuum / wraparound risk:**

```sql
SELECT relname, last_autovacuum, n_dead_tup
FROM pg_stat_user_tables ORDER BY n_dead_tup DESC LIMIT 10;
```

**Unused / duplicate indexes:**

```sql
SELECT schemaname, relname, indexrelname, idx_scan, pg_size_pretty(pg_relation_size(indexrelid)) AS size
FROM pg_stat_user_indexes ORDER BY idx_scan ASC, pg_relation_size(indexrelid) DESC LIMIT 15;
```

## Schema Exploration

Prefer `psql-cli <tier> search "<term>"` for interactive exploration. SQL equivalents:

```sql
-- list schemas
SELECT schema_name FROM information_schema.schemata;

-- list tables in a schema
SELECT table_name FROM information_schema.tables WHERE table_schema = 'public';

-- table structure
SELECT column_name, data_type, is_nullable FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'users' ORDER BY ordinal_position;
```

## Common Patterns

**Connection Issues:**

- Check connection utilization (SQL above); high utilization + connection errors = pool exhaustion
- Look for long-running queries holding connections

**Data Integrity:**

- Check for NULL values in required fields
- Verify foreign key relationships
- Look for orphaned records

**Performance Degradation:**

- Check buffer hit rates (should be >95%)
- Look for sequential scans on large tables
- Identify missing indexes via `EXPLAIN (ANALYZE, BUFFERS)`

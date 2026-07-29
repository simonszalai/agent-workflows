---
name: tool-postgres
description: Postgres access reference for database investigation — psql wrappers via the Bash tool (all Postgres MCP servers are retired).
---

# Postgres Access Reference

How to query project databases during investigation.

Also follow `../references/execution-economy.md` for run-local caching and bounded output.

**Important:** Production Postgres access is read-only. Use it for investigation and
querying only. Data modifications must go through application code (flows, scripts) and
the repo's approved schema/deploy system (ts-prefect uses Atlas after E0017; legacy repos
may still use Alembic/Prisma migrations).

## Primary interface: the repo's psql wrapper (`scripts/db/sql.sh`)

Database access is a checked-in psql wrapper run via the Bash tool. All Postgres MCP
servers (dbhub behind the gateway) are retired — the MCP approach lost the client
tool-registry race on cloud VMs, leaving sessions with no DB tools; a CLI self-heals
on first use. ts-prefect ships the reference implementation:

```
scripts/db/sql.sh <dev|staging|prod> "<SQL>"          # run a query (CSV output)
scripts/db/sql.sh <dev|staging|prod> search "<term>"  # find tables/columns/indexes/functions
```

- Credentials resolve lazily per call (op service-account token; silent on Mac and cloud).
  Never print DSNs or tokens.
- Prod is read-only (ts_readonly role + read-only transaction GUC); 30s statement timeout
  everywhere; output capped at 50 KB with a TRUNCATED marker — add LIMIT, don't retry
  without one.
- `psql` missing? `brew install libpq && brew link --force libpq` (Mac) or
  `apt-get install -y postgresql-client` (Linux) — the wrapper prints this too.
- A repo without a wrapper yet: copy ts-prefect's `scripts/db/sql.sh` and swap the
  op:// item names; do not hand-roll `psql "$DSN"` with a value in argv.

**CRITICAL:** When told to investigate a specific environment, pass that tier argument.
Never default to `prod` when staging or dev was requested.

## The autodev-memory global database (special case)

Its DSN lives in `op://AUTODEV-sensitive` — deliberately Touch-ID-gated (data-exposing
prod DB), so there is NO silent CLI path. For routine knowledge/ticket operations use
the autodev-memory MCP tools (one of the two MCP servers that remain). Direct SQL
against that DB is rare and interactive-only: follow the sensitive-vault-access skill
(reason required) and run psql under `op run` in Simon's terminal.

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

Prefer `scripts/db/sql.sh <tier> search "<term>"` for interactive exploration. SQL
equivalents:

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

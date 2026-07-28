---
name: tool-postgres
description: Postgres access reference for database investigation — psql wrapper (ts-prefect) or Postgres MCP tools (other projects).
---

# Postgres Access Reference

How to query project databases during investigation.

Also follow `../references/execution-economy.md` for run-local caching and bounded output.

**Important:** Production Postgres access is read-only. Use it for investigation and
querying only. Data modifications must go through application code (flows, scripts) and
the repo's approved schema/deploy system (ts-prefect uses Atlas after E0017; legacy repos
may still use Alembic/Prisma migrations).

## Primary interface: `scripts/db/sql.sh` (ts-prefect, since 2026-07-28)

In ts-prefect (and any repo that ships it), database access is a checked-in psql wrapper
run via the Bash tool — the dbhub `postgres` MCP server was removed (it lost the client
tool-registry race on cloud VMs, leaving sessions with no DB tools):

```
scripts/db/sql.sh <dev|staging|prod> "<SQL>"          # run a query (CSV output)
scripts/db/sql.sh <dev|staging|prod> search "<term>"  # find tables/columns/indexes/functions
```

- Credentials resolve lazily per call (op service-account token; silent on Mac and cloud).
  Never print DSNs or tokens.
- Prod is read-only (ts_readonly role + read-only transaction GUC); 30s statement timeout
  everywhere; output capped at 50 KB with a TRUNCATED marker — add LIMIT, don't retry
  without one.

**CRITICAL:** When told to investigate a specific environment, pass that tier argument.
Never default to `prod` when staging or dev was requested.

## MCP tool layout (projects still on Postgres MCP / Mac gateway transition)

Other projects still expose one `postgres` MCP server (DBHub behind the mcp-gateway) with
the environment as a tool-name suffix: `mcp__postgres__execute_sql_<env>` and
`mcp__postgres__search_objects_<env>` (env = prod/staging/dev; ts adds `prod_prefect` and
`autodev_ts`). Prod tools are read-only. The shared autodev-memory global database is its
own server: `mcp__postgres_autodev_global__execute_sql` / `__search_objects`. Older
sessions may expose legacy per-environment servers (`mcp__postgres_prod__execute_sql`
etc.) — same rules apply. If both the wrapper and MCP tools are available, prefer the
wrapper.

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

## Available Tools (per source)

| Tool (replace `{env}` with prod/staging/dev/...) | Purpose |
| ------------------------------------------------ | ------- |
| `mcp__postgres__execute_sql_{env}` | Run SQL (multiple statements allowed, `;`-separated) |
| `mcp__postgres__search_objects_{env}` | Search/explore schemas, tables, columns, indexes, procedures |

Everything else is plain SQL — see the recipes below for what the old dedicated tools
used to do.

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

Prefer `scripts/db/sql.sh <tier> search "<term>"` (or `search_objects_{env}` on MCP
projects) for interactive exploration. SQL equivalents:

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

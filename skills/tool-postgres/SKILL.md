---
name: tool-postgres
description: Postgres MCP tool reference for database investigation. Portable to any project using Postgres MCP.
---

# Postgres MCP Tool Reference

How to use Postgres MCP tools for database investigation.

Also follow `../references/execution-economy.md` for run-local caching and bounded output.

**Important:** Production Postgres MCP is read-only. Use it for investigation and querying
only. Data modifications must go through application code (flows, scripts) and the repo's approved schema/deploy system (ts-prefect uses Atlas after E0017; legacy repos may still use Alembic/Prisma migrations).

## Server & Tool Layout (DBHub, since 2026-07-12)

Postgres access goes through one `postgres` MCP server per project (DBHub behind the
mcp-gateway). All of the project's environments are **sources on that one server**, and the
tool name carries the environment as a suffix:

| Environment | Tool | Access |
| ----------- | ---- | ------ |
| Production | `mcp__postgres__execute_sql_prod` | Read-only (writes rejected) |
| Staging | `mcp__postgres__execute_sql_staging` | Read-write |
| Dev (local) | `mcp__postgres__execute_sql_dev` | Read-write |
| Prefect prod (ts only) | `mcp__postgres__execute_sql_prod_prefect` | Read-only |
| autodev-memory ts (ts only) | `mcp__postgres__execute_sql_autodev_ts` | Read-only |

Each source also has a schema-exploration tool: `mcp__postgres__search_objects_<env>`.

The shared autodev-memory global database is its own read-only single-source server, so
its tools keep plain names: `mcp__postgres_autodev_global__execute_sql` / `__search_objects`.

**Examples:**

```
# Production
mcp__postgres__execute_sql_prod(sql="SELECT ...")

# Staging
mcp__postgres__execute_sql_staging(sql="SELECT ...")

# Dev
mcp__postgres__execute_sql_dev(sql="SELECT ...")
```

**CRITICAL:** When told to investigate a specific environment, use that environment's tool
suffix. Never default to `_prod` when staging or dev was requested.

Older sessions may still expose the legacy per-environment servers
(`mcp__postgres_prod__execute_sql` etc.) — same rules apply, prefix instead of suffix.

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

Everything else is plain SQL via `execute_sql_{env}` — see the recipes below for what the
old dedicated tools used to do.

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

Prefer `search_objects_{env}` for interactive exploration. SQL equivalents:

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

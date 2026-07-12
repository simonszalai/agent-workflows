---
name: tool-postgres
description: Postgres MCP tool reference for database investigation. Portable to any project using Postgres MCP.
---

# Postgres MCP Tool Reference

How to use Postgres MCP tools for database investigation.

Also follow `../references/execution-economy.md` for run-local caching and bounded output.

**Important:** Production Postgres MCP is read-only. Use it for investigation and querying
only. Data modifications must go through application code (flows, scripts) and the repo's approved schema/deploy system (ts-prefect uses Atlas after E0017; legacy repos may still use Alembic/Prisma migrations).

## Environment-Specific Tool Names (CRITICAL)

Postgres MCP tools are namespaced by environment. **Always use the correct prefix** for the
environment you are investigating:

| Environment | Tool Prefix               | Access     |
| ----------- | ------------------------- | ---------- |
| Production  | `mcp__postgres_prod__`    | Read-only  |
| Staging     | `mcp__postgres_staging__` | Read-only  |
| Dev (local) | `mcp__postgres_dev__`     | Read-write |

**Examples:**

```
# Production
mcp__postgres_prod__execute_sql(sql="SELECT ...")

# Staging
mcp__postgres_staging__execute_sql(sql="SELECT ...")

# Dev
mcp__postgres_dev__execute_sql(sql="SELECT ...")
```

**CRITICAL:** When told to investigate a specific environment, use that environment's tool
prefix. Never default to `mcp__postgres_prod__` when staging or dev was requested.

## Mandatory query and payload bounds

Every SQL call must be bounded before execution. Read-only access does not make an unbounded read
safe or token-efficient.

- Select named columns; never start with `SELECT *`.
- Add a justified time/key predicate whenever the table is not provably tiny.
- Every query that can return multiple rows must have a deterministic `ORDER BY` and `LIMIT`.
  Start at `LIMIT 20`; the first-pass hard maximum is 100 rows. Retrieve another bounded page only
  if it can decide a stated question. Single-row counts/existence/min/max aggregates are already
  cardinality-bounded and do not need a cosmetic `ORDER BY`.
- Keep returned payload at or below 64 KiB per call. Omit large JSON/text/blob columns or project a
  bounded preview with `left(column::text, 1000)` plus `octet_length(column::text)`.
- Start with `COUNT`, grouped aggregates, existence checks, or min/max boundaries. Fetch samples
  only after the aggregate identifies the smallest useful slice.
- Bound arrays and JSON aggregation too: a single aggregate cell may not hide an unbounded result.
  Use a limited subquery before `json_agg`/`array_agg` and truncate large scalar values.
- If cardinality or row width is unknown, query bounded metadata/counts first. Do not execute the
  data query until its row and payload bounds are explicit.
- Save verbose results to run-local scratch and return compact summaries. Never paste a full table
  or large query result into model context.

Reject or rewrite a requested query that violates these bounds. If exact full export is genuinely
required, use a project-approved export path to a file/object store; do not route it through MCP or
the model context.

## Available Tools (per environment)

Each environment has the same set of tools, just with a different prefix:

| Tool (replace `{env}` with prod/staging/dev) | Purpose                                |
| --------------------------------------------- | -------------------------------------- |
| `mcp__postgres_{env}__execute_sql`             | Run SQL queries                        |
| `mcp__postgres_{env}__analyze_db_health`       | Check index, vacuum, connection health |
| `mcp__postgres_{env}__get_top_queries`         | Find slow/resource-intensive queries   |
| `mcp__postgres_{env}__explain_query`           | Analyze query execution plans          |
| `mcp__postgres_{env}__list_schemas`            | List all schemas                       |
| `mcp__postgres_{env}__list_objects`            | List tables/views in schema            |
| `mcp__postgres_{env}__get_object_details`      | Get table/view structure               |

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

## Performance Investigation

**Find slow queries:**

```
get_top_queries(sort_by="mean_time", limit=10)
```

**Find resource-intensive queries:**

```
get_top_queries(sort_by="resources", limit=10)
```

**Analyze specific query:**

```
explain_query(sql="SELECT ...", analyze=true)
```

## Health Investigation

**Comprehensive health check:**

```
analyze_db_health(health_type="all")
```

**Specific checks:**

```
analyze_db_health(health_type="index")      # Invalid, duplicate, bloated indexes
analyze_db_health(health_type="connection") # Connection utilization
analyze_db_health(health_type="vacuum")     # Transaction wraparound risk
analyze_db_health(health_type="buffer")     # Cache hit rates
```

## Schema Exploration

**List schemas:**

```
list_schemas()
```

**List tables in schema:**

```
list_objects(schema_name="public", object_type="table")
```

**Get table structure:**

```
get_object_details(schema_name="public", object_name="users", object_type="table")
```

## Common Patterns

**Connection Issues:**

- Check `analyze_db_health(health_type="connection")` for utilization
- High utilization + connection errors = pool exhaustion
- Look for long-running queries holding connections

**Data Integrity:**

- Check for NULL values in required fields
- Verify foreign key relationships
- Look for orphaned records

**Performance Degradation:**

- Check buffer hit rates (should be >95%)
- Look for sequential scans on large tables
- Identify missing indexes via explain_query

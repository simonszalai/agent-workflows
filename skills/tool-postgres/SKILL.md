---
name: tool-postgres
description: Postgres MCP tool reference for database investigation. Portable to any project using Postgres MCP.
---

# Postgres MCP Tool Reference

How to use Postgres MCP tools for database investigation.

**Important:** Production Postgres MCP is read-only. Use it for investigation and querying
only. Data modifications must go through application code (flows, scripts) and migrations
via Alembic.

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
SELECT * FROM schema.table ORDER BY created_at DESC LIMIT 10;
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
GROUP BY status;
```

**Find gaps in data:**

```sql
SELECT date_trunc('hour', created_at) as hour, COUNT(*)
FROM schema.table
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour ORDER BY hour;
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

---
name: tool-postgres
description: Postgres MCP tool reference for database investigation. Portable to any project using Postgres MCP.
---

# Postgres MCP Tool Reference

How to use Postgres MCP tools for database investigation.

**Important:** Production Postgres MCP is read-only. Use it for investigation and querying only. Data modifications must go through application code (flows, scripts) and migrations via Alembic.

## Available Tools

| Tool                                | Purpose                                |
| ----------------------------------- | -------------------------------------- |
| `mcp__postgres__execute_sql`        | Run read-only SQL queries              |
| `mcp__postgres__analyze_db_health`  | Check index, vacuum, connection health |
| `mcp__postgres__get_top_queries`    | Find slow/resource-intensive queries   |
| `mcp__postgres__explain_query`      | Analyze query execution plans          |
| `mcp__postgres__list_schemas`       | List all schemas                       |
| `mcp__postgres__list_objects`       | List tables/views in schema            |
| `mcp__postgres__get_object_details` | Get table/view structure               |

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

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

Use this order for a database investigation:

1. Run `psql-cli context <tier>` once to verify the resolved project, exact tier, and credential
   reference without reading the credential.
2. Design the smallest bounded SQL statement that answers the current questions.
3. Run one `psql-cli` invocation. Combine closely related checks into one result when that avoids
   repeated connections, but do not make an unbounded omnibus query.
4. Inspect the result before deciding whether another query is necessary.

Pass SQL as exactly one shell argument. For multiline SQL or PostgreSQL double-quoted identifiers,
use a quoted heredoc so the shell cannot remove or reinterpret quotes:

```bash
psql-cli prod "$(cat <<'SQL'
SELECT u.id, u.email, u."orgId"
FROM "User" AS u
WHERE u.id = 'known-id'
LIMIT 1
SQL
)"
```

Do not embed identifiers such as `u."orgId"` or `"User"` unescaped inside a shell
double-quoted SQL literal. The command may still run after the shell silently strips the identifier
quotes, producing misleading SQL errors or different identifier casing.

`psql-cli` resolves the exact Git `origin` through `config/project-tools.json`. There is no
default or fuzzy project/tier selection. Only tiers explicitly configured with canonical,
non-sensitive `op://.../value` references are available; a project or tier without a profile
fails closed. For deliberate work outside the registered repository, both `--project <id>` and
`--allow-cross-project` are required.

Credentials resolve lazily through the selected project's service-account environment/Keychain
profile and the audited `bin/op` shim. The URI is parsed into dedicated libpq `PG*` environment
variables for `psql`; it is never put in argv, a file, or logs. Output defaults to a 50 KiB cap
and carries an explicit `TRUNCATED` marker. Add a tighter `LIMIT`; do not rerun an unbounded query.

If `psql` is missing, install the PostgreSQL client (`brew install libpq` on macOS or the
platform's PostgreSQL client package on Linux).

**CRITICAL:** Pass the requested tier exactly. Never substitute `prod` for staging/dev or another
available tier for one that is unavailable. Direct SQL is unavailable when the registry has no
Postgres profile; use the project's supported application/API interface instead.

## Failure discipline

Treat one failed `psql-cli` call as evidence to classify, not as permission to invent a new database
transport.

1. Preserve the original exit status and complete error (`set -o pipefail` when piping output).
2. Re-run only the credential-free `psql-cli context <tier>` check if the resolved profile was not
   already captured.
3. Classify the failure before doing anything else:
   - SQL/parser/relation errors: fix the SQL or inspect the schema, then retry once.
   - Missing local `psql`: install or expose the PostgreSQL client as instructed above.
   - Authentication, TLS, host, or stale-credential errors: the wrapper/profile is broken or the
     registered credential is stale. Do not rewrite the query, change stdin/base64/file transport,
     read a different secret, substitute a different tier, or repeatedly retry the same call.
   - Timeout or truncation: make the query smaller; never raise the first-pass row or payload bounds.
4. Prefer repairing or escalating the registered `psql-cli` profile. Do not silently bypass its
   read-only credential and output controls by reaching into a deployed application's environment.

Changing JavaScript import syntax, adding catch blocks, testing production-only code locally,
base64-encoding a script, or copying it to a temporary file cannot fix a database authentication
failure or a remote dependency-resolution failure. Diagnose credentials, working directory, runtime,
and dependency availability before editing the query program.

### Exceptional application-shell fallback

Use a deployed application shell only when the repository's operational documentation explicitly
permits it and the investigation cannot proceed through the registered wrapper or a supported API.
Load the provider/deployment skill and repository runbook first. Application database credentials
can be broader than the wrapper's read-only role, so keep the following controls even when the shell
already exposes a connection URL:

1. Open one shell preflight and inspect `pwd`, the documented deploy directory, runtime availability,
   and dependency resolution before sending a query program. SSH home is not necessarily the deployed
   application directory. For Render native runtimes, `/home/bun` is commonly the login directory while
   the release and its installed packages are under `/home/bun/app`; verify this and `cd /home/bun/app`
   before importing project dependencies. Do not generalize that path to other providers. Verify an
   expected variable without revealing it with
   `test -n "${SYSTEM_DATABASE_URL:-}" && echo SYSTEM_DATABASE_URL=set`, then verify dependency
   resolution from the deploy directory. Never use `env`, `printenv`, or debug output that could dump
   the connection value.
2. Build one bounded query bundle locally after the preflight. Use one additional SSH invocation, one
   database client, one explicit `BEGIN READ ONLY`, `SET LOCAL statement_timeout = '30000ms'`, and one
   `ROLLBACK`/close path. Run all already-known related checks through that connection and emit one
   compact structured result. This means two application-shell SSH invocations total: one preflight and
   one query execution. Provider-runbook connection canaries are additional; perform or reuse them only
   as that runbook permits.
3. Do not open a new SSH and database connection for each count, relationship, or session check. Split
   the bundle only when a later query genuinely depends on evidence from the first result.
4. Never print the connection URL or environment values. Report variable names and behavioral checks
   only.

The fallback is not a second normal Postgres interface. Record why `psql-cli` was unavailable and
return to the wrapper after its registered credential or connectivity is repaired.

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

When several small checks are known up front, return them from one statement rather than opening one
connection per check. A JSON object of bounded scalar/subquery results is often the clearest shape:

```sql
SELECT jsonb_build_object(
  'user', (
    SELECT jsonb_build_object('id', id, 'role', role, 'orgId', "orgId")
    FROM "User" WHERE id = 'known-id' LIMIT 1
  ),
  'active_memberships', (
    SELECT COUNT(*) FROM "Member"
    WHERE "userId" = 'known-id' AND status = 'active'
  ),
  'recent_sessions', (
    SELECT COUNT(*) FROM "Session"
    WHERE "userId" = 'known-id'
      AND "createdAt" >= NOW() - INTERVAL '7 days'
  )
) AS investigation;
```

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

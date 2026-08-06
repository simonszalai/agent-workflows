# `psql-cli` Workflow

Use `psql-cli` as the canonical Postgres investigation interface. Do not replace it with application
credentials merely because the first query fails.

## Invocation order

1. Run `psql-cli context <tier>` once. Verify the project, exact tier, and credential reference
   without reading the credential.
2. Design the smallest bounded SQL statement that answers the known questions.
3. Run one `psql-cli` invocation. Combine closely related checks into one structured result when that
   avoids repeated connections, but do not make an unbounded omnibus query.
4. Inspect the result before deciding whether another query is necessary.

Pass SQL as exactly one shell argument. Use a quoted heredoc for multiline SQL and PostgreSQL
double-quoted identifiers:

```bash
verified_tier='TODO_EXACT_TIER'
psql-cli "$verified_tier" "$(cat <<'SQL'
SELECT entity_id, status, created_at
FROM app.entity
WHERE entity_id = 'known-id'
ORDER BY created_at DESC, entity_id DESC
LIMIT 20
SQL
)"
```

Do not embed identifiers such as `record."mixedCaseId"` unescaped inside a shell double-quoted SQL
literal. The shell can silently remove the identifier quotes while still producing a runnable command.

For several known checks, compose one bounded structured statement in run-local scratch, then pass the
completed file as one argument:

```bash
verified_tier='TODO_EXACT_TIER'
psql-cli "$verified_tier" "$(cat .context/investigation-bundle.sql)"
```

Keep the query in run-local scratch. Do not interpolate untrusted/user-supplied values into SQL; use a
repository-approved parameterized application/API path when dynamic values cannot be represented as
reviewed SQL literals. The parameterized templates belong to the exceptional Bun/`pg` fallback and are
not directly compatible with `psql-cli`.

## Failure classification

Preserve the original exit status and complete error. Use `set -o pipefail` when piping output.

- SQL, parser, or relation error: inspect the schema or fix the SQL, then retry once.
- Missing local `psql`: install or expose the PostgreSQL client.
- Authentication, TLS, host, or stale-credential error: treat the registered profile or connectivity
  as broken. Do not alter SQL transport, read another secret, substitute a tier, toggle TLS options,
  or repeatedly retry the call.
- Timeout or truncation: reduce work, rows, and returned columns. Do not raise first-pass bounds.

Run the credential-free context check once if it was not already captured, then prefer repairing or
escalating the registered profile. Changing import syntax, adding catch blocks, testing production-only
code locally, base64-encoding it, or copying it to a temporary file cannot fix authentication or remote
dependency resolution.

Use `application-shell-fallback.md` only when repository operational documentation explicitly permits
that exceptional route.

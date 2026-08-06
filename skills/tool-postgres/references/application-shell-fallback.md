# Exceptional Application-Shell Fallback

Use this path only when all of these conditions hold:

- `psql-cli` or a supported application API cannot answer the investigation.
- Repository operational documentation explicitly permits provider-shell database access.
- The provider/deployment skill and repository runbook are loaded and followed.
- The deployed runtime is Bun-compatible and the application has the `pg` package installed.

Fail closed when the runtime or driver differs. Use a repository-approved equivalent; do not improvise
a new provider-shell database client during an incident.

Application credentials can be broader than the wrapper's read-only role. Record why the wrapper was
unavailable and return to it after the profile or connectivity is repaired.

## Preflight before program changes

Perform provider-runbook identity, fingerprint, host-verification, and connection canaries first.
Then use one application-shell SSH invocation to inspect only:

1. Login working directory and documented deploy directory.
2. Runtime availability.
3. Dependency resolution from the deploy directory.
4. Presence, not value, of the expected connection variable.

Use a non-revealing presence check such as:

```bash
test -n "${TODO_DATABASE_URL_ENV:-}" && echo TODO_DATABASE_URL_ENV=set
```

Never run `env`, `printenv`, or debug output that could dump connection values.

SSH home is not necessarily the release directory. *Example (Render native Bun runtime):* SSH commonly
lands in `/home/bun`, while the release and installed packages are under `/home/bun/app`. Verify the
path, `cd /home/bun/app`, and only then test dependency imports. Do not generalize this path to other
providers.

Stop after a failed preflight. Changing stdin, base64, temporary-file, error-handling, or import syntax
does not repair a wrong working directory or missing dependency.

## One bounded execution

After preflight:

1. Copy `../templates/readonly-query-bundle.mjs`, `../templates/investigation-bundle.sql`, and
   `../templates/investigation-params.json` to run-local scratch.
2. Replace the template connection-variable name and every SQL identifier/type placeholder from
   repository context. Put dynamic values only in the JSON parameter array; never interpolate them into
   SQL or add credential values.
3. In one additional SSH invocation, stage all three customized files in a trap-cleaned temporary
   directory under the verified deploy directory and execute
   `bun readonly-query-bundle.mjs investigation-bundle.sql investigation-params.json` there. Keeping
   the runner below the deploy directory lets package resolution reach the application's installed
   dependencies. Use the provider runbook's approved transport and cleanup pattern.

The runner enforces one client, `BEGIN READ ONLY`, `SET LOCAL statement_timeout = '30000ms'`, one named
extended-protocol query, bounded JSON output, `ROLLBACK`, and close. PostgreSQL rejects multiple
commands in that prepared query, so input cannot end the read-only transaction and continue with a
write. Keep all already-known related facts in that call. Split the bundle only when a later query
genuinely depends on the first result.

Expected application-shell cost: two SSH invocations, one preflight and one execution, plus any
provider-runbook canaries. Expected database cost: one connection and four protocol calls (`BEGIN`,
`SET LOCAL`, query, `ROLLBACK`). Do not open one connection per count, relationship, or sample.

Never print the URL, environment values, full errors that may contain connection details, or unbounded
query results. The runner's 64 KiB check bounds transcript output after the driver returns rows; it does
not bound database or network payload. Enforce selected columns, SQL-side previews and byte lengths,
key/time predicates, deterministic ordering, and row limits inside the SQL template.

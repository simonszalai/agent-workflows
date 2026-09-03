# Four-role Postgres credentials

Canonical split used by Amaru, TS, Workflow, and Autodev. Config: `config/db-roles.json`.

## Vault items (grouped per tier)

Vault scopes the project, the item title the tier, one field per principal:

| Item | Vault | Fields |
|---|---|---|
| `Postgres prod` | `<PROJECT>-sensitive` | `root` (provider default `databaseUser`, NOT a real superuser / TablePlus only), `owner` (migrations + system client), `app`, `<app-slug>`, `<app-slug>_migrator` |
| `Postgres prod RO` | `<PROJECT>` regular | `canonical` (project ro), `<app-slug>` (app ro) |
| `Postgres staging` | `<PROJECT>` regular | `root`, `owner`, `app`, `ro`, `<app-slug>`, `<app-slug>_ro`, `<app-slug>_migrator` |

`admin_refs[tier].{root,owner}` in the config name the box's provider-default login ("root") and
admin owner fields explicitly. The "root" field is only Render's `databaseUser` — Render managed
Postgres exposes no actual superuser/root, so it is never a superuser escape hatch (TS now: `op://TS-sensitive/Postgres prod/root|owner`,
`op://TS/Postgres staging/root|owner`). Autodev has **prod only** (no staging DB).

## Postgres logins (project-prefixed)

| Project | owner | app | ro | root (provider; not renamed) |
|---|---|---|---|---|
| Amaru | `amaru_owner` | `amaru_app` | `amaru_ro` | prod `amaru_db_user`, staging `amaru_staging` |
| TS | `ts_owner` | `ts_app` | `ts_ro` | prod `ts_root`, staging `ts_duoh_user` |
| Workflow | `workflow_owner` | `workflow_app` | `workflow_ro` | prod `render` |
| Autodev | `autodev_owner` (SQL) | `autodev_app` | `autodev_ro` | shared instance `render` |

Every rotatable principal is a **capability** role (NOLOGIN after its first rotation) with versioned
`<capability>_login_<tag>` LOGIN roles beneath it; the vault field holds the current login's URL.

**TS note:** application tables are owned by `ts_user`, not the Render default login (`ts_root`).
Owner URLs use `?options=-c role=ts_user`. Render Postgres has no superuser: `GRANT ts_user` is not
a rotation/provision primitive. Dedicated migrators SET ROLE themselves; provisioning transfers the
consumer-DB relations (`mem_ts`) to them per relation. Amaru's `amaru_db_user` is the same shape.

**Autodev note:** shares Workflow's Render Postgres (`dpg-d66ig…`). Owner is a SQL role (not a
Render credential) so creating it does not steal Workflow's default credential.

## Tooling

```bash
# provision / rotate app+ro passwords, upsert vault fields
db-provision-roles --project <amaru|ts|workflow-pro|autodev> <staging|prod|all> \
  --reason "<why>" [--dry-run]
# rotate one principal (two-stage, zero downtime)
rotate-secret --ref 'op://TS-sensitive/Postgres prod/ts_prefect' --reason "<why>"
```

Human terminal. The canonical `op` shim owns sensitive-account selection and shows a purpose
notification only when its authentication preflight finds Touch ID is actually pending. Values
never print.

`db-provision-roles` refuses to re-enable LOGIN on a capability that has been rotated (NOLOGIN with
`_login_*` versions): rotate it with `rotate-secret` instead.

## Rotation (`secrets/providers/postgres-rotate`)

One registry entry = one principal = one vault field. Two stages, one resumable state file
(`~/.local/state/agent-workflows/db-rotation/<project>-<tier>-<scope>[-<app>].state`):

1. **rotate** — acquire the instance advisory lock (`<admin-project>/<instance-tier>`, printed
   read-free by `postgres-rotate --print-lock-key`), create + attest a versioned candidate login,
   activate every declared Render consumer (batch PUT → exact deploy → health), promote the candidate
   to the canonical vault field. Stops at phase `promoted`; the predecessor stays valid. A `--resume`
   at phase `activated`/`promoted` verifies the targets and health, it never PUTs or deploys again.
2. `rotate-secret` fans out to github/prefect/hermes/cross-project destinations, waits for deploys
   and health.
3. **finalize** (`ROTATE_FINALIZE=1`, `rotate-secret --finalize`) — reconcile orphan `_login_*`
   versions into the predecessor set, drain predecessor sessions (db + Render owner counters),
   prove the complete Render env/env-group/secret-file inventory holds no predecessor (declared
   consumers the fan-out has not reached are reported as such; `ROTATE_EXTRA_CONSUMER_DESTS`
   accepts more `sid/ENV` pairs; a clean scan is cached per `ROTATE_SWEEP_ID` in
   `ROTATE_INVENTORY_CACHE_DIR`), fence (NOLOGIN, reversible), retire (NOLOGIN + PASSWORD NULL is
   the safety property; DROP ROLE is best-effort), delete the candidate item.

Never retired: the instance table owner / admin owner and the root login. Exit codes: 0 · 2 usage,
state mismatch, lock contention or lock connection failure · 3 refused, nothing changed · 4 failed
before promotion · 5 promoted but a later proof failed (rerun / finalize again) · 75 lock lost.

All psql sessions use `sslmode=require` unless the URL says otherwise and carry
`lock_timeout`/`statement_timeout` (`DB_LOCK_TIMEOUT`, `DB_STATEMENT_TIMEOUT`).

## Per-app credentials

Each application principal gets its own login set, declared under
`projects.<proj>.apps.<app-slug>` (`roles.app` / `.ro` / `.migrator`). Roles are plain
slug-prefixed roles carrying the same grant sets the project's `{slug}_app` / `{slug}_ro` get; the
app slug is the vault field name (see the item table above). Items are written into the
**consumer** project's vault, even for cross-instance apps.

```bash
db-provision-roles --project <p> --app <app-slug> <staging|prod|all> --reason "<why>" [--dry-run]
db-provision-roles --project <p> --app <app-slug> --roles migrator <tier> --reason "<why>"
db-provision-roles --list   # shows apps per project
```

App mode connects as the owning instance's owner path, creates/rotates the LOGIN role(s), applies
grants on every configured database (tier database + `extra_databases`, or the app's `databases`
override), and upserts the vault field(s). Dedicated in-instance app URLs store the internal host;
the shared box and all cross-instance/RO URLs store the external host. Migrator provisioning
transfers the table owner's relations (tables, sequences, views, matviews, foreign tables, types)
in each target database to the migrator's SET ROLE target one `ALTER … OWNER TO` at a time and
verifies `pg_database.datdba` is unchanged — never `REASSIGN OWNED`, and never during rotation.

### Apps

| Project | App | Roles | Tiers | Databases |
|---|---|---|---|---|
| ts | `ts_prefect` | `ts_prefect_app` | staging, prod | tier DB |
| ts | `ts_dashboard` | `ts_dashboard_app`, `ts_dashboard_ro` | staging, prod | tier DB |
| amaru | `amaru_web` | `amaru_web_app` | staging, prod | tier DB |
| amaru | `amaru_mcp` | `amaru_mcp_app` | prod | tier DB |
| workflow-pro | `workflow_web` | `workflow_web_app` | staging, prod | tier DB |
| workflow-pro | `workflow_mcp` | `workflow_mcp_app` | prod | tier DB |
| autodev | `autodev_dashboard` | `autodev_dashboard_app` | prod | mem_autodev, mem_global, mem_workflow_pro |
| autodev | `autodev_memory` | `autodev_memory_app`, `autodev_memory_migrator` | prod | mem_autodev, mem_global, mem_workflow_pro |

`ts_scraper` and `ts_decrypt_proxy` have no DB rows in their manifests and are deliberately
absent. `autodev_dashboard` is an app (not ro) because the dashboard writes.

### Cross-instance consumers (modeled under autodev.apps)

| App | SQL roles | Owning box | Database | Admin via | Fields (consumer vault) |
|---|---|---|---|---|---|
| `autodev_mem_ts` | `autodev_mem_ts`, `_migrator`, `_ro` | TS prod (`dpg-d1rh6d…`) | `mem_ts` | ts owner credential | `op://AUTODEV-sensitive/Postgres prod/autodev_mem_ts[_migrator]`, `op://AUTODEV/Postgres prod RO/autodev_mem_ts` |
| `autodev_mem_amaru` | `autodev_mem_amaru`, `_migrator` | Amaru prod (`dpg-d506fs…`) | `mem_amaru` | amaru owner credential | `op://AUTODEV-sensitive/Postgres prod/autodev_mem_amaru[_migrator]` |

The role lives on the owning project's instance; the credential lives in the consumer's vault —
the consumer owns its credential.

## Prefect exception

The Prefect server owns its Alembic lifecycle, so both tiers keep the canonical migration-capable
credential (`Postgres <tier>/canonical`, rotated by the repo hook, excluded as an activation target).
Flow-run blocks use `ts_prefect_app`; production flow clients pass through PgBouncer, whose
`DATABASE_URL` must use the same login so its generated auth file contains that user. Never point
the server at `ts_prefect_app`; the rotator's inventory scan matches pgbouncer-hosted values too, so
a predecessor left in a PgBouncer `DATABASE_URL` blocks finalize.

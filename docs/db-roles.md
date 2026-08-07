# Four-role Postgres credentials

Canonical split used by Amaru, TS, Workflow, and Autodev.

## Secret names (no project prefix)

Vault scopes the project (`op://TS/...`). Item titles:

| Item | Vault | Purpose |
|---|---|---|
| `PROD_POSTGRES_URL_ROOT` | `*-sensitive` | Provider default / TablePlus only |
| `PROD_POSTGRES_URL_OWNER` | `*-sensitive` | Migrations + system client |
| `PROD_POSTGRES_URL_APP` | `*-sensitive` | Render runtime `DATABASE_URL` |
| `PROD_POSTGRES_URL_RO` | regular | Agents / CI read-only |
| `STAGING_POSTGRES_URL_*` | regular (all four) | Same roles for staging |

Autodev has **prod only** (no staging DB).

## Postgres logins (project-prefixed)

| Project | owner | app | ro | root (provider; not renamed) |
|---|---|---|---|---|
| Amaru | `amaru_owner` | `amaru_app` | `amaru_ro` | prod `amaru_db_user`, staging `amaru_staging` |
| TS | `ts_owner` | `ts_app` | `ts_ro` | prod `ts_root`, staging `ts_duoh_user` |
| Workflow | `workflow_owner` | `workflow_app` | `workflow_ro` | prod `render` |
| Autodev | `autodev_owner` (SQL) | `autodev_app` | `autodev_ro` | shared instance `render` |

**TS note:** application tables are owned by `ts_user`, not `ts_root`. Owner URLs use `?options=-c role=ts_user`.

**Autodev note:** shares Workflow’s Render Postgres (`dpg-d66ig…`). Owner is a SQL role (not a Render credential) so creating it does not steal Workflow’s default credential.

## Tooling

```bash
# config
agent-workflows/config/db-roles.json

# provision / rotate app+ro passwords, upsert vault items
db-provision-roles --project <amaru|ts|workflow-pro|autodev> <staging|prod|all> \
  --reason "<why>" [--dry-run]
```

Human terminal. The canonical `op` shim owns sensitive-account selection and shows a purpose
notification only when its authentication preflight finds Touch ID is actually pending. Values
never print.

## After provision

1. Point services: `DATABASE_URL` → `*_APP`, `MIGRATE_DATABASE_URL` / `SYSTEM_DATABASE_URL` → `*_OWNER`.
2. Redeploy every re-pointed service.
3. Agents use `project-tools.json` postgres tiers (`*_RO` only).
4. Retire unsuffixed `PROD_POSTGRES_URL` / `STAGING_POSTGRES_URL` once nothing references them.

## Per-app credentials (slice 3a)

Each application principal gets its own login pair(s), declared under
`projects.<proj>.apps.<app-slug>` in `config/db-roles.json`. Roles are plain
slug-prefixed LOGIN roles carrying the same grant sets the project's
`{slug}_app` / `{slug}_ro` get.

### Item naming (flat for now — product-grouped items land in slice 6)

| Item | Vault | Purpose |
|---|---|---|
| `{PROD\|STAGING}_POSTGRES_URL_{APPSLUG_UPPER}` | prod → `*-sensitive`, staging → regular | app login URL |
| `{PROD\|STAGING}_POSTGRES_URL_{APPSLUG_UPPER}_RO` | regular | ro login URL (when the app declares one) |

`APPSLUG_UPPER` is the app's `item_prefix` minus its trailing underscore
(e.g. `TS_PREFECT_` → `PROD_POSTGRES_URL_TS_PREFECT`). Items are written into
the **consumer** project's vault, even for cross-instance apps.

### Provisioning

```bash
db-provision-roles --project <p> --app <app-slug> <staging|prod|all> \
  --reason "<why>" [--dry-run]
db-provision-roles --list   # shows apps per project
```

App mode connects as the owning instance's owner path (Render default
credential after cutover; the shared autodev box uses the instance default),
creates/rotates the LOGIN role(s), applies grants on every configured database
(tier database + `extra_databases`, or the app's `databases` override), and
upserts the vault item(s). Dedicated in-instance app URLs store the internal
host; the shared box and all cross-instance/RO URLs store the external host.

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
| autodev | `autodev_memory` | `autodev_memory_app` | prod | mem_autodev, mem_global, mem_workflow_pro |

`ts_scraper` and `ts_decrypt_proxy` have no DB rows in their manifests and are
deliberately absent. `autodev_dashboard` is an app (not ro) because the
dashboard writes (semantic mutations, human commands).

### Cross-instance consumers (modeled under autodev.apps)

| App | SQL role | Owning box | Database | Admin via | Item (consumer vault) |
|---|---|---|---|---|---|
| `autodev_mem_ts` | `autodev_mem_ts` | TS prod (`dpg-d1rh6d…`) | `mem_ts` | ts owner credential | `op://AUTODEV-sensitive/PROD_POSTGRES_URL_AUTODEV_MEM_TS` |
| `autodev_mem_amaru` | `autodev_mem_amaru` | Amaru prod (`dpg-d506fs…`) | `mem_amaru` | amaru owner credential | `op://AUTODEV-sensitive/PROD_POSTGRES_URL_AUTODEV_MEM_AMARU` |

The role lives on the owning project's instance; the credential item lives in
the consumer's vault — the consumer owns its credential.

## Staging cutover (done 2026-08-06)

| Project | Service | Env | Role user |
|---|---|---|---|
| Amaru | `amaru-web-staging` | `DATABASE_URL` / `MIGRATE` / `SYSTEM` | app / owner / owner |
| TS | `ts-dashboard-staging` | `DATABASE_URL` | `ts_app` |
| TS | `ts-prefect-server-staging` | Prefect DB URLs (asyncpg, db `ts_staging_prefect`) | `ts_app` |
| TS | GHA `DATABASE_URL_STAGING` | secret | `ts_app` |
| Workflow | `workflow-pro-staging` | `DATABASE_URL` / `MIGRATE` / `SYSTEM` | app / owner / owner |
| Workflow | `application-scheduler-staging` | `DATABASE_URL` | `workflow_app` |

Prefect server needs the **external** host form of the APP URL (internal host alone caused `update_failed` once). Web services on Render private network accept the internal host stored in the vault.

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

Human terminal (Touch ID). Values never print.

## After provision

1. Point services: `DATABASE_URL` → `*_APP`, `MIGRATE_DATABASE_URL` / `SYSTEM_DATABASE_URL` → `*_OWNER`.
2. Redeploy every re-pointed service.
3. Agents use `project-tools.json` postgres tiers (`*_RO` only).
4. Retire unsuffixed `PROD_POSTGRES_URL` / `STAGING_POSTGRES_URL` once nothing references them.

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

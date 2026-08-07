# Central secrets engine

1Password is the single source of truth; `bin/sync-secrets` pushes values one
direction only (vault → destination), and `bin/rotate-secret` mints/collects
new values, updates the vault in place, and fans the sync out to every
registered consumer. Nothing writes back to the vault during sync; nothing
deletes a destination secret, ever. Secret values never reach stdout, stderr,
argv, logs, or disk.

## Layout

| Piece | Location |
|---|---|
| Engine libraries (manifest parser, op reads, transforms, Render API, vault writes) | `secrets/lib/` |
| Channel writers (github, render, prefect) | `secrets/lib/writers/` |
| Rotation providers (self_minted, manual, postgres, resend, openai, xai, aws_iam) | `secrets/providers/` |
| Rotation registry | `config/secret-rotation.json` |
| Per-repo routing manifest | `<repo>/scripts/secrets/manifest` |
| Entry points | `bin/sync-secrets`, `bin/rotate-secret`, `bin/dev-env` |

## Manifest format

Tab-separated, exactly five fields per row; `#` comments and blank lines
ignored. Validation is strict and whole-file fail-closed: any malformed row
(wrong field count, empty field, unknown KIND/TRANSFORM, unsupported REF,
duplicate `(KIND, DEST, ENVNAME)`) rejects the entire manifest (exit 1;
missing file exit 2).

```
KIND<TAB>DEST<TAB>ENVNAME<TAB>REF<TAB>TRANSFORM
```

| Field | Values |
|---|---|
| KIND | `github` \| `render` \| `prefect` \| `dev` |
| DEST | github: `owner/repo`; render: service id `srv-...`/`crn-...`; prefect: `staging`\|`prod`; dev: profile name |
| ENVNAME | destination env-var / secret name (also the `--only` selector key) |
| REF | `op://<vault>/<item>/<field>` (any field name) or `literal:<value>` |
| TRANSFORM | `self`, `conn-id`, `db=<name>`, `pgbouncer=<host:port>/<db>`, `asyncpg-internal=<db>`, `asyncpg-external=<db>` |

Transforms are pure (stdin → stdout): one canonical URL per Postgres instance
lives in the vault; every consumer shape is derived at push time, never
materialized in the vault.

## Vault conventions

- **Sensitivity is the vault suffix, not the environment.** `<VAULT>-sensitive`
  holds data-exposing secrets (prod DB write URLs, prod session keys): reads go
  through the canonical `bin/op` shim (human account, Touch ID, mandatory
  reason, notification). Plain vaults are service-account readable and silent.
- **Environment is encoded in ITEM NAMES, never in destination env-var names.**
  Two accepted shapes:
  - legacy flat items: `STAGING_*` prefix vs unprefixed prod
    (`STAGING_POSTGRES_URL_APP` / `PROD_POSTGRES_URL_APP`), single `value`
    field;
  - **product-grouped items (target convention for new items):** one item per
    product+tier named like `Postgres prod` / `Postgres staging`, with one
    field per app credential (e.g. fields `app`, `owner`, `ro`). This is why
    REF accepts any field name, not just `value`.
- Destination env NAMES stay unprefixed; the manifest row picks the right item
  per DEST/tier.

## sync-secrets

```bash
sync-secrets [--repo <path>] [--dry-run] [--dest <DEST>] [--only NAME[,NAME...]] \
             [--changed 'op://Vault/Item[/field]'] [--reason TEXT] \
             [--channel github|render|prefect] [--no-deploy]
```

- Default repo = the cwd's git toplevel; manifest = `<repo>/scripts/secrets/manifest`
  (missing → exit 2).
- Project layer (service-account token env/Keychain item, Render API key ref)
  resolves from the repo's git remote via `bin/project-context` — no ambient
  fallback, no hardcoded per-service key tables.
- Default sweep = github + render. Prefect is explicit only and prompts on the
  prod tier. `dev` rows are never pushed (consumed by repo dev-env tooling).
- `--changed`: exact REF equality, or `op://Vault/Item/` prefix when field-less
  — never bare substring. Cannot combine with `--channel`; excluded from
  prefect. Zero matches anywhere → exit 1.
- Writers resolve+validate the ENTIRE batch before the first write (empty or
  failed read refuses the write — a blank push once destroyed
  `DATABASE_URL_PROD`); Render PUTs run in parallel waves
  (`SYNC_PUT_CONCURRENCY`, default 8) and deploys trigger last, only if every
  PUT succeeded.
- Exit codes: 0 ok, 1 operational, 2 usage, 3 refusal (sensitive read from an
  agent shell; `--dry-run` is agent-safe and reads/writes nothing).
- **DB-credential guard** (render channel): rows whose ENVNAME is exactly
  `DATABASE_URL`, `MIGRATE_DATABASE_URL`, or `SYSTEM_DATABASE_URL` are owned by
  the Postgres tooling (`rotate-secret` provider `postgres` /
  `db-provision-roles`), never by a plain sync. Full sweeps (no `--changed` /
  writer `--ref`/`--ref-prefix` selection) **skip** those rows with a printed
  `skipped (db credential — use rotate-secret/db tooling)` line — dry-run plans
  mark them the same way. A `--changed`/`--ref` selection that would push one
  of them exits 2 pointing at the rotation tooling. The match is exact:
  derived per-database credentials such as autodev's `DATABASE_URL_GLOBAL`
  remain routine pushes. `--skip-db-rows` (used by rotate-secret's postgres
  fan-out, which already activated those rows itself) downgrades the refusal
  to the same skip-with-note behaviour.

## rotate-secret

```bash
rotate-secret --project <id> --item "<Item title>" --field <field> --reason "<why>" \
              [--dry-run] [--yes] [--accept-brief-outage]
rotate-secret --ref 'op://Vault/Item/field' --reason "<why>" [--resume] [--keep-old] [...]
printf %s '<new>' | rotate-secret --ref '...' --reason "<why>" --complete
```

Registry-driven (`config/secret-rotation.json`): unknown (project, item, field)
is exit 2 with the known-entries list — providers are never invented. Vault
writes address items by immutable id and verify by re-read. After any
successful mint+vault write, the fan-out runs
`sync-secrets --repo <r> --changed <ref>` for the owner repo and every
registered consumer repo, once per ref in the entry's `sync_refs` (default:
the entry ref; `[]` disables the fan-out for prefect-only entries; AWS pairs
list both items). Dual-key providers destroy the predecessor only in a
`provider_finalize` step that runs AFTER verify + fan-out succeeded.

Exit codes: 0 rotated+vault+sync+verify OK; 2 usage/unknown entry/rotation
state or lock contention; 3 manual playbook or precondition refusal, nothing
changed; 4 provider/verify error (safe state); 5 the vault holds the NEW value
but a post-vault step failed — consumer sync (idempotent recovery commands
printed) or postgres retirement proof (`--resume`).

### Providers

| provider | behaviour |
|---|---|
| `self_minted` | openssl rand, per-entry `generate` config; in-place vault write |
| `manual` | registry playbook + `--complete` stdin flow |
| `postgres` | full dual-principal zero-downtime rotator (below) |
| `resend` | dual: snapshot old key ids by `config.key_name` prefix → create → vault → sync → verify (entry `verify_command` / `config.canary` send) → delete old. No `config.key_name` ⇒ exit 3 |
| `openai` | dual via the OpenAI Admin API (project service accounts). Needs `config.admin_key_ref` + `config.project_id`, else exit 3 playbook |
| `xai` | MANUAL by design: no confirmed xAI key-management API shape; console + `--complete` |
| `aws_iam` | dual access-key PAIR via the aws CLI (`config.iam_user` + `config.profile` or admin key refs; `config.secret_ref` names the secret item). Both items written before any sync; old key Inactive→delete only after verify+fan-out; refuses when the user has an unknown second key |

### Postgres rotation (dual-principal, zero-downtime)

`secrets/providers/postgres-rotate` is the central port of amaru-web's
`scripts/db/rotate-credentials`, generalized over `config/db-roles.json`
(project/tier/db_id/roles/apps, cross-instance apps via `instance`, shared
boxes via `admin_via`) and driven by the registry entry's consumer list
(dest+env are the activation targets; github dests are fan-out-only).

- One registry entry = one principal. Scope derives from the item title:
  `{PROD|STAGING}_POSTGRES_URL_{ROOT|OWNER|APP|RO|<APPSLUG>[_RO]}`.
- Candidate = versioned login `<capability>_login_<versionTag>` granted the
  stable capability role (`INHERIT FALSE, SET TRUE`); URLs carry
  `options=-c role=<capability>`. OWNER goes through the Render managed
  credential API. ROOT and `sql_role` owners (autodev on the shared box)
  refuse with exit 3 — never create/delete a Render credential there.
- Pipeline: advisory lock (zero-consumer root, watchdog kills the tree on
  loss, exit 75 internally) → value-free 0600 state file
  (`${DB_ROTATION_STATE_DIR:-~/.local/state/agent-workflows/db-rotation}/<project>-<tier>.state`,
  phases initial→prepared→activated→promoted→retired) → candidate creation +
  role-safety attestation → snapshot → PUT all → trigger all (exact deploy
  ids, HTTP 201+`.id` only) → wait all → probe all → canonical promotion by
  immutable id → ≥120 s drain + Render `openConnections` evidence → exhaustive
  Render env/group/secret-file inventory → reversible NOLOGIN fence → second
  drain → retirement. Any incomplete proof keeps the predecessor (exit 5,
  `--resume`).
- **Health URLs are a fail-closed registry**: `health_urls` in
  `config/secret-rotation.json` maps service id → endpoint returning HTTP 200
  with `{status:"ok", databaseRoleSafe:true}`. An unregistered target service
  refuses rotation before any mutation.
- After promotion the normal rotate-secret fan-out runs with
  `sync-secrets --skip-db-rows` (the rotator already activated the declared
  Render rows; the fan-out covers github rows and derived consumers).

## dev-env

```bash
dev-env [--repo <path>] <profile> [--reason TEXT] [--no-sensitive] [--refresh] -- <command...>
dev-env [--repo <path>] <profile> --keys      # ENVNAMEs only, zero op reads
dev-env [--repo <path>] --profiles            # list dev profiles, zero op reads
```

Resolves one manifest `dev` profile and injects it ONLY into the child process
env (no `.env` files). Plain rows resolve in one batched `op inject` under the
project service-account token; sensitive rows resolve individually through the
canonical shim (Touch ID; reason required via `--reason` /
`SENSITIVE_ACCESS_REASON` / `OP_ACCESS_REASON`, agent shells refused) or are
skipped wholesale with `--no-sensitive`. An empty resolved value exports
nothing (exit 1). The child's exit code is propagated.

Encrypted cache (amaru port): aes-256-cbc/pbkdf2, passphrase = the project SA
token on fd 3, `${DEV_ENV_CACHE_DIR:-~/.cache/agent-workflows-devenv}/<project>/
<profile>[.nosens].enc` (dir 0700, file 0600), header `v1 <rows-sha256> <epoch>`,
TTL `DEV_ENV_CACHE_TTL` (86400), row-hash invalidation, `--refresh` bypass; no
SA token means the cache is silently skipped.

## Follow-ups

1. Slice 2: migrate the ts-prefect / amaru / workflow_pro hubs onto this engine
   (repos keep only their manifest + dev-env).
2. Slice 3/4: central port of the dual-principal Postgres rotator; retire the
   amaru bridge.
3. Fill the rotation registry from the full Tier-B migration table.

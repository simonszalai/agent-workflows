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
| Rotation providers (self_minted, manual, postgres stub) | `secrets/providers/` |
| Rotation registry | `config/secret-rotation.json` |
| Per-repo routing manifest | `<repo>/scripts/secrets/manifest` |
| Entry points | `bin/sync-secrets`, `bin/rotate-secret` |

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

## rotate-secret

```bash
rotate-secret --project <id> --item "<Item title>" --field <field> --reason "<why>" \
              [--dry-run] [--yes] [--accept-brief-outage]
rotate-secret --ref 'op://Vault/Item/field' --reason "<why>" [...]
printf %s '<new>' | rotate-secret --ref '...' --reason "<why>" --complete
```

Registry-driven (`config/secret-rotation.json`): unknown (project, item, field)
is exit 2 with the known-entries list — providers are never invented. Vault
writes address items by immutable id and verify by re-read. After any
successful mint+vault write, the fan-out runs
`sync-secrets --repo <r> --changed <ref>` for the owner repo and every
registered consumer repo.

Exit codes: 0 rotated+vault+sync+verify OK; 2 usage/unknown entry; 3 manual
playbook printed, nothing changed; 4 provider/verify error (safe state);
5 sync failed post-mint (idempotent recovery commands printed).

Providers: `self_minted` (openssl rand, per-entry `generate` config), `manual`
(playbook + `--complete` stdin flow), `postgres` (slice-1 stub — amaru bridges
to `amaru-web/scripts/db/rotate-credentials`; central port lands in slice 3/4).

## Follow-ups

1. Slice 2: migrate the ts-prefect / amaru / workflow_pro hubs onto this engine
   (repos keep only their manifest + dev-env).
2. Slice 3/4: central port of the dual-principal Postgres rotator; retire the
   amaru bridge.
3. Fill the rotation registry from the full Tier-B migration table.

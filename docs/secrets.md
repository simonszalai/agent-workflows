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
| Engine libraries (config loader, op reads, transforms, Render API, vault writes, provider helpers) | `secrets/lib/` |
| Channel writers (github, render, prefect, hermes) | `secrets/lib/writers/` |
| Rotation providers (self_minted, manual, postgres, resend, openai, aws_iam) | `secrets/providers/` |
| Project config (routes + rotation + health, one per project) | `<primary-repo>/secrets.yaml` |
| Non-primary repo pointer | `<repo>/secrets.yaml` containing `extends: ../<primary-repo>/secrets.yaml` |
| Entry points | `bin/sync-secrets`, `bin/rotate-secret`, `bin/rotate-project`, `bin/dev-env`, `bin/with-dev-env`, `bin/import-render-env` |

`rotate-project` writes a value-free checkpoint under
`${ROTATE_PROJECT_STATE_DIR:-~/.local/state/agent-workflows/rotate-project}/<project>.state`.
A failed sweep records completed/minted entry ids and batched Render dests.
Rerunning the same command skips those entries (SELF_MINTED is not reminted)
and retries deferred deploys. A successful sweep deletes the checkpoint so the
next invocation is a new rotation. `--fresh` discards an unfinished checkpoint.

The sweep overlaps independent work and refuses the rest:
- Non-postgres entries in a phase mint/sync in parallel (writes to the same
  1Password item stay sequential), then idle-wait every dest concurrently,
  trigger each dest, and wait-live in parallel.
- Postgres entries run in dest-disjoint + instance-lock-disjoint waves. Dual-key
  rotation still deploys and drains per entry, so overlapping Render dests
  (HTTP 202) or the same advisory lock (exit 2) stay sequential. An autodev
  prod sweep packs 8 postgres entries into 6 waves: dashboard+memory share the
  workflow-pro/prod lock, and six of eight entries deploy autodev-memory.

The engine holds no project data: every command discovers the project config
from the repo it runs in (or `--repo`), fails closed when none exists, and
derives each rotation entry's consumer set from the routes sharing its ref
(`exclude_dests` removes a route from the activation surface without hiding
it). The predecessor layout — per-repo `scripts/secrets/manifest` TSVs plus a
central `config/secret-rotation.json` with a hand-maintained `consumers[]`
copy of the routes — is retired; at migration 58 of 93 entries had drifted
from the routes they restated.

## Route format

Each route is one push of one vault field to one destination. Validation is
strict and whole-file fail-closed: a malformed route, unknown kind/transform,
unsupported REF, duplicate `(kind, dest, env)`, or a rotation entry whose ref
has no route rejects the entire config (exit 2, also for a missing file). The
whole file is parsed, validated and cached in one python call per process.

```
- {repo: <name>, kind: github|render|prefect|dev|hermes, dest: <dest>, env: <ENVNAME>, ref: <REF>, transform: <TRANSFORM>}
```

| Field | Values |
|---|---|
| KIND | `github` \| `render` \| `prefect` \| `dev` \| `hermes` |
| DEST | github: `owner/repo`; render: service id `srv-...`/`crn-...`; prefect: `staging`\|`prod`; dev: profile name; hermes: absolute credential file path on the box (top-level `hermes.ssh` names the SSH destination) |
| ENVNAME | destination env-var / secret name (also the `--only` selector key) |
| REF | `op://<vault>/<item>/<field>` (any field name) or `literal:<value>` |
| TRANSFORM | `self`, `conn-id`, `db=<name>`, `pgbouncer=<host:port>/<db>`, `asyncpg-internal=<db>`, `asyncpg-external=<db>`, `rehost=<host[:port]>/<db>` |

Transforms are pure (stdin → stdout): one canonical URL per Postgres instance
lives in the vault; every consumer shape is derived at push time, never
materialized in the vault.

## Config schema (strict)

Top-level keys: `project`, `repos`, `routes` (required), `health`, `hermes`
(`{ssh: <dest>}`), `rotation`. Route keys: exactly `repo kind dest env ref
transform`. Rotation entry keys: `ref provider mode owner_repo` (required) plus
`verify verify_command generate playbook sync_refs sync_repos config hook
exclude_dests project disabled_reason`. Anything else is an unknown key and
rejects the file. Every message is
`<path>: <where>: <why>` (`route N: ...`, `rotation '<id>': ...`).

Rules beyond shape: duplicate YAML keys (two `rotation` ids) are rejected by
the loader; `provider` must have a handler file `secrets/providers/<p>.sh`
(postgres, self_minted, manual, resend, openai, aws_iam); `mode` ∈
`SELF_MINTED | MANUAL | DUAL_KEY | IN_PLACE`; two entries may not share a
`ref`; `sync_refs` are routed op refs; `exclude_dests` name dests that route
the entry's refs; `owner_repo` ∈ `repos`, and `repos` lists every repo with a
route; prefect dests are `staging|prod`; `generate` is `{format: hex|base64,
bytes: 1..4096}`; `hook` is `activate|full`. Provider `config` keys are
checked per provider (resend `key_name` [+ `permission auth_key_ref canary`];
openai `admin_key_ref project_id` [+ `sa_prefix`]; aws_iam `iam_user
secret_ref` + `profile` or `admin_key_id_ref`/`admin_secret_ref`, and
`sync_refs` must include `secret_ref`). Missing required config keys are NOT
an error: the entry is valid but SYNC-only — `provider_auto_ready` is false,
`rotate-project` only re-pushes the vault value, and the provider prints a
playbook on a live run.

## Vault conventions

- **Sensitivity is the vault suffix, not the environment.** `<VAULT>-sensitive`
  holds data-exposing secrets (prod DB write URLs, prod session keys): reads go
  through the canonical `bin/op` shim (human account, Touch ID, mandatory
  reason, notification). Plain vaults are service-account readable and silent.
- **Which service account reads a plain ref is decided by the ref's VAULT, not
  by the project being run.** A manifest may legitimately route a credential
  another project owns (autodev consumes `op://TS/Autodev memory/api_token`).
  When the running project owns the vault, its token is used directly; when
  another project owns it, the ref is handed to `bin/op` unpinned so its
  registry-driven owner routing (`projects[].service_account.vaults` in
  `config/project-tools.json`) picks the right account and fails closed on an
  unregistered vault or missing token. Pinning the running project's token
  instead produced `could not read secret: "TS" isn't a vault in this account`
  and a silent `RESOLVE FAILED` row on every rotation of such an entry.
- **Environment is encoded in ITEM NAMES, never in destination env-var names.**
  Two accepted shapes:
  - legacy flat items: `STAGING_*` prefix vs unprefixed prod
    (`STAGING_POSTGRES_URL_APP` / `PROD_POSTGRES_URL_APP`), single `value`
    field — being retired by the slice-6 regrouping below;
  - **product-grouped items (THE convention — final decision, slice 6):** one
    item = one product/subsystem per project; fields = that product's secrets.
    Refs are `op://{Vault}/{Item}/{field}`, e.g. `op://TS/xAI/api_key`,
    `op://TS-sensitive/Postgres prod/ts_prefect`. Environment is encoded in
    ITEM NAMES (`Postgres prod`, `Postgres staging`, `xAI staging`) — one
    uniform convention. This is why REF accepts any field name, not just
    `value`.
- Destination env NAMES stay unprefixed; the manifest row picks the right item
  per DEST/tier. ENVNAMEs never change during regrouping — only REFs.
- Prod-write and prod-RO credentials never share an SA-readable item: write
  URLs live in the `*-sensitive` item (`Postgres prod`), RO fields live in the
  regular-vault sibling item (`Postgres prod RO`).

## Product-grouped item migration (slice 6)

`config/1p-grouping.json` is the committed mapping: every old flat
`op://` ref across all routed repos + agent-workflows configs →
`{new_item, new_field, vault}`. Refs whose source item does not exist yet
(pending provisioning/minting/seeding) carry `pending_source: true` — they are
mapped so the ref rewrite lands, but copy/verify skip them; the item is minted
directly at the new grouped ref later.

`bin/migrate-1p-grouping` executes the mapping:

| Mode | Behaviour |
|---|---|
| `--plan` (default) | prints the full mapping plan + stats purely from config. Credential-free: zero op calls, agent-safe |
| `--copy --reason X` | human terminal: for each mapping whose source item exists, read old value → upsert the grouped item field (immutable id) → verify byte-equality by re-read. Skips `pending_source`. Idempotent; NEVER deletes old items |
| `--verify` | re-reads both sides, hash-compares, prints a table. A full pass (every non-pending mapping OK) records verify state keyed by the mapping content hash |
| `--apply-refs [--repo <path>]` | rewrites every mapped ref across the configured repos' WORKING TREES (manifests, `config/secret-rotation.json`, `config/project-tools.json`, `config/db-roles.json`, docs, env files). Refuses without a matching `--verify` pass; prints per-repo diff summaries |
| `--retire-plan` | slice-7 preview: PRINTS the old items safe to delete (verified + zero remaining working-tree refs). Deletion itself is slice 7 and manual |

### Cutover runbook (human at the vault, Touch ID)

```bash
# 0. review the plan (agent-safe, no credentials)
bin/migrate-1p-grouping --plan

# 1. copy values into the grouped items (old items untouched)
bin/migrate-1p-grouping --copy --reason "slice 6: 1P product-grouped regrouping"

# 2. verify byte-equality of every non-pending mapping (records the gate state)
bin/migrate-1p-grouping --verify

# 3. rewrite refs in every working tree (or one repo at a time with --repo)
bin/migrate-1p-grouping --apply-refs

# 4. review each repo's diff, one PR per repo; merge; then re-run any
#    dev-env/sync-secrets --dry-run smoke you want. Old-item deletion is
#    slice 7: bin/migrate-1p-grouping --retire-plan   (print-only)
```

Re-running any step converges; nothing in this flow deletes or rotates a
secret, so a failed step is always safe to repeat.

## sync-secrets

```bash
sync-secrets [--repo <path>] [--dry-run] [--dest <DEST>] [--only NAME[,NAME...]] \
             [--changed 'op://Vault/Item[/field]'] [--reason TEXT] \
             [--channel github|render|prefect|hermes] [--no-deploy] [--include-db]
```

- Default repo = the cwd's git toplevel; config = `<repo>/secrets.yaml` (or its `extends:` target)
  (missing → exit 2).
- Project layer (service-account token env/Keychain item, Render API key ref)
  resolves from the repo's git remote via `bin/project-context` — no ambient
  fallback, no hardcoded per-service key tables.
- Default sweep = github + render + hermes + prefect (both prefect tiers, each
  only when it has rows; channels run concurrently, `prefect:prod` last in the
  foreground — it prompts unless `SECRETS_ASSUME_YES=1`, which rotate-secret
  and rotate-project export because the operator already confirmed the live
  rotation). `--channel prefect` takes `--dest staging|prod` (default: both).
  `dev` rows are never pushed (consumed by `dev-env` / `with-dev-env`).
- `--changed`: exact REF equality, or `op://Vault/Item/` prefix when field-less
  — never bare substring. Cannot combine with `--channel`; reaches every
  default channel, prefect included. Zero matches anywhere → exit 1; a ref
  routed only to `dev` is a fact, not a failure.
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
- **`--include-db` (initial cutover only)**: the one-time cutover of a service
  from a shared vault item to a freshly provisioned per-app item needs exactly
  one push of those canonical DB rows before the postgres rotator can own them
  (its health-endpoint requirement isn't met yet). `--include-db` is valid
  only together with a targeted `--changed` selection AND `--reason` — on a
  full sweep it exits 2 — and pushes the selected DB rows like normal rows
  (batch validation, empty-value refusal, deploy-last all still apply). Every
  subsequent rotation MUST go through `rotate-secret` (provider `postgres`) /
  `db-provision-roles`, never `--include-db` again.

## rotate-secret

```bash
rotate-secret --project <id> --item "<Item title>" --field <field> --reason "<why>" [--dry-run] [--yes]
rotate-secret --ref 'op://Vault/Item/field' --reason "<why>" [--dry-run] [--yes]
              [--no-finalize | --finalize | --resume]
printf %s '<new>' | rotate-secret --ref '...' --reason "<why>" --complete   # manual / SYNC-only entries
```

Config-driven (the project `secrets.yaml` rotation section): unknown (project,
item, field) is exit 2 with the known-entries list — providers are never
invented. Vault writes address items by immutable id and verify by re-read.

**Every rotation is two-stage.** `rotate` mints/stages the new credential
(the predecessor STAYS valid) and writes the vault; then the fan-out runs
`sync-secrets --repo <r> --changed <ref>` for the owner repo and every
`sync_repos` repo, once per ref in the entry's `sync_refs` (default: the entry
ref; `[]` disables the fan-out; AWS pairs list both fields), triggered deploys
are recorded and waited live, the health gate passes, and only then
`finalize` retires the predecessor. Between the stages a value-free
finalize-state file
(`${ROTATE_STATE_DIR:-~/.local/state/agent-workflows/rotate-secret}/<project>/<id>.json`,
0600: id, ref, provider, rotatedAt, the provider's finalize json, deploy ids,
fannedOut + proven flags) makes the run resumable:

| flag | behaviour |
|---|---|
| default | rotate → state → verify → fan-out → hook post-sync (`fannedOut`) → wait live + health → finalize → state removed |
| `--no-finalize` | stop after fan-out (+hook); exit 0; state stays (rotate-project batches finalize) |
| `--finalize` | ONLY finalize from persisted state (after wait-live/health if deploys are not yet proven); no state → "nothing to finalize", exit 0; state without `fannedOut` (mint done, fan-out never completed) → refused, exit 5, rerun `--resume`; failure → exit 6 |
| `--resume` | state exists → skip mint, re-verify, redo fan-out (every touched Render service redeploys, changed or not) → wait → finalize; postgres also maps onto the rotator's `--resume` (no rotator state = fresh run); no state → normal run |
| `--complete` | externally minted value on stdin once (providers with `PROVIDER_ACCEPTS_COMPLETE=1`: manual, and resend/openai/aws_iam entries that are not auto-ready) |

A normal run that finds existing finalize-state REFUSES (exit 2: rerun with
`--resume` or `--finalize`) — no provider can silently double-mint.

Exit codes: 0 ok · 2 usage/config/state refusal · 3 playbook/precondition,
nothing changed · 4 provider/verify error (vault consistent; a verify failure
after the mint leaves the state file, `--resume` re-verifies) · 5 vault holds
the NEW value but fan-out/hook/wait failed (recovery printed; `--resume`) · 6
rotation complete but predecessor cleanup pending (`--finalize` retries it).

**Cross-project consumers.** A rotation entry's routes — and therefore its
fan-out — are scoped to the project that owns it, so a credential a SECOND
project also routes needs `sync_repos` or that project's destinations keep the
retired value:

```yaml
  ts-postgres-prod-ro-canonical:
    ref: op://TS/Postgres prod RO/canonical
    sync_repos:
    - ../autodev-memory        # autodev routes this into SCHEMA_DRIFT_DATABASE_URL_RO
```

Paths are relative to the declaring project's `secrets.yaml`, the same
convention as `extends:`. Validation is fail-closed: each named repo must
exist, resolve to a config (following one pointer hop), belong to a *different*
project, and actually route one of the entry's fan-out refs. `--dry-run` lists
the extra sync legs and the cross-project consumer rows.

Nothing detects an *undeclared* cross-project consumer automatically — no
component enumerates every project's config — so when adding a route whose ref
lives in another project's vault namespace, check whether that project already
registers it and add `sync_repos` there.

The repo rotation hook (`scripts/secrets/rotate-hook`, `hook: activate|full`
or an undeclared post-sync hook) is looked up in the entry's `owner_repo`
(resolved through `repos:`), not the cwd.

### Provider contract

`secrets/providers/<name>.sh` is sourced by rotate-secret; each provider sources
`secrets/lib/provider-common.sh` (`entry_field`, `bearer_curl` with the key on
a curl `--config` pipe, `run_verify_command`, `finalize_delete_ids`,
`playbook_unconfigured`, `provider_api_base`).

| function | contract |
|---|---|
| `provider_auto_ready` | rc 0 iff `config.*` suffices to mint (read-free). self_minted/postgres always; manual never; resend/openai/aws_iam iff configured |
| `provider_plan` | optional read-free dry-run detail |
| `provider_rotate` | mint + vault write; predecessor stays valid; may set `PROVIDER_FINALIZE_JSON` (value-free). rc 0 · 3 playbook/refused · 4 error · **7 leftovers found, call `provider_reconcile`** |
| `provider_reconcile` | rc 0 = rotation completed without a mint (`PROVIDER_FINALIZE_JSON` set) · rc 3 = playbook |
| `provider_verify` | entry `verify_command` when set — run in a child shell with `ROTATE_NEW_VALUE` (aws_iam also `ROTATE_NEW_SECRET_VALUE`) exported to that child only — else the provider's own probe |
| `provider_finalize <json>` | retire the predecessors named in the persisted json (works in a separate process); already gone = ok; rc≠0 → rotate-secret exit 6 |
| `provider_playbook` | human description |
| `PROVIDER_ACCEPTS_COMPLETE=1` | enables `--complete` |

`*_API_BASE` overrides (resend/openai) are honoured only under
`SECRETS_TEST_MODE=1`.

### Providers

| provider | finalize json | behaviour |
|---|---|---|
| `self_minted` | — | openssl rand per entry `generate`; in-place vault write; nothing to finalize |
| `manual` | — | registry playbook, exit 3; `--complete` stdin flow |
| `postgres` | rotator state | full dual-principal zero-downtime rotator (below); finalize = retirement via the rotator's resume path |
| `resend` | `{delete_ids}` | predecessors = keys named exactly `<config.key_name> <UTC ts>`; create → vault → fan-out → verify (`verify_command` / `config.canary` send / vault re-read); finalize authenticates with the current vault value (the NEW key) and deletes the recorded ids (404 = fine). No `config.key_name` ⇒ SYNC-only + playbook |
| `openai` | `{delete_ids}` | Admin API project service accounts (`config.admin_key_ref` + `config.project_id`); predecessors = `<sa_prefix>-<ts>` across every `has_more` page; verify `GET /v1/models`; dashboard-minted originals need manual deletion |
| `aws_iam` | `{old_key_id}` | id+secret PAIR written with `vault_replace_fields` (one locked write) before any sync; no other key → mint; exactly one other key → rc 7 → reconcile (vault pair must pass STS; the other key becomes the predecessor, newer = orphan of a crash, older = unfinished rotation); verify via STS or `verify_command`; finalize Inactive→delete, failure = exit 6, rerun `--finalize` |

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
  the project `secrets.yaml` `health:` section maps service id → endpoint returning HTTP 200
  with `{status:"ok", databaseRoleSafe:true}`. An unregistered target service
  refuses rotation before any mutation.
- After promotion the normal rotate-secret fan-out runs with
  `sync-secrets --skip-db-rows` (the rotator already activated the declared
  Render rows; the fan-out covers github rows and derived consumers).

## dev-env, with-dev-env, import-render-env

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

`with-dev-env [--repo <path>] [--profile <name>] [--no-sensitive] [--refresh] <command...>`
is the launcher for package.json / Conductor commands: it picks the project's
single dev profile (or `--profile` / `WITH_DEV_ENV_PROFILE`), adds
`--no-sensitive` automatically in agent shells unless flags were given
explicitly, and execs `dev-env`.

`import-render-env [--repo <path>] [--dry-run] [--reason TEXT]` seeds MISSING
vault items from the live Render env (create-only, first routed service per
ref is the source; existing items are never touched; `--dry-run` lists item
titles only and reads no values; agent shells refused). Idempotent bootstrap
for a repo whose vault is not yet populated.

## Follow-ups

1. Slice 2: migrate the ts-prefect / amaru / workflow_pro hubs onto this engine
   (repos keep only their manifest + dev-env).
2. Slice 3/4: central port of the dual-principal Postgres rotator; retire the
   amaru bridge.
3. Fill the rotation registry from the full Tier-B migration table.

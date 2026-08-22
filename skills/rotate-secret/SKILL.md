---
name: rotate-secret
description: Rotate a registered secret through the central agent-workflows engine (registry lookup, provider handler, in-place vault write, sync-secrets fan-out) and push manifest-routed secrets to their destinations. Use when a credential must be rotated, was exposed, or when a vault item changed and its consumers (GitHub/Render/Prefect) need re-syncing.
---

# Rotate a secret / sync secrets

Central engine: `bin/rotate-secret`, `bin/sync-secrets`, registry
each project's `secrets.yaml` (rotation section), docs in `docs/secrets.md`.

## Decision procedure (fail closed)

1. **Find the registry entry.** Run `rotate-secret --ref 'op://Vault/Item/field' --dry-run`
   (or `--project/--item/--field`). Exit 2 means the secret is NOT registered:
   stop and report the known-entries list the script printed. **Never invent a
   provider or rotate an unregistered secret ad hoc** — add a registry entry
   first (a human decision).
2. **Dry-run first** for anything non-trivial. `--dry-run` prints the provider,
   mode, and the full consumer fan-out; it reads nothing and writes nothing, so
   it is safe from agent shells.
3. **Live run needs `--reason`** (concise, operation-specific, with ticket id
   when known) and a human terminal: live rotations refuse agent shells
   (exit 3). Non-interactive runs additionally need `--yes`.
4. **Interpret exit codes; do not freeform-recover:**
   - `0` — rotated: vault write verified, fan-out synced, deploys live +
     health gate passed, predecessor retired (finalize).
   - `2` — usage / unknown entry / invalid config / finalize-state refusal
     ("unfinished rotation for <id>; rerun with --resume (or --finalize)");
     postgres lock contention. Nothing changed.
   - `3` — playbook printed or precondition refused (MANUAL provider,
     SYNC-only entry without provider config, aws reconcile refusal, sql_role
     owner scope, unregistered health URL), nothing changed. Show the output;
     offer `--complete` only when the output says so (step 5).
   - `4` — provider or verify error, safe state (vault consistent). Report the
     script output verbatim; if it says the vault already holds the NEW value
     (verify failed after the mint) the recovery is `--resume`.
   - `5` — vault holds the NEW value but fan-out / hook / wait-live failed:
     the recovery is `--resume` (skips the mint, redoes fan-out, waits,
     finalizes). `--finalize` is refused (exit 5) until a fan-out completed.
     Never improvise a different recovery.
   - `6` — rotation complete, predecessor cleanup pending (revoke/delete
     failed or deploys not yet proven): rerun with `--finalize`; it is
     idempotent (already-deleted predecessors are fine).
   Every rotation is two-stage: the predecessor stays valid until finalize,
   which runs only after the consumers are proven on the new value.
   `--no-finalize` stops after fan-out (rotate-project uses it), `--finalize`
   runs only the retirement from persisted state.
5. **Manual completion.** After the operator minted the new value externally:
   `printf %s '<new-value>' | rotate-secret --ref '...' --reason '...' --complete`
   — reads stdin once, writes the vault item in place, fans out sync. Only
   providers declaring `PROVIDER_ACCEPTS_COMPLETE=1` accept it: `manual`, and
   resend/openai/aws_iam entries that are SYNC-only (no provider config).

**Never echo, log, or capture a secret value.** Values flow op → pipe →
destination only. If a value is ever printed, treat the credential as exposed
and rotate it.

## Providers

Auto-rotation = the provider file exists AND `provider_auto_ready` (its
`config.*` suffices); otherwise the entry is SYNC-only (rotate-project only
re-pushes the vault value; a live rotate-secret prints the playbook).

| provider | mode | auto when | rotate | finalize (`provider_finalize <json>`) | verify |
|---|---|---|---|---|---|
| `self_minted` | SELF_MINTED | always | `openssl rand` per `generate`, in-place vault write | nothing (old value dies as consumers redeploy) | vault re-read; `verify_command` if set |
| `manual` | MANUAL | never | prints the registry playbook, exit 3; `--complete` writes vault + fans out | operator retires the old credential in the UI after consumers verified | `verify_command` if set |
| `postgres` | DUAL_KEY | always | central dual-principal rotator: candidate login → PUT/deploy/probe → promotion (predecessor stays valid) | rotator resume path: drain → inventory → retire | deploy proofs + health `{status:"ok", databaseRoleSafe:true}` |
| `resend` | DUAL_KEY | `config.key_name` | predecessors = keys named exactly `<key_name> <ts>`; create; vault-replace | deletes the recorded ids with the NEW key; 404 fine | `verify_command` / `config.canary` send / vault re-read |
| `openai` | DUAL_KEY | `config.admin_key_ref` + `config.project_id` | Admin API service account `<sa_prefix>-<ts>`; predecessors across all pages | deletes recorded service accounts; dashboard-minted originals by hand | `verify_command` / `GET /v1/models` |
| `aws_iam` | DUAL_KEY | `config.iam_user` + `config.secret_ref` + (`profile` or admin refs) | id+secret PAIR written in one locked write; exactly one extra key on the user → reconcile (vault pair must pass STS) instead of refusing | Inactive→delete the recorded key id; failure = exit 6, `--finalize` retries | `verify_command` (gets `ROTATE_NEW_VALUE` + `ROTATE_NEW_SECRET_VALUE`) / STS |

xAI keys are `provider: manual` entries with a console playbook (no
key-management API is confirmed).

## sync-secrets (per-repo push)

Routes live in the project config at `<primary-repo>/secrets.yaml`
(`KIND<TAB>DEST<TAB>ENVNAME<TAB>REF<TAB>TRANSFORM`); the engine lives centrally.

*Example (vault item edited by hand — push it everywhere it routes):*

```bash
sync-secrets --repo /Users/simon/dev/workflow_pro --changed 'op://WORKFLOW_PRO/Resend/api_key' --reason 'F0123 rotated Resend key'
```

*Example (preview a repo's full sweep, safe anywhere):*

```bash
sync-secrets --repo /Users/simon/dev/amaru-web --dry-run
```

- A rotation entry may declare `sync_repos: [../<other-primary-repo>]` when a
  **second project** routes the same ref (paths relative to the declaring
  `secrets.yaml`). The rotation fan-out then sweeps that project too; without it
  only the owning project is swept and the other project's destinations keep the
  retired value. `--dry-run` prints the extra legs and cross-project consumers.
- Default sweep = `github` + `render` + `hermes` + `prefect` (both tiers; the
  prod prefect tier prompts for confirmation unless `SECRETS_ASSUME_YES=1`,
  which rotate-secret/rotate-project export); `--channel` restricts to one
  (`--channel prefect --dest staging|prod` for a single tier).
- `--changed` matches REF by exact equality, or by `op://Vault/Item/` prefix
  when given without a field — never bare substring.
- Idempotent, upsert-only, never deletes. `--dry-run` reads nothing, writes
  nothing, works from agent shells. `--no-deploy` pushes without triggering
  Render deploys.
- Exit codes: 0 ok, 1 operational, 2 usage (incl. missing manifest), 3 refusal
  (sensitive read from an agent shell).

**Important:** an empty or failed read never overwrites a live destination
value — the writers resolve and validate the entire batch before the first
write, and Render deploys trigger only after every PUT succeeded (deploy-last).

Reference: `docs/secrets.md` (manifest format, vault sensitivity convention,
item naming, engine interfaces).

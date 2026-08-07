---
name: rotate-secret
description: Rotate a registered secret through the central agent-workflows engine (registry lookup, provider handler, in-place vault write, sync-secrets fan-out) and push manifest-routed secrets to their destinations. Use when a credential must be rotated, was exposed, or when a vault item changed and its consumers (GitHub/Render/Prefect) need re-syncing.
---

# Rotate a secret / sync secrets

Central engine: `bin/rotate-secret`, `bin/sync-secrets`, registry
`config/secret-rotation.json`, docs in `docs/secrets.md`.

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
   - `0` — rotated: vault write verified, consumer fan-out synced.
   - `2` — usage / unknown entry / unknown provider. Nothing changed.
   - `3` — MANUAL provider: the playbook was printed, nothing changed. Show the
     playbook to the user and offer the `--complete` flow (step 5).
   - `4` — provider or verify error, safe state (vault consistent). Report the
     script output verbatim.
   - `5` — vault holds the NEW value but a consumer sync failed. The script
     prints the exact recovery commands (idempotent re-sync per repo). Run or
     report those; never improvise a different recovery.
5. **Manual completion.** After the operator minted the new value externally:
   `printf %s '<new-value>' | rotate-secret --ref '...' --reason '...' --complete`
   — reads stdin once, writes the vault item in place, fans out sync.

**Never echo, log, or capture a secret value.** Values flow op → pipe →
destination only. If a value is ever printed, treat the credential as exposed
and rotate it.

## Providers (slice 1)

| provider | mode | what happens | overlap/outage | failure recovery |
|---|---|---|---|---|
| `self_minted` | SELF_MINTED | mints `openssl rand` (registry `generate`: hex/base64, bytes), writes vault by immutable id, verifies by re-read, fans out sync | old value dies as consumers redeploy (seconds of overlap) | exit 4 = vault safe, retry; exit 5 = re-run printed sync legs |
| `manual` | MANUAL | prints the registry playbook, exits 3, changes nothing; `--complete` does vault write + fan-out | per playbook; some entries need `--accept-brief-outage` | re-run `--complete` (vault write is idempotent by value) |
| `postgres` | DUAL_KEY | STUB: amaru bridges to `amaru-web/scripts/db/rotate-credentials`; other projects exit 4 until the central port (slice 3/4) | zero-downtime dual-principal (amaru) | amaru rotator's own state machine owns resume |

Verification: `self_minted` verifies the vault write by re-read; entry `verify`
fields describe the behavioural check to run after redeploy.

## sync-secrets (per-repo push)

The routing manifest lives in each consuming repo at `scripts/secrets/manifest`
(`KIND<TAB>DEST<TAB>ENVNAME<TAB>REF<TAB>TRANSFORM`); the engine lives centrally.

*Example (vault item edited by hand — push it everywhere it routes):*

```bash
sync-secrets --repo /Users/simon/dev/workflow_pro --changed 'op://WORKFLOW_PRO/RESEND_API_KEY/value' --reason 'F0123 rotated Resend key'
```

*Example (preview a repo's full sweep, safe anywhere):*

```bash
sync-secrets --repo /Users/simon/dev/amaru-web --dry-run
```

- Default sweep = `github` + `render`. **Prefect is explicit only**
  (`--channel prefect`; prod tier prompts for confirmation) and is excluded
  from `--changed` fan-out.
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

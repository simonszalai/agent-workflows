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
   - `0` — rotated: vault write verified, consumer fan-out synced, predecessor
     cleaned up (dual-key providers).
   - `2` — usage / unknown entry / unknown provider; for postgres also
     rotation-state mismatch or advisory-lock contention. Nothing changed.
   - `3` — playbook printed or precondition refused (MANUAL provider,
     unconfigured dual provider, sql_role owner scope, unregistered health
     URL), nothing changed. Show the output and offer `--complete` (step 5).
   - `4` — provider or verify error, safe state (vault consistent; postgres:
     paused before promotion, both logins valid — `--resume`). Report the
     script output verbatim.
   - `5` — vault holds the NEW value but a post-vault step failed: consumer
     sync (the script prints the exact idempotent re-sync commands) or
     postgres retirement proof (`--resume` after fixing the reported problem).
     Never improvise a different recovery.
5. **Manual completion.** After the operator minted the new value externally:
   `printf %s '<new-value>' | rotate-secret --ref '...' --reason '...' --complete`
   — reads stdin once, writes the vault item in place, fans out sync.

**Never echo, log, or capture a secret value.** Values flow op → pipe →
destination only. If a value is ever printed, treat the credential as exposed
and rotate it.

## Providers (slice 4a)

| provider | mode | flags | what happens | overlap behaviour | failure recovery | verify |
|---|---|---|---|---|---|---|
| `self_minted` | SELF_MINTED | — | mints `openssl rand` (registry `generate`: hex/base64, bytes), writes vault by immutable id, fans out sync | old value dies as consumers redeploy (seconds of overlap) | exit 4 = vault safe, retry; exit 5 = re-run printed sync legs | vault re-read; entry `verify` prose after redeploy |
| `manual` | MANUAL | `--complete` | prints the registry playbook, exits 3, changes nothing; `--complete` does vault write + fan-out | per playbook; some entries need `--accept-brief-outage` | re-run `--complete` (idempotent by value) | per entry `verify` |
| `postgres` | DUAL_KEY | `--resume`, `--keep-old` | central dual-principal rotator: versioned candidate login → batch PUT to registry consumers → exact deploys → health probes → canonical promotion → drain + full Render inventory → reversible fence → retirement. Fail-closed `health_urls` config; ROOT and `sql_role` owners (autodev shared box) refuse (exit 3) | zero downtime: both principals valid until retirement; ≥120 s mandatory drain grace | value-free state file per `<project>-<tier>`; exit 2 = lock/state contention; exit 4 = paused before promotion; exit 5 = promoted, retirement unproven — always `--resume`, never improvise | deploy-id proofs + `{status:"ok", databaseRoleSafe:true}` health + canonical byte-equality, all inside the rotator |
| `resend` | DUAL_KEY | — | snapshots old key ids by `config.key_name` prefix, creates a new key, vault-replace, sync, verify, deletes ONLY the snapshotted ids | both keys valid until finalize; consumers converge on deploy | exit 3 = no `config.key_name`, use `--complete`; exit 4 after success message = predecessor cleanup failed, delete in dashboard | entry `verify_command`, else `config.canary` send with the new key, else vault re-read |
| `openai` | DUAL_KEY | — | dual via Admin API project service accounts (`config.admin_key_ref` + `config.project_id`); prefix-named predecessors deleted in finalize | both keys valid until finalize | exit 3 = unconfigured (playbook + `--complete`); dashboard-minted originals need manual deletion | entry `verify_command`, else GET /v1/models with the new key |
| `xai` | MANUAL | `--complete` | always exit 3: no confirmed xAI key-management API shape (management key only drives xai-sdk collections gRPC) — console rotation + `--complete` | operator-controlled | re-run `--complete`; prefect rows need explicit `--channel prefect` | consumers work with new key BEFORE console deletion |
| `aws_iam` | DUAL_KEY | — | id+secret rotated as a PAIR: refuses if the IAM user has an unknown second key, creates the new pair, writes BOTH vault items before any sync (`sync_refs` lists both), verifies, then Inactive→delete the old key in finalize | both keys valid until finalize; deploy-last delivers both envs in one deploy | exit 3 = unconfigured or two-key conflict (nothing changed); cleanup failure leaves old key Inactive/valid — finish in console | entry `verify_command`, else `sts get-caller-identity` with the new pair |

Verification: dual-key providers never destroy the predecessor before their
verify step AND the consumer fan-out both succeeded (`provider_finalize`).
Entry `verify` fields describe the behavioural check to run after redeploy.

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

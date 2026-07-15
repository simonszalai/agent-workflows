---
name: sensitive-vault-access
description: Safely request interactive access to 1Password *-sensitive vaults with a mandatory human-readable reason and macOS notification. Use before any command, script, deployment, verification, or investigation that will resolve an op://*-sensitive reference or otherwise trigger Touch ID for sensitive credentials.
---

# Sensitive vault access

Before accessing any `op://*-sensitive/...` reference, classify the operation:

1. **Read-only:** stop before resolving the sensitive reference. Production read-only database
   work MUST use the service-account-readable RO credential/profile, never the write-capable
   sensitive credential. If no RO route is documented, report that missing route as the blocker;
   do not fall back to Touch ID. Commands described as verify, inspect, report, list, diff, schema
   check, or diagnostics are read-only unless their documented behavior explicitly writes.
2. **Mutating:** only after confirming the command genuinely requires write capability, state the
   concrete purpose in one concise sentence. Include the ticket/milestone or operation when known;
   never include secret values.
3. Pass that purpose command-locally as `SENSITIVE_ACCESS_REASON` so it cannot leak into unrelated
   later calls.

*Example (ts-prefect, read-only production verification — silent; no Touch ID):*

```bash
scripts/secrets/dev-env ts-prefect-prod-ro -- \
  uv run python scripts/graph/ingestion_cost_report.py --version 1
```

*Example (ts-prefect, reviewed production mutation):*

```bash
SENSITIVE_ACCESS_REASON="Activate the reviewed F0123 production prompt" \
  scripts/secrets/dev-env ts-prefect-prod -- <write-command>
```

If a wrapper supports `--reason`, prefer it:

```bash
scripts/secrets/dev-env ts-prefect-prod \
  --reason "Activate the reviewed F0123 production prompt" -- <write-command>
```

The access layer must send a macOS notification immediately before Touch ID showing the
vault/item, reason, and requester. Missing reasons must fail closed before invoking 1Password.

Never bypass this contract with `/opt/homebrew/bin/op`, `OP_BIN`, or an alternate wrapper. Never
print or log resolved values.
Never set `OP_DESKTOP=1`, request Touch ID, or use a `*-sensitive` profile merely to complete a
read-only check.

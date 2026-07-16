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

## Session reuse

For an approved mutation that genuinely requires a sensitive credential, always route direct
reads through `agent-workflows/bin/op` (normally by setting it as `OP_BIN` for the existing
secrets wrapper). The shim caches each resolved sensitive reference in a **memory-only helper
scoped by `CONDUCTOR_SESSION_ID`**:

- the first read requires `SENSITIVE_ACCESS_REASON`, sends the “what is it for?” notification,
  and may prompt for Touch ID;
- repeated reads of the same reference and flags return from the session cache without another
  notification or fingerprint prompt;
- values are never written to disk, command arguments, audit logs, or the ambient environment;
- the cache uses a user-only socket and expires after eight idle hours;
- a different sensitive item still requires its own clearly attributed approval;
- non-Conductor shells (no `CONDUCTOR_SESSION_ID`) do not cache.

Do not set `OP_SENSITIVE_NOTIFICATION_SENT` to suppress the shim. It is intentionally ignored on
a cache miss: every operation that can produce a new fingerprint prompt must first show its
purpose in the notification.

```bash
SENSITIVE_ACCESS_REASON="Deploy the reviewed E0003 staging Render configuration" \
OP_BIN="$HOME/dev/agent-workflows/bin/op" \
  scripts/secrets/dev-env amaru-staging -- <write-command>
```

Re-reading the same reference later in that Conductor session reuses the memory cache
automatically. This cache does not turn a write credential into an approved read-only route and
does not extend approval to a different vault item.

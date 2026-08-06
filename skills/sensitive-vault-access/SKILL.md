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

On a sensitive cache miss, the canonical shim preflights the idempotent `op signin` for the selected
human account. If authentication remains pending long enough to indicate a biometric prompt, it
shows the macOS purpose notification alongside Touch ID with the vault/item, reason, and requester.
Already-authenticated calls complete the preflight during the grace period and do not notify. The
shim then selects the checked-in canonical human account unless the reviewed command supplies an
explicit account. Missing reasons, unusable notification helpers, invalid account selectors,
authentication failures, and notification failures block before the sensitive command runs.
`OP_DESKTOP=1` is neither required nor a supported sensitive-access workaround.

Never bypass this contract with `/opt/homebrew/bin/op`, an alternate wrapper, or an `OP_BIN` that
does not name the canonical shim in the consumer/provider's reviewed root. Never print or log
resolved values. Never request Touch ID or use a `*-sensitive` profile merely to complete a
read-only check.

## Session reuse

For an approved mutation that genuinely requires a sensitive credential, attest one reviewed root
and route the provider/consumer, redaction wrapper, and `OP_BIN` through that same root. Do not mix
a reviewed provider with a dirty live shim or an alternate checkout. When the consumer accepts
`OP_BIN`, it must name `<reviewed-root>/bin/op`.

Only sensitive children have inherited service-account, Connect, and `OP_SESSION_*` credentials
removed. Ordinary non-sensitive reads retain inherited or Keychain-backed silent service-account
behavior. The shim caches each resolved sensitive reference in a **memory-only helper scoped by
`CONDUCTOR_SESSION_ID`**:

- the first read requires `SENSITIVE_ACCESS_REASON`; when authentication is needed, it shows the
  “what is it for?” notification alongside the Touch ID prompt;
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
REVIEWED_ROOT=/absolute/path/to/the/attested/agent-workflows
SENSITIVE_ACCESS_REASON="Run the reviewed mutation for F0123" \
OP_BIN="$REVIEWED_ROOT/bin/op" \
  "$REVIEWED_ROOT/bin/redacted-exec" -- \
  "$REVIEWED_ROOT/bin/reviewed-provider" <write-command>
```

Re-reading the same reference later in that Conductor session reuses the memory cache
automatically without a notification or authentication attempt. This cache does not turn a write
credential into an approved read-only route and does not extend approval to a different vault
item.

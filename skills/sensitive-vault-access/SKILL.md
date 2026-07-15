---
name: sensitive-vault-access
description: Safely request interactive access to 1Password *-sensitive vaults with a mandatory human-readable reason and macOS notification. Use before any command, script, deployment, verification, or investigation that will resolve an op://*-sensitive reference or otherwise trigger Touch ID for sensitive credentials.
---

# Sensitive vault access

Before accessing any `op://*-sensitive/...` reference:

1. Prefer a non-sensitive or read-only route when it can accomplish the task. Production read-only database work must use the service-account-readable RO credential, not the write-capable sensitive credential.
2. State the concrete purpose in one concise sentence. Include the ticket/milestone or operation when known; never include secret values.
3. Pass that purpose command-locally as `SENSITIVE_ACCESS_REASON` so it cannot leak into unrelated later calls:

```bash
SENSITIVE_ACCESS_REASON="Verify F0123 production schema after deployment" \
  scripts/secrets/dev-env ts-prefect-prod -- <command>
```

If a wrapper supports `--reason`, prefer it:

```bash
scripts/secrets/dev-env ts-prefect-prod \
  --reason "Verify F0123 production schema after deployment" -- <command>
```

The access layer must send a macOS notification immediately before Touch ID showing the vault/item, reason, and requester. Missing reasons must fail closed before invoking 1Password.

Never bypass this contract with `/opt/homebrew/bin/op`, `OP_BIN`, or an alternate wrapper. Never print or log resolved values.

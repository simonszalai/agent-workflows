---
name: sensitive-vault-access
description: Safely request interactive access to 1Password *-sensitive vaults with a mandatory human-readable reason and macOS notification. Use before any command, script, deployment, verification, or investigation that will resolve an op://*-sensitive reference or otherwise trigger Touch ID for sensitive credentials.
---

# Sensitive vault access

## Client-managed MCP and OAuth credentials

Codex, Conductor, Claude, browsers, and other clients own the credentials they obtain for MCP
servers and OAuth sessions. Those credential stores are a capability boundary, not an alternate
secret source for agents.

- **Never** invoke `security`, Keychain APIs, SQLite/config-store readers, or equivalent commands
  to locate, inspect, test, or extract a client-managed credential. In particular, never read
  entries such as `Codex MCP Credentials`, even through `redacted-exec` and even if the value would
  remain in memory.
- Never repurpose a browser session cookie, application cookie, OAuth refresh/access token, or
  other client session material as an MCP bearer token. Never build a direct `curl`/`fetch`/custom
  MCP client to work around an unavailable injected MCP tool.
- Use only the MCP tools injected into the current agent session. Credential-free status commands
  may establish configuration or auth *mode*, but they do not prove that a usable token exists and
  do not authorize reading the client's credential store.
- If a tool is missing because the catalog is stale, authentication is absent/expired, or the
  injected server is unavailable, stop that scope and report `BLOCKED`. The remedy is a supported
  client login/reconnect followed by a fresh agent session; it is never manual credential recovery.

These rules apply to read-only and mutating work in every environment. `SENSITIVE_ACCESS_REASON`,
Touch ID approval, and redaction wrappers do not permit bypassing this boundary.

**Staging and dev never belong here.** Every staging and dev credential — reads *and* writes,
including the `owner` and `app` database roles — lives in the regular `<PROJECT>` vault and resolves
silently through the project's service account. Only production **write** credentials are sensitive;
production read-only is regular too. A staging task that appears to need Touch ID is a
misconfiguration: report it, do not approve it. See `../tool-postgres/SKILL.md` for the full table.

A regular-vault read that prompts has one of two causes, and neither is fixed by escalating:

- the addressed vault is missing from `projects[].service_account.vaults` in
  `config/project-tools.json`, or its project's token is absent from the Keychain — `bin/op` fails
  closed with a specific error naming the fix;
- the caller passed `--account`, which bypasses the service-account path entirely. Never pass
  `--account` for a regular-vault read.

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

Notification ownership is exclusive to the canonical `bin/op` shim. Project-level wrappers must
not invoke a notifier, call `osascript`, pre-announce sensitive access, or set
`OP_SENSITIVE_NOTIFICATION_SENT`; they pass the reason to the canonical shim and let it decide
whether authentication is actually pending. A project wrapper may validate that a reason exists
before starting a multi-read operation, but it must not produce the user notification itself.
For a command such as `op inject` whose references arrive only on stdin, the wrapper may set the
value-free `OP_SENSITIVE_VAULT_HINT=<name>-sensitive` and `OP_SENSITIVE_ITEM_HINT=<description>`
for the canonical shim; it must not consume or log the input stream itself.
Shared tooling that must write a regular vault with the reviewed human account may set
`OP_USE_CANONICAL_HUMAN_ACCOUNT=1`; the shim resolves the selector centrally without classifying
that regular-vault operation as sensitive or showing a sensitive-access notification.

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

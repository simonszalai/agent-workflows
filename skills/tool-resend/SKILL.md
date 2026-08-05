---
name: tool-resend
description: Safely inspect and manage Resend through the project-aware official CLI wrapper.
---

# Resend CLI Reference

Use the official Resend CLI through `resend-cli` (agent-workflows/bin, on PATH).
Never call the raw `resend` binary for project work: its saved login and profile are
user-global and may select the wrong account.

## Project and authentication contract

`resend-cli` resolves the repository's exact Git `origin` through the committed
`config/project-tools.json` registry. There is no default profile or fuzzy directory
matching. Projects without a Resend profile fail closed. Profiles require a full-access
management key because the wrapper verifies account identity by listing domains before every
authenticated command.

The skill contains no credential. The wrapper:

1. selects the project from the exact repository remote;
2. reads only that profile's committed `op://...` reference through the audited `bin/op`
   shim, or accepts an already-approved process-local `RESEND_API_KEY`;
3. injects the key only into the official CLI child process;
4. verifies the account exposes the registry's expected canary domain;
5. forces non-interactive JSON output for authenticated commands.

It never writes a key to a repository, dotenv file, CLI config, command argument, or shell
profile. `login`, `logout`, `auth`, `--api-key`, `--profile`, and insecure credential storage
are blocked. API-key creation is also blocked because the command emits a new secret.

Safe, credential-free profile check:

```bash
resend-cli context
```

Authenticated account check:

```bash
resend-cli doctor
```

## Read operations

Known read commands auto-detect the project and need no write flags:

```bash
resend-cli domains list | jq '.data // .'
resend-cli emails list --limit 20 | jq '.data // .'
resend-cli emails get <email-id> | jq '{id,from,to,subject,status,last_event}'
resend-cli logs list --limit 20 | jq '.data // .'
resend-cli webhooks list | jq '.data // .'
resend-cli templates list | jq '.data // .'
```

Always bound and filter output. Email and API logs can contain recipient addresses, subjects,
message bodies, request bodies, and response bodies. Retrieve full records only when the task
requires them, and never paste bulk logs into agent context.

## Mutation guardrails

Unknown, interactive, and mutating commands fail unless all three safeguards are present:

```bash
resend-cli --project <id> --write \
  --reason "Send the user-approved test email for ticket F0123" \
  emails send --from sender@example.com --to approved@example.com \
  --subject "Test" --text "Test message"
```

Before running a mutation:

- the user must explicitly authorize the specific remote change or email send;
- `--project` must name the intended registered profile;
- `--reason` must describe the authorized purpose;
- inside a Git repository, the explicit project must match its exact registered origin.

If the operation can affect production, run the complete command through
`redacted-exec -- resend-cli ...`; never capture raw authenticated mutation output.

A deliberate cross-project operation additionally requires `--allow-cross-project`. Do not use
that flag to work around a missing or incorrect registry mapping.

Sending email, forwarding inbound mail, contact imports, domain verification, webhook listeners,
and draft/template changes are mutations. `--dry-run` still requires the mutation guard because
the allowlist is deliberately conservative. Use idempotency keys for retryable sends when the
command supports them.

## Installation

The official installer places the binary at `~/.resend/bin/resend`:

```bash
curl -fsSL https://resend.com/install.sh | bash
```

The wrapper checks that path before Homebrew or `PATH`. Do not run `resend login` after install.

## Common commands

| Task | Command |
| ---- | ------- |
| Selected profile, no auth | `resend-cli context` |
| Validate credential/account | `resend-cli doctor` |
| List domains | `resend-cli domains list` |
| Domain/DNS status | `resend-cli domains get <id>` |
| Recent sent email | `resend-cli emails list --limit 20` |
| Email delivery details | `resend-cli emails get <id>` |
| API request logs | `resend-cli logs list --limit 20` |
| Registered webhooks | `resend-cli webhooks list` |
| Send email (explicit approval only) | `resend-cli --project <id> --write --reason "<purpose>" emails send ...` |

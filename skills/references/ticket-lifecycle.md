# Ticket lifecycle reference

This is the canonical lifecycle for ticket-level workflow skills.

## Key terms

- **Land**: merge a completed branch/PR into the target branch (`main` or `staging`).
- **Deploy**: run deployment steps, wait for deploy infrastructure, or push deploy config.
- **Verify**: observe staging/production and update ticket status from evidence.

Ticket execution skills may **land** code when their policy allows it. They must not deploy or
verify. Verification and promotion are separate timer-friendly skills.

## Standalone ticket statuses

```text
backlog -> planning -> planned -> building
```

After a successful landing:

```text
# direct-to-main landing
to_verify_prod -> completed | verify_prod_failed

# staging landing
to_verify_staging -> verify_staging_failed
                 \-> ticket-promote -> to_verify_prod -> completed | verify_prod_failed
```

Use `abandoned` and `on_ice` only for explicit cancellation/deprioritization.

## Epic-step ticket statuses

Epic source tickets are parked as `absorbed_into_epic` and never land. Epic step tickets are
ordinary tickets that are executed with epic context. After their code is landed for the
milestone/integration target, they move to `merged`; the parent epic or milestone gate owns
staging/prod verification.

```text
backlog -> planning -> planned -> building -> merged
```

## Required MCP support

The workflow skills assume the ticket system accepts the staging verification statuses:

- `to_verify_staging`
- `verify_staging_failed`

If the MCP server rejects one of these statuses, stop and report that the autodev-memory enum
migration is missing. Do not emulate status with tags or free-form metadata.

## Approval

There is no `approved` ticket status. Approval is the decision to leave `planned` and start
`building`.

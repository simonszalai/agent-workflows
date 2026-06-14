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
backlog -> up_next -> in_progress -> planned -> in_progress
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

## Blockers are metadata, not statuses

Do not create or use a `blocked` lifecycle status. Any lifecycle column can have a blocker.
When work/deploy/verification is waiting on an external dependency, keep the ticket in the
correct lifecycle status and set independent blocker metadata:

- `blocked_at`
- `blocked_by`
- `blocked_reason`
- `blocked_context`

Example: after an automatable production deploy is complete, a ticket should still move to
`to_verify_prod`. If verification is waiting on a Thomas-only `ts-decrypt-proxy` production
deploy, set `blocked_by="Thomas"` and include `{"repo":"ts-decrypt-proxy","target":"production"}`
in `blocked_context`. The dashboard shows this as a red blocker indicator in the normal status
column.

## Epic-step ticket statuses

Epic source tickets are parked as `absorbed_into_epic` and never land. Epic step tickets are
ordinary tickets that are executed with epic context. After their code is landed for the
milestone/integration target, they move to `merged`; the parent epic or milestone gate owns
staging/prod verification.

```text
backlog -> up_next -> in_progress -> planned -> in_progress -> merged
```

## Staging verification statuses

The ticket lifecycle enum includes the staging segment as of **migration 025**:

- `ready_to_deploy_staging`
- `to_verify_staging`
- `verify_staging_failed`

A standalone ticket landed to staging advances to `to_verify_staging` directly (no epic
required); the dashboard board surfaces it in the "Verify staging" lane. Do not emulate status
with tags or free-form metadata.

## Approval

There is no `approved` ticket status. Approval is the decision to leave `planned` and start
work again by setting `in_progress`. Ticket statuses `planning`, `building`, and `active`
are retired; use `in_progress` for any ticket-related flow that has started.

# Ticket lifecycle reference

This is the canonical lifecycle for ticket-level workflow skills.

## Key terms

- **Land**: merge a completed branch/PR into the target branch (`main` or `staging`).
- **Deploy**: run deployment steps, wait for deploy infrastructure, or push deploy config.
- **Verify**: observe staging/production behavior and update ticket status from evidence.

`/ticket-flow` may deploy standalone tickets only by invoking `/auto-deploy`, which owns the
merge/deploy mechanics and next verification status. Ticket execution must not perform
ad-hoc deployment commands or post-deploy behavior verification. Verification and promotion are
separate timer-friendly skills.

## Standalone ticket statuses

```text
backlog -> up_next -> in_progress -> planned -> in_progress
```

After a successful standalone landing/deployment:

```text
# direct-to-production landing/deployment
to_verify_prod -> completed | prod_verified_needs_cleanup | verify_prod_failed

# staging landing/deployment
to_verify_staging -> verify_staging_failed
                 \-> staging_verified -> ticket-promote -> to_verify_prod -> completed | prod_verified_needs_cleanup | verify_prod_failed
```

Staging PASS **auto**-invokes `/ticket-promote` only for low-risk scopes that pass the
auto-promotion gate (`ticket-verify` §9b: FINALIZED contract fully graded on fresh
post-activation evidence, and no schema/deploy-config/auth category in the diff).
Schema-, deploy-config-, or auth-bearing tickets rest at `staging_verified` until a human
runs `/ticket-promote` explicitly — that resting state is normal, not a stall.

`/ticket-promote` is the post-staging production step: it lands the promoted commits on
`main` AND runs the project's production deploy steps before setting `to_verify_prod`.

`to_verify_prod` means: **production landing AND deploy steps are complete; behavior is
unverified.** Only `/ticket-verify production` moves a ticket from `to_verify_prod` to
`completed`, `prod_verified_needs_cleanup`, or `verify_prod_failed`.

`prod_verified_needs_cleanup` means: **production behavior passed verification, but deferred
cleanup still needs trigger/execution/soak/final evidence, or approval for critical/unknown
destructive cleanup, on the same ticket/epic.**
Only `/ticket-verify production` moves it to `completed` (cleanup evidence passed) or
`verify_prod_failed` (cleanup evidence failed/out-of-scope/revert required).

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

## Deferred cleanup holding status

Deferred cleanup is not split into a child cleanup ticket. When `ticket-verify` §10a finds a
structured decommission/retirement follow-up after production verification passes, the original
ticket/epic keeps a `deferred_cleanup` artifact and moves to `prod_verified_needs_cleanup`:

```text
to_verify_prod
  -> prod_verified_needs_cleanup  # blocked_by trigger_condition | approval | soak as needed
  -> completed | verify_prod_failed
```

Approval, trigger, and soak are blocker metadata per the existing blocker policy above, not
separate statuses. Bounded noncritical destructive cleanup (including terminal Prefect flow-run
history) is automatically eligible and does not require approval; critical/unknown destructive
cleanup still does. Normal work pickup queues skip blocked items (`next_ticket` excludes them),
but `/ticket-verify production` includes cleanup holders in its default verification queue; an
explicit ticket ID can target one holder. See
`ticket-verify` §10/§10a for the artifact contract and execution rules. Legacy
`cleanup=true` child tickets may be read for historical context, but new cleanup work stays on
the parent item.

## Epic-step ticket statuses

Epic source tickets are parked as `absorbed_into_epic` and never land. Epic step tickets are
ordinary tickets that are executed with epic context. After their code is landed for the
milestone/integration target, they move to `merged`; the parent epic or milestone gate owns
staging/prod verification.

```text
backlog -> up_next -> in_progress -> planned -> in_progress -> merged
```

When `/ticket-verify` is invoked with an explicit parent epic/milestone scope, it may also use
the shared verification states as parent-owned flags:

```text
merged -> staging_verified -> to_verify_prod -> completed
```

These status changes mean "the parent epic gate verified/promoted this step", not that the step
was verified or promoted as a standalone ticket. Default ticket verification/promotion queues
should still skip epic step tickets unless the parent epic/milestone scope is explicit.

## Staging verification statuses

The ticket lifecycle enum includes the staging segment as of **migration 025**:

- `ready_to_deploy_staging`
- `to_verify_staging`
- `staging_verified`
- `verify_staging_failed`

A standalone ticket landed to staging advances to `to_verify_staging` directly (no epic
required); the dashboard board surfaces it in the "Verify staging" lane. Do not emulate status
with tags or free-form metadata.

## Approval

There is no `approved` ticket status. Approval is the decision to leave `planned` and start
work again by setting `in_progress`. Ticket statuses `planning`, `building`, and `active`
are retired; use `in_progress` for any ticket-related flow that has started.

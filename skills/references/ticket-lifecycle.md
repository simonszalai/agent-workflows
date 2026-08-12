# Ticket lifecycle reference

The canonical state machine for tickets. Role names below (executor, promoter, verifier) mean
"whoever performs that step in the current session" — there are no dedicated phase skills.

## Key terms

- **Land**: merge a completed branch/PR into the target branch (`main` or `staging`).
- **Deploy**: run deployment steps, wait for deploy infrastructure, or push deploy config.
- **Verify**: observe staging/production behavior and update ticket status from evidence.

Landing/deploy mechanics, behavior verification, and production promotion are separate steps:
never mark work verified from build output, and never treat a landing as a verification.

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
                 \-> staging_verified -> promotion -> to_verify_prod -> completed | prod_verified_needs_cleanup | verify_prod_failed
```

A staging PASS may auto-promote only low-risk scopes: the ticket's contract fully graded on
fresh post-activation evidence, and no schema, deploy-config, or auth category in the diff.
Schema-, deploy-config-, or auth-bearing tickets rest at `staging_verified` until a human
explicitly asks for promotion — that resting state is normal, not a stall.

**Promotion** is the post-staging production step: it lands the promoted commits on `main`
AND runs the project's production deploy steps before setting `to_verify_prod`.

`to_verify_prod` means: **production landing AND deploy steps are complete; behavior is
unverified.** Only production verification with evidence moves a ticket from `to_verify_prod`
to `completed`, `prod_verified_needs_cleanup`, or `verify_prod_failed`.

`prod_verified_needs_cleanup` means: **production behavior passed verification, but deferred
cleanup still needs trigger/execution/soak/final evidence, or approval for critical/unknown
destructive cleanup, on the same ticket/epic.** Only production verification moves it to
`completed` (cleanup evidence passed) or `verify_prod_failed`.

Use `abandoned` and `on_ice` only for explicit cancellation/deprioritization.

## Blockers are metadata, not statuses

Do not create or use a `blocked` lifecycle status. Any lifecycle column can have a blocker.
When work/deploy/verification is waiting on an external dependency, keep the ticket in the
correct lifecycle status and set independent blocker metadata: `blocked_at`, `blocked_by`,
`blocked_reason`, `blocked_context`.

Example: after an automatable production deploy completes, the ticket still moves to
`to_verify_prod`; if verification waits on a human-only deploy elsewhere, set
`blocked_by="<person>"` with the repo/target in `blocked_context`.

## Deferred cleanup holding status

Deferred cleanup is not split into a child cleanup ticket. When production verification passes
but a structured decommission/retirement follow-up remains, the original ticket/epic keeps a
`deferred_cleanup` artifact and moves to `prod_verified_needs_cleanup`:

```text
to_verify_prod
  -> prod_verified_needs_cleanup  # blocked_by trigger_condition | approval | soak as needed
  -> completed | verify_prod_failed
```

Approval, trigger, and soak are blocker metadata, not separate statuses. Bounded noncritical
destructive cleanup (including terminal Prefect flow-run history) is automatically eligible and
does not require approval; critical/unknown destructive cleanup does. Normal work pickup queues
skip blocked items (`next_ticket` excludes them), but production verification includes cleanup
holders in its default queue. New cleanup work stays on the parent item; legacy `cleanup=true`
child tickets are historical context only.

## Epic-step ticket statuses

Epic source tickets are parked as `absorbed_into_epic` and never land. Epic step tickets are
ordinary tickets executed with epic context. After their code lands for the milestone/integration
target, they move to `merged`; the parent epic or milestone gate owns staging/prod verification.

```text
backlog -> up_next -> in_progress -> planned -> in_progress -> merged
```

When verification runs with an explicit parent epic/milestone scope, it may also use the shared
verification states as parent-owned flags:

```text
merged -> staging_verified -> to_verify_prod -> completed
```

These mean "the parent epic gate verified/promoted this step", not that the step was verified
standalone. Default verification/promotion queues skip epic step tickets unless the parent
epic/milestone scope is explicit.

## Staging verification statuses

The ticket lifecycle enum includes the staging segment as of **migration 025**:
`ready_to_deploy_staging`, `to_verify_staging`, `staging_verified`, `verify_staging_failed`.

A standalone ticket landed to staging advances to `to_verify_staging` directly (no epic
required). Do not emulate status with tags or free-form metadata.

## Approval

There is no `approved` ticket status. Approval is the decision to leave `planned` and start
work again by setting `in_progress`. Statuses `planning`, `building`, and `active` are retired;
use `in_progress` for any started flow.

### Origin and execution-approval audit state

Ticket `origin` is immutable audit provenance, not an ownership, authorization, execution, or
pickup boundary. A project-scoped principal with ticket write capability may create tickets in
any canonical lifecycle status and move tickets across statuses inside its project scope. Never
infer an execution gate from an origin value.

`approve_execution=true` remains an explicit connected-admin action stamping
`execution_approved_at`/`execution_approved_by` for audit. The pair is not a prerequisite for
pickup or leaving `planned`; null fields do not block implementation.

`next_ticket` is the canonical pickup contract: unblocked `planned` or `backlog` tickets by
lifecycle state, repo scope, and ordering. Do not add a second origin/approval filter, status
rewrite, tag, or blocker.

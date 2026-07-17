---
name: ticket-full-auto
description: >-
  Explicit single-ticket wrapper that runs ticket-flow to staging, produces and verifies bounded
  staging evidence, promotes a clean PASS to production, verifies production, and completes the
  ticket. Stops on every failure, blocker, unsafe evidence trigger, or genuine timing wait.
max_turns: 300
---

# Ticket Full Auto

Run one standalone ticket through the complete staging-first delivery lifecycle without spending
model turns polling external systems.

This is an orchestrator over existing lifecycle owners. It does not reimplement planning, deploy,
verification, promotion, or status mutations:

```text
/ticket-flow <ID> --target staging
/ticket-verify staging <ID> --no-promote --produce-evidence
/ticket-promote <ID>
  -> /ticket-verify production <ID>
  -> completed
```

## Usage and authorization

```text
/ticket-full-auto F0123
/ticket-full-auto B0042
```

Use only when the user explicitly asks for the full staging-to-production dance or invokes this
skill. That invocation authorizes the production promotion/deploy after an exact staging `PASS`.
Never infer this authorization from a normal `/ticket-flow` request.

It also grants standing approval for plan-conformant, deterministic, corroborated `gated_auto`
review fixes and bounded resolve/re-review rounds. This does not authorize product-intent changes,
destructive scope expansion, materially different tradeoffs, new secrets/schema/infrastructure/cost,
or choosing between unresolved reviewer recommendations. Stop only when such a genuine decision is
not already answered by the ticket/current conversation, required infrastructure or authorization is
unavailable, the fix would expand scope, or required evidence cannot safely be produced.

This skill is standalone-ticket only. Route related ticket sets to `/goal-flow` and epics to
`/epic-flow --full-auto`.

## Shared contracts

Read and follow:

- `../references/execution-economy.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- the called skills' own boundaries

All CI and Prefect waits must use one bounded waiter process. In Conductor, dispatch only the wait
to one fresh leaf with `fork_turns: "none"`, then block once for its terminal result. Never poll a
resumable process session or re-sample the parent model while the external run is pending.

## Process

### 1. Resolve and resume safely

Load the standalone ticket once with `detail="light", include_events=false`. Cache the artifact
manifest, including any `deferred_cleanup` or legacy flow-run-cleanup artifact. Refuse epic members,
source tickets, abandoned tickets, and ambiguous repository scope.

Resume from lifecycle truth rather than repeating completed phases:

| Current status | Action |
|---|---|
| build/planning statuses | run `/ticket-flow <ID> --target staging` |
| `to_verify_staging` | continue at staging verification |
| `staging_verified` | continue at production promotion only when the latest staging evidence is an exact `PASS` from a FINALIZED contract |
| `to_verify_prod` | run `/ticket-verify production <ID>` |
| `completed` | report already complete and stop successfully |
| `verify_staging_failed` / `verify_prod_failed` | stop; do not retry past a failure without a new explicit user instruction |
| `prod_verified_needs_cleanup` | run `/ticket-verify production <ID>` to process the owning cleanup contract |

Do not resume past `BLOCKED`, `NEEDS_MORE_TIME`, `PASS (contract-missing)`, missing evidence, or a
stale evidence artifact merely because the lifecycle status appears later than expected.

### 2. Build and deploy to staging

Run:

```text
/ticket-flow <ID> --target staging
```

Require its normal persisted plan/build/review/deployment artifacts, local health gate, staging PR,
successful staging deployment mechanics, and final `to_verify_staging` status. During review, apply
the standing-approval contract above instead of stopping on a misclassified p1/sensitive finding.
If a phase fails or reports a genuine manual/external blocker, stop immediately and return its
evidence and next action.

### 3. Produce and verify staging evidence

Run:

```text
/ticket-verify staging <ID> --no-promote --produce-evidence
```

`--produce-evidence` exists for staging environments where schedules, scrapers, consumers, or other
runtime producers are intentionally idle. It permits one safe bounded producer run under
`ticket-verify`'s contract; it never permits a deploy, schedule enablement, backfill, or unbounded
pipeline run.

Stop on every outcome except exact `PASS`:

- `FAIL`: stop so the user can inspect the failing flow/evidence. Do not fix, redeploy, or promote.
- `BLOCKED`: stop with the exact missing deployment, unsafe trigger, or contract repair.
- `NEEDS_MORE_TIME`: stop with the recorded awaited condition and exact resume command. It is valid
  only when a live producer or already-triggered downstream process will produce evidence by waiting.
- `PASS (contract-missing)`: stop; a derived contract is not production-promotion evidence.
- exact `PASS`: require the persisted staging evidence artifact and continue.

### 4. Preserve ticket-attributed incident cleanup

Before production promotion, inspect the cached bug-ticket source/investigation and cleanup artifact
manifest for Prefect flow runs explicitly attributed to the incident that created the ticket. Follow
`ticket-verify`'s `verify-deferred-cleanup.md` preflight and ensure those original incident runs are
represented by one normalized `deferred_cleanup` with `cleanup_kind="flow_run_cleanup"`.

Fetch only the bodies required by the manifest: normally `source`, `investigation`, and
`deferred_cleanup`; fetch a legacy cleanup body directly by its artifact ID. Do not reload every
ticket artifact or event.

Accept only structured attribution: an existing ticket tag/triage cluster, explicit run IDs labeled
as the original incident failures, or a legacy flow-run-cleanup artifact. Do not collect arbitrary
UUIDs from prose, and do not include the staging evidence run, production verification runs,
post-fix failures, deployments, schedules, task runs, blocks, or application rows.

The cleanup command must be project-owned, dry-run-first, fix-time bounded, and independently
verifiable. For ts-prefect, use the maintained ticket-scoped command documented by the repository:

```text
uv run python -m scripts.prefect_ops.delete_ticket_flow_runs --ticket <ID>
```

That ts-prefect command requires the ticket tag/triage cluster recorded by its investigation path.
An explicit-ID-only ticket needs a project command that enforces exactly those IDs; do not pretend
the tag-based command covers untagged IDs.

`ticket-verify production` appends the artifact, activation boundary, execution, and non-interactive
arguments. If incident runs are attributed but no safe cleanup contract can be normalized, stop
before promotion with the exact contract repair; full-auto must not silently complete while the
ticket's resolved Prefect failures remain on the failure board.

### 5. Promote, deploy, verify, clean, and complete production

After exact staging `PASS`, run:

```text
/ticket-promote <ID>
```

This explicit wrapper invocation satisfies the human authorization requirement for production, but
does not waive `/ticket-promote`'s schema, migration, deploy, auth, parity, CI, or rollback gates.
`/ticket-promote` lands the verified work on `main`, runs production deploy steps, sets
`to_verify_prod`, and invokes `/ticket-verify production <ID>`. After production behavior records an
exact `PASS`, that verifier dry-runs, scope-checks, and deletes the terminal pre-fix Prefect incident
runs attributed to the ticket. Cleanup never runs before production PASS.

Stop immediately if promotion, a production deploy step, or production verification fails or blocks.
Success requires a production verification artifact with exact `PASS`, independently verified
incident cleanup when the ticket attributed Prefect runs, and final `completed` status. If production
passes but deferred cleanup remains, report `prod_verified_needs_cleanup` rather than claiming
completion; its cleanup contract owns the next run.

## Terminal report

Report one row for each lifecycle gate with command, result, PR/commit or flow-run identifier,
evidence artifact ID, and resulting ticket status. End with exactly one of:

- `COMPLETE` — production verification passed and the ticket is `completed`;
- `STOPPED` — include the failed/blocked/timing gate and exact next command or human decision.

Never report full-auto success from a staging PASS alone.

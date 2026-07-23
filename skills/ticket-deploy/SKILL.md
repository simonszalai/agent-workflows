---
name: ticket-deploy
description: >-
  Deploy-and-verify phase for one standalone ticket. Takes a target argument — staging, prod,
  or full — and orchestrates the existing owners: auto-deploy (deploy mechanics), ticket-verify
  (evidence), ticket-promote (production landing + deploy). Self-heals routine CI failures and
  stops on behavior-verification failures, blockers, unsafe evidence triggers, genuine timing
  waits, or human-judgment decisions.
max_turns: 300
---

# Ticket Deploy

Run the deploy+verify phase of one standalone ticket. This is an orchestrator over existing
lifecycle owners; it does not reimplement deploy mechanics, verification, promotion, or status
mutations:

- `/auto-deploy` — PR creation, merge, deploy steps, deployment-mechanics checks, status updates
- `/ticket-verify` — behavior/evidence verification, verdicts, evidence artifacts
- `/ticket-promote` — staging→main landing + production deploy steps

## Usage

```text
/ticket-deploy F0123 staging   # deploy to staging + verify staging; stop there
/ticket-deploy F0123 prod      # production leg only (status-aware, see below)
/ticket-deploy F0123 full      # staging leg, then on exact staging PASS the production leg
```

The target argument is required: `staging`, `prod` (alias `production`), or `full`.

This skill is standalone-ticket only. Epic members are deployed and gated at milestone level by
`/milestone-flow` / `/epic-flow`; refuse them and route there.

## Authorization

Invoking this skill with `prod` or `full` is the explicit human authorization for production
promotion/deploy (after an exact staging `PASS` where one exists). Never infer that authorization
from a `staging` invocation. `staging` and `full` also authorize
`/ticket-verify staging --produce-evidence` (one safe bounded producer run under ticket-verify's
contract; never a deploy, schedule enablement, backfill, or unbounded pipeline run).

## Shared contracts

Read and follow:

- `../references/execution-economy.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/ci-self-heal.md`
- the called skills' own boundaries

All CI and Prefect waits must use one bounded waiter process. In Conductor, dispatch only the wait
to one fresh leaf with `fork_turns: "none"`, then block once for its terminal result. Never poll a
resumable process session or re-sample the parent model while the external run is pending.

This skill authorizes autonomous repair of mechanical CI failures throughout staging and
production delivery. Follow `ci-self-heal.md`: inspect terminal logs, fix routine repository
failures, re-run focused + final-tree validation and review, commit/push, wait on the new tree,
and resume automatically. A red CI check alone is never a terminal outcome.

## Process

### 1. Resolve and resume safely

Load the standalone ticket once with `detail="light", include_events=false`. Cache the artifact
manifest, including any `deferred_cleanup` or legacy flow-run-cleanup artifact. Refuse epic
members, source tickets, abandoned tickets, and ambiguous repository scope.

Enter from lifecycle truth rather than repeating completed legs:

| Current status | `staging` | `prod` | `full` |
|---|---|---|---|
| built, branch pushed (pre-deploy) | §2 | direct-production gate (§4a) | §2 |
| `to_verify_staging` | §3 | stop: staging verify pending — run `staging` or `full` | §3 |
| `staging_verified` | report already verified; stop | §4 | §4 |
| `to_verify_prod` | n/a | §5 verification only | §5 verification only |
| `prod_verified_needs_cleanup` | n/a | `/ticket-verify production <ID>` | same |
| `completed` | report already complete; stop successfully | same | same |
| `verify_staging_failed` / `verify_prod_failed` | stop; do not retry past a failure without a new explicit user instruction | same | same |

Do not resume past `BLOCKED`, `NEEDS_MORE_TIME`, `PASS (contract-missing)`, missing evidence, or
a stale evidence artifact merely because the lifecycle status appears later than expected.

### 2. Deploy to staging (`staging` and `full`)

Run `/auto-deploy <ID> staging`. Require successful staging deployment mechanics and final
`to_verify_staging` status. If it returns because CI is red, enter the shared CI self-heal loop
and resume at the interrupted phase after CI passes. On any other failure it reverts status and
reports; relay and stop.

### 3. Produce and verify staging evidence (`staging` and `full`)

Run:

```text
/ticket-verify staging <ID> --no-promote --produce-evidence
```

Stop on every outcome except exact `PASS`:

- `FAIL`: stop so the user can inspect the failing flow/evidence. Do not fix, redeploy, or promote.
- `BLOCKED`: stop with the exact missing deployment, unsafe trigger, or contract repair.
- `NEEDS_MORE_TIME`: stop with the recorded awaited condition and exact resume command. It is
  valid only when a live producer or already-triggered downstream process will produce evidence
  by waiting.
- `PASS (contract-missing)`: stop; a derived contract is not production-promotion evidence.
- exact `PASS`: require the persisted staging evidence artifact. For target `staging`, report and
  stop here (the ticket rests at `staging_verified` for an explicit `prod`/`full` continuation).
  For target `full`, continue to §4.

### 4. Production leg — promote staging-verified work (`prod` and `full`)

Preconditions: latest staging evidence is an exact `PASS` from a FINALIZED contract, and §4b
(incident cleanup preservation) has been checked.

Run:

```text
/ticket-promote <ID>
```

This explicit invocation satisfies the human authorization requirement for production, but does
not waive `/ticket-promote`'s schema, migration, deploy, auth, parity, CI, or rollback gates.
`/ticket-promote` lands the verified work on `main`, runs production deploy steps, sets
`to_verify_prod`, and invokes `/ticket-verify production <ID>` (§5). Apply the same CI self-heal
loop to promotion PR checks.

### 4a. Production leg — direct-to-production (never staged)

Only for tickets whose delivery target is direct production (tiny safe standalone work per
`landing-policy.md`). Before deploying, re-run the landing-policy risk classification against the
actual diff. If the change is **not** tiny/safe — schema, auth, encryption, deploy-config, new
infrastructure/cost, wide blast radius, or material uncertainty — **stop and ask the user for
confirmation** before any production mutation; report exactly what makes it risky and recommend
the staging path. With a tiny/safe classification or explicit user confirmation, run
`/auto-deploy <ID> production`, then `/ticket-verify production <ID>` (§5).

### 4b. Preserve ticket-attributed incident cleanup

Before production promotion, inspect the cached bug-ticket source/investigation and cleanup
artifact manifest for Prefect flow runs explicitly attributed to the incident that created the
ticket. Follow `ticket-verify`'s `verify-deferred-cleanup.md` preflight and ensure those original
incident runs are represented by one normalized `deferred_cleanup` with
`cleanup_kind="flow_run_cleanup"`.

Fetch only the bodies required by the manifest: normally `source`, `investigation`, and
`deferred_cleanup`; fetch a legacy cleanup body directly by its artifact ID. Do not reload every
ticket artifact or event.

Accept only structured attribution: an existing ticket tag/triage cluster, explicit run IDs
labeled as the original incident failures, or a legacy flow-run-cleanup artifact. Do not collect
arbitrary UUIDs from prose, and do not include the staging evidence run, production verification
runs, post-fix failures, deployments, schedules, task runs, blocks, or application rows.

The cleanup command must be project-owned, dry-run-first, fix-time bounded, and independently
verifiable. For ts-prefect, use the maintained ticket-scoped command documented by the repository:

```text
uv run python -m scripts.prefect_ops.delete_ticket_flow_runs --ticket <ID>
```

That ts-prefect command requires the ticket tag/triage cluster recorded by its investigation
path. An explicit-ID-only ticket needs a project command that enforces exactly those IDs; do not
pretend the tag-based command covers untagged IDs.

`ticket-verify production` appends the artifact, activation boundary, execution, and
non-interactive arguments. If incident runs are attributed but no safe cleanup contract can be
normalized, stop before promotion with the exact contract repair; the run must not silently
complete while the ticket's resolved Prefect failures remain on the failure board.

### 5. Verify, clean, and complete production

`/ticket-verify production <ID>` owns the production verdict. After production behavior records
an exact `PASS`, that verifier dry-runs, scope-checks, and deletes the terminal pre-fix Prefect
incident runs attributed to the ticket. Cleanup never runs before production PASS.

Stop immediately only if a production deploy step or production behavior verification
fails/blocks, or CI repair reaches the explicit human-judgment gate. Success requires a
production verification artifact with exact `PASS`, independently verified incident cleanup when
the ticket attributed Prefect runs, and final `completed` status. If production passes but
deferred cleanup remains, report `prod_verified_needs_cleanup` rather than claiming completion;
its cleanup contract owns the next run.

## Terminal report

Load and apply `skills/references/terminal-outcomes.md` before reporting. Run the shared post-check
after the last lifecycle action and put exactly one large banner plus its confirmation/failure
block before the lifecycle-gate rows below. Only an exact production PASS, completed required
cleanup, a re-read canonical `completed` status, and a clean closeout audit may use
`# ✅ COMPLETED — READY TO CLOSE`. Staging-only success uses `# ✅ STAGING VERIFIED`; a deploy or
verification failure uses the environment-specific red-X banner.

Report one row for each lifecycle gate with command, result, PR/commit or flow-run identifier,
evidence artifact ID, and resulting ticket status. End with exactly one of:

- `COMPLETE` — production verification passed and the ticket is `completed` (targets `prod`/`full`);
- `STAGING VERIFIED` — target `staging` finished with exact staging `PASS`; next command is
  `/ticket-deploy <ID> prod`;
- `STOPPED` — include the failed/blocked/timing gate and exact next command or human decision.

Never report `full` success from a staging PASS alone.

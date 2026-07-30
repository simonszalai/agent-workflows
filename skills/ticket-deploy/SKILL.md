---
name: ticket-deploy
description: >-
  Deploy-and-verify phase for one standalone ticket. Takes a target argument — staging, prod,
  or full — and orchestrates the existing owners: auto-deploy (deploy mechanics), ticket-verify
  (evidence), ticket-promote (production landing + deploy). Self-heals routine CI failures and
  stops on behavior-verification failures, blockers, unsafe evidence triggers, genuine timing
  waits, or human-judgment decisions.
max_turns: 30
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

### Fresh deployment-owner boundary

The initial caller is a dispatcher only. Unless its packet explicitly says
`mode: deployment_owner`, it must not execute any deploy, promotion, verification, CI repair, or
remote mutation itself:

1. Load the ticket once with `detail="light", include_events=false`, then fetch only the exact
   artifact bodies named by that manifest. Hash every body. At minimum include the current
   `deployment_guide`.
2. Write one immutable packet of at most 16 KiB. It contains the ticket ID, normalized target,
   current head and working-tree identities, deployment-guide artifact ID and SHA-256,
   dependencies, evidence gates, lifecycle entry state, and required terminal return shape.
3. Record the light manifest read, exact artifact reads, and packet reference in a
   `workflow-ticket-context-check receipt` contract.
4. Create a `contract_profile: "bounded-owner"` envelope with `phase_name: "deployment"`,
   `fork_mode: "none"`, `owner_role: "deployment_owner"`, `dispatch_depth: 0`,
   `redispatch_allowed: false`, and
   `context_strategy: "light_manifest_exact_artifacts"`. Validate it before dispatch:

   ```text
   bin/phase-contract owner-dispatch <absolute-envelope-path>
   ```

5. Dispatch exactly one fresh owner and block once for its terminal result:

   ```text
   Agent(
     subagent_type="general-purpose",
     fork_turns="none",
     prompt="Use /ticket-deploy in deployment_owner mode. Read only the packet and envelope."
   )
   ```

Capture that result once and validate it with
`bin/phase-contract result <result-path> --dispatch <envelope-path>` before accepting it.
An invocation already marked `mode: deployment_owner` must verify the validated envelope, then
continue with the process below. It must never dispatch another deployment owner. This marker and
the envelope's `redispatch_allowed: false` are the recursion guard.

All CI and Prefect waits must use one bounded waiter process. In Conductor, dispatch only the wait
to one fresh leaf with `fork_turns: "none"`, then block once for its terminal result. Never poll a
resumable process session or re-sample the parent model while the external run is pending.

For each activated revision, `/ticket-verify` compiles all finalized rows into exactly one
`bin/deploy-verify-controller` manifest. This orchestrator consumes only its terminal JSON receipt
or bounded timeout/resume result. It must not run a second ad-hoc verifier, reattest identity
outside the controller, or split one revision's rows across model turns. Unsupported evidence
surfaces fail closed; all existing deploy, auth, exact-transport, safety, cleanup, and evidence
predicates remain in the manifest.

Before any high-cardinality external producer required by a deployment guide (cohort, soak,
per-record verifier, repeated SSH/API session, or equivalent), run one real unit through the
**exact final transport and execution path**: same argv/options, identity source, remote
interpreter, request/protocol framing, target mapping, timeouts, and cleanup. A dry-run, a different
ad-hoc health command, or a canary that bypasses the producer transport does not satisfy this gate.
Require gradeable output and preserve a bounded credential-free failure class/stderr excerpt before
spending the full work/connection budget. If the canary fails, stop before fan-out; never infer that
client authentication failed merely because a later SSH host-key/update phase failed.
This gate is satisfied by an exact-path canary already executed and recorded (run id +
parameters) for the same producer, revision, and parameter shape — for example by
`/ticket-verify` §3a earlier in this run. Cite the recorded run id instead of re-running it.

This skill authorizes autonomous repair of mechanical CI failures throughout staging and
production delivery. Follow `ci-self-heal.md`: inspect terminal logs, fix routine repository
failures, re-run focused + final-tree validation and review, commit/push, wait on the new tree,
and resume automatically. A red CI check alone is never a terminal outcome.

## Process

### 1. Resolve and resume safely

Load the standalone ticket once with `detail="light", include_events=false`. Cache the artifact
manifest, including any `deferred_cleanup` or legacy flow-run-cleanup artifact. Refuse epic
members, source tickets, abandoned tickets, and ambiguous repository scope.

Before the first remote mutation, compile the cached FINALIZED guide into the machine contract
defined by `/create-deployment-guide` and run:

```text
deployment-guide-contract --environment <staging|production|full> <absolute-contract-path>
```

This validation must precede `/auto-deploy`, `/ticket-promote`, schema/config mutation, evidence
producer triggers, and every other remote mutation. An invalid, DRAFT, stale, or incomplete
contract is a hard stop. Never repair the guide after mutation and retroactively call it valid.

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

Do not resume past `BLOCKED`, `NEEDS_MORE_TIME`, `PASS (contract-missing)` (unless its recorded
`risk_tier` is `tiny_safe` per ticket-verify §2a), missing evidence, or a stale evidence artifact
merely because the lifecycle status appears later than expected. An evidence artifact is *stale*
only when scope code landed on the environment's branch after the artifact's activation boundary,
or its `staging_head_sha` no longer contains the promoted commits; age alone is not staleness.

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

- `FAIL`: require a persisted failure class before any new revision. Only `code_defect` may enter
  the normal product build/review/redeploy loop. Route `verifier_defect`, `environment_capacity`,
  `external_observation`, and `invalid_evidence` to their bounded verifier/environment/
  observation/evidence owners without mutating product code. `unknown` fails closed and stops.
- `BLOCKED`: stop with the exact missing deployment, unsafe trigger, or contract repair.
- `NEEDS_MORE_TIME`: stop with the recorded awaited condition and exact resume command. It is
  valid only when a live producer or already-triggered downstream process will produce evidence
  by waiting.
- `PASS (contract-missing)`: stop; a derived contract is not production-promotion evidence —
  unless the evidence artifact records `risk_tier: tiny_safe` (ticket-verify §2a), in which case
  treat it as exact `PASS`.
- exact `PASS`: require the persisted staging evidence artifact. For target `staging`, report and
  stop here (the ticket rests at `staging_verified` for an explicit `prod`/`full` continuation).
  For target `full`, continue to §4.

Track staging revision sequence by activation key + evidence-contract version. After two staging
revisions for the same pair, enter stabilization mode: persist the latest failure class and exact
contract delta before any third code mutation. Same-risk follow-ups use one delta builder and one
delta reviewer; a newly crossed security, auth, runtime-protocol, migration, destructive-data, or
browser-patch boundary resets to the full/heavy review path with its specialist coverage. Rotation
continues these gates from the immutable checkpoint; it never skips them.

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
`landing-policy.md`). Before deploying, run the landing-policy risk classification against the
actual diff — reuse a `risk_tier` classification already recorded for the same diff SHA
(ticket-verify §2a) instead of re-deriving it. If the change is **not** tiny/safe — schema, auth, encryption, deploy-config, new
infrastructure/cost, wide blast radius, or material uncertainty — **stop and ask the user for
confirmation** before any production mutation; report exactly what makes it risky and recommend
the staging path. With a tiny/safe classification or explicit user confirmation, run
`/auto-deploy <ID> production`, then `/ticket-verify production <ID>` (§5).

Direct-to-main never leaves staging behind: `/auto-deploy production` includes the mandatory
main→staging back-sync (its Phase 8b, per `landing-policy.md`) — the same change is merged into
`staging` and deployed there in the same run. Confirm the back-sync row in auto-deploy's
verification checklist before reporting the direct-production leg complete.

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

Load and apply `skills/references/terminal-outcomes.md` before reporting. When `/ticket-deploy`
is the outermost run, run the shared post-check after the last lifecycle action and put exactly one
large banner plus its confirmation/failure block before the lifecycle-gate rows below; under
`/ticket-flow`, relay the result and let it own the post-check. Only an exact production PASS,
completed required cleanup, a re-read canonical `completed` status, and a clean closeout audit
may use
`## ✅ COMPLETED — READY TO CLOSE`. Staging-only success uses `## ✅ STAGING VERIFIED`; a deploy or
verification failure uses the environment-specific red-X banner.

Report one row for each lifecycle gate with command, result, PR/commit or flow-run identifier,
evidence artifact ID, and resulting ticket status. End with exactly one of:

- `COMPLETE` — production verification passed and the ticket is `completed` (targets `prod`/`full`);
- `STAGING VERIFIED` — target `staging` finished with exact staging `PASS`; next command is
  `/ticket-deploy <ID> prod`;
- `STOPPED` — include the failed/blocked/timing gate and exact next command or human decision.

Never report `full` success from a staging PASS alone.

---
name: ticket-deploy
description: >-
  Deploy-and-verify phase for one standalone ticket. Takes a target argument — staging, prod,
  or full — and orchestrates the existing owners: auto-deploy (deploy mechanics), ticket-verify
  (evidence), ticket-promote (production landing + deploy). Self-heals routine CI failures and
  autonomously repairs staging verification failures through fresh bounded owners, while stopping
  on exhausted repair budgets, unsafe evidence triggers, genuine timing waits, or human decisions.
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

Consume the ticket's persisted intensity and `ticket-run-budget-v1` receipt. If an older ticket has
neither, classify it once from the current plan/diff and create the receipt before the first model
dispatch. Never default an unclassified ticket to `heavy` merely to obtain the larger repair cap.
The durable receipt is the exact ticket `learning_report` whose title is
`run-budget <activation_key>` and metadata `kind` is `ticket_run_budget`; load/update only that
artifact with optimistic concurrency. A local scratch copy is not resume state.

### Fresh deployment-owner boundary

**Already-fresh callers skip the dispatch.** When the invoking agent is itself a fresh
`fork_turns: "none"` agent dispatched for this ticket's deploy phase with a bounded checkpoint
packet (the normal `/ticket-flow` §3→§4 hand-off), it **is** the deployment owner: it declares
`mode: deployment_owner`, verifies that its session id is the latest persisted `deployment_owner`
environment reservation for the active receipt, records that in its envelope, and continues with
the process below. A missing/mismatched reservation is a hard stop, not permission to self-allocate.
Spawning a second owner from an agent that is already fresh and bounded doubles the rollouts and
the wait for zero isolation gain. The dispatcher path below exists for long-lived callers —
interactive sessions and orchestrators still carrying prior-phase history.

The initial long-lived caller is a dispatcher only. Unless its packet explicitly says
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
   `context_strategy: "light_manifest_exact_artifacts"`. Include `run_budget` with
   `budget_scope: "environment"`, `session_role: "deployment_owner"`, and the exact persisted prior
   receipt inline. Validate it before dispatch:

   ```text
   bin/phase-contract owner-dispatch <absolute-envelope-path>
   ```

   `owner-dispatch` emits the next `run_budget_receipt`. Update the durable receipt artifact using
   `expected_updated_at` before dispatch; on a compare-and-set conflict, do not spawn from the stale
   reservation.

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

`owner-dispatch` is also the deployment owner's environment-budget reservation; it is not a
substitute for later reservations. Before a fresh deterministic-waiter or verifier session, validate
a `ticket-dispatch` envelope for `phase_name: "deploy_verify"`, the corresponding
`session_role`, and the same inline prior receipt, then persist its emitted receipt with
`expected_updated_at` before spawn. Before any repair owner, reserve
`session_role: "repair_owner"` and `starts_repair_cycle: true`: code changes consume `delivery`,
while verifier/evidence/capacity repairs consume `environment`. The original deployment owner
is not respawned: the bounded repair owner also performs any invalidated health/deploy mechanics,
then returns before a fresh waiter/verifier grades it. Those wait/verifier sessions consume the
environment bucket in order. A failed launch after persistence still consumes its reservation. No
role, rotation, retry, resumed invocation, or owner boundary bypasses this sequence.

All CI and Prefect waits must use one bounded waiter process. In Conductor, dispatch only the wait
to one fresh leaf with `fork_turns: "none"`, then block once for its terminal result. Never poll a
resumable process session or re-sample the parent model while the external run is pending.
The deployment owner returns the wait contract and stops watching before that leaf starts. No
parent watcher, backup timer, fallback agent, or second waiter may observe the same condition.

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

For staging, also load `../references/staging-autonomy.md`. This invocation is the mutation owner:
documented bounded staging fixtures, seeds, registrations, and other disposable prerequisites are
standing-authorized. Repair them and continue instead of returning a command for the user to run.

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
producer triggers, and every other remote mutation. If a staging contract is invalid, DRAFT, stale,
or incomplete but the accepted source/plan supplies the missing fact, route `owner_repair`,
re-finalize it, and validate again before mutation. Stop only when the repair needs missing human
intent. Never repair the guide after mutation and retroactively call it valid.

Enter from lifecycle truth rather than repeating completed legs:

| Current status | `staging` | `prod` | `full` |
|---|---|---|---|
| built, branch pushed (pre-deploy) | §2 | direct-production gate (§4a) | §2 |
| `to_verify_staging` | §3 | stop: staging verify pending — run `staging` or `full` | §3 |
| `staging_verified` | report already verified; stop | §4 | §4 |
| `to_verify_prod` | n/a | §5 verification only | §5 verification only |
| `prod_verified_needs_cleanup` | n/a | `/ticket-verify production <ID>` | same |
| `completed` | report already complete; stop successfully | same | same |
| `verify_staging_failed` | resume §3 from the persisted failure class and repair-round counter | stop: staging repair pending | resume §3 |
| `verify_prod_failed` | n/a | resume §5's contract-repair loop when the persisted class qualifies (verifier_defect/invalid_evidence, empty product-failure field); otherwise stop at the production safety boundary with the persisted remediation route | same |

Do not resume past `NEEDS_MORE_TIME`, `PASS (contract-missing)` (unless its recorded `risk_tier` is
`tiny_safe` per ticket-verify §2a), missing evidence, or a stale evidence artifact merely because
the lifecycle status appears later than expected. A `BLOCKED` verdict resumes only when its repair
packet classifies the precondition as agent-resolvable; otherwise it remains a stop. An evidence
artifact is *stale* only when scope code landed on the environment's branch after the artifact's
activation boundary, or its `staging_head_sha` no longer contains the promoted commits; age alone
is not staleness.

### 2. Deploy to staging (`staging` and `full`)

Run `/auto-deploy <ID> staging`. Its pre-CI local parity gate must extract and run every locally
reproducible GitHub Actions step, batch-repair the complete failure inventory, and prove a passing
exact-tree receipt before PR creation or the first CI wait. Require successful staging deployment mechanics and final
`to_verify_staging` status. If it returns because CI is red, enter the shared CI self-heal loop
and resume at the interrupted phase after CI passes. If it returns a staging-autonomy packet,
consume `staging_safe`/`owner_repair` and retry the invalidated phase. Relay and stop only at a
proved legitimate-stop boundary.

### 3. Produce and verify staging evidence (`staging` and `full`)

Run:

```text
/ticket-verify staging <ID> --no-promote --produce-evidence
```

Handle the verdict as follows:

- `FAIL`: require a persisted failure class, investigation artifact, and machine-readable repair
  packet before another attempt. Enter the staging repair loop below rather than returning the
  failure to the user.
- `BLOCKED`: require the verifier's staging-autonomy repair packet. Execute `staging_safe` actions
  directly, and route `owner_repair` through the bounded repair owner, then retry. Stop only for a
  proved `human_required` or `external_wait` classification. A missing documented synthetic fixture
  is not a reason to return control to the user.
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
contract delta before any third code mutation. Same-risk follow-ups use one repair owner and no
re-review; a newly crossed security, auth, runtime-protocol, migration, destructive-data, or
browser-patch boundary resets to the full/heavy review path with its specialist coverage. Rotation
continues these gates from the immutable checkpoint; it never skips them.

#### Staging repair/redeploy/reverify loop

The outer `/ticket-deploy` dispatcher owns this loop. `/ticket-verify` diagnoses and persists truth;
it never recursively invokes another deployment owner, and a repair cycle does not spawn a second
deployment owner.

1. Persist `repair_round`, activation key, evidence-contract version, failed evidence artifact,
   investigation artifact, failure class, exact failing rows, and prior attempted fix. The initial
   verification is round 0. The repair counter is shared with local build/review repair: permit
   **one total repair round** for `direct`/`standard` and three only for explicit `heavy`, so zero
   remain here if an ordinary local repair already consumed it. Each environment repair is followed
   by one new verification attempt. Persist the counter and chained
   `ticket-run-budget-v1` receipt across rotations and resumed invocations; neither a new agent nor a
   new `/ticket-flow` turn resets it.
2. For every agent-resolvable `FAIL` or `owner_repair` BLOCKED, dispatch exactly one fresh
   `fork_turns: "none"` repair subagent with the bounded failure packet. Route by class:
   `code_defect` through the normal repair owner, canonical local health gate, commit/push, and
   deploy (no same-risk re-review); `verifier_defect` to the verifier owner;
   `environment_capacity` to the environment owner;
   `external_observation` to the observation/provider owner; `invalid_evidence` to the evidence-
   contract owner; `unknown` to the exact missing-evidence owner when known. Only an already-`heavy`
   run may spend one separate investigator session after the verifier's in-session diagnosis; an
   ordinary run preserves `unknown` and stops rather than adding hidden fanout.
   The repair owner changes only its assigned surface and may run required local health/deploy
   mechanics, but it never produces the environment-verification verdict for its own fix.
   For a `staging_safe` BLOCKED packet, the deployment owner instead executes the exact documented
   environment action directly under `staging-autonomy.md`, records the before/postcondition and
   cleanup/rollback receipt, and clears blocker metadata only after proof. This safe operational
   lane allows at most three distinct actions per top-level run. It does not count against the
   product-code repair round. Do not dispatch another model merely to run a known bounded command.
3. Re-run every lifecycle stage invalidated by the repair. Product/config changes reuse the prior
   review disposition when same-risk, or run full heavy review only after a new boundary; they still
   require a final-tree health PASS, commit/push, and staging redeploy before verification. Verifier
   or evidence-only repairs reuse the activated product revision only when identity proves it is
   still current. Then invoke `/ticket-verify staging <ID> --no-promote --produce-evidence` once.
4. On another failure, persist the delta. Continue only when the selected intensity still has both
   a repair cycle and model-session capacity. Otherwise return `BUDGET_EXHAUSTED`; context rotation
   and a fresh user turn do not add capacity.
5. Stop successfully on exact `PASS`. Stop unsuccessfully on budget exhaustion, `human_required`,
   or `external_wait`. Before emitting `BLOCKED`, validate that no `staging_safe` or `owner_repair`
   packet remains within budget and include the staging-autonomy receipts. Report every attempted
   delta when the cap is exhausted.

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

A production verification FAIL is triaged before it stops the run. `/ticket-verify`'s §9d
investigation classifies every failed row; route on that classification:

- **Verifier/contract defect** (every failed row `verifier_defect` or `invalid_evidence`,
  `confirmed` or `likely` with reproducible evidence, product-failure field empty): enter the
  production contract-repair loop per verify-failure-investigation §3a-prod. Dispatch one fresh
  `fork_turns: "none"` repair subagent that changes **only** the verifier/evidence-contract
  surface — re-finalize the `deployment_guide` contract with the recorded revision reason — then
  re-run `/ticket-verify production <ID>` against the already-live revision. No product code,
  redeploy, or environment mutation is permitted in this loop; a repair that would need any of
  those disqualifies the path. The selected intensity's persisted repair/session caps apply
  (production verification failures share the same `repair_round` and run-budget receipt).
- **Anything else** — any `code_defect`, `environment_capacity`, `external_observation`,
  `unknown`, mixed classification, or non-empty product-failure field: stop at the production
  safety boundary with the persisted remediation route.

Stop immediately only if a production deploy step fails/blocks, a production behavior
verification failure does not qualify for the contract-repair loop above (or exhausts its
rounds), or CI repair reaches the explicit human-judgment gate. Success requires a
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

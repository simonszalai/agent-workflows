---
name: ticket-deploy
description: >-
  Deploy-and-verify for one standalone ticket. Takes a target argument — staging, prod, or
  full — and owns the deploy mechanics (PR, CI, merge, deploy steps), then hands evidence
  collection to /ticket-verify and production landing to /ticket-promote. Repairs routine CI
  and staging failures autonomously; stops on no-progress, unsafe evidence, or human decisions.
max_turns: 150
---

# Ticket Deploy

Run the deploy+verify leg of one standalone ticket. This skill owns deploy mechanics itself and
delegates only the two things with dedicated owners:

- `/ticket-verify` — behavior/evidence verification, verdicts, evidence artifacts
- `/ticket-promote` — staging→main landing + production deploy steps

## Usage

```text
/ticket-deploy F0123 staging   # deploy to staging + verify staging; stop there
/ticket-deploy F0123 prod      # production leg only (status-aware, see below)
/ticket-deploy F0123 full      # staging leg, then on exact staging PASS the production leg
```

The target argument is required: `staging`, `prod` (alias `production`), or `full`.

Standalone tickets only. Epic step tickets land on their milestone integration branch and are
gated by `/ticket-verify --epic`; refuse them here and say so.

## Authorization

Invoking with `prod` or `full` is the explicit human authorization for production
promotion/deploy (after an exact staging `PASS` where one exists). Never infer that
authorization from a `staging` invocation. `staging` and `full` also authorize
`/ticket-verify staging --produce-evidence` (one safe bounded producer run under ticket-verify's
contract; never a deploy, schedule enablement, backfill, or unbounded pipeline run).

## References

Read and follow:

- `../references/ticket-lifecycle.md`
- `../references/staging-autonomy.md` (staging legs)
- `../references/environment-topology.md`
- the called skills' own boundaries

## Process

### 1. Resolve and resume safely

Load the ticket once with `detail="light", include_events=false`, then fetch only the artifact
bodies you need — at minimum the current `deployment_guide`. Refuse epic step/source tickets,
abandoned tickets, and ambiguous repository scope. If the guide is DRAFT, stale, or missing a
fact the accepted plan supplies, repair and re-finalize it **before** any remote mutation —
never after, retroactively calling it valid.

Enter from lifecycle truth rather than repeating completed legs:

| Current status | `staging` | `prod` | `full` |
|---|---|---|---|
| built, branch pushed (pre-deploy) | §2 | direct-production gate (§4a) | §2 |
| `to_verify_staging` | §3 | stop: staging verify pending | §3 |
| `staging_verified` | report already verified; stop | §4 | §4 |
| `to_verify_prod` | n/a | §5 verification only | same |
| `prod_verified_needs_cleanup` | n/a | `/ticket-verify production <ID>` | same |
| `completed` | report already complete; stop | same | same |
| `verify_staging_failed` | resume §3 repair loop from the persisted failure evidence | stop: staging repair pending | resume §3 |
| `verify_prod_failed` | n/a | stop at the production safety boundary with the persisted remediation route | same |

A staging `BLOCKED` artifact classified `staging_safe`/`owner_repair`/`external_wait` is a
resumable checkpoint, not a user-interaction gate. Evidence is *stale* only when scope code
landed after the artifact's activation boundary; age alone is not staleness.

### 2. Deploy to staging (`staging` and `full`)

1. Run the repo's full local health gate (typecheck, tests, lint as the project defines) on the
   final tree before pushing. Fix the complete failure inventory first.
2. Push the branch, open a PR against `staging`, and wait for CI as one blocking call:
   `wait-ci <pr_number> --timeout 540`. Never poll `gh` in a loop.
3. **CI self-heal:** a red check alone is never terminal. Inspect the failing job's logs, fix
   routine repository failures (lint, types, flaky-but-reproducible tests, lockfiles, generated
   files), re-run local health, push, and wait on the new tree. Stop only for failures that need
   a human decision (product intent, secrets, infrastructure).
4. Merge, then run the staging deploy steps from the ticket's `deployment_guide` and the project
   deploy config — execute each automatable step yourself and verify its success before the
   next. Include any repo-required schema-deploy artifact (Atlas reviewed plan, migrations).
5. Set `to_verify_staging`.

Staging mutations follow `staging-autonomy.md`: documented bounded fixtures, seeds, and
registrations are standing-authorized — repair and continue instead of returning a command for
the user to run.

### 3. Verify staging (`staging` and `full`)

Run:

```text
/ticket-verify staging <ID> --no-promote --produce-evidence
```

Handle the verdict:

- **exact `PASS`**: require the persisted evidence artifact. Target `staging`: report and stop
  (the ticket rests at `staging_verified` for an explicit `prod`/`full` continuation). Target
  `full`: continue to §4.
- **`PASS (contract-missing)`**: stop — a derived contract is not production-promotion
  evidence — unless the artifact records `risk_tier: tiny_safe`, which counts as exact `PASS`.
- **`FAIL`**: enter the repair loop below rather than returning the failure to the user.
- **`BLOCKED`**: consume the repairability classification. Execute `staging_safe` actions
  directly, fix `owner_repair` items yourself, run the deterministic waiter for
  `external_wait`. Stop only for proven `human_required` or `agent_incapable`.
- **`NEEDS_MORE_TIME`**: require a proven live `external_wait`, wait on it with a bounded
  deadline (`wait-ci`, `wait-prefect-flow`, or the operation's own terminal predicate), and
  continue from the terminal result.

**Staging repair loop.** For an agent-resolvable `FAIL`: diagnose from the verifier's evidence,
fix the assigned surface (code defect → fix + local health + redeploy; verifier/contract defect →
re-finalize the contract, no redeploy), then re-run the verify command once. Permit repair rounds
only while each round makes concrete, stateable progress against the previous failure; when a
round changes nothing, stop and report every attempted delta. Never loop on hope.

### 4. Production leg — promote staging-verified work (`prod` and `full`)

Precondition: latest staging evidence is an exact `PASS` (or `tiny_safe` contract-missing PASS).

Run `/ticket-promote <ID>`. This invocation satisfies the human-authorization requirement but
waives none of ticket-promote's schema, isolation, parity, CI, or deploy gates. It lands the
work on `main`, runs production deploy steps, sets `to_verify_prod`, and hands off to
`/ticket-verify production <ID>` (§5). Apply the same CI self-heal loop to promotion PR checks.

### 4a. Production leg — direct-to-production (never staged)

Only for tiny safe standalone work. Classify the actual diff first: schema, auth, encryption,
deploy-config, new infrastructure/cost, wide blast radius, or material uncertainty means **not**
tiny/safe — stop and ask the user for confirmation before any production mutation, naming
exactly what makes it risky and recommending the staging path. With a tiny/safe classification
or explicit confirmation: PR against `main`, CI, merge, production deploy steps, then
`/ticket-verify production <ID>`.

Direct-to-main never leaves staging behind: merge the same change into `staging` and deploy it
there in the same run, and confirm that back-sync before reporting the leg complete.

Production mutation boundary: prefer audited MCP/server-side operations; never write the
production database from a local shell. Authenticated production CLI mutations with no remote
route run through `bin/redacted-exec -- <documented command>`.

### 5. Verify and complete production

`/ticket-verify production <ID>` owns the production verdict, deferred cleanup, and
`completed`. Relay its terminal result. If it fails with a pure verifier/contract defect
(product-failure evidence empty), re-finalize the contract and re-verify against the already-live
revision — no product code, redeploy, or environment mutation in that loop. Any other failure
class stops at the production safety boundary with the persisted remediation route. If
production passes but deferred cleanup remains, report `prod_verified_needs_cleanup` rather
than claiming completion.

## Terminal report

One row per lifecycle gate: command, result, PR/commit or run identifier, evidence artifact ID,
resulting ticket status. End with exactly one of:

- `COMPLETE` — production verification passed and the ticket is `completed` (`prod`/`full`);
- `STAGING VERIFIED` — target `staging` finished with exact staging `PASS`; next command is
  `/ticket-deploy <ID> prod`;
- `STOPPED` — the failed/blocked/timing gate and the exact next command or human decision.

Never report `full` success from a staging PASS alone. Every PASS line must cite concrete
evidence; end with a "Not verified:" line for anything claimed but not exercised in this run.

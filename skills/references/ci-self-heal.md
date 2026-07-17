# CI self-healing contract

Autonomous delivery workflows own routine CI repair. A failed check is evidence to investigate,
not an automatic terminal stop.

## Loop

1. Wait once for the current workflow/check set to reach a terminal result. In Conductor, delegate
   only the bounded `wait-ci` process to a fresh `fork_turns: "none"` leaf and block once.
2. Fetch the failed GitHub Actions job logs. Classify every failure before editing.
3. Handle **transient infrastructure** (runner/network/cache/service startup) by rerunning only the
   failed jobs once, then wait once on the new run.
4. Handle **mechanical repository failures** autonomously: unit/integration/e2e failures, lint,
   formatting, type errors, generated artifacts, lockfile drift, compatible dependency/security
   updates, deterministic migration/plan validation, and equivalent failures with a code-grounded
   fix.
5. Apply the smallest fix, run the focused failing command locally, then run the owning workflow's
   required review and final-tree health gate. Commit all workspace changes, push, and wait once on
   the new tree.
6. Repeat while each cycle makes concrete progress. Treat a changed failure signature as a new
   diagnosis, not proof that the loop is stuck.

## Human-judgment stop gate

Stop only when repair requires a genuine decision or unavailable authority, including:

- changing product behavior, public contracts, data semantics, or an agreed plan;
- adding a new vulnerability/audit ignore, accepting security risk, or choosing an incompatible
  dependency upgrade;
- destructive/schema/data action not already authorized by the ticket contract;
- unavailable credentials, permissions, external manual deployment, or a persistent third-party
  outage;
- three consecutive repair cycles with the same normalized failure signature and no new evidence
  or progress.

Never bypass, disable, mark-optional, or silently ignore a required check to make CI green. Never
rewrite unrelated code just because a broad check exposed a pre-existing failure; fix it only when
the repair is mechanical and low-risk, otherwise use the human-judgment gate.

## Evidence and resume

Record each cycle's failed check, root cause, files changed, local command result, commit SHA, and
terminal CI result. Keep the ticket in its active lifecycle state during repair. After green CI,
resume the interrupted deploy/promotion phase automatically; do not require another user command.

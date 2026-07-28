# CI self-healing contract

Autonomous delivery workflows own routine CI repair. A failed check is evidence to investigate,
not an automatic terminal stop.

## Pre-push local CI parity gate

GitHub Actions runs are the expensive outer loop; the goal is that the first push is usually
green. Before the **first** push of any branch that will trigger CI, and before **every** re-push
inside the repair loop:

1. Run `bin/ci-local --run` at the exact tree being pushed. It extracts the repo's own workflow
   `run:` steps (skipping setup actions) and executes them locally; a repo-local `bin/ci-local`
   or `scripts/ci-local` override wins automatically.
2. Treat the tool as scaffolding, not an oracle — apply judgment to its SKIPs:
   - Jobs skipped for `services:` (e.g. Postgres): if the service is already available locally,
     force the job with `--run --job <name>`; otherwise note the gap.
   - Steps skipped for `${{ ... }}` expressions or non-setup actions: reproduce the intent by
     hand when cheap (substitute `github.base_ref` etc.), otherwise accept CI as the authority
     for that job and say so in the push evidence.
   - If an extracted command fails for a purely local-environment reason (missing local tool,
     stale local cache), fix the local environment or adapt the command on the fly — do not
     "fix" repo code to satisfy a broken local setup, and never weaken the check itself.
3. Push only after every locally reproducible job passes. Record which jobs passed locally and
   which were skipped as not locally reproducible.

A local parity PASS never replaces the real check set; it only makes round-trips rare. Deploy-only
jobs (branch-gated migrate/release jobs) are out of scope for the local gate.

## Loop

1. Wait once for the current workflow/check set to reach a terminal result. In Conductor, dispatch
   only the exact bounded `wait-ci` command immediately to one fresh `fork_turns: "none"` leaf and
   block once. The parent never starts or polls a resumable process, polls the leaf, substitutes
   `gh ... --watch`, or performs repeated GitHub status reads.
2. Fetch the failed GitHub Actions job logs. Classify every failure before editing.
3. Handle **transient infrastructure** (runner/network/cache/service startup) by rerunning only the
   failed jobs once, then wait once on the new run.
4. Handle **mechanical repository failures** autonomously: unit/integration/e2e failures, lint,
   formatting, type errors, generated artifacts, lockfile drift, compatible dependency/security
   updates, deterministic migration/plan validation, and equivalent failures with a code-grounded
   fix.
5. Apply the smallest fix, run the focused failing command locally as the diagnostic, then run the
   full pre-push local CI parity gate (above) so one re-push clears every locally reproducible
   failure instead of discovering them one Actions run at a time. Run the owning workflow's
   required review and final-tree health gate, commit all workspace changes, push, and wait once
   on the new tree.
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

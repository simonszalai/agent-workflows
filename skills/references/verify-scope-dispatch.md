# Ticket Verify — Scope Selection and Multi-Scope Dispatch

Load this reference only for default-queue mode, epic/milestone mode, or a run containing more
than one scope. Explicit single-ticket verification does not need it.

## Default queue

Without explicit ticket IDs, select the target environment's union:

- `staging`: `to_verify_staging` and `verify_staging_failed`;
- `production`: `to_verify_prod`, `verify_prod_failed`, and
  `prod_verified_needs_cleanup`.

Re-attempt failed verification tickets instead of stranding them. If no fix landed after the
recorded activation boundary, state that the rerun is expected to reconfirm the prior failure.
Cleanup holders remain subject to their deferred-cleanup contract and blocker re-check.

Also include pending epic gates when the epic itself is in the environment's verification status
or one of its step tickets is. Discover them with `list_epics` plus the selected step tickets.
Verifying the parent gate subsumes its step tickets; never verify a covered step twice.

Skip abandoned, completed, and absorbed/source tickets. Do not verify an epic step loosely: route
it through its parent epic gate.

## Explicit epic or milestone

1. Load `get_epic(project, epic_id)` with artifacts, milestones, steps, events, and blockers.
2. With `--milestone`, restrict scope to that milestone's step tickets and gate package.
3. Without `--milestone`, verify the current/final gate across completed milestones.
4. Load `verify-epic-gates.md` and follow its persistence and lifecycle rules.

## Parallel verifier dispatch

Build one queue-wide evidence plan before dispatch. Normalize each contract row by environment,
authoritative surface, activation boundary, query/command, parameters, and interpretation. Coalesce
only rows one execution can prove without broadening tenant, identifier, time, or permission scope.

- Group compatible database, log, flow/deployment, browser, and provider checks.
- Spawn one bounded verifier per independent group, not one per ticket. Use
  `fork_turns: "none"` and provide the exact command/query, payload cap, activation boundary, and
  `scope -> evidence row IDs -> expected interpretation` mapping.
- Prefer one bounded keyed query when scopes share a surface but use different predicates.
- Run independent groups in one foreground parallel batch; never background work required for
  synthesis.
- The orchestrator computes verdicts, persists artifacts, and changes statuses. Verifiers never
  mutate ticket state or execute canary/cleanup mutations.

Coalescing saves execution, not evidence obligations. Every scope retains its own mapped verdict
and evidence artifact. One scope's failure must not contaminate unrelated mappings.

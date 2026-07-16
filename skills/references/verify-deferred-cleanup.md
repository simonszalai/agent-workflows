# Verify: Deferred post-verification cleanup

On-demand reference for `ticket-verify/SKILL.md`. Load this when a `deferred_cleanup` artifact
exists, a legacy flow-run-cleanup artifact exists, or a production bug ticket structurally
attributes Prefect incident flow runs. Section numbers (§2, §3, §4, §5, §9a) refer to sections in
`ticket-verify/SKILL.md`.

## Ticket-attributed Prefect incident cleanup preflight

On a production bug-ticket verification, inspect the already-loaded artifact manifest plus the
bounded source/investigation context for Prefect flow runs explicitly attributed to the incident
that created the ticket. Recognized structured attribution is limited to:

- a legacy flow-run-cleanup artifact containing a ticket tag or triage cluster;
- a ticket tag plus flow names, terminal failure states, and an error signature recorded by triage;
- exact flow-run IDs explicitly labeled as the original incident/triggering failures.

Do not regex every UUID from ticket prose. Exclude staging canary/evidence runs, production
verification runs, post-fix failures, task-run IDs, deployment IDs, and any active/nonterminal run.
The cleanup target is terminal Prefect **flow-run history only**; never delete flows, deployments,
schedules, blocks, artifacts, or application rows under this cleanup kind.

When structured attribution exists, ensure one parent `deferred_cleanup` artifact exists with
`cleanup_kind="flow_run_cleanup"`. Normalize a legacy artifact in place rather than creating a
duplicate. Preserve its ticket tag, flow names, states, error signature, triage time, and explicit
run IDs. Set the production activation boundary from §4 as the fix-time ceiling so post-fix failures
remain visible and fail verification instead of being swept away.

Use the repository's maintained ticket-scoped cleanup command. It must support dry-run, an artifact
input, fix-time enforcement, exact target reporting, and non-interactive execution. Example for
ts-prefect:

```text
uv run python -m scripts.prefect_ops.delete_ticket_flow_runs --ticket <ID>
```

The verifier appends `--artifact`, `--fix-time`, `--execute`, and the documented non-interactive
flag only after production behavior has recorded exact `PASS`. Persist the incident membership,
dry-run target IDs/count, and before state in verification evidence before deletion because Prefect
logs and run metadata disappear with the run.

If structured incident attribution exists but the cleanup command, signature/scope, fix-time, or
independent before/after check is missing, do not silently treat the ticket as cleanup-free. Record
production behavior PASS, move it to `prod_verified_needs_cleanup`, and block on the exact cleanup
contract repair. If there is no structured incident-run attribution, do not invent cleanup from
unrelated run IDs.

## 10. Deferred post-verification cleanup (production PASS only)

Some tickets carry a cleanup action that must run only once the fix is confirmed live in
production — never before. This is the single mutation ticket-verify may perform, and only after
a `PASS` verdict has been recorded for that ticket. Like the bounded canary trigger, it is
executed by the orchestrator itself — never delegated to a (read-only) verifier agent.

The generic contract is a **`deferred_cleanup` artifact**. (The old `flow-run-cleanup` artifact
name is retired; flow-run deletion is now just a `deferred_cleanup` with
`cleanup_kind="flow_run_cleanup"`.)

```json
{
  "cleanup_command": "<command; run with --artifact <temp-file> --fix-time <activation boundary §4> --execute plus any documented non-interactive flags (e.g. --yes)>",
  "scope_manifest": ["<exactly what the command may touch: tables, deployments, paths, ids>"],
  "reversibility": "reversible | destructive (missing/unknown => destructive)",
  "data_criticality": "noncritical | critical (missing/unknown => critical)",
  "cleanup_kind": "<e.g. flow_run_cleanup, deployment_retirement, table_drop>",
  "trigger_condition": {"check_command": "<read-only; exit 0 = trigger true, non-zero = not yet>", "description": "<when this becomes safe>"},
  "soak_window": "<duration the effect must soak before final verification>",
  "evidence_contract": [{"command": "<read-only check>", "good": "<expected>", "bad-interpretation": "<what a bad output means>"}],
  "revert_ref": "<commit/artifact to restore>", "revert_command": "<optional explicit revert>"
}
```

Execution rules:

1. Fetch the artifact and write its JSON body to a temp file under the run-scoped scratch
   directory from §5; delete it as part of §9a cleanup.
2. **Dry-run first, independently checked:** run `cleanup_command` WITHOUT `--execute` and diff
   its declared targets against `scope_manifest` BEFORE any mutating run. Anything out of scope
   → ABORT here; never reach `--execute`.
3. Run `cleanup_command`, appending `--artifact <temp-file>`, `--fix-time <activation boundary
   from §4>`, `--execute`, and any documented non-interactive flags.
4. **Scope enforcement is not self-report alone:** after execution, re-diff reported effects
   against `scope_manifest` AND corroborate with the out-of-band read-only checks from
   `evidence_contract` (before/after inventory) rather than trusting the command's own counts.
   Any out-of-scope effect → ABORT/blocked, capture the diff into `blocked_context`, do not
   re-run. A command whose executed effects cannot be independently observed is not eligible for
   automatic destructive cleanup, whatever its label says.
5. Fold the command's reported counts into the verdict output.

**Automatic same-cycle path:** after production PASS, the orchestrator runs cleanup without
operator approval when either condition holds:

- it is concretely reversible (`revert_ref` or `revert_command` is present); or
- it is destructive but `data_criticality="noncritical"`, its dry-run yields an exact bounded
  target set wholly inside `scope_manifest`, and the before/after `evidence_contract` can
  independently observe every effect.

`flow_run_cleanup` that deletes only terminal Prefect flow-run history (run metadata/logs, not
deployments, schedules, blocks, artifacts, or application rows) is a built-in noncritical cleanup
kind. It is automatically eligible even when a legacy artifact omits `data_criticality`. Before
executing a legacy artifact, normalize it in place with `cleanup_kind="flow_run_cleanup"`,
`data_criticality="noncritical"`, the dry-run's exact run IDs as `scope_manifest`, and read-only
before/after checks as its `evidence_contract`. The command must enforce the ticket selector and
activation/fix-time boundary; otherwise leave the item blocked as an invalid cleanup contract.

Missing/unknown criticality remains critical for every other destructive cleanup kind. Those
items use the §10a approval-gated path. A `noncritical` label never bypasses dry-run, exact scope,
activation-boundary, or independent before/after enforcement.
Anything else is deferred in-place (§10a). A ticket/epic without a `deferred_cleanup` artifact or
structured incident-run attribution has no cleanup step, and a non-PASS verdict never triggers one.

## 10a. In-place cleanup holding status (production PASS only)

Every structured decommission/retirement follow-up identified during verification MUST stay on
the **same parent ticket/epic** as a `deferred_cleanup` artifact. Do **not** create a child
cleanup ticket by default. Prose-only follow-ups in learning_reports are a violation: normalize
them into the parent's `deferred_cleanup` artifact before changing status.

§10a runs BEFORE the parent is set `completed`:

1. Dedup/normalize: if equivalent cleanup is already represented by a parent
   `deferred_cleanup` artifact (`cleanup_kind` + scope), update it rather than duplicating it.
   Legacy child cleanup tickets may be read for context, but new work remains on the parent.
2. Set the parent status to `prod_verified_needs_cleanup`.
3. Set blocker metadata on the parent when appropriate:
   - `blocked_by="trigger_condition"` with `blocked_context.check_command` when the trigger is
     not yet true;
   - `blocked_by="approval"` for destructive cleanup that is critical/unknown or is not eligible
     for the bounded noncritical automatic path in §10;
   - `blocked_by="soak"` with `blocked_context={"soak_until": ...}` after cleanup execution if a
     soak window must elapse before final cleanup verification.

Cleanup holding lifecycle (same item, new status; see `ticket-lifecycle.md`):

- `to_verify_prod` production PASS + pending cleanup → `prod_verified_needs_cleanup`.
- `/ticket-verify production` includes `prod_verified_needs_cleanup` in its default queue; an
  explicit `/ticket-verify production <ID>` may target one holder. Either path evaluates the
  cleanup trigger/approval/soak from blocker metadata and the `deferred_cleanup` artifact.
- Trigger false: the §3 blocker-metadata refresh is the **only** permitted write.
- Trigger true + automatically eligible (§10): clear any stale approval/trigger blocker → run
  `cleanup_command` with scope enforcement → keep `prod_verified_needs_cleanup` with
  `blocked_by="soak"` if soaking is required, otherwise grade the cleanup `evidence_contract`.
- Destructive critical/unknown cleanup, or destructive cleanup that fails any automatic-safety
  precondition, remains `blocked_by="approval"`; this is an absolute no-run gate. Approval = an
  operator clears the blocker (optionally recording `blocked_context.approved_by`).
- Post-soak/final cleanup verification grades the artifact's `evidence_contract` — it IS the
  FINALIZED cleanup contract (§2) → `completed` | `verify_prod_failed` (revert =
  `revert_ref`/`revert_command`). A verify before `soak_until` must refuse completion
  (`NEEDS_MORE_TIME`).

Periodic sweep/supervisor adoption of due cleanup holders is a contract-consumer concern; this
skill guarantees explicit-invocation evaluation only.

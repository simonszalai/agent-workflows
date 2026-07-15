---
name: epic-flow
description: Fully autonomous epic orchestrator. Plans/splits, runs milestone flows that deploy and verify each staging gate, then promotes/deploys/verifies production when explicitly authorized.
max_turns: 800
---

# Epic Flow

End-to-end epic execution coordinator. Use this when the user asks to run an epic, execute an
entire epic, continue across milestones, or do it without further human intervention.

## Operating modes

`/epic-flow` has two modes:

- **Full-auto** — enabled by `--full-auto` or by an explicit user request like "execute the whole
  epic" / "without me". This mode is authorized to invoke milestone-flow, which itself deploys and
  verifies each staging gate, plus production promotion and final verification after all milestone
  gates pass.
- **Gate-stop** — enabled by `--stop-at-gates` or by an ambiguous/manual request. This mode plans,
  splits, and stops before invoking a milestone gate if the user has not authorized deploy/verify.
  Do not call `/milestone-flow` in gate-stop as a "build-only" substitute; milestone-flow is a
  deploy+verify command.

Never silently choose gate-stop when the user explicitly asked for a hands-off/full-auto epic.
Never advance to a later milestone until the current milestone's staging gate has passed.

## Usage

```text
/epic-flow E0007 --full-auto       # run the whole epic, including gates
/epic-flow E0007                   # infer full-auto only if the user's request authorized it
/epic-flow E0007 --staging-only    # stop after every milestone is staged and verified
/epic-flow E0007 --milestone M2    # run one milestone and its gate
/epic-flow E0007 --stop-at-gates   # plan/split/readiness only; stop before milestone-flow deploy+verify
```

## References

Read before acting:

- `../references/execution-economy.md`
- `../references/epic-lifecycle.md`
- `../references/conductor-multi-repo.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`

## Full-auto process

### 1. Load and normalize the epic

- Load `get_epic(project, epic_id)` with source tickets, step tickets, artifacts, events, and
  blockers.
- Cache that response/version as the orchestration snapshot and pass bounded milestone extracts to
  milestone-flow. Reload only after `/epic-plan`, `/epic-split`, or a completed milestone mutates
  the epic; do not re-read the unchanged full epic between routing decisions.
- If the epic spans multiple repos, resolve every involved repo to an actual Conductor workspace
  path or linked directory using `conductor-multi-repo.md`. If any required repo is missing, stop
  before invoking milestone-flow and report the missing repo/path requirement.
- If no canonical epic plan exists, or milestone pass conditions are missing/vague/stale, run
  `/epic-plan`; that skill owns synchronizing milestone gate criteria from source tickets and
  artifacts.
- If milestones, step tickets, dependency edges, cross-repo contracts, ticket-level plan
  artifacts, or step ticket `planned` statuses are missing or stale, run `/epic-split`.
- Re-check the plan after splitting. A milestone is valid only when it is an independently
  stageable/observable risk boundary: it has acceptance criteria, deployment-guide evidence for
  staging and production, and does not require unbuilt later milestones to pass its gate. If that
  is not true, improve the plan/split before building; do not paper over the gap with a fake gate.

### 2. Walk milestones in order

For each milestone in dependency order:

1. If the milestone already has a recorded staging `PASS` and every included step still matches
   the verified commits, skip to the next milestone.
2. Run `/milestone-flow <EPIC_ID> <MILESTONE>` to execute the step-ticket DAG **and the staging
   gate**. That skill owns ticket parallelism, gate package creation, `/auto-deploy <EPIC_ID>
   staging`, `/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote`, and
   any milestone-local fix/redeploy/reverify loop.
3. Accept milestone success only when `/milestone-flow` reports a staging `PASS` and artifact ids
   for all required evidence destinations:

   - canonical milestone-gate `verification_evidence` artifact on the epic;
   - full `verification_evidence` artifact on every included step ticket;
   - compact epic-level verification summary artifact.

   If any required artifact destination is missing, re-enter `/milestone-flow` or the verifier
   evidence-write path rather than marking the milestone complete.
4. For milestones after the first, ensure the milestone verifier included current-milestone
   evidence plus an impact-based regression subset from previously passed milestone gates. If a
   later milestone breaks earlier verified behavior, treat `/milestone-flow` as failed/incomplete
   and keep the fix loop inside that milestone before continuing.

### 3. Production promotion after all staging gates pass

After the final milestone has a staging `PASS`:

- If `--staging-only` is set, stop and report that production was intentionally not touched.
- Otherwise run the ordered epic production promotion/deploy path:

  ```text
  /ticket-promote --epic <EPIC_ID>
  /ticket-verify production --epic <EPIC_ID>
  ```

`/ticket-promote --epic` must promote only the verified epic step commits, in milestone
order, using isolated worktrees and the repo's production deployment instructions. It must not
silently include unrelated staging work. `/ticket-verify production --epic` is the final evidence
gate; mark the epic complete only after it passes.

## Gate-stop process

When running with `--stop-at-gates`, do planning/splitting/readiness checks only, then stop before
calling `/milestone-flow` and print the exact command that would run the full deploy+verify gate:

```text
/milestone-flow <EPIC_ID> <MILESTONE>
```

Do not claim the milestone is complete until `/milestone-flow` actually runs and the staging gate
passes.

## Parallelism

Parallelism is delegated to `/milestone-flow`, which uses dependency waves and repo write
scope analysis. Never parallelize same-repo overlapping work just to save time.

## Output

Always report:

- epic id and current mode (`full-auto` or `gate-stop`);
- current milestone and gate verdict;
- step tickets and statuses changed;
- deploy/promote commands run and their evidence artifacts;
- for each verified milestone/final gate: canonical gate artifact id, per-step ticket evidence
  artifact ids, and compact epic summary artifact id;
- next automatic action or, if blocked, the exact blocker and safest resume command.

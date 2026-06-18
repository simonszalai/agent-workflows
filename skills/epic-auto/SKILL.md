---
name: epic-auto
description: Fully autonomous epic orchestrator. Plans/splits, runs milestone flows, deploys and verifies staging after each milestone, then promotes/deploys/verifies production when explicitly authorized.
max_turns: 800
---

# Epic Auto

End-to-end epic execution coordinator. Use this when the user asks to run an epic, execute an
entire epic, continue across milestones, or do it without further human intervention.

## Operating modes

`/epic-auto` has two modes:

- **Full-auto** — enabled by `--full-auto` or by an explicit user request like "execute the whole
  epic" / "without me". This mode is authorized to invoke deploy, verify, promotion, and fix-loop
  skills until the epic is done or a genuine external blocker is reached.
- **Gate-stop** — enabled by `--stop-at-gates` or by an ambiguous/manual request. This mode plans,
  splits, and runs milestone build flows, then prints the exact next gate command instead of
  running it.

Never silently choose gate-stop when the user explicitly asked for a hands-off/full-auto epic.
Never advance to a later milestone until the current milestone's staging gate has passed.

## Usage

```text
/epic-auto E0007 --full-auto       # run the whole epic, including gates
/epic-auto E0007                   # infer full-auto only if the user's request authorized it
/epic-auto E0007 --staging-only    # stop after every milestone is staged and verified
/epic-auto E0007 --milestone M2    # run one milestone and its gate
/epic-auto E0007 --stop-at-gates   # build-only/gate handoff mode
```

## References

Read before acting:

- `../references/epic-lifecycle.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`

## Full-auto process

### 1. Load and normalize the epic

- Load `get_epic(project, epic_id)` with source tickets, step tickets, artifacts, events, and
  blockers.
- If no canonical epic plan exists, run `/epic-plan`.
- If milestones, step tickets, dependency edges, or cross-repo contracts are missing or stale,
  run `/epic-split`.
- Re-check the plan after splitting. A milestone is valid only when it is an independently
  stageable/observable risk boundary: it has acceptance criteria, deployment-guide evidence for
  staging and production, and does not require unbuilt later milestones to pass its gate. If that
  is not true, improve the plan/split before building; do not paper over the gap with a fake gate.

### 2. Walk milestones in order

For each milestone in dependency order:

1. If the milestone already has a recorded staging `PASS` and every included step still matches
   the verified commits, skip to the next milestone.
2. Run `/epic-milestone-flow <EPIC_ID> <MILESTONE>` to execute the step-ticket DAG. That skill
   owns ticket parallelism and must return only after all milestone steps are landed/`merged`.
3. Confirm the milestone gate report artifact exists and lists the exact step tickets, commits,
   repos, contracts, local checks, and evidence rows to verify.
4. Run the staging deploy gate:

   ```text
   /auto-deploy <EPIC_ID> staging
   ```

   If the repo/project uses a milestone-specific deploy target, pass the milestone scope through
   the project's deploy command/artifacts, but keep the status update on the parent epic.
5. Run the explicit epic/milestone staging verifier:

   ```text
   /ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote
   ```

   For milestones after the first, the verifier must include current-milestone evidence plus an
   impact-based regression subset from previously passed milestone gates. If a later milestone
   breaks an earlier verified behavior, treat that as the current milestone gate failing and run
   the fix loop before continuing.
6. Handle the verdict:
   - `PASS`: record the milestone gate result, leave included step tickets in the verified/ready
     state required by the lifecycle, and continue to the next milestone.
   - `NEEDS_MORE_TIME`: keep polling/re-running the timer-friendly verifier with backoff until it
     becomes `PASS` or `FAIL`. If this session must stop for budget/runtime reasons, persist the
     gate state and exact resume command; do not advance the milestone.
   - `FAIL`: create or identify the fix ticket(s) inside the same milestone, run `/ticket-flow` on
     those fixes with epic context, redeploy staging, and re-run the verifier. Stop only for a
     genuine external/manual blocker or the same unresolved failure repeating after the documented
     retry/fix loop.

### 3. Production promotion after all staging gates pass

After the final milestone has a staging `PASS`:

- If `--staging-only` is set, stop and report that production was intentionally not touched.
- Otherwise run the ordered epic production promotion/deploy path:

  ```text
  /promote-to-production --epic <EPIC_ID>
  /ticket-verify production --epic <EPIC_ID>
  ```

`/promote-to-production --epic` must promote only the verified epic step commits, in milestone
order, using isolated worktrees and the repo's production deployment instructions. It must not
silently include unrelated staging work. `/ticket-verify production --epic` is the final evidence
gate; mark the epic complete only after it passes.

## Gate-stop process

When running with `--stop-at-gates`, do steps 1-2 through `/epic-milestone-flow`, then stop at the
next deploy/verify boundary and print the exact gate commands that full-auto would have run. Do
not claim the milestone is complete until the gate actually passes.

## Parallelism

Parallelism is delegated to `/epic-milestone-flow`, which uses dependency waves and repo write
scope analysis. Never parallelize same-repo overlapping work just to save time.

## Output

Always report:

- epic id and current mode (`full-auto` or `gate-stop`);
- current milestone and gate verdict;
- step tickets and statuses changed;
- deploy/promote commands run and their evidence artifacts;
- next automatic action or, if blocked, the exact blocker and safest resume command.

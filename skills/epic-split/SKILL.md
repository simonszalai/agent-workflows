---
name: epic-split
description: Idempotently reconcile an approved epic plan into milestone-assigned step tickets with dependency edges and cross-repo contracts. Friendly canonical name for the existing autodev epic step creation workflow.
max_turns: 150
---

# Epic Split

Turn an approved epic plan into milestone-assigned step tickets, or reconcile existing step
tickets when the plan has changed. This is the coherent public name for the behavior currently
documented in `/autodev-epic-create-steps`.

Default reruns are idempotent: update matching existing steps, each step ticket's own `plan`
artifact, milestone assignments, contracts, and DAG edges; create only missing steps; do not
duplicate existing step tickets or plan artifacts.

## Boundaries

- Does not build, land, deploy, or verify.
- Creates/updates step tickets only after the epic plan is sufficiently settled.
- Source tickets remain parked as `absorbed_into_epic`.
- Does not detach, abandon, or delete stale existing steps unless explicitly requested via a
  from-scratch/rederive cleanup instruction. By default, reports stale steps as proposed removals.

## Usage

```text
/epic-split E0007
/epic-split E0007 --reconcile
/epic-split E0007 --milestone M3
/epic-split E0007 --rederive
/epic-split E0007 --from-scratch
```

## Process

1. Load `get_epic` including artifacts, sources, milestones, steps, and deps.
2. Ensure a current epic `plan` artifact exists. If missing, contradictory, or missing concrete
   milestone pass conditions, run `/epic-plan` first. Do not create criteria-free gates.
3. Decompose the plan into the desired step set:
   - one step = one repo;
   - split cross-repo work into provider/consumer tickets;
   - assign each step to a milestone;
   - build an acyclic blocker -> blocked DAG;
   - run the **runtime evidence closure** check before creating tickets: if a milestone's
     acceptance criteria require runtime/staging evidence (canary run, observer, flow,
     deployment, stored rows, polling, scheduler, worker, Prefect, supervisor, webhook, live
     readback), the same milestone's desired step set must include the code/config/command that
     will produce that evidence. Do not leave a gate requiring stored rows or a flow run while
     splitting only schema/parser/model tickets and deferring the runtime surface to a later
     milestone.
4. Match desired steps to existing epic steps before creating anything:
   - match by repo, milestone, title/intent, source artifact content, and cross-repo contract;
   - reuse ticket IDs for still-valid steps;
   - update backlog/planned matching tickets whose scope, milestone, or contract changed;
   - never create a duplicate ticket for a step intent that already has an epic step;
   - never rewrite merged/completed steps; create a follow-up step if additional work is needed.
5. Write contracts into both sides of every cross-repo dependency.
6. **Ensure the target milestones exist and have pass conditions.** If the plan defines a
   checkpoint the epic has no milestone row for (common on a fresh epic), create it with
   `create_epic_milestone(...)` using named arguments for `project`, `epic_id`, `title`,
   `description`, `acceptance_criteria`, `position`, and `is_gate` — do not block waiting for a
   human to create milestones. If an existing milestone row is missing or has stale
   `acceptance_criteria`, update it from the canonical plan before assigning steps. Only stop and
   ask if a *named* milestone is genuinely ambiguous.
7. Create only missing step tickets with `create_ticket(..., epic_id=E000N, status="backlog")`.
8. Create or update a ticket-level `plan` artifact for every desired non-completed step ticket:
   - use `create_artifact(..., artifact_type="plan")` when the ticket has no plan;
   - use `update_artifact(...)` when a live/current plan exists but is stale;
   - immediately after the plan artifact is created/updated, call
     `update_ticket(..., status="planned", summary_bullets=[...], command="/epic-split")` for
     that step ticket. A step with a current ticket-level plan must not remain in `backlog`;
   - the source artifact is the **scope**; the plan artifact is the **implementation plan** for
     that one repo/step: goal, non-goals, approach, ordered build phases, expected files/modules,
     migrations/config/deploy notes, test plan, acceptance evidence, rollback/kill-switch notes,
     and cross-repo contracts consumed/exposed;
   - do not copy the epic plan verbatim and do not create duplicate plan artifacts;
   - do not rewrite merged/completed steps; create a follow-up step if post-completion work is
     needed.
9. Use `add_epic_step` / `assign_epic_step_milestone` / `set_epic_member_deps(replace=True)` to pin order,
   milestone, and edges.
10. Treat stale steps carefully:
   - default: leave stale steps attached and report them as `stale-proposed-removal`;
   - if the user explicitly asked for `--from-scratch`, `--rederive` with cleanup, or removal,
     detach stale steps with `remove_epic_step` and clear/replace their edges;
   - never abandon/delete ticket records as part of split unless the user explicitly asks.
11. Re-load the epic and verify:
   - all steps are assigned as intended;
   - every desired non-completed step ticket has a current `plan` artifact and `status="planned"`;
   - DAG is acyclic;
   - cross-repo edges have contracts;
   - every gate milestone has concrete `acceptance_criteria`;
   - every gate milestone with runtime evidence criteria has at least one same-milestone step
     whose plan explicitly owns the producing runtime surface (Prefect YAML/flow,
     supervisor/worker registration, deploy-owned canary CLI, or disposable integration-DB
     evidence if the gate was deliberately scoped away from staging runtime rows);
   - no duplicate step tickets exist for the same step intent;
   - warnings are empty.

## Relationship to existing skill

If `/autodev-epic-create-steps` is available and up to date, this skill may delegate the
mechanical step creation to it after validating that the epic plan is current.

## Output

A table:

```text
Order  Milestone  Ticket  Repo       Plan/Status       Blockers  Contract
1      M1         F0112   ts-prefect plan:yes planned  -         exposes companies.market_etf_symbol
2      M1         F0111   ts-prefect plan:yes planned  F0112    reads companies.market_etf_symbol
```

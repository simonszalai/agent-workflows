---
name: epic-split
description: Split an approved epic plan into milestone-assigned step tickets with dependency edges and cross-repo contracts. Friendly canonical name for the existing autodev epic step creation workflow.
max_turns: 150
---

# Epic Split

Turn an approved epic plan into milestone-assigned step tickets. This is the coherent public name
for the behavior currently documented in `/autodev-epic-create-steps`.

## Boundaries

- Does not build, land, deploy, or verify.
- Creates/updates step tickets only after the epic plan is sufficiently settled.
- Source tickets remain parked as `absorbed_into_epic`.

## Usage

```text
/epic-split E0007
/epic-split E0007 --milestone M3
/epic-split E0007 --rederive
```

## Process

1. Load `get_epic` including artifacts, sources, milestones, steps, and deps.
2. Ensure a current epic `plan` artifact exists. If missing or contradictory, run `/epic-plan`.
3. Decompose into minimal step tickets:
   - one step = one repo;
   - split cross-repo work into provider/consumer tickets;
   - assign each step to a milestone;
   - build an acyclic blocker -> blocked DAG.
4. Write contracts into both sides of every cross-repo dependency.
5. Create step tickets with `create_ticket(..., epic_id=E000N, status="backlog")`.
6. Use `add_epic_step` / `assign_epic_step_milestone` / `set_epic_member_deps` to pin order,
   milestone, and edges.
7. Re-load the epic and verify:
   - all steps are assigned as intended;
   - DAG is acyclic;
   - cross-repo edges have contracts;
   - warnings are empty.

## Relationship to existing skill

If `/autodev-epic-create-steps` is available and up to date, this skill may delegate the
mechanical step creation to it after validating that the epic plan is current.

## Output

A table:

```text
Order  Milestone  Ticket  Repo       Blockers  Contract
1      M1         F0112   ts-prefect -         exposes companies.market_etf_symbol
2      M1         F0111   ts-prefect F0112    reads companies.market_etf_symbol
```

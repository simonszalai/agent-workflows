---
name: epic-plan
description: Deep planning for an autodev epic from absorbed source tickets and epic artifacts. Consolidates context, researches broadly, runs adversarial plan critique, and writes the canonical epic plan. Does not create step tickets.
max_turns: 200
---

# Epic Plan

Create the canonical plan for an epic. Use after tickets have been absorbed into an epic or
after substantial epic artifacts have accumulated.

## Boundaries

- Always deep: no light planning path.
- Does not create step tickets; use `/epic-split` after the plan is accepted.
- Does not build, land, deploy, or verify.

## References

- `../references/epic-lifecycle.md`
- `../references/execution-phases.md`

## Usage

```text
/epic-plan E0007
/epic-plan E0007 --focus M3
```

## Process

1. Resolve project and load `get_epic(project, epic_id)`.
2. Load all absorbed source tickets with `get_ticket`.
3. Read all epic artifacts in chronological order.
4. Run broad codebase and memory research across involved repos.
5. Consolidate the design:
   - latest confirmed decisions override earlier drafts;
   - duplicates collapse;
   - contradictions become open questions, not guesses.
6. Draft the epic plan:
   - goal and non-goals;
   - milestone list and gates;
   - expected step-ticket breakdown direction;
   - cross-repo contracts to create;
   - risks, rollback/promotion strategy, verification gates.
7. Run adversarial critics for completeness, correctness, YAGNI, sequencing, data safety,
   deploy/verify gates, and cross-repo contracts.
8. Revise until no critical unresolved critic findings remain. Stop for user decisions if
   critics expose unresolved product/architecture choices.
9. Write a `plan` epic artifact via `create_epic_artifact`.

## Output

Report:

- canonical plan artifact title/id;
- milestones/gates;
- open questions, if any;
- recommended next command: `/epic-split E0007`.

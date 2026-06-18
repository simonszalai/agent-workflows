# Epic lifecycle reference

Epics are not large tickets. An epic is the ordered, cross-repo execution plan for one coherent
feature. It owns milestone gates and cross-repo contracts.

## Source tickets

Users may start with ordinary tickets. When those tickets are too large or clearly belong
together, they are absorbed into an epic:

```text
regular tickets -> absorb_ticket_into_epic -> source tickets in absorbed_into_epic
```

Source tickets motivate the epic. They are parked, hidden from ordinary boards, and never land.
Their artifacts become epic planning input.

## Epic planning

Epic planning is always deep:

1. load all epic artifacts and absorbed source tickets;
2. run broad codebase and memory research;
3. consolidate contradictions by recency/confirmation;
4. write a single epic plan artifact;
5. run adversarial plan critics;
6. stop on genuine product/architecture open questions.

## Milestones

A milestone is a logical gate: a deploy/verify/decision point. A milestone can contain several
step tickets across multiple repos. Steps can be parallelized only when the dependency graph and
repo conflict analysis allow it.

## Step tickets

Each step ticket belongs to exactly one repo. Cross-repo work is split into multiple step
tickets connected by explicit contracts.

## Contracts

For every cross-repo dependency edge, write the contract in both step tickets:

- provider exposes: schema/API/function/config/event and version/shape;
- consumer reads: assumptions, expected shape, contract tests/verification.

Same-repo edges order the waterfall but do not need cross-repo contracts.

## Execution

Epic execution works one milestone at a time:

```text
epic-plan -> epic-split
  -> milestone-flow M1 -> deploy staging -> verify M1 staging gate
  -> milestone-flow M2 -> deploy staging -> verify M2 staging gate
  -> ...
  -> ordered epic production promotion/deploy -> final production verify
```

The lower-level ticket-flow may execute individual step tickets, but it must load epic context
and respect the contracts. The epic/milestone orchestrator owns parallelism and gate progression.

In full-auto mode, `/epic-flow` owns the gate loop: it runs the milestone flow, deploys the parent
epic to staging, invokes explicit epic/milestone verification, fixes failures inside the same
milestone, and proceeds only after a staging `PASS`. Milestone flow itself never deploys or
verifies environments.

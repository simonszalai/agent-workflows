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
tickets connected by explicit contracts. During epic splitting/planning, every execution step must
receive its own ticket-level `plan` artifact; immediately after that artifact is created or
updated, the step ticket status must be set to `planned` (with refreshed summary bullets), so
plan-bearing step tickets never remain in `backlog`.

## Contracts

For every cross-repo dependency edge, write the contract in both step tickets:

- provider exposes: schema/API/function/config/event and version/shape;
- consumer reads: assumptions, expected shape, contract tests/verification.

Same-repo edges order the waterfall but do not need cross-repo contracts.

## Execution

Epic execution works one milestone at a time:

```text
epic-plan -> epic-split
  -> milestone-flow M1 (build + deploy staging + verify M1 staging gate)
  -> milestone-flow M2 (build + deploy staging + verify M2 staging gate)
  -> ...
  -> ordered epic production promotion/deploy -> final production verify
```

The lower-level ticket-flow may execute individual step tickets, but it must load epic context
and respect the contracts. The epic/milestone orchestrator owns parallelism and gate progression.
A **direct** ticket-flow run on a step (no `--epic-context`) that completes its milestone hands
off to `/milestone-flow` so the deploy + gate still run; a delegated run (`--epic-context`) or one
that leaves siblings open lands only and lets `/milestone-flow` deploy the milestone as a unit.

`/milestone-flow` owns the staging gate loop for the milestone it is asked to run: it executes the
step-ticket DAG, writes the gate package, deploys the parent epic/milestone target to staging,
invokes explicit epic/milestone verification, fixes failures inside the same milestone, and returns
success only after a staging `PASS`. `/epic-flow` sequences milestones and owns final production
promotion/verification after all staging gates pass; it must not treat a build-only milestone
handoff as complete.

## Epic status vocabulary

The epic itself carries an `epic_status` (set via `update_epic`), separate from its step
tickets' statuses. Canonical values, in lifecycle order:

```text
planning -> in_progress -> to_verify_staging -> staging_verified -> to_verify_prod -> completed
```

- `to_verify_staging` / `staging_verified` are set per milestone gate progress (the last
  milestone gate PASS moves the epic to `staging_verified`).
- `to_verify_prod` is set when production promotion of the epic lands (`/ticket-promote
  --epic`); `completed` when `/ticket-verify production` passes the epic scope.
- Blockers are metadata, not statuses — same rule as tickets (see ticket-lifecycle.md).

## Verification evidence placement

Epic/milestone verification must leave durable evidence in three places before any lifecycle status
advances:

1. **Milestone/final gate artifact on the epic** — the canonical full `verification_evidence` proof
   package for the gate scope (`E0007/M2`, `E0007/final`, etc.).
2. **Step-ticket artifacts** — a `verification_evidence` artifact on every included step ticket,
   containing that step's relevant evidence rows, outputs, verdict, status action, and a pointer to
   the canonical epic gate artifact. A step ticket must never show `staging_verified` or `completed`
   solely because an epic artifact exists elsewhere.
3. **Epic summary artifact** — a compact epic-level rollup/index of verified gates, canonical
   evidence artifact ids, step-ticket evidence artifact ids, remaining risks, and next actions.

The canonical gate artifact is the source of truth for the gate verdict; ticket artifacts make each
step auditable in isolation; the epic summary is only a readable index.

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

## Splitting rules

Every step costs a fixed ceremony (plan artifact, self-review, full health gate, CI, PR,
merge) that runs strictly serially inside one repo. Split for parallelism or for a real risk
boundary, never for tidiness. Whoever creates or reconciles an epic — a planner, `/epic-flow`,
or an operator session calling the MCP directly — applies these rules; `/epic-flow` §2
reconciles an existing split against them before building anything.

1. **Bundle work that shares a primitive.** Two steps in the same repo stay separate only when
   they can be built and tested in parallel with non-overlapping write scopes, or when they sit
   on different sides of a gate. A step whose tests or staging probe cannot run until a sibling
   lands (a retriever over a column the sibling adds) is the same step.
2. **One repo per step, literally.** Any file in another repo is its own step in that repo,
   with contracts in both tickets. Never "a separate PR in <repo>, coordinated in this step":
   that hides a remote workspace and a gate dependency.
3. **Acceptance criteria are gradable at the gate's tier.** A staging gate lists only
   staging-observable evidence. Anything that needs production time (24h post-activation
   metrics, cost vs a production baseline) belongs to the epic's production criteria. Nothing
   requires a human's labour (hand-labelled samples, manual sign-off) unless a named human step
   exists; otherwise the agent produces it and the criterion says so.
4. **Precondition producers are deploy rows, not gate failures.** Backfills, prompt-row seeds,
   enum additions, and config inserts a gate criterion depends on are deployment-guide rows of
   that milestone's deploy. A prompt row for a new slot is seeded in the milestone that adds the
   enum (a row with no reader is harmless; a reader with no row asserts).
5. **Resolve identifiers in the epic plan.** Model ids, config keys, table and column names,
   and cost caps are settled during planning from code and memory. "Confirm exact id in the
   step" stalls a worker later.
6. **Validation code ships with the behaviour change.** A replay-harness arm or scorecard
   change lands in the step that changes the behaviour it measures; a validation step is then
   run-only (execute, persist artifacts, write the deployment guide) and needs no PR unless it
   commits results. Size its cost cap from prior runs recorded in memory.
7. **The step plan is written once.** The split writes each step's `plan` artifact and sets
   `planned`; `/ticket-flow` enters at implementation and does not write a second plan.

## Execution

Epic execution works one milestone at a time:

```text
plan -> split into milestone-assigned step tickets
  -> milestone M1: build steps + deploy staging + verify M1 staging gate
  -> milestone M2: build steps + deploy staging + verify M2 staging gate
  -> ...
  -> ordered epic production promotion/deploy -> final production verify
```

Individual step tickets may be executed on their own, but must load epic context and respect the
contracts. The milestone gate loop executes the step-ticket DAG, writes the gate package, deploys
the parent epic/milestone target to staging, runs explicit epic/milestone verification, fixes
failures inside the same milestone, and succeeds only on a staging `PASS`. Final production
promotion/verification happens only after all staging gates pass; a build-only milestone handoff
is not complete.

One orchestrator session owns the whole epic. Multi-repo epics do not need a multi-repo
checkout: every step/deploy/promotion in another repo runs in a Conductor workspace for that
repo (one per epic×repo, branch = integration target), dispatched and polled through the
Conductor MCP; the ticket system is the shared state, and each repo deploys its own integration
target in deployment-guide order before the milestone gate runs once from the orchestrator.
Writing to a repo from outside a workspace for that repo is never allowed (see
`../epic-flow/SKILL.md` §Remote repos).

## Epic status vocabulary

The epic itself carries an `epic_status` (set via `update_epic`), separate from its step
tickets' statuses. Canonical values, in lifecycle order:

```text
planning -> in_progress -> to_verify_staging -> staging_verified -> to_verify_prod -> completed
```

- `to_verify_staging` / `staging_verified` are set per milestone gate progress (the last
  milestone gate PASS moves the epic to `staging_verified`).
- `to_verify_prod` is set when production promotion of the epic lands; `completed` when
  production verification passes the epic scope.
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

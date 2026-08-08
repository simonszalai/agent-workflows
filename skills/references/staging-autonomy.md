# Staging Autonomy Contract

Load this contract from any mutation-capable workflow that deploys to or verifies staging. The
default is action, not escalation: if an agent can restore a documented, bounded staging
precondition safely, it does so and continues the workflow without asking the user.

## 1. Classify before returning `BLOCKED`

Every unmet staging precondition gets one `repairability` value:

- `staging_safe`: executable now under the standing authorization below;
- `owner_repair`: agent-resolvable, but it needs a tracked code/config/deploy owner rather than an
  inline environment command;
- `external_wait`: no action is missing; a live external operation/producer is making progress and
  passive time can reach an explicit terminal predicate;
- `human_required`: missing intent, authorization, credential approval, or an irreversible choice;
- `agent_incapable`: a concrete action is required, but no available agent can perform it with the
  callable tools, permissions, credentials, or environment it has.

`BLOCKED` is not a valid terminal result from a mutation-capable staging owner while any unmet
precondition is `staging_safe`, `owner_repair`, or `external_wait`. A read-only verifier may return
`BLOCKED` for a required action outside its mutation boundary, but it must return this
classification and an executable repair/wait packet to its caller. The caller repairs or waits and
re-verifies in the same top-level run.

## 2. Standing authorization for `staging_safe`

Execute without confirmation only when every condition is proved from repository instructions,
the finalized deployment guide/gate package, an existing project script, or an authoritative tool
schema:

1. the target is positively identified as staging; no endpoint, credential, data source, or
   downstream service resolves to production;
2. scope is explicit and bounded before execution: named synthetic identities/resources or a hard
   record/work cap, never a database-wide reset, full backlog scan, backfill, or uncapped loop;
3. the action is idempotent or has a tested rollback/cleanup path, and the owner records the
   targeted before-state needed to restore it;
4. side effects stay inside staging: no real customer messages, public posts, payments, production
   writes, secret rotation/minting, or uncontrolled paid-provider work;
5. the command uses an existing audited project route and approved credential mechanism. It does
   not invent SQL, flags, fixture semantics, or credentials from prose;
6. success and failure have source-of-truth postconditions that can be checked immediately.

Typical authorized repairs include creating documented synthetic tenants/users/rows, aligning a
small ticket-owned staging fixture across services, restoring a missing disposable test resource,
running an idempotent staging-only seed command, registering a documented staging-only verifier
object, and retrying an idempotent staging deploy step after its dependency is restored.

The following are never `staging_safe`: production or mixed-environment mutation; destructive or
unbounded data operations; real-world notifications/payments/public effects; secret creation or
rotation; authorization-policy changes; guessing among multiple fixtures/targets; and any action
whose blast radius, cost, rollback, or target environment is unknown.

When the choice is between preserving broken disposable staging state and restoring the documented
bounded test state, restore staging. Do not ask the user to run a command the agent can run through
an available approved tool.

## 3. Execute and prove the repair

The active mutation owner performs a simple documented environment action directly. It delegates
only when a code/config edit, another repository, or a distinct deployment owner is required. The
read-only verifier never grades its own mutation.

For each distinct precondition:

1. write a compact repair receipt with `repairability`, source citation/path, target environment,
   exact command/tool, explicit resource bounds, before-state reference, rollback/cleanup, and
   success predicate;
2. execute the command once through the project-approved route, keeping secret-bearing output
   redacted and noisy output bounded;
3. check the postcondition immediately. On partial failure, rollback or finish restoring a coherent
   staging state before doing anything else;
4. clear/supersede blocker metadata only after the source-of-truth check passes;
5. batch any other already-known `staging_safe` prerequisites, then invoke one fresh read-only
   verification pass against the same activated revision;
6. persist the receipt and outcome in the verification/deployment evidence and, when the missing
   prerequisite was absent from the canonical guide/gate package, repair that artifact for future
   runs.

Safe operational prerequisites do not consume the product-code repair round. Bound this lane to at
most three distinct actions per top-level staging run, one execution per unchanged command and
target. A failed/no-op action may be replaced only after new evidence changes the command, target,
or hypothesis. Two consecutive actions with no source-of-truth progress end the lane; do not loop.

## 4. Wait for live external work

`external_wait` is nonterminal. Use it only after source-of-truth evidence proves all of these:

1. a specific run/deploy/job/provider operation exists and has started or is durably queued;
2. its worker/provider is healthy enough to make progress, with fresh progress, an authoritative
   ETA/SLA, or an observed/documented completion cadence;
3. success and failure terminal predicates are explicit;
4. no deploy, trigger, approval, configuration, credential, or other action is still missing.

Start one deterministic waiter immediately. Derive its deadline from the operation's ETA/SLA or
observed/documented completion cadence plus headroom instead of using a short generic timeout. The
waiter, not the model, performs repeated status reads; the mutation owner blocks once for its
compact terminal result and then continues the workflow. Wait through ordinary queueing, provider
processing, deployment, propagation, and eventual-consistency delays when the evidence says they
will complete.

If a harness/provider hard limit expires while the same operation remains healthy and progressing,
persist the wait receipt and return `NEEDS_MORE_TIME` with the exact continuation command or
automatic continuation hook. Schedule the automatic continuation when the harness supports it;
require user invocation only when no continuation mechanism exists. Never relabel a progressing
wait as `BLOCKED`, `FAIL`, no-progress, or a reached repair/action limit. If evidence instead shows the
operation cannot advance without an action,
reclassify that action as `staging_safe`, `owner_repair`, `human_required`, or `agent_incapable`.

## 5. Legitimate stops

`BLOCKED` is reserved for exactly two cases: `human_required`, or `agent_incapable`. A no-progress
repair lane or exhausted repair/model budget is `STOPPED`/`FAILED`, not `BLOCKED`; a live passive
condition is `external_wait`/`NEEDS_MORE_TIME`, not `BLOCKED`. A staging blocker report must include
the classification, evidence that an action is required, why that action needs a human or cannot be
performed by any available agent, actions already attempted, rollback/cleanup state, and the single
exact next action.

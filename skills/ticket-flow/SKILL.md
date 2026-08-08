---
name: ticket-flow
description: >-
  Autonomous single-ticket execution with MCP ticket tracking: compact delivery for direct and
  standard work, full phase skills for heavy work, then ticket-deploy when applicable.
max_turns: 60
---

# Ticket Flow

Autonomously execute **one ticket** from GitHub issue, existing F/B/R ticket, or conversation
context. The normal path is deliberately compact:

```text
direct:   one delivery owner -> parent health
standard: one delivery owner -> one reviewer -> optional repair -> parent health
heavy:    /ticket-plan <ID> -> /ticket-build <ID>
/ticket-deploy <ID> staging      # default
/ticket-deploy <ID> full         # when invoked as /ticket-flow <ID> prod
```

Ticket Flow is ticket-level only. It is not an epic orchestrator, but if the ticket is an epic
step it must load the parent epic context and honor the milestone contracts.

The user entrypoint remains `/ticket-flow`; this skill invokes the deterministic contract binaries
itself. Do not ask the user to construct or run envelopes manually.

## Hard boundaries

- May create/resume exactly one ticket.
- Owns the standalone ticket delivery decision: **staging-first** for complex/risky/uncertain
  work, **direct-production** only for tiny safe work (and then only via `/ticket-deploy`'s
  direct-production gate, which asks for confirmation when the diff is not tiny/safe).
- `direct`/`standard` use the compact delivery contract below; they do not invoke separate
  planning/build/test-writing skills. `heavy` delegates planning to `/ticket-plan` and
  implementation to `/ticket-build`. Deployment and environment verification remain owned by
  `/ticket-deploy` (`/auto-deploy`, `/ticket-verify`, `/ticket-promote`).
- Without the `prod` argument, stops after the staging verify leg — production promotion
  requires an explicit `/ticket-flow <ID> prod` or `/ticket-deploy <ID> prod|full`.
- Must not advance an epic/milestone gate; epic skills own that.
- Must not use `.context/` for ticket artifacts; use MCP artifacts.
- Must always produce a plan MCP artifact before the first edit (every intensity, including
  `direct`).
- Ticketless ultra-light edits are `/go-fable`, not this skill. There is no `/lfg`.

## References

Read before acting:

- `../references/execution-economy.md`
- `../references/execution-intensity.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/environment-topology.md`
- `../references/execution-phases.md`
- `../references/delegated-ticket-context.md`
- `../references/epic-lifecycle.md` when the ticket is an epic step
- `../references/conductor-multi-repo.md` when the ticket is an epic step, cross-repo
  contract provider/consumer, or the repo is a linked Conductor directory

## Usage

```text
/ticket-flow F0123                 # plan -> build -> deploy staging -> verify staging, stop
/ticket-flow F0123 prod            # ...continue: promote -> deploy prod -> verify prod -> completed
/ticket-flow #123                  # from GitHub issue
/ticket-flow                       # create ticket from conversation
/ticket-flow F0123 --no-land       # build/review only; do not merge or deploy
/ticket-flow F0123 --skip-local-verify
/ticket-flow F0123 --intensity direct|standard|heavy
/ticket-flow F0123 --light         # alias → intensity direct
/ticket-flow F0123 --deep          # alias → intensity heavy
```

Invoking with `prod` is the explicit human authorization for production promotion/deploy after
an exact staging `PASS` (it maps to `/ticket-deploy <ID> full`). It also grants standing approval
for plan-conformant, deterministic, corroborated `gated_auto` review fixes and bounded repair work.
This does not authorize product-intent changes, destructive scope
expansion, materially different tradeoffs, new secrets/schema/infrastructure/cost, or choosing
between unresolved reviewer recommendations.

Legacy names: `/auto-flow`, `/ticket-full-auto` (≈ `/ticket-flow <ID> prod`), and `/goal-flow`
are retired; route related ticket sets to per-ticket `/ticket-flow` runs or an epic.

## Delivery target selection

Choose the intended delivery target **before planning/building** so the verification strategy,
deployment guide, and risk controls match the path:

1. a valid `bin/environment-capability` production-only result from exact topology metadata plus
   explicit production acceptance/user authorization;
2. explicit `--target staging|production|prod|main|none` or `--no-land`;
3. existing PR base / branch ancestry, if a PR already exists;
4. epic milestone/integration target, for epic-step tickets only;
5. landing policy risk classification.

Target meanings:

- `staging` (default) = merge/deploy to staging first; `/ticket-verify staging` tests it before
  any production promotion. Note the *target* is distinct from the `prod` *argument*: target
  describes where the code lands first; the `prod` argument decides whether the flow continues
  through production after staging passes.
- `--target production`/`prod`/`main` = direct-to-production for tiny safe standalone work only;
  executed via `/ticket-deploy <ID> prod`, whose direct-production gate re-checks the risk
  classification and asks for confirmation when the diff is not tiny/safe.
- `none` / `--no-land` = build/review/local-verify only.

The Conductor workspace target branch is a hint, not permission to bypass risk classification.
If the workspace appears to target `main` but the ticket is not tiny/safe, **route the standalone
ticket to staging automatically** unless the user explicitly requested direct production.
Never infer production-only from failed staging access. Unknown or missing topology stays
staging-first. A valid production-only capability is passed unchanged in every immutable child
packet so ticket-deploy and ticket-verify consume the route rather than improvising a bypass.

## Process

### 0. Resolve ticket and target

- Resolve project from `<!-- mem:project=X -->` and repo from git remote.
- Resolve the surface through `bin/environment-capability` and cache its JSON result. Production
  routing is valid only when the exact topology, acceptance contract, user authorization, and
  verifier-mode gates all pass.
- If the ticket's `repo` does not match the current repo, switch only to an available linked
  Conductor directory for that repo after checking its git remote; otherwise stop and report the
  missing repo workspace. Do not implement a ticket for one repo inside another repo.
- If input is a ticket ID, load it once via
  `get_ticket(detail="light", include_events=false)` for identity/lifecycle only and cache
  `context_version` plus the artifact manifest. Do not fetch artifact bodies in this parent.
  Hydration belongs to the context curator below. A lifecycle refresh must send the cached version
  and is valid only when a new `context_version` is returned.
- If input is an issue/conversation, search existing tickets first; create a new ticket only
  when no matching non-terminal ticket exists.
- Detect epic-step context from explicit epic membership, `related`, `tags.related_epic`, or
  source text. If found, load `get_epic` once and cache its version plus the step's
  milestone/contracts. Consume the milestone's active shared packet: the epic artifact titled
  `milestone-packet <EPIC_ID> <MILESTONE>` (artifact_type `deployment_guide`, metadata
  `kind: "milestone_packet"`); verify the SHA-256 recorded in the packet body against the exact
  body bytes and record its version/hash in every phase result. Delegated phases receive only that
  packet artifact id/version/hash plus their exact step scope, not copied epic history.
- On a direct epic-step entry, if the packet is absent, create the initial packet artifact from
  the bounded `get_epic` snapshot before planning. A delegated `--epic-context` run treats a
  missing packet as a caller-contract failure and returns to milestone-flow; it must not invent a
  sibling packet.
- If an epic-step phase identifies a specifically missing fact, request a new packet version from
  the owning milestone orchestrator. Reload MCP/source context only when the packet version
  advances or that exact missing fact is required. Never rewrite the packet from a child or let
  sibling ticket-flows create divergent milestone packets.
- Decide and record the delivery target using `landing-policy.md`.
- **Decide and record intensity** using `execution-intensity.md` before planning/building:
  parse `--intensity` / `--light` / `--deep`; epic membership alone has no floor; raise to `heavy`
  only on named safety surfaces. Write
  `intensity`, `intensity_reason`, and `intensity_floor` into every phase envelope and child
  packet. Escalate only if later phases discover a new floor trigger; never silently downgrade.
  Intensity never skips the plan artifact.
- **Resume from lifecycle truth**: skip phases whose artifacts and status already exist (a
  `planned` ticket with a plan artifact enters at build; a built, locally verified ticket enters
  at deploy). A `verify_staging_failed` status is a resumable checkpoint inside the autonomous
  staging repair loop, not a user-interaction gate. Resume from its persisted failure class and
  round counter and cumulative run-budget receipt. Production failures retain their
  environment-specific safety boundary. A fresh conversation reuses that receipt; it never resets
  model-session or repair capacity.
  A staging `BLOCKED` artifact with `repairability: staging_safe | owner_repair` is likewise a
  resumable checkpoint, not a user-interaction gate; resume `/ticket-deploy` with its repair packet.
- Treat ticket origin as immutable audit provenance only. Never branch delivery, pickup, status
  transitions, or blocker metadata on origin or on null execution-approval fields. Consume
  `next_ticket` eligibility as canonical server truth; `approve_execution=true` is an explicit
  admin-only audit action, not an implementation prerequisite.

### 1. Gather context

**Single retrieval owner.** Follow `delegated-ticket-context.md`. The ticket-flow parent must not
load artifact bodies or run memory, entry-expansion, or similar-ticket searches. It dispatches one
fresh no-history context curator after resolution. For a bug without a confirmed investigation,
run the bounded diagnosis or `/investigate` first, then reuse `/investigate`'s curator packet when
its `context_version`, next phase, and task fingerprint match; otherwise dispatch once after
persistence. This is the only bulk MCP retrieval pass for that phase/version.

The curator reads every current ticket artifact and all applicable memories/past-ticket evidence in
its isolated session, then returns one <=8 KiB phase packet and runtime receipt. The parent reads
only that packet. For epic steps, the curator packet is combined with the separately bounded active
milestone packet reference; never copy epic history into either packet.

Validate the curator receipt with
`bin/workflow-ticket-context-check receipt <receipt.json>` before each phase dispatch. Repeated
same-version reads fail. Plan and deployment-guide updates are bounded replacements; their older
revisions remain in MCP artifact history, not appended to the current body. If an exact fact is
missing, request one targeted curator refresh; do not replay raw MCP reads in this parent.

### 2. Select compact or heavy delivery

**`direct` / `standard`:** do not invoke `/ticket-plan` or `/ticket-build`. Dispatch exactly one
fresh `fork_turns: "none"` `delivery_owner` with the immutable source/epic packet, existing plan
when resuming, intensity fields, artifact schemas, and allowed write scope. In that one session it:

1. reads the curated ticket-context packet and performs only the bounded code lookup needed for the
   change; it does not repeat the packet's artifact or memory retrieval;
2. persists a short plan MCP artifact and `summary_bullets` **before its first edit** (or verifies
   and follows the existing plan on resume);
3. creates minimal MCP `build_todo` artifacts mechanically from that plan;
4. implements the bounded change, writes focused behavior tests, and may run focused tests;
5. checkpoints each todo and returns plan/todo bodies, changed paths, focused-test evidence, and
   final tree SHA so the parent can repair a cross-provider MCP no-op.

There is no separate researcher, planner, build-planner, builder chain, or test-writer session.
If the owner proves the work crosses a safety floor or needs an unresolved architectural choice,
it stops before the risky edit and returns `needs_heavy`; persist the checkpoint and enter the
heavy path instead of adding roles to the compact path.

**`heavy`:** run `/ticket-plan <ID>`, persist its plan/curated-context checkpoint, then start
`/ticket-build <ID>` in a fresh no-history session. Heavy planning owns its critic and any explicit
peer escalation. A history fork is allowed only when a self-contained packet is genuinely
impossible: record the reason and use the smallest explicit numeric count, never all history.

### 3. Review and locally verify

For compact delivery, first verify the plan/build-todo artifacts exist and reissue any missing MCP
writes from the owner's structured receipt. The parent runs the canonical full health command on
that tree. A failure is inventoried completely; before any changed-tree fix, reserve the one shared
repair-cycle id. Maintained deterministic autofixes run first in the current orchestrator session,
which is recorded as the `repair_owner` even when no fresh repair subagent is needed. All remaining
findings go to that same allowance. The parent reruns the gate once on the changed tree.

`direct` then stops reviewing. `standard` dispatches exactly one fresh native general reviewer over
the diff, plan, todo/deviation record, and health evidence. It does not run validation or edit.
Combine all accepted findings into one batch for the same repair allowance if it remains. Do not
re-review a same-risk repair; run one final parent health gate only when repair changed the tree. A
newly crossed risk boundary escalates to the heavy review path. If the repair was already consumed,
or its changed tree still fails, return `BUDGET_EXHAUSTED` with the checkpoint and exact resume
command. `heavy` follows `/ticket-build`'s larger explicit cap. `--skip-local-verify` skips health
only on explicit user instruction.

After delivery, persist the final-tree SHA, health evidence, build/review artifacts, and delivery
checkpoint. Start deploy/verify in another fresh no-history agent with only that checkpoint and the
active epic packet reference when applicable.

### 4. Deploy and verify

If `--no-land` or target `none`, stop after locally verified delivery and report remaining commands.

**Standalone, staging target (default):**

```text
/ticket-deploy <ID> staging        # without the prod argument
/ticket-deploy <ID> full           # with the prod argument
```

`/ticket-deploy` owns the entire leg: `/auto-deploy` staging deploy, staging evidence
verification, and — `full` only, gated on exact staging `PASS` — promotion, production deploy,
production verification, incident cleanup, and `completed`. Relay its terminal report and stop
conditions verbatim. A staging `FAIL` or agent-resolvable `BLOCKED` is not immediately terminal:
`/ticket-deploy` applies `staging-autonomy.md`, executes bounded operational prerequisites directly,
and may run one product repair/redeploy/reverify cycle on `direct`/`standard`, or up to three on
explicit `heavy`. Relay a stop only after PASS, the applicable cumulative cap is exhausted, or the
child proves `human_required`/`external_wait`. Do not convert a documented staging seed, fixture,
registration, deploy, or other deterministic repair into a request for the user to invoke a command.

**Standalone, direct-production target:** `/ticket-deploy <ID> prod` (its §4a gate re-checks
risk and asks for confirmation when the diff is not tiny/safe).

**Epic step:** epic steps do not use `/ticket-deploy`. Land/merge the step into the milestone
integration branch and set the step to `merged`. A milestone may contain multiple steps whose
runtime surfaces must be deployed **together**, so the deploy + cross-step gate is a
**milestone-level operation owned by `/milestone-flow`**, never a per-step one. ticket-flow does
not deploy a single step's runtime surface in isolation and does not run the milestone gate
itself.

The deploy must still happen, though — a direct `/ticket-flow` run on an epic step must **not**
dead-end at `merged` with the milestone left undeployed:

- **Delegated run** (invoked by `/milestone-flow` with `--epic-context`): land + set `merged` and
  stop. `/milestone-flow` owns the whole-milestone deploy + gate once every step is merged.
- **Direct run** (a human runs `/ticket-flow <step>` itself, no `--epic-context`): land + set
  `merged`, then **continue into the deploy instead of stopping**. If this landing makes the
  milestone complete (every sibling step ticket in the milestone is now `merged`), invoke
  `/milestone-flow <EPIC_ID> <MILESTONE>` — which deploys the milestone to staging and runs the
  gate — so the `/ticket-flow` run includes the deploy. If sibling steps are still open, do
  **not** deploy a partial milestone: stop at `merged` and report that `/milestone-flow` will
  deploy + verify once the remaining steps land.

Epic-specific invariants (hold on both paths):

- the target is the milestone/integration branch (usually `staging`), never a solo production
  landing — production promotion of epic steps is owned by `/epic-flow` /
  `/ticket-promote --epic` after all milestone gates pass;
- the runtime deploy steps that produce milestone evidence (`prefect deploy`, scheduler/worker
  registration, canary/observer runs, DAG syncs, runtime blocks) and the cross-step gate
  (`/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote
  --produce-evidence`) run **inside
  `/milestone-flow`**, whether it was reached via `/epic-flow` or via the direct-run hand-off
  above. ticket-flow never runs them directly.

A `merged` epic step alone is not proof the milestone is deployed or verified; only the
`/milestone-flow` gate PASS proves that.

### 4a. Fanout and phase rotation contract

Fanout is conditional, not a checklist. A separate investigator exists only on `heavy` for a bug
without a proven root cause; compact diagnosis stays with the delivery owner. The compact path has
one delivery owner; only `standard` adds one general review wave. A verifier exists only for an
actual environment gate, so delegated epic steps have none. Every
additional role cites a recorded trigger in `fanout_budget`. A same-risk repair uses one repair
owner and no re-review. Reset to full/heavy review, retain the matching specialist, and name the
new boundary when the diff first crosses security, auth, runtime protocol, migration,
destructive-data, or browser-patch risk.
The same budget records activation/contract keys and prior staging revision IDs; from revision
three it is invalid without the prior failure class and exact contract delta. This preflight runs
before builder dispatch, not after another code mutation.

Planning, build/review/local verification, and deploy/environment verification are durable phase
boundaries. Before every active phase dispatch, write an envelope with
`contract_profile: "ticket-flow"`, the validated runtime `context_receipt`, `fanout_budget`, and
`run_budget`, then run:

```bash
bin/phase-contract ticket-dispatch <envelope.json>
```

The `ticket-run-budget-v1` envelope reserves exactly one delegated model session. Its
`activation_key` must match `fanout_budget.activation_key`; that binds all resumes to the same
source/plan/diff activation instead of letting a new conversation mint another allowance. Persist
the new receipt before starting the session. Every replacement generation, failed launch, review,
waiter leaf, verifier, and repair owner gets a unique session id; resuming keeps the same `run_id`.
The validator enforces:

| Intensity | Delivery sessions | Environment sessions when applicable | Repair cycles |
|---|---:|---:|---:|
| `direct` | 2 | 6 | 1 |
| `standard` | 3 | 6 | 1 |
| `heavy` | 12 | 12 | 3 |

The required reservation shape is:

```json
{
  "contract_version": "ticket-run-budget-v1",
  "ticket_id": "F0123",
  "run_id": "<SHA-256 of ticket-run-budget-v1:ticket_id:activation_key>",
  "activation_key": "<same as fanout_budget.activation_key>",
  "intensity": "standard",
  "budget_scope": "delivery",
  "session_id": "<unique model session>",
  "session_role": "delivery_owner",
  "max_sessions": 3,
  "max_repair_cycles": 1,
  "intensity_escalation_reason": null,
  "starts_repair_cycle": false,
  "repair_cycle_id": null,
  "prior_receipt": null
}
```

**Durable receipt transport.** Store the command's exact `run_budget_receipt` JSON as the body of
one ticket `learning_report` artifact titled `run-budget <activation_key>`, with metadata
`kind: "ticket_run_budget"`, `contract_version: "ticket-run-budget-v1"`, `run_id`,
`activation_key`, and `state: "active"`. This is runtime state, not a retrospective. Create it after
the first reservation; for every later reservation, fetch that exact artifact, pass its parsed JSON
object inline as `prior_receipt`, and update it with `expected_updated_at` **before** spawning the
reserved session. A compare-and-set conflict means another dispatcher advanced the chain: do not
spawn; reload the exact artifact and either reserve a new unique session id once or stop on a second
conflict. Never materialize this ticket-owned receipt under `.context/`, and never use a local path
as the durable hand-off between cloud sessions. On terminal completion/exhaustion, update the same
artifact to `state: "terminal"`; a terminal `BUDGET_EXHAUSTED` artifact for the same activation is
returned as-is on resume. Only a changed activation key may start a new run.
`run_id` is the deterministic SHA-256 defined above, never a random/resume-specific id. If more than
one active artifact exists for that deterministic id, stop on an orchestration conflict rather than
choosing one or spawning.

Use `budget_scope: environment` and the matching canonical maximum only for deploy/wait/verifier
sessions. On a one-way intensity escalation, preserve the chain and set
`intensity_escalation_reason` to the named trigger; never create a new run id for the larger cap.
`fanout_budget` must carry the same `intensity` plus explicit
`investigation_required` and `environment_verification_required` booleans; its role counts follow
those facts rather than zero-filling mandatory agents.

Environment capacity covers one continuing deploy owner, the single deterministic waiter leaf when
needed, each verifier attempt, and an environment-scoped repair owner when needed. It is not
allocated for `--no-land` or individual epic-step delivery. A validator response with
`status: BUDGET_EXHAUSTED` is terminal for the run: persist the incomplete unit and exact resume
command; never rotate or start a new conversation to obtain a fresh counter.

Accept the phase result only after
`bin/phase-contract result <result.json> --dispatch <envelope.json>` passes. The ticket-dispatch
profile mechanically rejects all-history forks, unconditional investigator/verifier roles, excess
fanout without triggers, repeated same-version context receipts, missing delta/full-review
transitions, run-budget exhaustion, and these hard per-generation ceilings
(`max_packet_bytes: 16384`):

| Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed | Max rotations |
|---|---:|---:|---:|---:|---:|
| `planning` | 25 | 4 | 30 min | 50,000 | 1 |
| `build_review` | 40 | 12 | 60 min | 90,000 | 2 |
| `deploy_verify` | 20 | 8 | 45 min | 60,000 | 3 |

This table is the required fixed context/token budget. An observable first compaction is an
immediate `rotate_required` boundary. **Budgets are cumulative, not renewable:** rotation
continues a phase from its checkpoint, it does not grant a fresh full budget indefinitely. The
`Max rotations` column is the hard per-phase generation cap, mechanically enforced by
`bin/phase-contract ticket-dispatch` (a dispatch whose `rotation_generation` exceeds it is
rejected). When the last permitted generation ends without `complete`, persist the checkpoint and
stop with the exact resume command and the unresolved unit — the phase shape was wrong for the
work, and more generations spend hours confirming that.

On valid `rotate_required`, first reserve the replacement against the same cumulative run receipt.
If capacity remains, persist the receipt artifact, owning phase's MCP artifacts,
tree/landing/deploy state, and next immutable checkpoint before a fresh `fork_turns: "none"`
replacement. Resume at the first
incomplete unit; do not re-plan an accepted plan, rerun completed build todos, reopen resolved
findings, duplicate a landing/deploy, or rewrite verification evidence. The old owner receives no
follow-up work. If capacity does not remain, return `BUDGET_EXHAUSTED` rather than dropping a gate
or manufacturing another generation.

Each delegated phase uses the durable progress lease in `execution-economy.md`. The parent blocks
once, performs at most one expiry inspection, consumes a terminal result, renews at most once only
after checkpoint/tool-receipt advancement, and otherwise interrupts and rotates from the last
durable checkpoint. Sleep/paused/unknown is state evidence, not elapsed-time execution failure.

### 5. Status truth

Statuses are set by the owning phase skills, never duplicated here:

| Ticket kind | Path | Terminal status of this run |
|---|---|---|
| Standalone, default | `/ticket-deploy staging` | `staging_verified` (exact PASS) or the verify verdict's status |
| Standalone, `prod` argument | `/ticket-deploy full` | `completed` (or `prod_verified_needs_cleanup`) |
| Standalone, direct production | `/ticket-deploy prod` | `completed` |
| Epic step | integration branch landing | `merged` (or per `/milestone-flow` on the direct-run hand-off) |

If `/ticket-deploy` reports an `external_wait`/`human_required` deploy dependency, the ticket status
reflects the next verification state and the blocker lives in the ticket's independent blocker
metadata, not as a lifecycle status. `staging_safe`/`owner_repair` dependencies remain inside the
active staging workflow instead of appearing here as terminal blockers.

## Output

Load and apply `skills/references/terminal-outcomes.md` to the terminal result returned by the
owning deploy/verification workflow. Run the shared post-check once at the outer workflow boundary,
then put its single large outcome banner and details block before the format below. Preserve the
distinction between staging success, production success, partial epic landing, and final
closeability; only a clean production closeout with canonical `completed` status is
`## ✅ COMPLETED — READY TO CLOSE`.

**Evidence rules (apply to every variant below):** each PASS/complete line must be traceable
to concrete evidence — the command run, test counts, PR link, deploy output, artifact id.
End every report with an explicit "Not verified:" line listing anything claimed but not
exercised in this run. The user must never have to ask "did you actually do X?" — if X lacks
evidence, the report says so first.
Also report rotation count/reasons and productive, stall/sleep, and elapsed phase time when
available.

Standalone ticket, default (stops after staging verify):

```text
Ticket flow complete: F0123
Intensity: standard (bounded pattern fix; floor=none)
Phases: compact delivery PASS -> general review PASS -> /ticket-deploy staging
Landed: PR #456 -> staging
Staging verification: PASS (evidence artifact <id>)
Status: staging_verified

Not verified: production behavior (run /ticket-flow F0123 prod or /ticket-deploy F0123 prod)
```

Standalone ticket, `prod`:

```text
Ticket flow COMPLETE: F0123
Intensity: heavy (schema migration; floor=none)
Phases: heavy /ticket-plan -> /ticket-build -> /ticket-deploy full
Staging: PR #456, verify PASS (artifact <id>)
Production: promoted via /ticket-promote (PR #457), verify PASS (artifact <id>)
Status: completed
```

Epic step reports follow the §4 epic variants: state loudly whether the milestone was deployed
and gated (direct run completing the milestone) or is still partial (`merged`, NOT deployed yet),
so `merged` is never mistaken for "shipped".

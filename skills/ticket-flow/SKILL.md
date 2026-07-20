---
name: ticket-flow
description: >-
  Autonomous single-ticket execution with MCP ticket tracking: runs ticket-plan, ticket-build,
  and ticket-deploy in sequence. Default stops after staging verification; the optional `prod`
  argument continues through production promotion, verification, and completion.
max_turns: 300
---

# Ticket Flow

Autonomously execute **one ticket** from GitHub issue, existing F/B/R ticket, or conversation
context, by sequencing the three phase skills:

```text
/ticket-plan <ID>
/ticket-build <ID>
/ticket-deploy <ID> staging      # default
/ticket-deploy <ID> full         # when invoked as /ticket-flow <ID> prod
```

Ticket Flow is ticket-level only. It is not an epic orchestrator, but if the ticket is an epic
step it must load the parent epic context and honor the milestone contracts.

## Hard boundaries

- May create/resume exactly one ticket.
- Owns the standalone ticket delivery decision: **staging-first** for complex/risky/uncertain
  work, **direct-production** only for tiny safe work (and then only via `/ticket-deploy`'s
  direct-production gate, which asks for confirmation when the diff is not tiny/safe).
- Delegates all phase execution: planning to `/ticket-plan`, implementation to `/ticket-build`,
  deployment and environment verification to `/ticket-deploy` (which owns `/auto-deploy`,
  `/ticket-verify`, and `/ticket-promote`). Must not perform ad-hoc planning, build, deployment,
  or verification work outside those skills.
- Without the `prod` argument, stops after the staging verify leg — production promotion
  requires an explicit `/ticket-flow <ID> prod` or `/ticket-deploy <ID> prod|full`.
- Must not advance an epic/milestone gate; epic skills own that.
- Must not use `.context/` for ticket artifacts; use MCP artifacts.
- `/lfg` remains the ticketless/current-branch workflow and is not changed by this skill.

## References

Read before acting:

- `../references/execution-economy.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/execution-phases.md`
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
```

Invoking with `prod` is the explicit human authorization for production promotion/deploy after
an exact staging `PASS` (it maps to `/ticket-deploy <ID> full`). It also grants standing approval
for plan-conformant, deterministic, corroborated `gated_auto` review fixes and bounded
resolve/re-review rounds. This does not authorize product-intent changes, destructive scope
expansion, materially different tradeoffs, new secrets/schema/infrastructure/cost, or choosing
between unresolved reviewer recommendations.

Legacy names: `/auto-flow`, `/ticket-full-auto` (≈ `/ticket-flow <ID> prod`), and `/goal-flow`
are retired; route related ticket sets to per-ticket `/ticket-flow` runs or an epic.

## Delivery target selection

Choose the intended delivery target **before planning/building** so the verification strategy,
deployment guide, and risk controls match the path:

1. explicit `--target staging|production|prod|main|none` or `--no-land`;
2. existing PR base / branch ancestry, if a PR already exists;
3. epic milestone/integration target, for epic-step tickets only;
4. landing policy risk classification.

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

## Process

### 0. Resolve ticket and target

- Resolve project from `<!-- mem:project=X -->` and repo from git remote.
- If the ticket's `repo` does not match the current repo, switch only to an available linked
  Conductor directory for that repo after checking its git remote; otherwise stop and report the
  missing repo workspace. Do not implement a ticket for one repo inside another repo.
- If input is a ticket ID, load it once via `get_ticket(detail="full",
  artifact_types=["source", "investigation", "plan"], include_events=false)` and cache the
  response until the workflow changes one of those artifacts.
- If input is an issue/conversation, search existing tickets first; create a new ticket only
  when no matching non-terminal ticket exists.
- Detect epic-step context from explicit epic membership, `related`, `tags.related_epic`, or
  source text. If found, load `get_epic` once and cache its version plus the step's
  milestone/contracts. Consume the milestone's active shared packet from
  `.context/epic-flow/<EPIC_ID>/<MILESTONE>/current.json`; verify the referenced immutable packet's
  SHA-256 and record its version/hash in every phase result. Delegated phases receive only that
  packet path/version/hash plus their exact step scope, not copied epic history.
- On a direct epic-step entry, if the packet is absent, create the initial immutable version and
  atomic manifest from the bounded `get_epic` snapshot before planning. A delegated
  `--epic-context` run treats a missing packet as a caller-contract failure and returns to
  milestone-flow; it must not invent a sibling packet.
- If an epic-step phase identifies a specifically missing fact, request a new packet version from
  the owning milestone orchestrator. Reload MCP/source context only when the atomic current
  manifest advances or that exact missing fact is required. Never edit a published packet or let
  sibling ticket-flows create divergent milestone packets.
- Decide and record the delivery target using `landing-policy.md`.
- **Resume from lifecycle truth**: skip phases whose artifacts and status already exist (a
  `planned` ticket with a plan artifact enters at build; a built, locally verified ticket enters
  at deploy). Do not resume past a `verify_*_failed` status without a new explicit user
  instruction.

### 1. Gather context

**Single retrieval owner.** When §2 will invoke `/ticket-plan` (the standalone path), ticket-flow
must **not** run its own codebase research or memory/similar-ticket searches here — `/ticket-plan`
Phases 3-4 own knowledge retrieval (memory search across risk boundaries, codebase research,
similar-ticket search) and are the single source of truth for it. Duplicating those searches in
§1 wastes tokens and risks divergent context. `/ticket-plan` returns a **prior-knowledge blob**
(the applicable rules/patterns it retrieved); carry that blob forward into `/ticket-build` so
builders and reviewers inherit the same knowledge without re-searching.

§1 keeps only the context work that `/ticket-plan` does not do:

- Bug: investigate root cause first; for production incidents use hypothesis evaluation. (This
  triage feeds the plan; it is not the plan's knowledge retrieval.)
- Epic step: include the parent epic plan, milestone acceptance criteria, blockers, contracts,
  and the repo/path/branch mapping from `conductor-multi-repo.md` in the context passed to
  planning/build agents.

If a ticket takes a path that does **not** invoke `/ticket-plan`, run the memory/knowledge
retrieval here instead (search `mcp__autodev-memory__search` across the ticket's actual risk
boundaries — schema/defaults/raw SQL, decrypt-proxy/tailnet/auth, Prefect deployment/runtime,
encryption/plaintext fields, external API contracts — not just `search_tickets` /
`get_similar_tickets`), because the single owner must always run exactly once.

### 2. Plan

Run `/ticket-plan <ID>` (the single planning skill) with its complexity-based light/heavy gate.
Force deep planning when the ticket is an epic step, cross-repo contract consumer/provider,
schema/data change, or otherwise high risk. Heavy path only: adversarial plan critique until no
critical unresolved findings remain; peer planning follows `/ticket-plan`'s explicit
risk/uncertainty/disagreement escalation gate. The plan lands as an MCP `plan` artifact with
`summary_bullets` set on the ticket.

After planning, persist the plan artifact and prior-knowledge checkpoint. End the planning phase
agent and start build in a fresh `fork_turns: "none"` agent with only the plan/build packet. A
history fork is allowed only when a self-contained packet is genuinely impossible: record the
reason and use the smallest explicit numeric count of recent turns, never all history.

### 3. Build, review, locally verify

Run `/ticket-build <ID>`. It honors open dashboard review comments before building, creates
build todos via `/create-build-todos`, implements via `/build`, reviews via `/review`, resolves
via `/resolve-review`, enforces the artifact persistence gate, runs the local health gate, and
pushes the feature branch. With `--skip-local-verify`, pass that through (the health gate is
skipped only on explicit user instruction). Stop for unresolved design decisions.

After build, persist the final-tree SHA, health evidence, build/review artifacts, and delivery
checkpoint. Start deploy/verify in another fresh no-history agent with only that checkpoint and the
active epic packet reference when applicable.

### 4. Deploy and verify

If `--no-land` or target `none`, stop after `/ticket-build` and report remaining commands.

**Standalone, staging target (default):**

```text
/ticket-deploy <ID> staging        # without the prod argument
/ticket-deploy <ID> full           # with the prod argument
```

`/ticket-deploy` owns the entire leg: `/auto-deploy` staging deploy, staging evidence
verification, and — `full` only, gated on exact staging `PASS` — promotion, production deploy,
production verification, incident cleanup, and `completed`. Relay its terminal report and stop
conditions verbatim; do not retry past a `FAIL`/`BLOCKED` verdict.

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
  (`/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote`) run **inside
  `/milestone-flow`**, whether it was reached via `/epic-flow` or via the direct-run hand-off
  above. ticket-flow never runs them directly.

A `merged` epic step alone is not proof the milestone is deployed or verified; only the
`/milestone-flow` gate PASS proves that.

### 4a. Phase rotation budget

Planning, build/review/local verification, and deploy/environment verification are durable phase
boundaries. Choose and record a fixed context/token budget for each phase owner. Force a checkpoint
and fresh `fork_turns: "none"` replacement after the first compaction or when the budget is reached,
whichever comes first. The replacement receives only the durable checkpoint and phase packet.
Never continue an indefinitely growing agent merely because it still responds.

### 5. Status truth

Statuses are set by the owning phase skills, never duplicated here:

| Ticket kind | Path | Terminal status of this run |
|---|---|---|
| Standalone, default | `/ticket-deploy staging` | `staging_verified` (exact PASS) or the verify verdict's status |
| Standalone, `prod` argument | `/ticket-deploy full` | `completed` (or `prod_verified_needs_cleanup`) |
| Standalone, direct production | `/ticket-deploy prod` | `completed` |
| Epic step | integration branch landing | `merged` (or per `/milestone-flow` on the direct-run hand-off) |

If `/ticket-deploy` reports an external/manual deploy dependency, the ticket status reflects the
next verification state and the blocker lives in the ticket's independent blocker metadata, not
as a lifecycle status.

## Output

**Evidence rules (apply to every variant below):** each PASS/complete line must be traceable
to concrete evidence — the command run, test counts, PR link, deploy output, artifact id.
End every report with an explicit "Not verified:" line listing anything claimed but not
exercised in this run. The user must never have to ask "did you actually do X?" — if X lacks
evidence, the report says so first.

Standalone ticket, default (stops after staging verify):

```text
Ticket flow complete: F0123
Phases: /ticket-plan PASS -> /ticket-build PASS -> /ticket-deploy staging
Landed: PR #456 -> staging
Staging verification: PASS (evidence artifact <id>)
Status: staging_verified

Not verified: production behavior (run /ticket-flow F0123 prod or /ticket-deploy F0123 prod)
```

Standalone ticket, `prod`:

```text
Ticket flow COMPLETE: F0123
Phases: /ticket-plan -> /ticket-build -> /ticket-deploy full
Staging: PR #456, verify PASS (artifact <id>)
Production: promoted via /ticket-promote (PR #457), verify PASS (artifact <id>)
Status: completed
```

Epic step reports follow the §4 epic variants: state loudly whether the milestone was deployed
and gated (direct run completing the milestone) or is still partial (`merged`, NOT deployed yet),
so `merged` is never mistaken for "shipped".

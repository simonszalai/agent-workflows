---
name: ticket-flow
description: >-
  Autonomous single-ticket execution with MCP ticket tracking: runs ticket-plan, ticket-build,
  and ticket-deploy in sequence. Default stops after staging verification; the optional `prod`
  argument continues through production promotion, verification, and completion.
max_turns: 60
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
- Must always produce a plan MCP artifact before build (every intensity, including `direct`).
- Ticketless ultra-light edits are `/go-fable`, not this skill. There is no `/lfg`.

## References

Read before acting:

- `../references/execution-economy.md`
- `../references/execution-intensity.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/environment-topology.md`
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
/ticket-flow F0123 --intensity direct|standard|heavy
/ticket-flow F0123 --light         # alias → intensity direct
/ticket-flow F0123 --deep          # alias → intensity heavy
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
  `get_ticket(detail="light", include_events=false)`, cache `context_version` plus exact artifact
  IDs, and fetch only the required source/investigation/plan bodies by artifact ID. A refresh must
  send the cached version and is valid only when a new `context_version` is returned.
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
  parse `--intensity` / `--light` / `--deep`; apply epic-step floor (`standard` minimum when
  `--epic-context` or epic membership is present); raise to `heavy` on safety surfaces. Write
  `intensity`, `intensity_reason`, and `intensity_floor` into every phase envelope and child
  packet. Escalate only if later phases discover a new floor trigger; never silently downgrade.
  Intensity never skips the plan artifact.
- **Resume from lifecycle truth**: skip phases whose artifacts and status already exist (a
  `planned` ticket with a plan artifact enters at build; a built, locally verified ticket enters
  at deploy). Do not resume past a `verify_*_failed` status without a new explicit user
  instruction. When resuming at build, re-derive intensity from the packet or the same gate and
  pass it into `/ticket-build`.
- For a Hermes-origin ticket, consume only server-returned pickup/approval truth. The restricted
  principal cannot self-approve or set execution statuses; an admin approval pair authorizes the
  current live plan, and any later Hermes edit clears it. Do not add a client-side origin filter or
  carry a cached approval past an edit.

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

Maintain one runtime context receipt for the ticket. It records the light manifest read(s), direct
artifact IDs/hashes, bounded excerpts/packet hashes passed to children, and canonical artifact
updates. Validate it with
`bin/workflow-ticket-context-check receipt <receipt.json>` before each phase dispatch. Repeated
same-version reads fail. Plan and deployment-guide updates are bounded replacements; their older
revisions remain in MCP artifact history, not appended to the current body.

### 2. Plan

Run `/ticket-plan <ID>` with the recorded intensity packet (`intensity`, `intensity_reason`,
`intensity_floor`). `/ticket-plan` maps intensity to its light/heavy path and **always**
persists an MCP `plan` artifact (including `direct`). Force `heavy` when the intensity gate or
floor says so (epic step floor, cross-repo contract, schema/data, other high risk). Heavy path
only: adversarial plan critique until no critical unresolved findings remain; peer planning
follows `/ticket-plan`'s explicit risk/uncertainty/disagreement escalation gate. Set
`summary_bullets` on the ticket.

After planning, persist the plan artifact and prior-knowledge checkpoint. End the planning phase
agent and start build in a fresh `fork_turns: "none"` agent with only the plan/build packet
including intensity fields. A history fork is allowed only when a self-contained packet is
genuinely impossible: record the reason and use the smallest explicit numeric count of recent
turns, never all history.

### 3. Build, review, locally verify

Run `/ticket-build <ID>` with the same intensity packet. It honors open dashboard review comments
before building, materializes build todos per intensity (`direct` minimal; `standard`/`heavy`
via `/create-build-todos`), implements via `/build`, reviews via `/review`, resolves via
`/resolve-review`, enforces the artifact persistence gate, runs the local health gate per
intensity, and pushes the feature branch. With `--skip-local-verify`, pass that through (the
health gate is skipped only on explicit user instruction). Stop for unresolved design decisions.

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

### 4a. Fanout and phase rotation contract

The default per-ticket shape is one investigator, one builder chain, one review wave, and one
verifier. Every additional role must cite a recorded escalation trigger in the phase envelope's
`fanout_budget`. A same-risk follow-up revision uses exactly one delta builder and one delta
reviewer. Reset to full/heavy review, retain the matching specialist, and name the new boundary
when the diff first crosses security, auth, runtime protocol, migration, destructive-data, or
browser-patch risk. Economy never removes specialist coverage for a genuinely new boundary.
The same budget records activation/contract keys and prior staging revision IDs; from revision
three it is invalid without the prior failure class and exact contract delta. This preflight runs
before builder dispatch, not after another code mutation.

Planning, build/review/local verification, and deploy/environment verification are durable phase
boundaries. Before every active phase dispatch, write an envelope with
`contract_profile: "ticket-flow"`, the validated runtime `context_receipt`, and `fanout_budget`,
then run:

```text
bin/phase-contract ticket-dispatch <envelope.json>
```

Accept the phase result only after
`bin/phase-contract result <result.json> --dispatch <envelope.json>` passes. The ticket-dispatch
profile mechanically rejects all-history forks, excess fanout without triggers, repeated
same-version context receipts, missing delta/full-review transitions, and these hard
per-generation ceilings (`max_packet_bytes: 16384`):

| Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed |
|---|---:|---:|---:|---:|
| `planning` | 30 | 4 | 45 min | 60,000 |
| `build_review` | 40 | 12 | 60 min | 90,000 |
| `deploy_verify` | 20 | 8 | 45 min | 60,000 |

This table is the required fixed context/token budget. An observable first compaction is an
immediate `rotate_required` boundary.

On valid `rotate_required`, persist the owning phase's MCP artifacts, tree/landing/deploy state, and
next immutable checkpoint before a fresh `fork_turns: "none"` replacement. Resume at the first
incomplete unit; do not re-plan an accepted plan, rerun completed build todos, reopen resolved
findings, duplicate a landing/deploy, or rewrite verification evidence. The old owner receives no
follow-up work. Safety coverage is unchanged: rotate and continue rather than dropping a health,
review, deploy, or verification gate.

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

If `/ticket-deploy` reports an external/manual deploy dependency, the ticket status reflects the
next verification state and the blocker lives in the ticket's independent blocker metadata, not
as a lifecycle status.

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
Phases: /ticket-plan PASS -> /ticket-build PASS -> /ticket-deploy staging
Landed: PR #456 -> staging
Staging verification: PASS (evidence artifact <id>)
Status: staging_verified

Not verified: production behavior (run /ticket-flow F0123 prod or /ticket-deploy F0123 prod)
```

Standalone ticket, `prod`:

```text
Ticket flow COMPLETE: F0123
Intensity: heavy (schema migration; floor=none)
Phases: /ticket-plan -> /ticket-build -> /ticket-deploy full
Staging: PR #456, verify PASS (artifact <id>)
Production: promoted via /ticket-promote (PR #457), verify PASS (artifact <id>)
Status: completed
```

Epic step reports follow the §4 epic variants: state loudly whether the milestone was deployed
and gated (direct run completing the milestone) or is still partial (`merged`, NOT deployed yet),
so `merged` is never mistaken for "shipped".

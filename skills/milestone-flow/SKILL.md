---
name: milestone-flow
description: Execute one epic milestone's step-ticket DAG, deploy the milestone to staging, and run the explicit epic/milestone verification gate.
max_turns: 100
---

# Milestone Flow

Execute one milestone of an epic. This is the milestone-level orchestrator over multiple
`/ticket-flow` runs. It is normally called by `/epic-flow`, but may also be entered directly by a
`/ticket-flow` run that lands a milestone's **final** step (the direct-run hand-off — see
`ticket-flow` §5), or invoked manually. It owns the full milestone gate: build step tickets,
deploy the parent epic/milestone integration target, and verify the epic/milestone evidence
contract before returning success.

If entered when every step ticket is **already `merged`** (e.g. via the ticket-flow hand-off, or
a re-run), do not rebuild merged steps — skip straight to the gate package, the staging deploy,
and the verifier. The deploy is idempotent, so re-entering after a partial run is safe.

## Boundaries

- Works on one epic milestone at a time.
- May run independent step tickets in parallel when safe.
- Must pass epic context and contracts into each ticket-flow.
- Must create/update a complete gate package after the step tickets land.
- Must deploy the parent epic/milestone target to staging after the gate package exists.
- Must run the explicit epic/milestone staging verifier after deployment.
- Stops successfully only after the milestone staging gate is `PASS` and required evidence
  artifacts exist.
- Does not promote to production or run production verification unless a separate production
  command explicitly owns that final epic gate.

## Usage

```text
/milestone-flow E0007 M2
/milestone-flow E0007 --next
/milestone-flow E0007 M2 --executor hermes   # place unresolved-repo steps via Hermes workspaces
```

`--executor` selects how step ticket-flows are placed and awaited per
`../references/conductor-multi-repo.md` §Executor modes: `local` (default; linked
directories + same-workspace `fork_turns: "none"` subagents) or `hermes` (one Conductor
workspace/session per unresolved step repo via the Hermes Conductor MCP). Auto-select `hermes`
only when the run was started by a Hermes scheduled agent. Everything else in this skill —
packets, waves, gates, budgets, evidence — is executor-independent.

## References

Read before acting on any cross-repo milestone or linked Conductor workspace:

- `../references/execution-economy.md`
- `../references/conductor-multi-repo.md`

## Process

### 1. Load milestone graph

- `get_epic(project, epic_id, detail="light")` for structure/manifests, then selected plan,
  deployment-guide, and verification bodies with `detail="full"`, explicit `artifact_types`, and
  an explicit `response_byte_budget`. Never load an unbounded all-body epic.
- This first response and its version are the run cache. Reuse it through wave construction and
  pass bounded milestone/step extracts to delegated ticket-flows; reload only after a workflow in
  this run mutates epic structure or gate artifacts.
- Resolve the milestone's active shared packet: the epic artifact titled
  `milestone-packet <EPIC_ID> <MILESTONE>` (artifact_type `deployment_guide`, metadata
  `kind: "milestone_packet"`). If direct entry finds none, create it from this bounded response
  using the `epic-flow` packet contract: the body's first line states `packet_version: v<NNN>` and
  `sha256: <hash of the exact body bytes>`. Publish a new version only via `update_artifact` (the
  artifact history keeps prior versions immutable); verify the recorded hash against the body
  before use. This milestone-flow is the sole packet writer while it owns the milestone. Packet
  readers must filter gate-package reads by title/metadata so the packet is never mistaken for the
  milestone gate package. Do not use `.context/` for the packet: hermes-executed children have no
  shared filesystem, and the artifact transport is the single mechanism for both executors.
- Give children only the packet artifact id, version, and SHA-256. Require every result/checkpoint
  to record that version/hash. Reload MCP/source data only when the packet version advanced or a
  child identifies one specifically missing fact. Update by publishing a new version with a new
  recorded hash; never duplicate epic history in a child prompt.
- Resolve milestone by display id (`M2`) or choose the first incomplete milestone for `--next`.
- Load all step tickets in that milestone.
- Read parent epic plan, milestone acceptance criteria, blockers, and contracts.

### 2. Validate readiness

Stop if:

- epic has unresolved planning open questions;
- any required blocker from an earlier milestone is not complete/merged;
- cross-repo contracts are missing;
- (`local` executor only) any step repo in the milestone cannot be resolved to the primary
  workspace, a linked Conductor directory, or an explicit user-provided repo root. Under
  `--executor hermes` an unresolved repo is not a stop: resolve it by creating a Conductor
  workspace per `conductor-multi-repo.md` §Executor modes;
- two same-repo steps are marked parallel but touch overlapping/conflicting areas;
- the milestone has no staging evidence contract. Ask `/epic-flow`/planning to repair the
  milestone before build work continues.
- the milestone evidence contract requires runtime/staging behavior (canary run, observer,
  flow, deployment, stored rows, polling, scheduler, worker, Prefect, supervisor, webhook, or
  live readback) but no included step owns the producing runtime surface. Repair the split before
  building; a schema/parser/model-only milestone cannot pass a stored-row or flow-run gate.

### 3. Build execution waves

Create waves from the blocker -> blocked DAG:

Before executing a wave, record each step's `repo -> path (or workspace/session id) -> branch ->
target/base` mapping. In `local` mode, do not start a repo's ticket-flow unless that repo root is
available and its current branch is the branch intended for that repo's step. In `hermes` mode,
create/reuse the step's Conductor workspace on that branch first and record its workspace id in
the mapping.

**Knowledge retrieval gate for the wave.** Before dispatching any step, run an
`mcp__autodev-memory__search` query per repo/risk-boundary represented in the wave (schema/raw SQL,
deploy/runtime, decrypt-proxy/tailnet/auth, encryption, external APIs, etc.) and brief the delegated
`/ticket-flow` with the relevant entries. This is separate from `get_ticket`/`get_epic` and
`search_tickets`: ticket artifacts explain planned work, while knowledge entries carry recurring
gotchas that must constrain the build. If no relevant entries are found, record that in the wave
handoff so later audits can distinguish "searched and none found" from "Codex/Grok skipped KB".

- independent different-repo steps may run in parallel;
- same-repo steps default to serial unless their write scopes are demonstrably disjoint;
- if unsure, serialize.

Every `local` ticket-flow dispatch uses `fork_turns: "none"` plus the active shared packet and its
exact step scope. A history fork is permitted only when a self-contained packet is genuinely
impossible; record the reason first and use the smallest explicit numeric count of recent turns.
Never use an all-history fork. Every `hermes` dispatch is one workspace + one session + one prompt
carrying the identical command line, packet artifact id/version/hash, knowledge briefing, and
result schema; a remote session is always packet-only (it has no parent history to fork), and it
is awaited under the same lease rules as a local leaf.

### 4. Execute each wave

For each step ticket that is **not already `merged`**, run `/ticket-flow <ID> --epic-context
--target staging` (or the milestone's configured integration target). Skip steps already
`merged` (e.g. when entered via the ticket-flow hand-off). The `--epic-context` flag is required:
it tells `/ticket-flow` it is delegated, so it lands only and does **not** hand back into
`/milestone-flow`. The dispatch carries the active shared-packet artifact id/version/hash rather
than copied parent context, plus `intensity_floor: standard` (raise to `heavy` when the step
plan/source names schema, auth, secrets, billing, deploy-config, or cross-repo contracts) per
`../references/execution-intensity.md`. Each non-skipped ticket-flow must:

- load the parent epic plan and milestone contract;
- build/review/local-verify the step;
- persist the step's durable audit trail **on the step ticket**: the `build_todo` and `review_todo`
  artifacts (plus a `plan` if the step needed its own). A step that lands with only a `source`
  artifact is not auditable — later `/retrospect` / `/autodev-wtf` cannot tell what was built or
  reviewed and wrongly reads it as "no workflow ran";
- land according to the milestone target;
- set the step ticket to `merged` after a successful epic-step landing;
- never run staging/production verification and never advance the milestone gate itself.

**Per-step audit gate (before §5).** After each wave, confirm via `get_ticket(detail="light",
artifact_types=["build_todo", "review_todo"], include_events=false)` that every landed
step ticket actually carries its `build_todo` and `review_todo` artifacts. A delegated
`/ticket-flow` — especially a cross-provider (Codex/Grok) run whose MCP `create_artifact` calls
silently no-op'd — can build, review, and land entirely in-session yet leave none of them on the
ticket (this is exactly how E0014 M3 / F0179 landed with only `source` + `verification_evidence`).
If any step is missing them, re-attach them from that step's build/review record before writing the
gate package; do not mark the milestone auditably complete with steps that have no build/review
trail.

### 5. Milestone gate package

After all step tickets in the milestone are `merged`, write an epic artifact (use
`deployment_guide` when the artifact type must be chosen) summarizing:

- milestone id and acceptance criteria;
- steps landed, ticket ids, commits/PRs, and repos touched, including each repo's path, branch,
  and target/base branch;
- contracts satisfied and any contract tests run;
- local checks and review results;
- staging and production evidence rows that `/ticket-verify --epic --milestone` must grade,
  with each row mapped to the step ticket(s) and contract edge(s) it verifies so per-ticket
  verification artifacts can be written without guesswork;
- a **runtime evidence closure** section for any runtime evidence row:
  `evidence row -> producing step ticket -> deployed object/command`. If the row expects a
  Prefect flow or canary, name the actual entrypoint, deployment YAML entry, supervisor
  registration if applicable, and the command that will create durable evidence. If the deployed
  object/command does not exist, do not mark the gate package complete; create/fix a step in the
  same milestone first.
- required evidence destinations for the later verifier: canonical milestone-gate artifact on the
  epic, full step-ticket `verification_evidence` artifacts, and compact epic summary artifact;
- risks for staging verification and likely failure-to-step mappings;
- the exact next command, normally
  the deploy/verify commands this same `/milestone-flow` is about to run.

### 6. Deploy the milestone staging gate

After the gate package exists and names real runtime producers, run the staging deploy for the
parent epic/milestone:

```text
/auto-deploy <EPIC_ID> staging
```

If project artifacts specify a milestone-scoped deploy selector, pass that selector through the
project's deployment command, but keep status/evidence ownership on the parent epic milestone. Do
not skip this because a PR is merged: merged code is not deployed runtime evidence.

Tests, builds, migrations, large diffs, deployment output, and other noisy commands in this flow or
its children must use `bin/compact-exec` (or an established equally compact stricter wrapper).
Preserve the full log on disk and read only bounded summaries/tails. Every failure must report the
wrapper's absolute `output_file` and exact `rerun_command`; never paste a full deployment log into
the milestone context.

Treat deployment as incomplete until the deployment mechanics are verified by `/auto-deploy`
(migrations/blocks/scheduler/worker/Prefect registrations/service deploys as applicable). If
deployment fails, record the blocker/failure on the epic or affected step ticket and stop; do not
run behavior verification against stale code.

### 7. Verify the milestone staging gate

Immediately after a successful deploy, run the explicit epic/milestone verifier:

```text
/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote
```

The verifier must write all required evidence destinations before the gate can advance:

- canonical milestone-gate `verification_evidence` artifact on the epic;
- full `verification_evidence` artifact on every included step ticket;
- compact epic-level verification summary artifact.

If any evidence destination is missing, treat the verifier result as not ready to advance and
re-run/fix the evidence write rather than marking the milestone complete.

### 8. Handle verifier verdicts

- `PASS`: confirm all evidence artifacts exist, confirm `/ticket-verify` updated the included
  step ticket statuses per the lifecycle (single owner — do not update them here), and return
  milestone success.
- `NEEDS_MORE_TIME`: persist the exact awaited condition, source-of-truth query, fixed interval,
  deadline/attempt cap, explicit success/failure predicates, and verifier resume command. Use
  `wait-prefect-flow` for a Prefect run; otherwise write one deterministic bounded poller under
  the run scratch directory. The poller alone performs repeated status reads and emits one compact
  terminal result. It must exit nonzero at the cap with the exact resume/retry command. Do not
  periodically re-run the model-driven verifier.
  Outside Conductor, run that poller in one blocking foreground call. In Conductor, dispatch only
  the exact deterministic poller command immediately to one fresh `fork_turns: "none"` leaf and
  make the parent block once for its terminal result. The parent never starts or polls a resumable
  process, polls the leaf, substitutes a CLI `--watch`, or performs repeated provider status reads.
  After a successful predicate, start one fresh verifier agent and grade once. On timeout, persist
  the gate state and resume command and report it; never claim milestone success. Repeated `wait`,
  `write_stdin`, `wait_agent`, GitHub/Prefect/Render reads, or other model status checks are
  prohibited.
- `FAIL`: identify or create fix ticket(s) inside the same milestone, run `/ticket-flow` on those
  fixes with epic context, refresh the gate package, redeploy staging, and re-run the verifier.
  Use one fresh no-history repair owner per round and persist the failure class, contract delta,
  attempted fix, and round across rotations. Continue for up to three repair/redeploy/reverify
  rounds — each round is a full ticket-flow plus deploy plus gate, so three failed rounds mean the
  milestone's diagnosis is wrong, not that a fourth attempt is due.
  Stop earlier only for genuinely missing human information/authorization or an external condition
  no agent can change; otherwise stop only if round 3 still fails.

Do not leave deployment or verification to `/epic-flow`; `/milestone-flow` owns them for the
milestone it was asked to execute.

### 9. Durable phase checkpoints and rotation

Treat readiness, each execution wave, the gate package, staging deploy, and staging verification as
durable phase boundaries. At each boundary, persist the canonical step/epic artifact and the
current packet artifact version. Apply the validated dispatch/result/rotation contract in `execution-economy.md`
with `max_packet_bytes: 16384` and these default hard per-generation budgets:

| Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed |
|---|---:|---:|---:|---:|
| readiness | 30 | 3 | 45 min | 60,000 |
| one execution wave | 80 | 8 | 180 min | 160,000 |
| gate package | 35 | 3 | 60 min | 70,000 |
| staging deploy | 40 | 4 | 180 min | 80,000 |
| staging verification | 60 | 6 | 180 min | 120,000 |

This table is the required fixed context/token budget. An observable first compaction is an
immediate `rotate_required` boundary.

An execution wave with more than eight safe step checkpoints must be split into generations. On a
valid `rotate_required`, persist every returned per-step completion before dispatching a fresh
`fork_turns: "none"` replacement with only the next immutable packet/checkpoint. Start at the first
incomplete step or evidence row. The old owner receives no follow-up work; merged steps, deploy
state, review records, and written verification evidence are never replayed.

Each owner runs under the `execution-economy.md` durable progress lease: one bounded parent block,
one expiry inspection, and at most one renewal only when a checkpoint/tool receipt advanced.
Terminal-at-expiry is consumed; stale progress or the hard absolute deadline interrupts and rotates.
Represent sleep/paused/unknown truthfully and never infer execution failure from elapsed time alone.

## Output

Load and apply `skills/references/terminal-outcomes.md` after the milestone verifier and final
artifact/status re-read. Run the shared post-check and put one large banner plus details block
before the format below. A passed milestone gate uses `## ✅ STAGING VERIFIED` with the later
milestone/production work called out under `Not verified`; a failed deploy or verification uses
the matching red-X banner and includes partial step/ticket changes and the safest resume action.

```text
Milestone flow complete: E0007 M2
Executor: local | hermes (workspace/session ids for any hermes-placed steps)
Steps: 3/3 merged
Gate package: deployment_guide artifact updated
Deploy: PASS (/auto-deploy E0007 staging)
Environment verify: PASS (/ticket-verify staging --epic E0007 --milestone M2 --no-promote)
Gate evidence: verification_evidence artifact ids recorded
Rotations: {count}; reasons: {reason counts}; productive/stall/elapsed: {when available}

Next: /epic-flow continues with the next milestone, or production promotion after all milestones pass.
```

---
name: milestone-flow
description: Execute one epic milestone's step-ticket DAG, deploy the milestone to staging, and run the explicit epic/milestone verification gate.
max_turns: 400
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
```

## References

Read before acting on any cross-repo milestone or linked Conductor workspace:

- `../references/execution-economy.md`
- `../references/conductor-multi-repo.md`

## Process

### 1. Load milestone graph

- `get_epic(project, epic_id)`. `get_epic` responses are often large (tens of KB) and may
  be spilled to a file — read with `jq` / offsets; don't try to swallow the whole payload.
- This first response and its version are the run cache. Reuse it through wave construction and
  pass bounded milestone/step extracts to delegated ticket-flows; reload only after a workflow in
  this run mutates epic structure or gate artifacts.
- Resolve the milestone's active shared packet from
  `.context/epic-flow/<EPIC_ID>/<MILESTONE>/current.json`. If direct entry has no packet, create it
  from this bounded response using the `epic-flow` packet contract: immutable `packets/v<NNN>.md`,
  SHA-256 of its exact bytes, and an atomically renamed current manifest. Verify the hash before
  use. This milestone-flow is the sole packet writer while it owns the milestone.
- Give children only the active packet path, version, and SHA-256. Require every result/checkpoint
  to record that version/hash. Reload MCP/source data only when the manifest version changed or a
  child identifies one specifically missing fact. Update by publishing a new immutable version and
  atomically advancing the manifest; never mutate the active packet or duplicate epic history in a
  child prompt.
- Resolve milestone by display id (`M2`) or choose the first incomplete milestone for `--next`.
- Load all step tickets in that milestone.
- Read parent epic plan, milestone acceptance criteria, blockers, and contracts.

### 2. Validate readiness

Stop if:

- epic has unresolved planning open questions;
- any required blocker from an earlier milestone is not complete/merged;
- cross-repo contracts are missing;
- any step repo in the milestone cannot be resolved to the primary workspace, a linked Conductor
  directory, or an explicit user-provided repo root;
- two same-repo steps are marked parallel but touch overlapping/conflicting areas;
- the milestone has no staging evidence contract. Ask `/epic-flow`/planning to repair the
  milestone before build work continues.
- the milestone evidence contract requires runtime/staging behavior (canary run, observer,
  flow, deployment, stored rows, polling, scheduler, worker, Prefect, supervisor, webhook, or
  live readback) but no included step owns the producing runtime surface. Repair the split before
  building; a schema/parser/model-only milestone cannot pass a stored-row or flow-run gate.

### 3. Build execution waves

Create waves from the blocker -> blocked DAG:

Before executing a wave, record each step's `repo -> path -> branch -> target/base` mapping.
Do not start a repo's ticket-flow unless that repo root is available and its current branch is the
branch intended for that repo's step.

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

Every ticket-flow dispatch uses `fork_turns: "none"` plus the active shared packet and its exact
step scope. A history fork is permitted only when a self-contained packet is genuinely impossible;
record the reason first and use the smallest explicit numeric count of recent turns. Never use an
all-history fork.

### 4. Execute each wave

For each step ticket that is **not already `merged`**, run `/ticket-flow <ID> --epic-context
--target staging` (or the milestone's configured integration target). Skip steps already
`merged` (e.g. when entered via the ticket-flow hand-off). The `--epic-context` flag is required:
it tells `/ticket-flow` it is delegated, so it lands only and does **not** hand back into
`/milestone-flow`. The dispatch packet carries the active shared-packet path/version/hash rather
than copied parent context. Each non-skipped ticket-flow must:

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
  `bin/wait-prefect-flow` for a Prefect run; otherwise write one deterministic bounded poller under
  the run scratch directory. The poller alone performs repeated status reads and emits one compact
  terminal result. It must exit nonzero at the cap with the exact resume/retry command. Do not
  periodically re-run the model-driven verifier.
  Run that poller in one blocking foreground call. If the harness would yield, send only the poller
  to one fresh `fork_turns: "none"` leaf and make the parent block once for its terminal result.
  After a successful predicate, start one fresh verifier agent and grade once. On timeout, persist
  the gate state and resume command and report it; never claim milestone success. Repeated `wait`,
  `write_stdin`, `wait_agent`, GitHub/Prefect/Render reads, or other model status checks are
  prohibited.
- `FAIL`: identify or create fix ticket(s) inside the same milestone, run `/ticket-flow` on those
  fixes with epic context, refresh the gate package, redeploy staging, and re-run the verifier.
  Stop only for a genuine external/manual blocker or the same unresolved failure repeating after
  the documented retry/fix loop.

Do not leave deployment or verification to `/epic-flow`; `/milestone-flow` owns them for the
milestone it was asked to execute.

### 9. Durable phase checkpoints and rotation

Treat readiness, each execution wave, the gate package, staging deploy, and staging verification as
durable phase boundaries. At each boundary, persist the canonical step/epic artifact and active
packet manifest, then start the next phase in a fresh `fork_turns: "none"` agent with only its
packet/checkpoint. Choose and record a fixed context/token budget before each phase. Force rotation
after the first compaction or when that budget is reached, whichever happens first; never continue
an indefinitely growing agent merely because it still responds.

## Output

Load and apply `skills/references/terminal-outcomes.md` after the milestone verifier and final
artifact/status re-read. Run the shared post-check and put one large banner plus details block
before the format below. A passed milestone gate uses `## ✅ STAGING VERIFIED` with the later
milestone/production work called out under `Not verified`; a failed deploy or verification uses
the matching red-X banner and includes partial step/ticket changes and the safest resume action.

```text
Milestone flow complete: E0007 M2
Steps: 3/3 merged
Gate package: deployment_guide artifact updated
Deploy: PASS (/auto-deploy E0007 staging)
Environment verify: PASS (/ticket-verify staging --epic E0007 --milestone M2 --no-promote)
Gate evidence: verification_evidence artifact ids recorded

Next: /epic-flow continues with the next milestone, or production promotion after all milestones pass.
```

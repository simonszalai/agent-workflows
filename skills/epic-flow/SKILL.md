---
name: epic-flow
description: Fully autonomous epic orchestrator. Plans/splits, runs milestone flows that deploy and verify each staging gate, then promotes/deploys/verifies production when explicitly authorized.
max_turns: 100
---

# Epic Flow

End-to-end epic execution coordinator. Use this when the user asks to run an epic, execute an
entire epic, continue across milestones, or do it without further human intervention.

The user entrypoint remains `/epic-flow`; this skill invokes the deterministic contract binaries
itself. Do not ask the user to construct or run budget envelopes manually.

## Operating modes

`/epic-flow` has three modes:

- **Full-auto** — enabled by `--full-auto` or by an explicit user request like "execute the whole
  epic" / "without me". This mode is authorized to invoke milestone-flow, which itself deploys and
  verifies each staging gate, plus production promotion and final verification after all milestone
  gates pass.
- **Gate-stop** — enabled by `--stop-at-gates` or by an ambiguous/manual request. This mode plans,
  splits, and stops before invoking a milestone gate if the user has not authorized deploy/verify.
  Do not call `/milestone-flow` in gate-stop as a "build-only" substitute; milestone-flow is a
  deploy+verify command.
- **Production-only** — selected only when `bin/environment-capability` resolves an exact topology
  entry with `staging_available: false`, `verification_environment: production`, a matching
  approved verifier mode, an explicitly production-only acceptance contract, and explicit user
  authorization. It runs production milestone gates instead of inventing staging. Never select
  this mode because staging is down, absent from a deploy, or unreachable.

Never silently choose gate-stop when the user explicitly asked for a hands-off/full-auto epic.
Never advance to a later milestone until the current milestone's selected environment gate has
passed. That is staging normally; in production-only mode it is the exact production gate verdict.
Unknown or missing topology remains fail-closed on the normal staging-first path.

## This skill does not own design

`/epic-flow` orchestrates **sequencing, packaging, milestone boundaries, gates, deploy order, and
fix loops**. It must never edit an epic or step-ticket `plan` artifact's *design* — the mechanism,
API, transport, concurrency shape, or optimisation a step uses — directly with `update_artifact`.
If normalization or a readiness re-check concludes the design must change, route it through
`/epic-plan` (or `/epic-split` for step decomposition), which owns source traceability, the
critic panel, and the citation rules for user-attributed decisions. Recording a gate verdict,
milestone assignment, DAG edge, or deploy note on an artifact is in scope; rewriting what the
code should do is not.

This boundary exists because E0027's F0296 step plan was rev'd from "pre-warm the first record to
completion" to "release the fan-out on the first streamed delta" by this skill's orchestrator
under a composite "rev 4 amendment" change note. No source ticket asked for it, no critic saw it,
it became a milestone gate criterion and a required test, and it never worked in staging.

## Usage

```text
/epic-flow E0007 --full-auto       # run the whole epic, including gates
/epic-flow E0007                   # infer full-auto only if the user's request authorized it
/epic-flow E0007 --staging-only    # stop after every milestone is staged and verified
/epic-flow E0007 --milestone M2    # run one milestone and its gate
/epic-flow E0007 --stop-at-gates   # plan/split/readiness only; stop before milestone-flow deploy+verify
/epic-flow E0007 --production-only # valid only after environment-capability passes every gate
/epic-flow E0007 --executor hermes # place unresolved-repo milestone steps via Hermes workspaces
```

`--executor` (`local` default, `hermes`) is passed through unchanged to every `/milestone-flow`
invocation; see `../references/conductor-multi-repo.md` §Executor modes. Auto-select `hermes` only
when the run was started by a Hermes scheduled agent. A Hermes-scheduled unattended run defaults
to `--staging-only`: production promotion under `--executor hermes` additionally requires the
explicit production authorization in the run's own instruction (a standing "full-auto" schedule is
not that authorization).

## References

Read before acting:

- `../references/execution-economy.md`
- `../references/epic-lifecycle.md`
- `../references/conductor-multi-repo.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/deployment-ownership.md`
- `../references/environment-topology.md`

## Full-auto process

### 1. Load and normalize the epic

- Resolve `(project, repo, surface)` through `bin/environment-capability` before choosing the
  environment route. Record its JSON result in the immutable milestone packet. Production-only
  selection requires `--production-contract`, `--user-authorized`, and the exact registered
  verifier mode; a non-passing or unknown result follows staging-first behavior.
- Load `get_epic(project, epic_id, detail="light")` for structure/manifests. Request only the
  needed `plan`, `deployment_guide`, or `verification_evidence` bodies with `detail="full"`,
  selected `artifact_types`, and an explicit `response_byte_budget`.
- Cache that response/version as the orchestration snapshot and pass bounded milestone extracts to
  milestone-flow. Reload only after `/epic-plan`, `/epic-split`, or a completed milestone mutates
  the epic; do not re-read the unchanged full epic between routing decisions.
- Create one active bounded, versioned shared packet per milestone as an **epic artifact** titled
  `milestone-packet <EPIC_ID> <MILESTONE>` (artifact_type `deployment_guide`, metadata
  `kind: "milestone_packet"`). The body's first line records `packet_version: v<NNN>` and
  `sha256: <hash of the exact body bytes>`; publish new versions only via `update_artifact`, whose
  history keeps prior versions immutable. Never store the packet under `.context/` — hermes-executed
  children have no shared filesystem, and the artifact transport is the single mechanism for both
  executors. Gate-package readers must filter by title/metadata so the packet is never mistaken
  for the milestone gate package.
- The packet contains only the parent plan/acceptance contract, step/DAG summary, repo/path/branch
  map, relevant knowledge, activation/deploy constraints, and required return/checkpoint schemas.
  Cap the packet body at 16 KiB; summarize or reference immutable artifact IDs/paths rather than
  exceeding the cap. Delegated work receives the packet artifact id, version, and SHA-256, not
  duplicated epic history. Every consumer verifies the hash and records the version/hash it used in
  its terminal result.
- Advance the packet version only when a source artifact, epic structure, contract, relevant
  knowledge, or completed milestone checkpoint changes. Consumers reload MCP/source context only
  after the packet version advances or when a specifically named missing fact is required. Route a
  missing-fact request to the orchestrator for a bounded packet update; do not independently reload
  the whole epic.
- Before the first milestone dispatch, classify every step and create one epic `learning_report`
  titled `run-budget <activation_key>` with metadata `kind: "epic_run_budget"` and body equal to the
  exact `epic-run-budget-v1` receipt. Derive its ceiling with
  `bin/phase-contract epic-budget <budget.json>`: delivery is `2 * direct_steps + 3 *
  standard_steps + 12 * heavy_steps`, milestone overhead is `6 * milestone_count`, and production
  adds `3` only when explicitly authorized. Initial `step_addition_reasons` must cover every
  classified step. Persist each emitted receipt with
  `expected_updated_at` before its reserved milestone/waiter/verifier/repair/production session
  starts. Each milestone packet references this artifact id/version/hash; it does not copy or reset
  the ledger.
- Import each step's latest `ticket-run-budget-v1` terminal receipt through `ticket_run_receipts`
  after the child returns; `reservation: null` is permitted only for that advancing roll-up. New fix
  tickets may enlarge the ceiling once through a named `step_addition_reasons` entry, and a step may
  only raise intensity through `step_intensity_escalation_reasons`. Each
  `step_activation_keys` value is fixed for the epic run and must match that ticket's receipt.
  `run_id` is the deterministic SHA-256 of
  `epic-run-budget-v1:epic_id:activation_key`; multiple active artifacts for it are a hard conflict.
  Resume, rotation, retry, packet version, and a new milestone session never add capacity. A
  same-activation `BUDGET_EXHAUSTED` receipt is terminal.

  ```json
  {
    "contract_version": "epic-run-budget-v1",
    "epic_id": "E0007",
    "run_id": "<SHA-256 of epic-run-budget-v1:epic_id:activation_key>",
    "activation_key": "<epic plan/step activation>",
    "step_intensities": {"F0101": "direct", "F0102": "standard"},
    "step_activation_keys": {"F0101": "<fixed>", "F0102": "<fixed>"},
    "step_addition_reasons": {
      "F0101": "planned M1 step",
      "F0102": "planned M2 step"
    },
    "step_intensity_escalation_reasons": {},
    "milestone_ids": ["M1", "M2"],
    "production_authorized": false,
    "production_authorization_reason": null,
    "max_sessions": 17,
    "ticket_run_receipts": [],
    "reservation": {
      "session_id": "<unique delegated session>",
      "session_role": "milestone_owner",
      "milestone_id": "M1",
      "starts_repair_cycle": false,
      "repair_cycle_id": null
    },
    "prior_receipt": null
  }
  ```
- If the epic spans multiple repos, resolve every involved repo to an actual Conductor workspace
  path or linked directory using `conductor-multi-repo.md`. Declare a repo missing only on
  **positive evidence of absence**: check the Conductor workspace map, linked directories inside
  the current workspace, and the sibling workspace paths named by `conductor-multi-repo.md`, and
  record the exact paths checked. A failed first lookup is not "missing" — false positives here
  have wrongly blocked milestones. Only after that full sweep still finds nothing: under the
  `local` executor, stop before invoking milestone-flow and report the missing repo/path
  requirement plus the checked paths; under `--executor hermes`, record the repo as
  hermes-placed — milestone-flow will create its Conductor workspace per
  `conductor-multi-repo.md` §Executor modes instead of stopping.
- If no canonical epic plan exists, or milestone pass conditions are missing/vague/stale, run
  `/epic-plan`; that skill owns synchronizing milestone gate criteria from source tickets and
  artifacts.
- If milestones, step tickets, dependency edges, cross-repo contracts, ticket-level plan
  artifacts, or step ticket `planned` statuses are missing or stale, run `/epic-split`.
- Re-check the plan after splitting. A milestone is valid only when it is an independently
  observable risk boundary: it has acceptance criteria, deployment-guide evidence for staging and
  production in normal mode (production evidence only in validated no-staging mode), and does not
  require unbuilt later milestones to pass its gate. If that is not true, improve the plan/split
  before building; do not paper over the gap with a fake gate.
- Before the first build, create and validate the non-mutating deployment/config ownership
  inventory. A fully autonomous straight-to-production run uses `mode="straight_to_prod"` and
  blocks on unresolved owners, missing owner workspaces, absent third-repo config steps, or an
  incomplete deployment guide. `--staging-only` uses `mode="staging_only"`: preserve the same gaps
  as `record_only` without falsely blocking unrelated staging work.

### 2. Walk milestones in order

For each milestone in dependency order:

1. If the milestone already has a recorded staging `PASS` and every included step still matches
   the verified commits, skip to the next milestone.
2. Run `/milestone-flow <EPIC_ID> <MILESTONE>` (appending `--executor hermes` when that mode is
   active) to execute the step-ticket DAG and environment gate.
   Normally that is the staging gate: `/auto-deploy <EPIC_ID> staging` then `/ticket-verify staging
   --epic <EPIC_ID> --milestone <MILESTONE> --no-promote`. In validated production-only mode, the
   immutable packet instead delegates the reviewed production deploy/verification command and
   verifier mode. Dispatch with `fork_turns: "none"` and only the active milestone packet
   artifact id/version/hash plus the exact command and result schema. The accumulated root thread never
   performs production verification or remediation piecemeal.
   Each milestone gets a new session even when the prior one ended cleanly and the next step uses
   the same repo. Reserve `session_role: "milestone_owner"` against the durable epic budget before
   dispatch. Never resume, follow up, or reuse a prior milestone owner. Consume only its compact
   terminal receipt plus durable artifact ids, update the next packet, and dispatch a new no-history
   owner.
3. Accept milestone success only when `/milestone-flow` reports the selected environment `PASS`
   (staging normally, production only after the mechanical capability gate) and artifact ids
   for all required evidence destinations:

   - canonical milestone-gate `verification_evidence` artifact on the epic;
   - full `verification_evidence` artifact on every included step ticket;
   - compact epic-level verification summary artifact.

   If any required artifact destination is missing, re-enter `/milestone-flow` or the verifier
   evidence-write path rather than marking the milestone complete.
   Likewise, do not surface a milestone staging `BLOCKED` result when its receipt says
   `repairability: staging_safe | owner_repair`: dispatch one fresh milestone owner at the same
   durable packet checkpoint so `staging-autonomy.md` can finish the bounded repair/reverify lane.
   Keep `external_wait` inside the deterministic wait lane. Surface `BLOCKED` only for proved
   `human_required`/`agent_incapable`; no-progress or budget exhaustion are `STOPPED`/`FAILED`.
4. For milestones after the first, ensure the milestone verifier included current-milestone
   evidence plus an impact-based regression subset from previously passed milestone gates. If a
   later milestone breaks earlier verified behavior, treat `/milestone-flow` as failed/incomplete
   and keep the fix loop inside that milestone before continuing.

### 3. Production promotion after all normal staging gates pass

After the final milestone has a staging `PASS`:

- If `--staging-only` is set — including its default under a Hermes-scheduled unattended run —
  stop and report that production was intentionally not touched.
- Immediately before promotion, rebuild the ownership inventory from current tracked files and
  workspaces with `mode="promotion"`, `recheck_of`, and `rechecked_at_epoch`, then validate it.
  Promotion blocks on any newly unresolved owner/workspace/guide gap.
- Otherwise run the ordered epic production promotion/deploy path:

  ```text
  /ticket-promote --epic <EPIC_ID>
  /ticket-verify production --epic <EPIC_ID>
  ```

Reserve each fresh production owner/waiter/verifier against the same epic receipt with
`session_role: "production_owner"`, `production_waiter`, or `production_verifier`. The validator
permits at most three and rejects them unless `production_authorized` was durably raised with the
current invocation's explicit authorization reason.

`/ticket-promote --epic` must promote only the verified epic step commits, in milestone
order, using isolated worktrees and the repo's production deployment instructions. It must not
silently include unrelated staging work. `/ticket-verify production --epic` is the final evidence
gate; mark the epic complete only after it passes.

In production-only mode, milestone owners already landed/deployed/verified the production gates
from immutable packets. Do not run a fictional staging promotion or duplicate the final production
verification. After the last production milestone PASS, re-read lifecycle/evidence truth and close
only when every required production gate artifact exists.

## Gate-stop process

When running with `--stop-at-gates`, do planning/splitting/readiness checks only, then stop before
calling `/milestone-flow` and print the exact command that would run the full deploy+verify gate:

```text
/milestone-flow <EPIC_ID> <MILESTONE>
```

Do not claim the milestone is complete until `/milestone-flow` actually runs and the selected
environment gate passes.

## Parallelism

Parallelism is delegated to `/milestone-flow`, which uses dependency waves and repo write
scope analysis. Never parallelize same-repo overlapping work just to save time.

Every delegated epic/milestone call uses `fork_turns: "none"` and the shared packet above. A
history fork is allowed only when a self-contained packet is genuinely impossible: record the
reason before dispatch and use the smallest explicit numeric count of recent turns. Never use an
all-history fork.

The root carries only durable receipts across milestone boundaries. Child commentary, tool logs,
watcher state, and conversation history are not copied into the next packet. This makes the fresh
session boundary effective rather than nominal.

## Phase checkpoints and rotation

Treat normalized plan/split, each milestone gate, and final production promotion/verification as
durable phase boundaries. Apply the validated dispatch/result/rotation contract in
`execution-economy.md`; prose-only or unspecified budgets are invalid. These are the default hard
per-generation budgets:

| Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed |
|---|---:|---:|---:|---:|
| normalize plan/split | 60 | 4 | 90 min | 100,000 |
| one milestone gate owner | 80 | 8 | 180 min | 160,000 |
| production promotion/verification | 60 | 6 | 180 min | 120,000 |

Use `max_packet_bytes: 16384`. If a milestone needs more than eight safe work-unit checkpoints,
slice it into bounded execution-wave generations rather than enlarging the session. Persist the
current epic artifact/checkpoint and packet artifact version at every safe boundary. A valid
`rotate_required` result causes an immediate fresh `fork_turns: "none"` replacement from the first
incomplete unit; the old owner gets no follow-up work. Preserve passed milestones, landing state,
deploy state, and verification artifacts rather than rerunning them.

Every phase dispatch also carries the durable progress lease from `execution-economy.md`. The
parent blocks once per lease. At expiry it performs one inspection only: terminal results are
consumed, one renewal is allowed only after checkpoint/tool-receipt advancement, and stale or
hard-deadline work is interrupted and rotated. Sleep/paused/unknown time is reported, not mislabeled
as execution failure.

Production-only phase owners are always fresh delegated generations from immutable packets. The
root is a thin coordinator: it validates topology, packet hashes, phase results, lifecycle state,
and evidence IDs, but performs no browser, deploy, fix, or status-read work itself.

Any production or epic remediation that changes code/config/auth becomes a new fix ticket/epic
step attached to the failed milestone. It must pass normal build, review, landing, config/secret
ownership, deploy, and re-verification stages. Never finish through ticketless `/go-fable`, an
untracked auxiliary branch, or a detached verifier implementation. Child step tickets receive
`intensity_floor: none`; epic membership alone is not a risk signal. Raise to `heavy` only when the
step itself names a safety surface per `../references/execution-intensity.md`.

## Output

Load and apply `skills/references/terminal-outcomes.md` at each terminal stop of the requested
epic run. After the final milestone or production action, run the shared post-check, re-read the
epic and affected step tickets, and put exactly one large outcome banner plus details block before
the report below. A clean final production PASS with canonical completed state uses
`## ✅ COMPLETED — READY TO CLOSE`; staging-only success uses `## ✅ STAGING VERIFIED`; gate-stop,
blocked, and failed runs use their accurate non-complete banner.

Always report:

- epic id, current mode (`full-auto` or `gate-stop`), and executor (`local` or `hermes`, with
  created workspace/session ids for hermes-placed steps);
- current milestone and gate verdict;
- step tickets and statuses changed;
- deploy/promote commands run and their evidence artifacts;
- for each verified milestone/final gate: canonical gate artifact id, per-step ticket evidence
  artifact ids, and compact epic summary artifact id;
- rotation count/reasons and productive, stall/sleep, and elapsed phase time when available;
- next automatic action or, if blocked, the exact blocker and safest resume command.

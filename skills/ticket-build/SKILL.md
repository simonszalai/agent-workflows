---
name: ticket-build
description: >-
  Implementation phase for one planned ticket: intensity-aware build todos, build, adaptive
  review, resolve findings, and the local health gates. Thin orchestrator over create-build-todos,
  build, write-tests, review, and resolve-review; does not plan, land, deploy, or verify
  environments.
max_turns: 100
---

# Ticket Build

Implement one ticket that already has a **plan MCP artifact**, through a locally verified tree
with all build/review artifacts persisted. This is an orchestrator over existing phase owners
(`/create-build-todos`, `/build`, `/write-tests`, `/review`, `/resolve-review`); it does not
reimplement them and does not land, merge, deploy, or run environment verification — those belong
to `/ticket-deploy`. Intensity (`direct` / `standard` / `heavy`) follows
`../references/execution-intensity.md`.

## Usage

```text
/ticket-build F0123
/ticket-build F0123 --intensity direct|standard|heavy
/ticket-build F0123 --light
/ticket-build F0123 --deep
```

## Prerequisites

- Ticket exists, non-terminal, with a **plan MCP artifact** (run `/ticket-plan` first otherwise).
  Missing plan is a hard stop at every intensity — never invent a plan here.
- Repo matches the ticket's `repo`; for epic steps, the caller (normally `/ticket-flow`) supplies
  the epic context extract and intensity floor.

## Process

Follow `../references/execution-phases.md`, `../references/execution-economy.md`, and
`../references/execution-intensity.md`.

1. **Load context once.** `get_ticket(detail="full", artifact_types=["source", "plan"],
   include_events=false)`; cache the response. Carry forward the planner's prior-knowledge blob
   into the build and review packets so builders and reviewers inherit the same knowledge without
   re-searching. Resolve intensity from the parent packet or standalone flags/gate; epic steps
   floor at `standard`. Record `intensity` / `intensity_reason` / `intensity_floor` on every
   child packet.
2. **Honor dashboard review comments.** Check `open_comment_count`; if the user left open review
   comments on the plan/source, resolve them (revise via `/ticket-plan` when the plan itself must
   change) before building. Do not build past unresolved feedback. There is no `approved` status;
   leaving `planned` means setting `in_progress`.
3. **Build todos (intensity-aware).** Always produce MCP `build_todo` artifacts (audit/resume):
   - **`direct`:** do **not** spawn the deep build-planner. Materialize minimal todos from the
     plan (one todo per clear plan step, or a single todo for a one-step plan): objective, files,
     acceptance, complexity tag. Finalize `deployment_guide` only when deploy shape is
     non-trivial; otherwise leave/skip draft with an explicit reason.
   - **`standard`:** invoke `/create-build-todos` (normal depth); a single-step plan may yield
     one deepened todo.
   - **`heavy`:** invoke `/create-build-todos` with deep research.
4. **Implement.** Invoke `/build`: partition the dependency DAG into coherent sequential builder
   chains, checkpoint every covered todo individually, and keep unrelated lint/type fixes in a
   separate commit. Builder-chain subagents implement only; they do not run validation.
5. **Write tests.** On `direct`, the builder chain writes focused tests in-chain when behavior
   changed — no separate test-writer agent. On `standard`/`heavy`, invoke `/write-tests` in
   orchestrator mode for the whole initial change set when behavior changed. The test-writing
   subagent writes tests but does not execute them.
6. **Pre-review health gate (main orchestrator only).** After all initial implementation and
   test-writing changes are present, run the canonical project health command exactly once. Record
   the PASS by `(tree SHA, exact command)`. On failure, do not repair from the bounded tail or from
   only the first failed layer. Inspect the complete `output_file` with bounded searches and build
   one **complete failure inventory** covering every failed subcommand, diagnostic category, and
   affected file. If the canonical command short-circuited, or completeness is uncertain, run all
   of its independent leaf checks once as one non-short-circuit diagnostic sweep (start every leaf,
   preserve every exit status, aggregate once). This sweep diagnoses the failed gate; it is not a
   second health gate. Before repair, record one structured inventory with the source tree SHA,
   gate log, every leaf check and exit status, diagnostic categories/files, and
   `completeness: complete`; repair dispatch is forbidden while completeness is unknown.

   Resolve the inventory as one batch. The orchestrator first runs the project's maintained
   deterministic autofixes (formatter `--write`/`--fix`, lint autofix, import ordering) across the
   whole changed surface without a subagent. If non-mechanical findings
   remain, dispatch one repair chain with the entire remaining inventory; never dispatch or
   validate one category, command, or file at a time. The repair builder still does not validate.
   Only after the whole batch is repaired does this orchestrator rerun the canonical gate once on
   the changed tree. Diagnostics that a maintained CLI can fix never get an LLM repair owner.
   The workflow permits at most three changed-tree whole-batch repair-and-rerun rounds total. A
   deterministic-only batch needs no repair owner but its gate rerun still consumes one of those
   three executions. Each later round begins with the same complete-inventory rule so only genuinely
   new or cascading failures can appear later. Record every
   failure-driven rerun and stop only if the third round still fails — three fresh-owner rounds
   after a deterministic batch means the failure is not mechanical, and more rounds have
   historically bought hours, not fixes. A repair that does not change the tree records a no-op and skips the invalid
   duplicate gate execution before the next fresh repair owner. Stop before the cap only when the
   repair requires genuinely missing human information/authorization or an external condition no
   agent can change.
   On **`direct`**, when risk surfaces are absent, this may be the only full gate if review does
   not change the tree. Never skip health entirely.
7. **Review and resolve.** Invoke the `/review` skill with the intensity packet (do not hand-roll
   it): light path for `direct`/`standard` unless safety triggers upgrade; heavy when intensity
   or the review path gate requires it. Conditionally escalate peers, synthesize once, and hand
   actionable findings to `/resolve-review`. Resolve rounds: `direct` ≤1, `standard` ≤1,
   `heavy` ≤2 (stop earlier when no actionable findings remain). Apply the conditional coverage
   gate in `execution-phases.md` only when peer escalation fired. Reviewers inspect the diff and
   recorded evidence only, and resolution builders implement only; neither runs validation. Stop
   for unresolved design decisions. If the diff first crosses a safety floor, escalate intensity
   for review/resolve and record the new reason.
8. **Persistence gate (cross-provider MCP paths only).** On Codex or other cross-provider runs
   `create_artifact` can silently no-op, so confirm via `get_ticket(detail="light",
   artifact_types=["build_todo", "review_todo"], include_events=false)` that the ticket carries
   its `build_todo` artifacts and the `review_todo` artifacts the adaptive review wrote, and
   re-issue anything missing. On native runs, trust the `create_artifact` results — this guards a
   known transport failure, it is not a re-read of your own work. Either way, a ticket must not
   proceed to landing with only a `source` artifact (plan + build_todos required).
9. **Final health gate (main orchestrator only).** Compare the final tree SHA to the pre-review
   PASS. If unchanged, reuse that PASS. If review resolution changed the tree, run the same
   canonical full health command exactly once on the new final tree. This makes at most two normal
   full gates: post-build/pre-review and post-resolution/final. Focused diagnostics are permitted
   only to identify a failing orchestrator gate and are keyed by `(tree SHA, exact command)`.
   A failure uses the same complete-inventory, deterministic-autofix-batch-first,
   fresh-repair-owner, whole-batch rerun contract and three-round cap from
   step 6; never return a resumable formatting, lint, type, test, or other deterministic failure to
   the user merely to obtain a fresh attempt budget.
   Do not query staging/prod as verification and do not trigger flows/processes.
10. **Push.** Before the push, run the pre-push local CI parity gate from
   `../references/ci-self-heal.md` (`bin/ci-local --run` at the final tree, with judgment on its
   SKIPs) so the first CI run is normally green. Then ensure the feature branch is pushed to the
   remote (no PR — `/auto-deploy` creates the PR at deploy time). Record which jobs passed
   locally and which were not locally reproducible.

### Phase checkpoints, rotation, and command output

- Build-todo creation, implementation, test-writing, pre-review health, review, review resolution,
  and final health are durable phase boundaries. Persist the current MCP artifacts and tree SHA at
  each boundary, then start the next phase in a fresh `fork_turns: "none"` agent with only its
  bounded checkpoint/packet (including intensity fields). The health phase owner is an
  orchestrator, never a builder/reviewer/resolver subagent.
- Apply the validated dispatch/result/rotation contract in `execution-economy.md` with
  `max_packet_bytes: 16384` and these default hard per-generation budgets:

  | Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed |
  |---|---:|---:|---:|---:|
  | build-todo creation | 30 | 4 | 30 min | 60,000 |
  | implementation | 80 | 12 | 120 min | 160,000 |
  | test-writing | 40 | 4 | 45 min | 80,000 |
  | each health gate | 30 | 2 | 45 min | 60,000 |
  | review | 50 | 6 | 60 min | 90,000 |
  | review resolution | 50 | 8 | 60 min | 100,000 |

- This table is the required fixed context/token budget. An observable first compaction is an
  immediate `rotate_required` boundary.
- A valid `rotate_required` persists every completed todo/finding and the current tree SHA before a
  fresh `fork_turns: "none"` replacement starts at the first incomplete unit. The old owner gets no
  follow-up work. Preserve the coherent builder chain and orchestrator-owned validation contract:
  rotate a chain at the next safe per-todo checkpoint; never make a builder validate or drop a gate.
- Tests, builds, migrations, large diffs, and other noisy commands must use `bin/compact-exec` or an
  established equally compact stricter wrapper. Full output stays in the log; the model receives
  only the bounded summary/tail. On failure, report the absolute `output_file` and exact
  `rerun_command` before routing the fix.

## Output

```text
Ticket build complete: F0123
Intensity: {direct|standard|heavy} ({reason}; floor={none|standard|heavy})
Branch: {branch} (pushed)
Build todos: {n} completed; review: {light|heavy}, {n} findings resolved
Pre-review health gate: PASS ({command} @ {sha})
Final health gate: REUSED ({command} @ {sha}) | PASS ({command} @ {final sha})
Artifacts: plan present; build_todo x{n}, review_todo x{n} persisted
Rotations: {count}; reasons: {reason counts}; productive/stall/elapsed: {when available}
Next: /ticket-deploy F0123 staging|prod|full
```

On failure, report the exact phase, evidence, and the unresolved decision or failing check.

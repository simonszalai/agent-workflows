---
name: ticket-build
description: >-
  Implementation phase for one planned ticket: compact direct/standard delivery, risk-focused
  heavy delivery, independent review when required, and parent-owned local health gates.
max_turns: 100
---

# Ticket Build

Implement one ticket that already has a **plan MCP artifact**, through a locally verified tree
with all required artifacts persisted. `direct`/`standard` use one compact delivery owner;
`heavy` uses concise planner-owned todos, one coherent builder chain with tests in-chain, and
targeted `/review`/`/resolve-review` coverage. It does not land, merge, deploy, or run environment verification — those belong
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
`../references/execution-intensity.md`. Ticket hydration follows
`../references/delegated-ticket-context.md`.

1. **Load context once, outside the main thread.** Read one light manifest for lifecycle and plan
   presence. Reuse a caller-supplied curator packet only when its `context_version`, build phase,
   and task fingerprint match; otherwise dispatch one fresh no-history context curator. Claude uses
   `context-curator` on `sonnet`; Codex
   uses `gpt-5.6-luna`. The curator reads all current artifact bodies and applicable
   memory/past-ticket evidence and returns one relevance-filtered build packet with no fixed byte
   ceiling. Validate its receipt. The build
   orchestrator must not replay artifact, memory, entry-expansion, or similar-ticket calls. Carry
   the
   packet path/hash into build and review so children inherit the same knowledge without
   re-searching. Resolve intensity from the parent packet or standalone flags/gate; epic membership
   alone has no floor. Record `intensity` / `intensity_reason` / `intensity_floor` on every child
   packet.
2. **Honor dashboard review comments.** Check `open_comment_count`; if the user left open review
   comments on the plan/source, resolve them (revise via `/ticket-plan` when the plan itself must
   change) before building. Do not build past unresolved feedback. There is no `approved` status;
   leaving `planned` means setting `in_progress`.
3. **Deliver (intensity-aware).** Always produce MCP `build_todo` artifacts for audit/resume.
   - **`direct` / `standard`:** dispatch exactly one fresh `fork_turns: "none"`
     `delivery_owner`. It
     mechanically materializes minimal todos from the approved plan, implements the whole bounded
     change, writes focused behavior tests, may run focused tests, checkpoints each todo, and
     returns one structured receipt. Do not invoke `/create-build-todos`, `/build`, or
     `/write-tests`; do not split planning, implementation, and tests across agents.
   - **`heavy`:** mechanically materialize concise risk/dependency-aware todos from the approved
     plan, then invoke one coherent `/build` chain that implements them and writes focused tests
     in-chain. Split once only when independent risk/subsystem ownership genuinely requires it.
     Do not invoke a separate deep-research todo agent or standalone `/write-tests` by default.
     These subagents do not run validation.
   Finalize `deployment_guide` only when deploy shape is non-trivial; otherwise record the skip.
4. **Pre-review health gate (main orchestrator only).** After all initial implementation and
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

   Resolve the inventory as one batch. Before the first changed-tree repair, record the repair
   round in the durable phase checkpoint. The orchestrator first runs the project's
   maintained deterministic autofixes (formatter `--write`/`--fix`, lint autofix, import ordering)
   across the whole changed surface without a fresh subagent. If non-mechanical findings remain,
   one `repair_owner` receives
   to one repair chain with the entire remaining inventory; never dispatch or validate one category,
   command, or file at a time. The repair builder still does not validate.
   Only after the whole batch is repaired does this orchestrator rerun the canonical gate once on
   the changed tree. Diagnostics that a maintained CLI can fix never get an LLM repair owner.
   `direct`/`standard` permit one changed-tree whole-batch repair-and-rerun cycle total; `heavy`
   permits two. Run the gate through a run-local receipt registry so rotation or resume cannot
   renew the chosen cap:

   ```bash
   MAX_REPAIRS=1  # heavy: 2
   bin/validation-receipt --owner orchestrator --max-repair-runs "$MAX_REPAIRS" \
     --registry <run-dir> -- <exact command>
   ```

   A deterministic-only batch needs no fresh repair subagent, but its gate rerun consumes the same
   recorded cycle. A no-op repair skips the invalid duplicate gate. When the selected cap is
   exhausted, persist the exact unresolved gate evidence as `repair_limit_reached`. Stop earlier only when the repair requires genuinely
   missing human information/authorization or an external condition no agent can change.
   On **`direct`**, when risk surfaces are absent, this may be the only full gate if review does
   not change the tree. Never skip health entirely.
5. **Review and resolve.** `direct` has no independent review. `standard` dispatches exactly one
   native general reviewer; a routine additive migration may add one targeted data reviewer without
   changing delivery intensity. `heavy` invokes `/review` with one combined code/plan-conformance
   reviewer plus at most one merged specialist for the named hard safety surface; peers remain
   deadlock-only.
   Before review dispatch, refresh the light manifest. If build/checkpoint updates advanced
   `context_version`, run one review-phase context curator and pass its packet path/hash; do not
   hydrate changed artifacts in this orchestrator.
   Reviewers inspect the diff and evidence only. Add accepted same-risk findings to the one ordinary
   repair batch; do not re-review its result. A new safety boundary escalates to heavy review before
   repair. Stop for unresolved design decisions.
6. **Persistence gate (cross-provider MCP paths only).** On Codex or other cross-provider runs
   `create_artifact` can silently no-op, so confirm via `get_ticket(detail="light",
   artifact_types=["build_todo", "review_todo"], include_events=false)` that the ticket carries
   its `build_todo` artifacts and the `review_todo` artifacts the adaptive review wrote, and
   re-issue anything missing. On native runs, trust the `create_artifact` results — this guards a
   known transport failure, it is not a re-read of your own work. Either way, a ticket must not
   proceed to landing with only a `source` artifact (plan + build_todos required).
7. **Final health gate (main orchestrator only).** Compare the final tree SHA to the pre-review
   PASS. If unchanged, reuse that PASS. If review resolution changed the tree, run the same
   canonical full health command exactly once on the new final tree. This makes at most two normal
   full gates: post-build/pre-review and post-resolution/final. Focused diagnostics are permitted
   only to identify a failing orchestrator gate and are keyed by `(tree SHA, exact command)`.
   A failure uses the same complete-inventory, deterministic-autofix-batch-first,
   fresh-repair-owner, whole-batch rerun contract and intensity cap from step 4. When the limit is
   reached, persist `repair_limit_reached` with the exact evidence; a fresh invocation does not
   create another attempt.
   Do not query staging/prod as verification and do not trigger flows/processes.
8. **Push.** Before the push, run the pre-push local CI parity gate from
   `../references/ci-self-heal.md` (`bin/ci-local --run --receipt <absolute-receipt-path>` at the
   final tree, with judgment on its SKIPs), batch-repair every locally reproducible failure, and
   validate the exact-tree receipt with `bin/ci-local --require-receipt <absolute-receipt-path>` so
   the first CI run is normally green. Then ensure the feature branch is pushed to the
   remote (no PR — `/auto-deploy` creates the PR at deploy time). Record which jobs passed
   locally and which were not locally reproducible.

### Phase checkpoints, rotation, and command output

- Compact todo creation, implementation, and focused tests are one delivery-owner session, not
  fresh agents at internal checkpoints. Review and optional repair are separate no-history
  sessions. Heavy planning and building remain separate, but todo creation and test writing stay
  inside those owners rather than creating subphases. Persist MCP artifacts and tree SHA at every boundary.
  The health phase owner is the orchestrator, never a delivery/reviewer/repair subagent.
- Apply the validated dispatch/result/rotation contract in `execution-economy.md` with
  `max_packet_bytes: 16384` and these default hard per-generation budgets:

  | Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed |
  |---|---:|---:|---:|---:|
  | compact delivery owner | 40 | 12 | 60 min | 90,000 |
  | heavy builder chain (todos + implementation + focused tests) | 40 | 12 | 60 min | 90,000 |
  | each health gate | 30 | 2 | 45 min | 60,000 |
  | review | 50 | 6 | 60 min | 90,000 |
  | review resolution | 50 | 8 | 60 min | 100,000 |

- This table is the required fixed context/token budget. An observable first compaction is an
  immediate `rotate_required` boundary.
- There is no cumulative model-session reservation. Persist every completed todo/finding and the
  tree SHA before a fresh no-history replacement starts at the first incomplete unit. The old owner
  gets no follow-up work. A heavy builder chain rotates only at the next safe per-todo checkpoint;
  session count alone never blocks review or verification.
- Tests, builds, migrations, large diffs, and other noisy commands must use `bin/compact-exec` or an
  established equally compact stricter wrapper. Full output stays in the log; the model receives
  only the bounded summary/tail. On failure, report the absolute `output_file` and exact
  `rerun_command` before routing the fix.

## Output

```text
Ticket build complete: F0123
Intensity: {direct|standard|heavy} ({reason}; floor={none|standard|heavy})
Branch: {branch} (pushed)
Build todos: {n} completed; review: {none|general|heavy}, {n} findings resolved
Pre-review health gate: PASS ({command} @ {sha})
Final health gate: REUSED ({command} @ {sha}) | PASS ({command} @ {final sha})
Artifacts: plan present; build_todo x{n}, review_todo x{n} persisted
Rotations: {count}; reasons: {reason counts}; productive/stall/elapsed: {when available}
Repair rounds: {used}/{cap}; no cumulative model-session stop gate
Next: /ticket-deploy F0123 staging|prod|full
```

On failure, report the exact phase, evidence, and the unresolved decision or failing check.

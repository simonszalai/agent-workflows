# Execution Economy

Shared contract for autonomous workflow orchestration. Efficiency changes execution shape, never
correctness, fail-loud behavior, lifecycle ownership, or required safety gates.

## Dispatch contract

- Every delegated call defaults to and should use `fork_turns: "none"`. Send a bounded,
  self-contained task packet containing the objective, exact scope, relevant paths/artifact IDs,
  constraints, expected return shape, and any orchestrator-owned validation command named for
  handoff rather than child execution. A history fork is allowed only when
  a self-contained packet is genuinely impossible. Before dispatch, record why it is impossible
  and use the smallest explicit numeric count of recent turns that supplies the missing fact.
  `fork_turns: "all"` is prohibited; convenience or an already-long conversation is not an
  exception.
- Give each agent one role and one write scope. No role drift: a researcher does not implement, a
  reviewer does not silently fix, and a verifier does not deploy or mutate lifecycle state.
- Cluster adjacent dependent work into coherent sequential chains when it shares subsystem/context
  and write scope. Split at independent branches, materially different subsystems, specialist/risk
  boundaries, or when the packet would become broad. Do not create one agent per tiny todo when
  one bounded chain packet can safely cover it.
- Batch independent tool calls in one turn. Parallelize only genuinely independent work; preserve
  dependency, schema, deploy, and promotion ordering.

## Output and retrieval bounds

- Set explicit output caps on commands and tools. Tests, builds, migrations, large diffs,
  deployment output, and every other potentially noisy command must run through
  `bin/compact-exec -- <command>` or an established equally compact repository wrapper when the
  command needs a stricter boundary. Preserve complete output in the wrapper's log and return only
  its bounded summary/tail. A failure report must include the wrapper's absolute `output_file` and
  precise `rerun_command`. Inspect only targeted excerpts instead of returning the full log.
- Active workflow examples are mechanically checked by `bin/workflow-noisy-command-check`.
  A raw noisy command is invalid unless the example demonstrates a small explicit output bound.
  `bin/compact-exec` reports `status`, `exit_code`, absolute `output_file`, bounded diagnostic
  `tail`, exact `rerun_command`, and the current `head_sha`, committed `head_tree_sha`, exact
  input working `tree_sha`, `post_tree_sha`, `tree_changed_during_command`, and `index_tree_sha`
  when run in a Git checkout.
- Bound code search by paths/globs and byte or result caps. Narrow broad searches after the first
  capped sample; never dump an entire repository or generated artifact into model context.
- Bound every SQL/data query by time window, selected columns, row limit, and payload size. Start
  with counts/aggregates, then retrieve the smallest sample that can decide the question.
- Cache immutable or run-stable inputs once per run: ticket/epic artifacts, git diff and file list,
  environment config, prior-memory packet, deploy guide, and query results. Record the source and
  freshness boundary; invalidate only when the underlying branch, artifact, deploy, or time window
  changes.
- The orchestrator retrieves shared ticket context once. Start with `detail="light"` to obtain the
  manifest, cache its `context_version` and artifact IDs, then call `get_artifact` for each exact
  body needed. Event history is only for explicit audit work. Pass immutable cached packet paths
  plus hashes to children; never make each child reload the same ticket or embed the same large
  artifact body in every delegated prompt. Active examples are checked by
  `bin/workflow-ticket-context-check`; unfiltered `detail="full"` reads fail unless a narrowly
  documented exception is present.
- Ticket orchestrators also persist those reads, packet references, and updates in one runtime
  receipt and validate it with
  `bin/workflow-ticket-context-check receipt <receipt.json>`. A repeated same-version manifest
  read is invalid. Child packets contain artifact IDs, hashes, and bounded excerpts. Current
  plan/deployment-guide bodies are bounded replacements; old revisions remain in artifact history
  rather than being appended to the canonical body.

## Waiting and polling

**Model-driven polling is absolutely prohibited.** A model must never repeatedly wake to inspect
the same pending condition. This includes repeated `wait`, `write_stdin`, or `wait_agent` calls;
GitHub status/check API reads, `gh run view`, or `gh pr checks`; Prefect inspect API/CLI calls;
Render deployment reads; and equivalent status checks. Background-command-plus-repeated-read loops
are prohibited, including as a fallback. A process may poll; the model is sampled only after one
terminal result or one timeout.

- GitHub PR checks and Actions runs use `wait-ci <pr>` or `wait-ci --run <run-id>`.
  Prefect flow runs use
  `wait-prefect-flow <flow-run-id> --command-prefix '<project prefect command>'`. Shared waiters
  are installed in the user executable directory and must resolve through `PATH`; never address
  them relative to the current repository. Each is one
  bounded process with explicit terminal success/failure predicates, one compact JSON result, and
  `status="timeout"` plus an exact `resume_command` when its hard deadline expires.
- If no purpose-built waiter exists, write a deterministic bounded poller under the run's scratch
  directory. It must use a fixed interval, a hard deadline or attempt cap, explicit success and
  failure terminal predicates, a full log on disk, and one compact terminal result. Timeout exits
  nonzero and prints the exact resume/retry command. The script, never the model, performs the
  repeated status reads.
- There is no maintained shared Render waiter. For a Render condition, use the generic scratch
  poller contract above only when its authenticated status transport is already available and
  secret-safe; otherwise stop with the exact resume command and missing-adapter limitation. Never
  replace the missing adapter with `render`/API status reads from repeated model turns.
- Run the waiter or poller as one blocking foreground tool call whenever the harness supports it.
  Resume model reasoning only after the process reaches a terminal predicate or its deadline.
- If the harness yields a resumable command session, do not build a model loop around the session.
  Use one supported long blocking wait. If that is unavailable, delegate only the deterministic
  waiter process to one fresh `fork_turns: "none"` leaf whose packet contains the identifiers,
  deadline, and exact command. The parent blocks once for the leaf's terminal result. If neither
  route exists, stop with the exact resume command instead of polling.
- **Conductor enforcement:** do not start a wait in a parent when unified exec will yield a
  resumable session. Dispatch the deterministic waiter immediately to the fresh no-history leaf
  and block once. If an accidental parent wait yields, terminate it and restart the exact command
  in the leaf; the parent must not poll the parent session itself.
- Never trade away a required test, review, deployment check, or verification row to save tokens.
  Missing evidence remains missing; failures remain loud.

## Durable checkpoints and phase rotation

Every long phase is a finite dispatch, not an advisory request to "stay concise." Before dispatch,
write an immutable packet plus a JSON phase envelope and run
`bin/phase-contract dispatch <envelope.json>`. An invalid envelope is a hard stop. The envelope
records:

- `phase_name`, zero-based `rotation_generation`, `first_incomplete_unit`, `started_at_epoch`, and
  `deadline_epoch` (exactly start plus the elapsed budget);
- `fork_mode`, `coordinator_generation`, `compaction_signal` (`available` or `unavailable`), and
  dispatch-time `compactions_observed: 0`; `fork_mode: "all"` is mechanically rejected;
- a finite positive `max_turns`, `max_checkpoints`, `max_elapsed_seconds`, and
  `max_packet_bytes`;
- `token_usage: "available"` plus a finite positive `max_tokens` when the provider exposes usage,
  otherwise `token_usage: "unavailable"` and `max_tokens: null`;
- the absolute immutable packet path and SHA-256, plus the prior checkpoint path/hash for every
  replacement generation.

Active `/ticket-flow` phases use the stricter
`bin/phase-contract ticket-dispatch <envelope.json>` profile. It requires the runtime context
receipt and fanout budget, and mechanically enforces ticket phase ceilings, the default one-role
shape, the delta-review path, and full specialist reset at a new risk boundary.

The phase packet repeats those limits and requires the owner to count its turns and safe checkpoint
advances. Harness `max_turns` and subprocess timeouts remain hard outer caps; set the packet budget
below them so the owner has room to checkpoint and return. A host without token usage or a reliable
compaction event is not allowed an unbounded phase: finite turns/checkpoints, elapsed time, and
packet bytes are the mechanical backstop.

Every phase owner returns exactly one JSON result. Capture it once, without reinterpretation, and
run `bin/phase-contract result <result.json> --dispatch <envelope.json>` before accepting it:

```json
{
  "phase_name": "implementation",
  "rotation_generation": 0,
  "coordinator_generation": 0,
  "fork_mode": "none",
  "compactions_observed": 0,
  "status": "rotate_required",
  "reason": "turn_budget",
  "checkpoint": {"path": "/absolute/checkpoint.json", "sha256": "<sha256>"},
  "completed_scope": ["todo-1"],
  "remaining_scope": ["todo-2"],
  "usage": {
    "turns_used": 48,
    "checkpoints_used": 4,
    "elapsed_seconds": 2700,
    "productive_seconds": 2400,
    "stall_seconds": 300,
    "tokens_used": null
  }
}
```

- `status` is exactly `complete`, `blocked`, `failed`, or `rotate_required`.
  `rotate_required` is nonterminal, not success or failure. Its exact `reason` is one of
  `first_compaction`, `turn_budget`, `elapsed_budget`, or `token_budget`; it must name a validated
  durable checkpoint, completed scope, and non-empty remaining scope. The turn budget also owns the
  finite safe-checkpoint work cap on hosts that do not expose a trustworthy turn counter.
- At every safe unit boundary, persist completion to the canonical MCP artifact or workflow
  checkpoint. Resume from the first incomplete unit; never rerun a completed unit or duplicate a
  mutation, landing, deployment, review finding, or verification row.
- If the host presents a compacted-summary marker or other reliable compaction indication, stop
  before any further implementation, review, deploy, or verification action, persist the safe
  checkpoint, and return `rotate_required` with `reason: "first_compaction"`. There is no portable
  way to infer an invisible host compaction; do not claim otherwise.
- `bin/phase-contract` rejects any result after an observed first compaction unless it is
  `rotate_required` with `reason: "first_compaction"` and a valid checkpoint. It also rejects an
  all-history fork or a result whose fork/coordinator/rotation generation differs from dispatch.
- On valid `rotate_required`, the parent first persists/validates the returned completion mapping
  and next immutable checkpoint, then dispatches one fresh `fork_turns: "none"` replacement using
  only that checkpoint and its bounded packet. Increment `rotation_generation`. The old owner is
  terminal: never send it `followup_task`, `send_message`, another prompt, or more work even if it
  remains responsive.
- Enforce the budget with dispatch limits, deterministic checkpoints, one terminal wait, or a
  host-supported timeout. Never introduce repeated `wait`, `write_stdin`, `wait_agent`, status
  reads, or heartbeat polling. Required safety gates remain required; rotate and continue instead
  of skipping them.
- Outer terminal reports include rotation count/reasons and, when the source exposes them,
  productive, stall/sleep, and total elapsed seconds separately.

### Durable progress leases

Every parent/child phase block is governed by a progress lease inside the absolute phase deadline.
Validate the lease with `bin/progress-lease issue <lease.json>`. Its durable-progress reference is
an immutable checkpoint or tool receipt with an absolute path, SHA-256, and monotonically
increasing sequence. Heartbeat prose, model responsiveness, and status text are not progress.

The parent performs exactly one bounded block/wait for a lease. At lease expiry it may perform
exactly one status inspection and then runs
`bin/progress-lease expiry <observation.json> --lease <lease.json>`:

- consume a terminal result immediately;
- when the durable sequence and hash advanced and the hard phase deadline remains, issue at most
  one renewed bounded lease;
- when progress is stale, the one renewal was already spent, or the absolute deadline arrived,
  interrupt and rotate/resume from the last validated durable checkpoint.

Represent `sleep`, `paused`, and `unknown` truthfully. Elapsed wall time alone is never execution
failure. There are no heartbeat loops, duplicate waits, repeated inspections, or unbounded
fallbacks; `rotate_required` and the finite phase budgets above remain authoritative.

Write an execution-economy receipt for every wait/status sequence and validate it with
`bin/progress-lease policy <receipt.json>`. The receipt identifies actor (`model` or
`deterministic_waiter`), operation, stable pending-condition key, and whether the observation was
the one lease-expiry inspection. Repeated model `wait_agent`, `write_stdin`, `list_agents`,
Render/GitHub status reads, or equivalent same-condition reads make compliance fail. A
deterministic bounded waiter may poll internally; the model consumes its terminal result once.
Outer closeout must run the policy check (or
`bin/workflow-efficiency-report --enforce-execution-economy`) and cannot claim compliant success
when the receipt/report fails. This is enforcement, never an instruction for the model to poll.

## Secret-safe operations

- Never run credential/profile/config introspection in an agent-visible shell (`prefect profile
  inspect`, config dumps, `env`, `printenv`, authenticated headers, or equivalent). Names may be
  inspected; resolved values may not. A credential printed by a tool is exposed even if it appears
  only in an intermediate tool result.
- Direct production database writes from a local agent shell are prohibited. Prefer an audited MCP
  mutation or a server-side deployment/workflow. For other authenticated production CLI mutations
  that have no audited remote route, mount the credential command-locally and run the command through
  `bin/redacted-exec -- ...`. That wrapper emits no raw log file and redacts environment-derived and
  labeled credential values before output reaches the transcript.
- Do not put authenticated production commands behind `bin/compact-exec`: its full raw log is an
  intentional feature and therefore the wrong boundary for possibly secret-bearing output.

## Final-tree evidence ownership

- Key expensive validation by `(tree SHA, exact command)`. Builder chains, orchestrated
  test-writers, reviewers, and review-resolution builders do not run validation commands. The main
  ticket/lfg orchestrator owns one full health gate after initial implementation and test-writing,
  before review. Reuse that recorded PASS when the final tree SHA is unchanged; if review
  resolution changes the tree, run the full gate exactly once on that new final tree. This is at
  most two normal full gates.
- A failing orchestrator gate may dispatch one narrowly scoped repair chain. The repair builder
  still does not validate; the orchestrator reruns the failed gate once on the changed tree and
  records that failure-driven rerun. Focused diagnostics used to isolate a gate failure are also
  orchestrator-owned and keyed by `(tree SHA, exact command)`.
- Execute reusable gates through
  `bin/validation-receipt --owner orchestrator -- <exact command>`. It persists the receipt under a
  key derived from the exact working-tree SHA and canonical working-directory + argv command. An
  exact-tree, exact-command PASS is returned without execution; any tree or command change
  invalidates reuse.
  An unchanged-tree failure cannot rerun. After a changed-tree repair, the orchestrator may execute
  the failed gate once. The wrapper mechanically rejects builder/reviewer ownership.
- `bin/workflow-efficiency-report` parses compact-exec receipts and reports validation executions
  keyed by `(tree_sha, normalized_exact_command)`. It classifies `initial_run`,
  `exact_tree_duplicate`, `changed_tree_run`, and `repair_run`. Attribution is diagnostic only:
  uncertainty fails open to executing validation, never to suppressing it; reuse requires certain
  exact tree and command identity.
- Removal/decommission work closes with a **negative inventory**, not only passing tests: record the
  before inventory of old entrypoints/writers/config/deployments, then prove every scoped item is
  absent after the final deploy. Search code and config, query live registrations/routes/jobs where
  applicable, and exercise the surviving path. Any unexplained old item is a failure, not cleanup
  debt to silently defer.

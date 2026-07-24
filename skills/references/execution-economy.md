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
- Bound code search by paths/globs and byte or result caps. Narrow broad searches after the first
  capped sample; never dump an entire repository or generated artifact into model context.
- Bound every SQL/data query by time window, selected columns, row limit, and payload size. Start
  with counts/aggregates, then retrieve the smallest sample that can decide the question.
- Cache immutable or run-stable inputs once per run: ticket/epic artifacts, git diff and file list,
  environment config, prior-memory packet, deploy guide, and query results. Record the source and
  freshness boundary; invalidate only when the underlying branch, artifact, deploy, or time window
  changes.
- The orchestrator retrieves shared ticket context once. Use lightweight artifact manifests for
  routing, selected full artifact types for execution, and event history only for explicit audit
  work. Pass cached file paths or bounded extracts to children; never make each child reload the
  same ticket or embed the same large artifact body in every delegated prompt.

## Waiting and polling

**Model-driven polling is absolutely prohibited.** A model must never repeatedly wake to inspect
the same pending condition. This includes repeated `wait`, `write_stdin`, or `wait_agent` calls;
GitHub status/check API reads, `gh run view`, or `gh pr checks`; Prefect inspect API/CLI calls;
Render deployment reads; and equivalent status checks. Background-command-plus-repeated-read loops
are prohibited, including as a fallback. A process may poll; the model is sampled only after one
terminal result or one timeout.

- GitHub PR checks and Actions runs use `bin/wait-ci <pr>` or `bin/wait-ci --run <run-id>`.
  Prefect flow runs use
  `bin/wait-prefect-flow <flow-run-id> --command-prefix '<project prefect command>'`. Each is one
  bounded process with explicit terminal success/failure predicates, one compact JSON result, and
  `status="timeout"` plus an exact `resume_command` when its hard deadline expires.
- If no purpose-built waiter exists, write a deterministic bounded poller under the run's scratch
  directory. It must use a fixed interval, a hard deadline or attempt cap, explicit success and
  failure terminal predicates, a full log on disk, and one compact terminal result. Timeout exits
  nonzero and prints the exact resume/retry command. The script, never the model, performs the
  repeated status reads.
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

- Before each durable phase boundary, persist the phase result to its canonical MCP artifact or
  workflow checkpoint. Start the next phase in a fresh `fork_turns: "none"` agent with only the
  checkpoint and bounded packet required for that phase.
- Choose and record a fixed context/token budget for every phase owner. Force replacement after
  the first context compaction or when that budget is reached, whichever happens first. Persist the
  checkpoint before replacement. Never keep an indefinitely growing agent merely because it still
  responds.

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
- Removal/decommission work closes with a **negative inventory**, not only passing tests: record the
  before inventory of old entrypoints/writers/config/deployments, then prove every scoped item is
  absent after the final deploy. Search code and config, query live registrations/routes/jobs where
  applicable, and exercise the surviving path. Any unexplained old item is a failure, not cleanup
  debt to silently defer.

# Execution Economy

Shared contract for autonomous workflow orchestration. Efficiency changes execution shape, never
correctness, fail-loud behavior, lifecycle ownership, or required safety gates.

## Dispatch contract

- Default delegated calls to `fork_turns: "none"`. Send a bounded, self-contained task packet
  containing the objective, exact scope, relevant paths/artifact IDs, constraints, expected return
  shape, and validation command. Fork conversation history only when the task cannot be made
  self-contained, and state why.
- Give each agent one role and one write scope. No role drift: a researcher does not implement, a
  reviewer does not silently fix, and a verifier does not deploy or mutate lifecycle state.
- Cluster work by shared context and non-overlapping write scope. Do not create one agent per tiny
  file or ticket when one bounded packet can safely cover the cluster.
- Batch independent tool calls in one turn. Parallelize only genuinely independent work; preserve
  dependency, schema, deploy, and promotion ordering.

## Output and retrieval bounds

- Set explicit output caps on commands and tools. For long-output commands (test suites,
  builds, migrations), run them through `bin/compact-exec -- <command>` — it writes full
  stdout/stderr to a run-local log and returns only the exit status plus a bounded tail.
  Inspect targeted excerpts from the log path on demand instead of repeatedly returning
  the full output.
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

- Prefer a blocking tool with a bounded timeout or one timer-friendly resume command. Do not spend
  model turns repeatedly asking whether a job is finished. For GitHub PR checks and Actions runs,
  use `bin/wait-ci` — one bounded, backoff-controlled process that returns one terminal JSON result.
  Invoke it as **one foreground tool call** with the outer tool timeout set slightly above
  `wait-ci --timeout`; do not background it and then poll task/process output from model turns.
  The process may poll GitHub many times, but the model is sampled once, after the process exits.
- When the tool harness cannot hold a foreground call for the expected duration, delegate only the
  wait to a fresh leaf with no inherited conversation (`fork_turns: "none"`). Its packet contains
  only repo, PR/run ID, timeout, and the exact `bin/wait-ci` command; it returns the final JSON once.
  The parent uses the platform's blocking agent-wait/wake mechanism once — never repeated status
  reads. If neither a blocking call nor a fresh waiter is available, stop with the resume command
  rather than model-polling.
- **Conductor enforcement:** unified exec yields long-running foreground commands as resumable
  sessions, which would force the parent to sample again for every `write_stdin`/`wait` poll. In
  Conductor, do not start `bin/wait-ci` in the parent at all. Always dispatch the wait immediately
  to one fresh `fork_turns: "none"` leaf and block once on that agent. A parent that receives a
  resumable session from an accidental CI wait must terminate that parent session and restart the
  exact bounded wait command in the leaf; it must not poll the parent session itself.
- `bin/wait-ci <pr>` waits for PR checks. `bin/wait-ci --run <run-id>` waits for one Actions run.
  `bin/wait-prefect-flow <flow-run-id> --command-prefix '<project prefect command>'` waits for one
  Prefect flow run. Each emits one terminal JSON result and a resume command on timeout.
  On interruption or timeout it returns `status="timeout"` plus an exact `resume_command`.
- If polling is unavoidable, use a shell/tool loop with a fixed interval, hard attempt/deadline cap,
  and full log on disk. Return once on completion or once at the cap with the exact resume command.
- Never trade away a required test, review, deployment check, or verification row to save tokens.
  Missing evidence remains missing; failures remain loud.

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

- Key expensive validation by `(tree SHA, command)`. Builders run targeted checks; the orchestrator
  owns one full health gate for the final tree. Reuse that recorded PASS everywhere downstream while
  the tree SHA is unchanged. A rebase, merge/conflict fix, generated-file change, or late edit creates
  a new tree and invalidates the old gate; run the gate once for the new tree.
- Removal/decommission work closes with a **negative inventory**, not only passing tests: record the
  before inventory of old entrypoints/writers/config/deployments, then prove every scoped item is
  absent after the final deploy. Search code and config, query live registrations/routes/jobs where
  applicable, and exercise the surviving path. Any unexplained old item is a failure, not cleanup
  debt to silently defer.

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

- Set explicit output caps on commands and tools. Write verbose stdout/stderr to a run-local file
  under `.context/<workflow>/<run-id>/`; return only the exit status, compact summary, and path.
  Inspect targeted excerpts on demand instead of repeatedly returning the full log.
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
  model turns repeatedly asking whether a job is finished.
- If polling is unavoidable, use a shell/tool loop with a fixed interval, hard attempt/deadline cap,
  and full log on disk. Return once on completion or once at the cap with the exact resume command.
- Never trade away a required test, review, deployment check, or verification row to save tokens.
  Missing evidence remains missing; failures remain loud.

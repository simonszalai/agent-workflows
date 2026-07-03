---
name: build-fable
description: Fable-variant build execution. Dispatches one Codex (GPT 5.5, xhigh) builder per build_todo via bin/external-build, checkpoints each to MCP after validating its JSON, self-repairs bounded, and finishes only when every todo is complete and the project health gate passes.
max_turns: 100
---

# Build (Fable variant)

Execute a plan by dispatching the **Codex GPT 5.5 builder** — `bin/external-build`, one run
per build_todo — instead of a Claude builder agent (style:
`skills/references/fable-prompting.md`). The orchestrator (you) owns everything stateful: MCP
artifact statuses, the health gate, the parity sweep, and all git history. The Codex side
only edits the working tree and returns structured JSON; it never commits, never touches MCP.

For multi-repo or linked-workspace contexts read `../references/conductor-multi-repo.md`.

## Usage

```
/build-fable F001            # Execute feature F001
/build-fable B0009           # Bug ticket
/build-fable F001 --step 2   # Execute one specific step
```

## Prerequisites (validate first, STOP on failure)

Same contract as the base `/build`:

- **Standard mode:** must be in a worktree, not the main repo, and not on `main`
  (`git rev-parse --abbrev-ref HEAD`, `git worktree list`).
- **Branch mode (cloud, `CLAUDE_CODE_REMOTE=true`):** must be on a feature branch; if on
  `main`, create `build/{id}` first.
- Ticket must carry a `plan` artifact (else `/auto-plan-fable`) and `build_todo` artifacts
  (else `/create-build-todos-fable`).
- **Ticketless mode (lfg):** `.context/plan.md` + `.context/build_todos/` replace MCP;
  checkpoints update the todo file's status header; skip every `update_ticket`/
  `update_artifact` call. Everything else is identical.

Set the ticket to `status="in_progress"` (`command="/build-fable"`, ticketed runs only).
Before building, incorporate plan feedback: check the plan's Open Questions/Additional Notes
and reconcile any build_todo they invalidate via `update_artifact`; if todos contradict the
plan, fix the todos first.

## Dispatch context (compensates for the Codex builder's missing MCP access)

Write once per run to `.context/build/context.md`:

- plan summary (what/how/why in a few lines);
- project health commands (test / typecheck / lint, from project CLAUDE.md);
- relevant memory-service gotchas: run `mcp__autodev-memory__search` for the areas this
  build touches and distill the applicable rules — the Codex builder cannot search memory,
  so what isn't in the todo or this file does not exist for it;
- applicable CLAUDE.md rules not already embedded in the todos.

## Build loop (sequential — never dispatch builders in parallel)

Two builders sharing one working tree race the git index; cross-repo concurrency belongs to
`/milestone-flow`. If a todo requires editing a different repo, STOP and send the work back
to epic splitting.

Order: pending todos by `sequence`, with `depends_on` prerequisites moved ahead. With
`--step N`, the execution set is just todo N. For each todo:

```bash
mkdir -p .context/build
# write the todo artifact content to .context/build/todo-{NN}.md, then:
external-build --task build \
  --todo-file .context/build/todo-{NN}.md \
  --context-file .context/build/context.md \
  --repo "$(pwd)" \
  --out .context/build/result-{NN}.json
```

**Run it in the background** (Bash `run_in_background`, then wait for completion and read the
`--out` file): GPT 5.5 at xhigh reasoning can exceed the foreground shell timeout on a real
todo. Model and reasoning effort are pinned inside the adapter (gpt-5.5 / xhigh) — do not
override them per-dispatch.

Branch on the result's `status`:

| `status` | Action |
| --- | --- |
| `complete` | Checkpoint (below), then dispatch the next todo |
| `failed` | Bounded self-repair: re-dispatch the SAME todo with the previous `error` + `verification_output` appended to the context file. Max **2** retries, then STOP and report the blocking todo — never build downstream on a broken foundation |
| `needs_replan` | STOP the loop; hand back to `/auto-plan-fable` with the builder's `error`. The plan is wrong; do not improvise around it |

An empty/invalid result file (adapter exit 2) counts as `failed`.

**Checkpoint (only on validated `complete`)** — the orchestrator, never the builder, marks a
todo done:

```
mcp__autodev-memory__update_artifact(project=PROJECT, repo=REPO,
  artifact_id={todo artifact id}, status="complete",
  content={todo content + Completion Notes: files_changed, deviations,
           verification_output, visual_evidence})
```

(Ticketless: update the `.context/build_todos/` file's status header + Completion Notes.)
This checkpoint is the entire resume story: re-running `/build-fable` picks up from the first
todo still `pending`.

## Done means the health gate, not the todo list

The build is complete ONLY when every todo is `complete` **and** the project's full
**test + typecheck + lint** passes against the whole working tree. If the gate fails despite
all todos self-reporting complete, a cross-file interaction broke: dispatch one Codex builder
scoped to the specific failure (a synthesized todo describing the failing command + output;
same ≤2 retry bound), re-run the gate; still failing → STOP and report.

Then the **migration parity sweep** (orchestrator-owned, repo-wide): diff the branch against
main for the repo's model/schema/migration paths. If schema files changed, verify per the
repo's active schema system — schema-truth repos (ts-prefect after E0017): Atlas plan/safety
checks and `verify_schema_truth.py` cover the change, no Alembic revisions; legacy repos: a
migration must exist (STOP and create it if not) and the deployment guide must name a
migration lane, never implying selective cherry-pick promotion is safe for migration-bearing
work.

Finally re-run the full test suite once (final gate run) and record the **Completion
Summary** (what was done, files changed, deviations, notes) plus a Work Log line on the plan
artifact via `update_artifact` (ticketless: `.context/plan.md`). Do not invoke `/write-tests`
— the orchestrator that called this skill owns that step.

Report outcomes faithfully: only claim a check passed if you can point to its output in this
session; if the gate failed or a step was skipped, say so plainly.

## Output

```
Build complete for {ID}: {title}

Steps: {N}/{N} completed (Codex GPT 5.5 via external-build)
Health gate: PASS (test {p}/{t}, typecheck OK, lint OK)
Screenshots: {absolute paths, required for UI/visual work; otherwise "not applicable"}

Next: /write-tests {ID}, then /review-fable {ID}
```

Blocked (`failed`, retries exhausted): name the todo, the error from the last structured
result, "Retries: 2/2 exhausted. Downstream steps not attempted.", and
`Next: fix the blocker, then /build-fable {ID} --step {N}`.

Halted (`needs_replan`): name the todo and reason;
`Next: /auto-plan-fable {ID} (revise), then /create-build-todos-fable, then /build-fable`.

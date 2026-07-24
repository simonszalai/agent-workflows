---
name: build
description: Execute an implementation plan through coherent sequential builder chains, checkpoint every covered build_todo individually, and leave validation to the orchestrator.
max_turns: 100
---

# Build Command

Execute a plan by spawning a `builder` agent to work through build_todos.

Follow `../references/execution-economy.md`. For any multi-repo or linked-workspace context, read
`../references/conductor-multi-repo.md`.

## Usage

```
/build 009                  # Execute bug #009 (NNN format)
/build F001                 # Execute feature F001 (FNNN format)
/build F001 --step 2        # Execute specific step
/build B0009                  # Bug ticket B0009
/build F001 --builder codex # Build with the external Codex builder (see below)
```

### External builder (`--builder codex`)

Same loop, different engine: each chain is dispatched through `bin/external-build --task
build` (defaults gpt-5.6 / `medium` reasoning) instead of a native builder agent. Pass
`--reasoning high` for a cross-cutting or migration-heavy chain, and `xhigh` only when
retrying a chain that failed at lower effort. Requirements specific to this mode:

- The Codex side has **no MCP or memory access**: the chain packet must be self-contained
  (`/create-build-todos` deepens each todo when told the builder is external) and the
  orchestrator writes a bounded context blob (relevant plan/contract excerpt, affected
  paths/interfaces, predecessor tree SHA, named orchestrator health command, relevant
  memory-service gotchas, prior-attempt errors on retry) to a file passed via
  `--context-file` — what is not in the chain or that file does not exist for the builder.
- Create the bounded memory packet before each dispatch:

  ```bash
  mkdir -p .context/build
  # write only this chain's todo bodies to .context/build/chain-{NN}.md, then:
  if ! cat .context/build/chain-{NN}.md | \
      autodev-memory-task-packet --cwd "$PWD" --session-id "${SESSION_ID:-}" \
        --agent-type builder --provider codex --mechanism external_build \
        --task-prompt-stdin --allow-unavailable > .context/build/memory-{NN}.md; then
    cat > .context/build/memory-{NN}.md <<'EOF'
  <autodev-memory-task-context>
  Memory context is unavailable. Do not infer that critical or build-specific memories were loaded.
  This external builder has no memory tool; proceed only from the approved todo and report the limitation.
  </autodev-memory-task-context>
  EOF
  fi
  external-build --task build \
    --todo-file .context/build/chain-{NN}.md \
    --context-file .context/build/context-{NN}.md \
    --memory-context-file .context/build/memory-{NN}.md \
    --repo "$(pwd)" \
    --out .context/build/result-{NN}.json
  ```

  Run the adapter as one blocking foreground tool call with the tool timeout above the adapter's
  bounded timeout, then read `--out` once after the process exits. If the harness cannot hold that
  call, delegate only this exact bounded command to one fresh `fork_turns: "none"` leaf and block
  once for its terminal result. Never background the adapter and repeatedly read its process or
  output file from model turns; if neither route can block, stop with the exact resume command.
- Validate the returned JSON against the build-mode contract before checkpointing;
  a run with no valid JSON counts as `failed` for the self-repair loop.
- Everything the orchestrator owns stays identical: per-todo MCP artifact statuses, validation,
  and every commit.

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

### Standard Mode (Worktree)

```bash
# 1. Check worktree (not main repo)
git rev-parse --abbrev-ref HEAD  # Must NOT be "main"
git worktree list | grep "$(pwd)" | grep -v "bare"  # Must match current dir

# 2. Load ticket and check artifacts exist
mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  detail="full", artifact_types=["plan", "build_todo"], include_events=false
)
# Check for build_todo artifacts — if none: STOP - run /create-build-todos first
# Check for plan artifact — if missing: STOP - run /ticket-plan first
```

### Branch Mode (Cloud)

When `CLAUDE_CODE_REMOTE=true`:

```bash
# 1. Check we're on a feature branch (not main)
git rev-parse --abbrev-ref HEAD  # Must NOT be "main"
# If on main: Create branch first

# 2. Load ticket and check artifacts exist
mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  detail="full", artifact_types=["plan", "build_todo"], include_events=false
)
# Check for build_todo artifacts — if none: STOP - run /create-build-todos first
# Check for plan artifact — if missing: STOP - run /ticket-plan first
```

**If any prerequisite fails:**

| Missing         | Action                                          |
| --------------- | ----------------------------------------------- |
| Not in worktree | Instruct user to create worktree (see below)    |
| On main (cloud) | Create branch with `git checkout -b build/{id}` |
| No build_todos  | **STOP** - run `/create-build-todos [id]` first |
| No plan         | **STOP** - run `/ticket-plan [id]` first          |

### Ticketless Mode (lfg)

When invoked by `/lfg` (no ticket exists), the filesystem replaces MCP:

- **Prerequisites:** read `.context/plan.md` (plan) and `.context/build_todos/` (todos)
  instead of `get_ticket`. Missing plan → STOP - run the lfg planning phase first. Missing
  todos → STOP - run `/create-build-todos` first.
- **Checkpoints:** on a validated `complete`, update the status header of the todo's file in
  `.context/build_todos/` (plus Completion Notes) instead of `update_artifact`. That file
  state is the resume story.
- **No MCP writes:** skip every `update_ticket` / `update_artifact` call in this skill.

Everything else is identical: coherent sequential chains, dependency order, granular per-todo
checkpoints, bounded chain-local self-repair (≤2 retries), and orchestrator-owned validation.

## Process

1. **Set ticket status to in_progress** (ticketed runs only — skip in ticketless mode):
   ```
   mcp__autodev-memory__update_ticket(
     project=PROJECT, ticket_id=ID, repo=REPO,
     status="in_progress",
     command="/build"
   )
   ```

2. **Verify execution context (REQUIRED):**

   **Standard Mode (Local Terminal):**
   - Run `git rev-parse --is-inside-work-tree` and `git worktree list`
   - **STOP if on main branch** - builds must run in a worktree
   - Verify current directory is a worktree, not the main repo
   - If not in worktree, instruct user to create one

   **Branch Mode (Cloud):**
   - Detected when `CLAUDE_CODE_REMOTE=true`
   - In branch mode, worktrees are not available - use feature branches instead
   - If on main: Create branch with `git checkout -b build/{id}`
   - All operations happen in current directory on the feature branch
   - This mode is used for cloud execution where worktrees aren't practical

3. **Process user feedback:**
   - Read plan artifact from `get_ticket` response — check Open Questions and Additional Notes
   - If answers or notes require changes to build_todos:
     - Update affected build_todo artifacts via `update_artifact`
     - Add/remove/modify steps as indicated
     - Document changes in work log

4. **Validate build_todos against plan:**
   - Verify build_todo artifacts align with plan artifact decisions
   - If build_todos contradict plan, update via `update_artifact` to resolve
   - Check memory service for relevant gotchas and patterns

5. **Build loop — coherent sequential builder chains:**

   Build the execution order from the **pending** build_todos: process in `step`/`sequence`
   order, but if a todo's `depends_on` names a todo that would otherwise sort later, move that
   dependency ahead so prerequisites always run first. Partition that ordered DAG into the
   **smallest reasonable set of coherent sequential chains**:

   - Group adjacent dependent todos only when they share repository subsystem/context and
     sequential write scope.
   - Split before a materially different subsystem, independent branch, distinct specialist/risk
     boundary, or any addition that would make the packet broad.
   - Same-worktree chains and chains with overlapping writes are **sequential**. Cross-repo
     concurrency is `/milestone-flow`'s job (separate repo workspaces/worktrees), not `/build`'s.
   - If a todo requires editing a different repo, stop and send the work back to epic splitting;
     do not edit linked repos from a single-repo `/build` run.

   If `--step N` was passed, the execution set is just todo N.

   For each chain, in order, dispatch one **fresh** builder that owns only that chain. Its packet
   contains only:

   - the full bodies and IDs of the todos in the chain;
   - the relevant plan/contract excerpt, affected paths/interfaces, and targeted risk notes;
   - the predecessor checkpoint/tree SHA; and
   - the structured return contract.

   Do not include the whole ticket/epic history, unrelated todos/artifacts, or a broad plan dump.

   **Per-chain model routing (mirror `resolve-review`'s cheap/strong split):** use the maximum
   complexity/risk among the chain's todos:

   - `model="sonnet"` when the entire chain is bounded to **<=2 files**, touches **no**
     schema/migration/auth/deploy-config paths, and makes **no** cross-module contract change.
   - `model="opus"` for cross-cutting or schema-bearing chains, and for **any retry** after a
     failed sonnet attempt (bounded self-repair below always escalates to opus).
   - **DEFAULT TO OPUS** whenever the `complexity` tag is missing, ambiguous, or you are
     uncertain — opus is the fail-safe; never downgrade to sonnet on a guess.

   ```
   Agent(
     subagent_type="builder",
     fork_turns="none",
     model={sonnet|opus per the routing rule above},
     prompt="
       MODE: build
       Ticket: {ticket_id}  Project: {PROJECT}  Repo: {REPO}

       Implement ONLY this coherent sequential chain, in order:
       {for each chain todo: #{sequence} {title} + full build_todo body}

       Relevant plan/contract excerpt: {bounded excerpt}
       Affected paths/interfaces: {bounded list}
       Predecessor checkpoint/tree SHA: {sha}
       Targeted risks/unverified items: {bounded list}
       Orchestrator validation command (name only; DO NOT run it): {exact command}

       Validation ownership:
       Implement and inspect code only. Do NOT run test suites, validation commands, typecheck,
       lint, builds, schema pulls, migrations, browser verification, or health commands. Report
       anything that remains unverified for the orchestrator.

       Hard-stop / needs_replan rule:
       If this todo implements a repeated writer (poller, observer, scheduler, queue,
       webhook, scraper, supervisor flow) and the design would persist duplicate unchanged
       source data proportional to polling frequency, do NOT blindly implement it. Return
       chain_status=needs_replan unless the todo names the downstream consumer, volume budget,
       dedupe/change-gating behavior, and retention/TTL for that append-only history.

       Return the structured build-result JSON per the builder Output (Build Mode) contract:
       { chain_status, todo_results[], files_changed, deviations, risks_unverified, error }
     "
   )
   ```

   Read the builder's structured result and branch on `chain_status`:

   | `chain_status`   | Orchestrator action                                                                    |
   | ---------------- | -------------------------------------------------------------------------------------- |
   | `complete`       | Validate every per-todo mapping, checkpoint each covered todo, then dispatch next chain |
   | `failed`         | **Bounded chain-local self-repair** — see below                                         |
   | `needs_replan`   | **STOP** and hand back to `/ticket-plan` with the builder's `error`; do not build on     |

   **Bounded self-repair (on `failed`):** first checkpoint any leading todos whose completion
   mappings are structurally valid. Dispatch a *fresh* builder for the remainder of the **same
   chain**, starting at its first incomplete todo, with the previous `error` and unverified risks
   as bounded context. Never rerun an already checkpointed todo. Retry at most **2** times and
   escalate a failed sonnet chain to `model="opus"`. If it still fails, **STOP** and report the
   first incomplete todo; do **not** attempt downstream chains on a broken foundation.

6. **Checkpoint (only on `complete`):**

   The orchestrator — not the builder — owns this write. Validate that every dispatched todo has
   exactly one completion mapping, its claimed files fit the chain scope, and no todo reports
   `failed`/`needs_replan`. Then checkpoint every covered todo individually so resume truth remains
   granular:

   ```
   mcp__autodev-memory__update_artifact(
     project=PROJECT, repo=REPO,
     artifact_id={todo artifact id},
     status="complete",
     content={todo content + Completion Notes from files_changed, deviations, risks_unverified}
   )
   ```

   In ticketless mode, update the status header of the todo's file in `.context/build_todos/`
   (plus the same Completion Notes) instead of calling `update_artifact`.

   This is the entire resume story: re-running `/build` picks up from the first todo still
   `pending`. No journal, no scratch file — the MCP artifact (ticketed) or the
   `.context/build_todos/` file (ticketless) is the source of truth.

7. **Stopping condition and validation handoff:**

   The implementation phase converges when every build_todo is individually checkpointed
   `complete`. Builder-chain results are implementation evidence, **not validation evidence**.

   - When called by `/ticket-build` or `/lfg`, return without running tests, typecheck, lint,
     builds, schema pulls, migrations, browser checks, or the project health command. The parent
     orchestrator writes tests, then owns the pre-review and conditional final full gates.
   - For a standalone `/build`, this skill's main/orchestrator (never a builder) runs one canonical
     full health command against the completed tree, keyed by `(tree SHA, exact command)`.

   Tests, builds, migrations, large diffs, and other noisy commands use `bin/compact-exec` or an
   established equally compact stricter wrapper. Preserve the full log and consume only its bounded
   summary/tail. A failure report includes the absolute `output_file` and exact `rerun_command`.

   If the standalone orchestrator health command fails, it may dispatch one narrowly scoped repair
   chain. That builder still does not run validation. After the changed tree returns, the
   orchestrator reruns the failed gate once, records the failure-driven rerun, and stops if it
   still fails. Focused diagnostics used to isolate a gate failure are also orchestrator-owned and
   keyed to `(tree SHA, exact command)`.

   Then run the **migration parity sweep** (repo-wide, orchestrator-owned): diff the branch
   against main for the repo's model/schema/migration paths.

   *Example (ts-prefect after E0017):*

   ```bash
   git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' atlas.hcl atlas/plans/ cli_tools/atlas/ migrations/db_object_manifest.py migrations/versions/ | head -20
   ```

   If model/schema files changed, use the repo's current schema system (check the project's
   CLAUDE.md for which one is active):

   - schema-truth repos: do not create legacy migrations; ensure the repo's schema plan/safety
     checks cover the change, and update the reviewed committed plan deliberately if production
     DDL is needed. *Example (ts-prefect after E0017):* no Alembic migrations — Atlas
     plan/safety checks and `verify_schema_truth.py` must cover the change.
   - legacy migration repos: if no migration exists, STOP and create one (omitting it means the
     column won't exist at runtime). If a migration exists, confirm the deployment guide names a
     migration lane (schema-first with immediate `main→staging` sync, or full parity merge).
     Do not leave the build artifact implying that normal selective ticket promotion is safe for
     migration-bearing work.

   If the plan removes/decommissions an old structure, the orchestrator closes its negative
   inventory after its applicable full gate: re-run the plan's bounded old-entrypoint/writer/config
   search and require zero unexplained matches. Runtime registrations are verified later by
   deploy/verify, but the build cannot report complete while scoped legacy code/config remains.

8. **After the loop converges:**
   - Do not run validation after an orchestrated handoff. In standalone mode, do not repeat the
     same full command against an unchanged tree; reuse the PASS keyed by `(tree SHA, command)`.
   - Record the Completion Summary: ticketed runs update the plan **artifact** via
     `update_artifact`; ticketless runs append it to `.context/plan.md`
   - Do **not** invoke `/write-tests` here — the orchestrator (`/ticket-flow`, `/lfg`) owns
     that step after `/build` returns

## Status Flow

```
pending -> in_progress -> complete   (orchestrator sets `complete` after validating the
                      -> skipped       builder's structured result — never the builder itself)
```

## Completion Summary Format

After completing all build steps, add this section to the plan (before the Work Log) — the plan
**artifact** via `update_artifact` for ticketed runs, or `.context/plan.md` for ticketless runs:

```markdown
---

## Completion Summary

**Completed:** YYYY-MM-DD
**Build Duration:** [time from first to last build step]

### What Was Done

- [Key change 1: brief description]
- [Key change 2: brief description]
- [Key change 3: brief description]

### Files Changed

| File              | Change              |
| ----------------- | ------------------- |
| `path/to/file.py` | [brief description] |

### Deviations from Plan

[Note any changes from the original plan, or "None - implemented as planned"]

### Notes for Future Reference

[Any learnings, gotchas, or context worth preserving, or "None"]
```

## Work Log Entry Format

After each step, add to the plan's Work Log (plan artifact via `update_artifact` for ticketed
runs; `.context/plan.md` for ticketless runs):

```markdown
| YYYY-MM-DD | build | Completed step NN: [title] | [result/notes] |
```

## Output

On convergence:

```
Build complete for {ID}: {title}

Steps: {N}/{N} completed
Validation: PENDING parent orchestrator | PASS ({command} @ {tree SHA}, standalone only)
Visual verification: PENDING parent orchestrator | {absolute screenshot paths, standalone only}

Implementation:
- {todo NN}: {one line: what changed} — checkpointed from chain {chain id}
- {todo NN}: ...

Risks/unverified: {union of builder reports, or "none reported"; never claim validation from a
builder result}

Next: /write-tests {ID}, then /review {ID} (review implementation against the plan)
```

**Evidence rules for the final report (trust contract):** implementation claims name their
per-todo checkpoint; validation claims name the orchestrator-owned command, result, and tree SHA.
Anything not exercised by the owning orchestrator stays under "Risks/unverified". Never turn a
builder's completion mapping into a validation claim.

If a todo is **blocked** (returned `failed` and self-repair exhausted its 2 retries):

```
Build blocked at step {N}: {title}

Error: {error from the builder's structured result}
Retries: 2/2 exhausted. Downstream steps not attempted.

Next: Fix the blocker, then re-run /build {ID} --step {N}
```

If a builder returned **needs_replan** (the plan itself is wrong):

```
Build halted at step {N}: {title} — plan needs revision

Reason: {error from the builder's structured result}

Next: /ticket-plan {ID} (revise the plan), then /create-build-todos, then /build {ID}
```

## Completion Notes

Fill in each completed build_todo:

```markdown
## Completion Notes

**Completed:** YYYY-MM-DD
**Actual changes:**

- Modified `src/path/to/file.py` lines 45-60
- Added test in `tests/test_feature.py`

**Issues encountered:**

- Had to adjust threshold to 0.72 instead of 0.75 based on testing

**Visual evidence (required for UI/visible work):**

- `/absolute/path/to/.context/screenshots/YYYYMMDD-HHMMSS-feature-state.png` — actual browser screenshot of the changed surface
```

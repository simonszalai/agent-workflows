---
name: build
description: Execute an implementation plan. Spawns builder agent to work through build_todos step by step.
max_turns: 100
---

# Build Command

Execute a plan by spawning a `builder` agent to work through build_todos.

## Usage

```
/build 009                  # Execute bug #009 (NNN format)
/build F001                 # Execute feature F001 (FNNN format)
/build F001 --step 2        # Execute specific step
/build B0009                  # Bug ticket B0009
```

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

### Standard Mode (Worktree)

```bash
# 1. Check worktree (not main repo)
git rev-parse --abbrev-ref HEAD  # Must NOT be "main"
git worktree list | grep "$(pwd)" | grep -v "bare"  # Must match current dir

# 2. Load ticket and check artifacts exist
mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
# Check for build_todo artifacts — if none: STOP - run /create-build-todos first
# Check for plan artifact — if missing: STOP - run /plan first
```

### Branch Mode (Cloud)

When `CLAUDE_CODE_REMOTE=true`:

```bash
# 1. Check we're on a feature branch (not main)
git rev-parse --abbrev-ref HEAD  # Must NOT be "main"
# If on main: Create branch first

# 2. Load ticket and check artifacts exist
mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
# Check for build_todo artifacts — if none: STOP - run /create-build-todos first
# Check for plan artifact — if missing: STOP - run /plan first
```

**If any prerequisite fails:**

| Missing         | Action                                               |
| --------------- | ---------------------------------------------------- |
| Not in worktree | Instruct user to create worktree (see below)         |
| On main (cloud) | Create branch with `git checkout -b auto-build/{id}` |
| No build_todos/ | **STOP** - run `/create-build-todos [id]` first      |
| No plan.md      | **STOP** - run `/plan [id]` first                    |

## Process

1. **Set ticket status to building:**
   ```
   mcp__autodev-memory__update_ticket(
     project=PROJECT, ticket_id=ID, repo=REPO,
     status="building",
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
   - If on main: Create branch with `git checkout -b auto-build/{id}` or `git checkout -b lfg/{id}`
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

5. **Spawn builder agent:**

   ```
   Agent(
     subagent_type="builder",
     model="opus",
     prompt="
       MODE: build
       Ticket: {ticket_id}
       Project: {PROJECT}
       Repo: {REPO}

       Execute all pending build_todo artifacts for this ticket.

       Plan summary: {plan artifact summary}

       Build todos (pending):
       {list of pending build_todo artifacts with sequence numbers}

       {if --step: 'Execute ONLY step {N}'}

       Work through each step in sequence order. For each step:
       1. Read the build_todo artifact content
       2. Implement changes following discovered patterns
       3. Run verification commands from the todo
       4. Run tests, type checker, linter
       5. Update artifact status to complete

       After all steps: run migration parity check (git diff model files vs migrations).

       Return completion summary with steps completed, test results, and any issues.
     "
   )
   ```

6. **After builder returns:**
   - Write tests: run `/write-tests {work-item-id}`
   - Run full test suite to check for regressions
   - Update plan artifact with completion summary via `update_artifact`

7. **Parallel execution (optional):**
   - If the plan has truly independent pieces of work (e.g., changes in separate repos,
     unrelated modules), spawn multiple builder agents in parallel
   - Good candidates for parallelization:
     - Work in different repositories
     - Independent features with no shared code paths
   - **After parallel work completes:** Verify everything fits together

   > **When in doubt, build sequentially.** Only parallelize when you're confident the
   > work is truly independent.

## Status Flow

```
pending -> in_progress -> complete
                      -> skipped (with reason)
```

## Completion Summary Format

After completing all build steps, add this section to `plan.md` (before the Work Log):

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

After each step, add to `plan.md`:

```markdown
| YYYY-MM-DD | build | Completed step NN: [title] | [result/notes] |
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
```

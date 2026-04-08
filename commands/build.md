---
description: Execute an implementation plan. Works through build_todos step by step, writes code, updates work log.
max_turns: 100
---

# Build Command

Execute a plan by working through build_todos.

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

1. **Verify execution context (REQUIRED):**

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

2. **Process user feedback:**
   - Read plan artifact from `get_ticket` response — check Open Questions and Additional Notes
   - If answers or notes require changes to build_todos:
     - Update affected build_todo artifacts via `update_artifact`
     - Add/remove/modify steps as indicated
     - Document changes in work log

3. **Validate build_todos against plan:**
   - Verify build_todo artifacts align with plan artifact decisions
   - If build_todos contradict plan, update via `update_artifact` to resolve
   - Check memory service for relevant gotchas and patterns

4. **Verify ready:**
   - Read plan artifact — understand the approach
   - List build_todo artifacts — identify pending steps (status != "complete")

5. **Execute each step:**
   - Read todo file - understand objective
   - Update artifact status: `mcp__autodev-memory__update_artifact(project=PROJECT, artifact_id=ID, status="in_progress")`
   - Implement changes as specified
   - **Run ALL verification commands** listed in the build todo's Verification section
   - **Count-verify bulk changes:** If the todo says "modify N call sites," run a grep
     to confirm all N were actually modified. Example:
     ```bash
     # If todo says "add prompt_version_id to 24 call sites"
     grep -r "prompt_version_id=" src/flows/ --include="*.py" | wc -l
     # Must match expected count
     ```
   - **Delete verification:** If todo says "delete file X," verify it no longer exists
   - **Elimination verification:** If the plan has a "What We're Eliminating" section, grep
     for imports of the old system after ALL build steps complete. Zero results required.
     This is a build blocker — do not proceed to tests or review until verified.
   - Run tests (project's test suite)
   - Run type checker (project's type checker)
   - Run linter (project's linter)
   - Update artifact: `update_artifact(artifact_id=ID, status="complete", content="<updated with completion notes>")`

6. **Handle issues:**
   | Issue | Action |
   | --------------------- | ------------------------------- |
   | Missing info | Note in todo, continue or pause |
   | Tests failing | Debug, fix, document |
   | Approach doesn't work | Revise plan.md, document changes |

7. **Write tests for new code:**
   - After all build steps are complete, run `/write-tests {work-item-id}`
   - This analyzes all code changes and writes appropriate tests:
     - Unit tests for pure logic and business rules
     - Integration tests for database operations
     - E2E tests for multi-step user flows
   - Run all new tests to verify they pass
   - Run full test suite to check for regressions

8. **Parallel execution (optional):**
   - If the plan has truly independent pieces of work (e.g., changes in separate repos, unrelated modules), spawn parallel subagents to speed up execution
   - Good candidates for parallelization:
     - Work in different repositories
     - Independent features with no shared code paths
     - Separate test suites that don't interact
   - **After parallel work completes:** Verify everything fits together
     - Run integration tests across affected repos
     - Check for interface mismatches
     - Ensure shared types/schemas are consistent

   > **When in doubt, build sequentially.** If independence isn't clear, don't take risks. Sequential execution is safer and easier to debug. Only parallelize when you're confident the work is truly independent.

9. **Migration parity check (REQUIRED after model changes):**
   - After all build steps, check if any model files were modified:
     ```bash
     git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' | head -20
     ```
   - If model files changed, verify a migration exists in this branch:
     ```bash
     git diff --name-only main -- migrations/versions/ | grep '\.py$'
     ```
   - **If models changed but no migration exists: STOP.** Create one before proceeding:
     ```bash
     uv run alembic revision --autogenerate -m 'description'
     ```
   - This is a build blocker — missing migrations cause production failures.

10. **Final:**
   - Run full test suite
   - Run type checker - fix any type errors before completing
   - Update plan artifact with completion summary via `update_artifact`

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

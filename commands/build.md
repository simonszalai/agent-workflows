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
/build work_items/active/009-fix-timeout  # Use explicit path
```

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

### Standard Mode (Worktree)

```bash
# 1. Check worktree (not main repo)
git rev-parse --abbrev-ref HEAD  # Must NOT be "main"
git worktree list | grep "$(pwd)" | grep -v "bare"  # Must match current dir

# 2. Check build_todos exist
ls work_items/*/[id]*/build_todos/*.md 2>/dev/null | head -1
# If empty: STOP - run /create-build-todos first

# 3. Check plan.md exists
test -f work_items/*/[id]*/plan.md || echo "MISSING plan.md"
```

### Branch Mode (Cloud/Auto-Fix)

When `CLAUDE_CODE_REMOTE=true` or invoked from `/auto-fix`:

```bash
# 1. Check we're on a feature branch (not main)
git rev-parse --abbrev-ref HEAD  # Must NOT be "main"
# If on main: Create branch first (see Branch-Based Execution below)

# 2. Check build_todos exist
ls work_items/*/[id]*/build_todos/*.md 2>/dev/null | head -1

# 3. Check plan.md exists
test -f work_items/*/[id]*/plan.md || echo "MISSING plan.md"
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

   **Branch Mode (Cloud/Auto-Fix):**
   - Detected when `CLAUDE_CODE_REMOTE=true` or invoked from `/auto-fix`
   - In branch mode, worktrees are not available - use feature branches instead
   - If on main: Create branch with `git checkout -b auto-build/{id}` or `git checkout -b auto-fix/{id}`
   - All operations happen in current directory on the feature branch
   - This mode is used for cloud execution where worktrees aren't practical

2. **Process user feedback:**
   - Read `plan.md` Open Questions section - review all Q&A pairs
   - Read `plan.md` Additional Notes section - note any corrections or clarifications
   - If answers or notes require changes to build_todos:
     - Update affected todo files with new requirements
     - Add/remove/modify steps as indicated
     - Document changes in work log

3. **Validate build_todos against plan:**
   - Verify build_todos align with plan.md decisions
   - If build_todos contradict plan.md, update plan.md or build_todos to resolve
   - Check knowledge base for relevant gotchas and patterns

4. **Verify ready:**
   - Read `plan.md` - understand the approach
   - List `build_todos/` - identify pending steps

5. **Execute each step:**
   - Read todo file - understand objective
   - Update status to `in_progress`
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
   - Run tests (project's test suite)
   - Run type checker (project's type checker)
   - Run linter (project's linter)
   - Update status to `complete`
   - Fill Completion Notes section
   - Add work log entry to `plan.md`

6. **Handle issues:**
   | Issue | Action |
   | --------------------- | ------------------------------- |
   | Missing info | Note in todo, continue or pause |
   | Tests failing | Debug, fix, document |
   | Approach doesn't work | Revise plan.md, document changes |

7. **Parallel execution (optional):**
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

8. **Final:**
   - Run full test suite
   - Run type checker - fix any type errors before completing
   - Add completion summary to `plan.md` (see format below)
   - Add final work log entry

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

---
description: Create detailed implementation steps from an approved plan. Spawns build-planner agent to create build_todos/.
max_turns: 75
---

# Create Build Todos Command

Create detailed implementation steps (`build_todos/`) from an approved `plan.md`. This command
performs **deep research** into the codebase, knowledge base, and git history to ensure all
existing patterns and rules are discovered and followed.

## Usage

```
/create-build-todos 009                              # Bug/incident #009 (NNN format)
/create-build-todos F001                             # Feature F001 (FNNN format)
/create-build-todos work_items/active/009-fix-timeout  # Use explicit path
```

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

```bash
# 1. Locate work item
find work_items -maxdepth 2 -type d -name "*[id]*" | head -1
# If empty: STOP - work item not found

# 2. Check plan.md exists
test -f work_items/*/[id]*/plan.md || echo "MISSING plan.md"
# If missing: STOP - run /plan first

# 3. Check plan is approved (has work log entry or explicit approval)
grep -E "^\| [0-9]{4}-[0-9]{2}-[0-9]{2} \| plan \|" work_items/*/[id]*/plan.md
# If no entries: warn that plan may not be reviewed
```

**If any prerequisite fails:**

| Missing             | Action                                 |
| ------------------- | -------------------------------------- |
| Work item not found | **STOP** - create work item first      |
| No plan.md          | **STOP** - run `/plan [id]` first      |
| Plan not reviewed   | **WARN** - suggest user review plan.md |

**Additional requirements:**

- Review and iterate on plan.md before running this command

## What This Command Does

**Deep research phase:**

1. **Knowledge base search** - Find all relevant:
   - References (architecture, patterns, standards)
   - Gotchas (pitfalls that apply to this change)
   - Solutions (past fixes for similar problems)

2. **Codebase pattern search** - Find all:
   - Similar implementations to follow
   - Conventions specific to affected areas
   - Error handling patterns in use
   - Test patterns for this type of code

3. **Git history analysis** - Understand:
   - Why affected code exists in its current form
   - Past issues with similar changes
   - Recent changes that might conflict
   - Contributors who know this area

**Implementation planning phase:**

4. **Create build_todos/** with detailed steps:
   - Specific files to modify
   - Code examples following discovered patterns
   - Dependencies between steps
   - Test requirements per step
   - Verification commands

## Process

1. **Locate work item:**
   - Same ID resolution as `/plan` command
   - Error if plan.md doesn't exist

2. **Read context:**
   - `plan.md` - The approved architecture plan
   - `source.md` - Original problem/feature description
   - `investigation.md` - Production findings (if exists)

3. **Spawn build-planner agent** for deep research:
   - Agent searches knowledge base exhaustively
   - Agent searches codebase for all relevant patterns
   - Agent analyzes git history for context
   - Agent may spawn additional researcher agents

4. **Write build_todos/**:
   - One file per implementation step
   - Steps ordered by dependencies
   - Each step includes discovered patterns to follow

5. **Commit build_todos/**:

   ```bash
   git add work_items/*/[id]*/build_todos/
   git commit -m "Create build todos for {work-item-id}

   Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
   ```

## Research Depth

The build-planner agent performs thorough research:

| Area            | What It Searches                               | Why                                        |
| --------------- | ---------------------------------------------- | ------------------------------------------ |
| Knowledge base  | All references, gotchas, solutions             | Avoid known pitfalls, follow standards     |
| Codebase        | Similar code, patterns, conventions            | Match existing style and approaches        |
| Git history     | Related commits, past issues, contributor info | Understand context and avoid past mistakes |
| Past work items | Similar build_todos, review findings           | Reuse patterns, avoid past review issues   |
| CLAUDE.md       | Project rules and critical requirements        | Ensure compliance with project rules       |

## Output

```
work_items/active/{NNN|FNNN}-title/
  plan.md             # Input (must exist)
  build_todos/        # Created by build-planner
    01-step-name.md
    02-step-name.md
    ...
```

Each build todo contains:

- **Objective** - What this step accomplishes
- **Files to Modify** - Specific files and line estimates
- **Discovered Patterns** - Patterns found that must be followed
- **Implementation Details** - Code snippets following patterns
- **Tests** - Test cases based on similar code
- **Verification** - Commands to verify step worked

## Agent Selection (if build-planner requests)

| Need                     | Agent          | Why                                |
| ------------------------ | -------------- | ---------------------------------- |
| Deeper pattern search    | `researcher`   | Find more examples in codebase     |
| Framework best practices | `web-searcher` | External docs for complex patterns |

## Post-Creation Validation

After all build todos are written, verify knowledge base compliance:

```bash
# Check that build todos reference the knowledge base
grep -rl "knowledge" work_items/*/[id]*/build_todos/ | wc -l
# If 0: WARNING - no knowledge base references found. Re-run research phase.

# Check that every build todo has "From knowledge base" subsection
for f in work_items/*/[id]*/build_todos/*.md; do
  grep -q "From knowledge base" "$f" || echo "MISSING knowledge base section: $f"
done
```

If validation fails, go back and add the missing knowledge base research before committing.

## Next Steps

After build_todos are created and committed:

```
/build F001                   # Execute build in current session
```

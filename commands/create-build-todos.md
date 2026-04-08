---
description: Create detailed implementation steps from an approved plan. Spawns build-planner agent to create build_todos/.
max_turns: 75
---

# Create Build Todos Command

Create detailed implementation steps (`build_todos/`) from an approved `plan.md`. This command
performs **deep research** into the codebase, memory service, and git history to ensure all
existing patterns and rules are discovered and followed.

## Usage

```
/create-build-todos 009                              # Bug/incident #009 (NNN format)
/create-build-todos F001                             # Feature F001 (FNNN format)
/create-build-todos B0009                              # Bug ticket B0009
```

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

```
# 1. Load ticket
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
# If not found: STOP - ticket not found

# 2. Check plan artifact exists
# Look for artifact with type="plan" in ticket response
# If missing: STOP - run /plan first
```

**If any prerequisite fails:**

| Missing             | Action                                 |
| ------------------- | -------------------------------------- |
| Ticket not found    | **STOP** - create ticket first         |
| No plan artifact    | **STOP** - run `/plan [id]` first      |
| Plan not reviewed   | **WARN** - suggest user review plan    |

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

2. **Read context** from `get_ticket` response:
   - Plan artifact - The approved architecture plan
   - Source artifact - Original problem/feature description
   - Investigation artifact - Production findings (if exists)

3. **Spawn build-planner agent** for deep research:
   - Agent searches memory service exhaustively
   - Agent searches codebase for all relevant patterns
   - Agent analyzes git history for context
   - Agent may spawn additional researcher agents

4. **Write build_todo artifacts:**
   - One artifact per implementation step
   - Steps ordered by dependencies via `sequence` field
   - Each step includes discovered patterns to follow
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="build_todo",
     title="<step title>",
     sequence=N,
     status="pending",
     content="<step content>",
     command="/create-build-todos"
   )
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

Build todo artifacts stored in MCP ticket system:

| Artifact | Type | Sequence |
|---|---|---|
| Step 1: [name] | build_todo | 1 |
| Step 2: [name] | build_todo | 2 |
| ... | build_todo | N |

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

After all build todos are written, verify memory service compliance by reading back
the ticket artifacts and checking each build_todo content contains memory service
references. If any are missing, go back and add the missing research.

## Next Steps

After build_todos are created and committed:

```
/build F001                   # Execute build in current session
```

# Universal Development Conventions

Shared conventions for all projects using Claude Code agent workflows.

## Agent Rules (Critical - Never Violate)

- Never commit/push without explicit user approval (except during /resolve-review final step)
- Never create markdown files unless explicitly instructed
- Never deploy or run production operations without explicit instruction
- Never create database migrations without explicit instruction
- **Never put work item artifacts in `.context/`** - see File Storage Rules below
- **Never modify `~/dev/*` (main repos) directly** - always work in the Conductor workspace
  that is in your context (e.g., `~/conductor/workspaces/<project>/<workspace-name>/`). The
  `~/dev/*` paths are the main checkouts and must not be touched unless explicitly requested.

## File Storage Rules (Critical - `.context/` vs `work_items/`)

When running inside Conductor, each workspace has a `.context/` directory. This directory is
**only for ephemeral inter-agent scratch data** (e.g., temporary intermediate results passed
between parallel subagents within a single session). It is gitignored and disposable.

**All persistent work artifacts go in `work_items/`**, never in `.context/`. This includes:

| Artifact                     | Correct Location                              |
| ---------------------------- | --------------------------------------------- |
| `plan.md`                    | `work_items/<status>/<item-id>/plan.md`       |
| `build_todos/`               | `work_items/<status>/<item-id>/build_todos/`  |
| `review_todos/`              | `work_items/<status>/<item-id>/review_todos/` |
| `source.md`                  | `work_items/<status>/<item-id>/source.md`     |
| Investigation reports        | `work_items/<status>/<item-id>/`              |
| Deployment guides            | `work_items/<status>/<item-id>/`              |
| Any file that should persist | `work_items/` or project source code          |

**Never use `.context/` for:**

- Plans, build todos, review findings, or any work item artifact
- Anything that needs to survive across sessions
- Anything that should be committed to git

**Only use `.context/` for:**

- Temporary data passed between parallel subagents in a single session
- Scratch computations that are consumed immediately and then discarded

## Code Style (All Projects)

- No backwards-compatibility shims - delete unused code completely
- No `Any` types in TypeScript or Python
- No `type: ignore` unless explicitly asked
- Prefer Pydantic models over dataclass (Python projects)
- Always return structured types from functions, never complex dicts
- Imports only at top of file (exception: circular imports with comment)
- Always use TEXT instead of VARCHAR for string columns (PostgreSQL)
- All timestamps need server_default with CURRENT_TIMESTAMP

## What I Mean by "Agent Workflows"

Agent workflows are the `.claude/` configuration system with three layers:

1. **Skills** - Portable methodology documents (the HOW)
   - Review checklists, research methods, tool references, testing patterns
   - NEVER contain project-specific details (no table names, service IDs, routes)
   - Loaded by agents as reference material
   - File: `skills/<name>/SKILL.md` with optional `templates/` subdirectory

2. **Agents** - Role definitions (the WHO)
   - Define a specialized agent's purpose, methodology, skills to load, tool access
   - Get project context from CLAUDE.md - not hardcoded
   - File: `agents/<name>.md`

3. **Commands** - Workflow orchestration (the WHAT)
   - User-invocable with `/<command-name>`
   - Spawn and coordinate agents, chain multi-step workflows
   - File: `commands/<name>.md`

### User-Level vs Project-Level

| Level   | Location                                    | Contains                                 |
| ------- | ------------------------------------------- | ---------------------------------------- |
| User    | `~/.claude/skills/`, `agents/`, `commands/` | Universal methodology for ALL projects   |
| Project | `.claude/skills/`, `agents/`, `commands/`   | Project-specific overrides and additions |

**Rule:** If a skill, agent, or command is used in 2+ projects, it belongs at user level.
Project-specific context (table names, services, routes) goes in CLAUDE.md, not in
agent/skill/command definitions.

Project-level overrides user-level when both have the same filename.

### Agent Workflow Distribution

Shared agents, commands, skills, and this CLAUDE.md live in `simonszalai/agent-workflows`.

| Environment     | Mechanism                               | Direction |
| --------------- | --------------------------------------- | --------- |
| Local dev       | `~/.claude/` symlinks → agent-workflows | Two-way   |
| NanoClaw        | Volume mount from agent-workflows       | Two-way   |
| Claude Code web | SessionStart copies agent-workflows     | One-way   |

**Resolution:** Claude Code checks project `.claude/` first, then user `~/.claude/`.

### Where to Make Changes

| Change type                      | Target                                    | Why                  |
| -------------------------------- | ----------------------------------------- | -------------------- |
| Project-specific agent/skill/cmd | `.claude/` in project repo                | Only relevant there  |
| Shared skill/agent/command       | `~/.claude/` (→ agent-workflows)          | Available everywhere |
| User-level CLAUDE.md conventions | `~/.claude/CLAUDE.md` (→ agent-workflows) | Shared rules         |
| Knowledge gotcha/reference       | `.claude/knowledge/` in project           | Project-specific     |
| Cross-session learning           | OpenMemory (via add-memory)               | Persists in cloud    |
| User correction/preference       | OpenMemory (user_preference)              | Cross-project        |

### Committing User-Level Changes (Critical)

When `/compound`, `/heal-workflows`, or any correction triggers an edit to a **user-level**
file (shared skill, agent, command, or this CLAUDE.md), the edit goes through the symlink
and modifies the `agent-workflows` repo directly. The agent MUST then:

1. `cd ~/dev/agent-workflows` (or wherever the repo is checked out)
2. `git add` the changed files
3. `git commit -m "compound: <description of what changed>"`
4. `git push origin main`

This ensures the improvement propagates to all environments. Without the push, the change
only exists locally and won't reach cloud sessions or other machines.

**Project-level changes** (files in the project's `.claude/` directory or `work_items/`)
do NOT need this — they are committed as part of normal project workflow.

**Cloud sessions:** File changes to `~/.claude/` are ephemeral. Learnings MUST be saved
to OpenMemory to persist. The `/compound` command handles this automatically.

## Proactive Command & Agent Triggers

When the user mentions these activities, proactively use the corresponding command or agent:

### Investigation & Research

| User says                                                 | Action             |
| --------------------------------------------------------- | ------------------ |
| "investigate", "what's wrong with", "why is this failing" | Run `/investigate` |
| "research", "how does X work", "find all instances of"    | Run `/research`    |
| "look into", "debug this", "root cause"                   | Run `/investigate` |

### Planning & Building

| User says                                      | Action                    |
| ---------------------------------------------- | ------------------------- |
| "plan", "design", "architect", "how should we" | Run `/plan`               |
| "build", "implement", "start working on"       | Run `/build`              |
| "create build todos", "break this down"        | Run `/create-build-todos` |

### Review & Quality

| User says                                   | Action                |
| ------------------------------------------- | --------------------- |
| "review", "check my code", "look over this" | Run `/review`         |
| "resolve review", "fix review findings"     | Run `/resolve-review` |

### Testing

| User says                                                 | Action              |
| --------------------------------------------------------- | ------------------- |
| "write tests", "add tests", "test coverage"               | Run `/write-tests`  |
| "fix tests", "tests failing", "CI failing", "test broken" | Run `/fix-tests`    |
| "verify in browser", "check the UI", "smoke test"         | Run `/test-browser` |

### Verification & Deployment

| User says                                       | Action                         |
| ----------------------------------------------- | ------------------------------ |
| "verify", "test this locally", "does this work" | Run `/verify-local`            |
| "check production", "verify deployed"           | Run `/verify-prod`             |
| "create deployment guide"                       | Run `/create-deployment-guide` |
| "create PR", "make a PR", "open PR"             | Run `/create-pr`               |

### Automation

| User says                               | Action            |
| --------------------------------------- | ----------------- |
| "auto-build", "build it end to end"     | Run `/auto-build` |
| "auto-fix", "fix this bug autonomously" | Run `/auto-fix`   |

### Learning & Correction Detection

| User says                                                          | Action                        |
| ------------------------------------------------------------------ | ----------------------------- |
| "compound", "document this", "save this learning"                  | Run `/compound`               |
| "what did we learn", "learn from review", "learn from this"        | Run `/compound`               |
| "no, do X instead", "that's wrong", "you should have"              | Proactively offer `/compound` |
| "don't do that", "actually the correct way is", "you keep doing X" | Proactively offer `/compound` |
| "retrospect", "what went wrong", "post-mortem"                     | Run `/retrospect`             |

**Correction detection:** When the user explicitly corrects Claude's approach or output,
proactively ask: "Should I `/compound` this so it doesn't happen again?" This ensures
corrections become permanent workflow/knowledge improvements.

### Maintenance

| User says                                                       | Action                 |
| --------------------------------------------------------------- | ---------------------- |
| "heal workflows", "check agent config"                          | Run `/heal-workflows`  |
| "heal knowledge", "organize knowledge", "consolidate knowledge" | Run `/heal-knowledge`  |
| "heal work items", "clean up work items"                        | Run `/heal-work-items` |

### Work Item Management

| User says                                               | Action                  |
| ------------------------------------------------------- | ----------------------- |
| "exclude from scope", "defer this", "out of scope"      | Spawn work-item-curator |
| "new work item", "track this as", "create backlog item" | Spawn work-item-curator |
| "add to F003", "update source.md", "add context to"     | Spawn work-item-curator |

### Agent Workflow Modification

| User says                                          | Action                              |
| -------------------------------------------------- | ----------------------------------- |
| "add a skill", "create an agent", "new command"    | Load agent-workflow-authoring skill |
| "update workflows", "modify agent", "change skill" | Load agent-workflow-authoring skill |

## Parallelism

When spawning multiple independent agents (e.g., /review spawns reviewer-code, reviewer-data,
reviewer-system), ALWAYS use parallel Task tool calls in a single message. Never spawn
sequentially when agents don't depend on each other's output.

## Work Items System

### Folder Structure

```
work_items/
├── active/     # Currently being worked on
├── backlog/    # Planned but not started
├── to_verify/  # Built, awaiting verification
└── closed/     # Completed and verified
```

### Naming Convention

- Bugs: `NNN-kebab-title` (e.g., `042-fix-duplicate-alerts`)
- Features: `FNNN-kebab-title` (e.g., `F003-add-user-dashboard`)
- Auto-fix bugs: `BNNN-kebab-title` (e.g., `B001-oom-fix`)

### Work Item Numbering (CRITICAL)

**These rules prevent duplicate ID conflicts:**

1. **Check ALL folders before creating**: active/, backlog/, to_verify/, closed/, completed/,
   AND root work_items/ folder
2. **Cross-project imports get NEW numbers**: Never keep the original number when importing a
   work item from another project
3. **Validate before creation**: Verify the number doesn't exist anywhere in the target project
4. **Numbers are project-scoped**: Each project maintains its own sequence

**When creating a work item:**

```bash
# Find highest existing number across ALL locations
find work_items -type d -name "F[0-9]*-*" | sed 's/.*\///; s/F//; s/-.*//' | sort -n | tail -1
# Then increment by 1 and verify it's unique
```

### Cross-Repository Work Items

When a feature spans multiple repositories (e.g., API changes in ts-scraper need corresponding
changes in ts-prefect), create linked work items in each repo.

**Scope:** Only work item **creation** should happen cross-repo. The actual implementation work
happens in dedicated worktrees/branches for each repo. The cross-repo work item serves as a
placeholder that clearly references the original work item.

**Key Rules:**

1. **Always commit to the main repo, not worktrees**: If working in a worktree, switch to the main
   repo directory before creating work items
2. **Check origin/main for next number**: Worktrees may be behind; always check the remote
3. **Reference the original work item clearly**: The source.md must specify the originating repo
   and work item ID so the relationship is unambiguous

**Process for creating a work item in another repository:**

```bash
# 1. Navigate to the main repo (NOT a worktree)
cd ~/dev/ts-prefect  # Main repo, not ~/conductor/workspaces/ts-prefect/...

# 2. Ensure you're on main and up to date
git checkout main
git fetch origin
git reset --hard origin/main  # If local main has diverged

# 3. Find the next available feature number from REMOTE (critical!)
git ls-tree -r --name-only origin/main work_items/ | grep -E "F[0-9]+-" | \
  sed 's/.*\(F[0-9]*\)-.*/\1/' | sort -u | tail -1
# Returns e.g., "F034" -> next is F035

# 4. Create the work item folder and source.md
mkdir -p work_items/backlog/F035-descriptive-slug

# 5. Write source.md - MUST reference the original work item
# (See Required Frontmatter below for the 'related' field)

# 6. Commit and push
git add work_items/backlog/F035-descriptive-slug/
git commit -m "Add F035: Feature title (ts-prefect side of ts-scraper/F004)"
git push origin main

# 7. Return to your working directory/worktree
```

**Common Mistakes:**

- Creating in a worktree instead of main repo → work item not visible to others
- Checking local branch for next number → may conflict with remote changes
- Vague references like "related to scraper work" → use explicit "ts-scraper/F004" format
- Doing implementation work in main branch → use dedicated worktrees/branches

### Required Frontmatter

```yaml
title: Human-readable title
type: bug | feature
status: active | backlog | to_verify | closed
created: YYYY-MM-DD
related: ts-scraper/F004 # Required for cross-repo: explicit repo-name/work-item-id format
```

**For cross-repo work items:** The `related` field is mandatory and must use the format
`repo-name/work-item-id` (e.g., `ts-scraper/F004`, `ts-prefect/F035`). This creates an
unambiguous link back to the original work item.

### Work Item Lifecycle

1. **Create** - backlog/ (or active/ if starting immediately)
2. **Start** - move to active/, set status: active
3. **Plan** - /plan creates plan.md in the work item folder
4. **Build todos** - /create-build-todos creates build_todos/ from plan
5. **Build** - /build works through build_todos step by step
6. **Review** - /review spawns reviewers, creates review_todos/
7. **Resolve** - /resolve-review fixes review findings
8. **Verify locally** - /verify-local runs local verification
9. **Deploy** - project-specific deployment
10. **Verify production** - /verify-prod checks production state
11. **Close** - move to closed/, set status: closed

### Autonomous Workflows

- `/auto-build`: Steps 2-8 + creates PR (for features with approved plans)
- `/auto-fix`: Investigate -> hypothesize -> fix -> review -> PR (for bugs)

## 2-Tier Knowledge System

| Tier   | Location           | Purpose             | Always in Context |
| ------ | ------------------ | ------------------- | ----------------- |
| Tier 1 | CLAUDE.md          | Critical rules      | Yes               |
| Tier 2 | .claude/knowledge/ | Detailed references | No (searched)     |

### Knowledge Base Structure

- `references/` - Architecture, patterns, deployment guides
- `gotchas/` - Common pitfalls and their solutions
- `solutions/` - Problem resolutions

### When to Search Knowledge Base

- Researching patterns for a new feature
- Looking for past solutions to similar problems
- Reviewing code for known gotchas
- Creating build_todos that need codebase patterns

## Markdown Formatting

- Line length: 100 characters max
- Exception: Tables and URLs may exceed

## Agent Dispatch: Foreground vs Background (Critical)

**Default to foreground** (do NOT set `run_in_background: true`) for ALL agent dispatches
unless the user explicitly asks for background execution. Foreground parallel calls block until
all agents complete and return results inline — this is the correct behavior for workflows
that need to consolidate agent output (review, research, investigation, etc.).

**Never use `run_in_background: true` when:**

- The orchestrator needs agent results to continue (e.g., `/review` consolidates findings)
- The workflow has a next step that depends on agent output
- Multiple agents are spawned and their results must be synthesized

**Only use `run_in_background: true` when:**

- The user explicitly asks to run something in the background
- The task is fire-and-forget (e.g., a long-running build the user doesn't need to wait for)
- The user wants to continue working while agents run

**Why this matters:** Background agents return immediately with just an output file path. If
the orchestrator then responds to the user without waiting, the agent results are lost and the
workflow breaks. This has caused repeated failures where agents "completed" but their output
was never collected or acted upon.

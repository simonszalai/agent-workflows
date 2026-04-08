# Universal Development Conventions

Shared conventions for all projects using Claude Code agent workflows.

## Agent Rules (Critical - Never Violate)

- Never commit/push without explicit user approval (except during /resolve-review final step)
- Never create markdown files unless explicitly instructed
- Never deploy or run production operations without explicit instruction
- Always create database migrations when schema changes require them (they are auto-deployed
  by CI on merge). Omitting a migration means the column won't exist at runtime.
- **Never put ticket artifacts in `.context/`** - see File Storage Rules below
- **Never modify `~/dev/*` (main repos) directly** - always work in the Conductor workspace
  that is in your context (e.g., `~/conductor/workspaces/<project>/<workspace-name>/`). The
  `~/dev/*` paths are the main checkouts and must not be touched unless explicitly requested.

## File Storage Rules (Critical)

When running inside Conductor, each workspace has a `.context/` directory. This directory is
**only for ephemeral inter-agent scratch data** (e.g., temporary intermediate results passed
between parallel subagents within a single session). It is gitignored and disposable.

**All ticket artifacts are stored in the MCP ticket system**, not on the local filesystem.
Use `mcp__autodev-memory__create_artifact` to store plans, build todos, review findings, etc.

**Never use `.context/` for:**

- Plans, build todos, review findings, or any ticket artifact
- Anything that needs to survive across sessions

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
| Knowledge gotcha/reference       | Memory service via `mcp__autodev-memory`  | Persisted in MCP     |

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

**Project-level changes** (files in the project's `.claude/` directory)
do NOT need this — they are committed as part of normal project workflow.

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
| "auto-fix", "fix this bug autonomously" | Run `/lfg`        |

### Learning & Correction Detection

| User says                                                          | Action                        |
| ------------------------------------------------------------------ | ----------------------------- |
| "save this", "remember this", "store this"                         | Run `/save`                   |
| "define X", "X means", "glossary", "add term"                      | Run `/glossary`               |
| "wtf", "why didn't you know this", "you should have known"         | Run `/wtf`                    |
| "compound", "document this", "save this learning"                  | Run `/compound`               |
| "what did we learn", "learn from review", "learn from this"        | Run `/compound`               |
| "no, do X instead", "that's wrong", "you should have"              | Proactively offer `/save`     |
| "don't do that", "actually the correct way is", "you keep doing X" | Proactively offer `/save`     |
| "retrospect", "what went wrong", "post-mortem"                     | Run `/retrospect`             |

**Correction detection:** When the user explicitly corrects Claude's approach or output,
proactively ask: "Should I `/save` this to the memory system?" This ensures corrections become
permanent knowledge. Use `/compound` when the correction also implies workflow/skill changes.

### Maintenance

| User says                                                       | Action                 |
| --------------------------------------------------------------- | ---------------------- |
| "heal workflows", "check agent config"                          | Run `/heal-workflows`  |
| "heal work items", "clean up work items"                        | Run `/heal-work-items` |
| "consolidate memories", "audit memories", "clean up memories"   | Run `/consolidate`     |

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

## Ticket System (MCP-Based)

All tickets and their artifacts are managed via the `mcp__autodev-memory` MCP server.
No local `work_items/` directory is used.

### Ticket Context Resolution

Every command that works with tickets must resolve `project` and `repo`:

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

These two values are required for all ticket MCP calls.

### Ticket Types and IDs

- Features: `F0023` (auto-generated by `create_ticket` with `type: "feature"`)
- Bugs: `B0023` (auto-generated with `type: "bug"`)
- Refactors: `R0023` (auto-generated with `type: "refactor"`)

IDs are **repo-scoped** — each repo maintains its own sequence per type prefix.
`create_ticket` auto-generates the next available ID. Use `seq_num` only for migrations.

### MCP Ticket Tools

| Tool | Purpose |
|---|---|
| `create_ticket` | Create a new ticket (description becomes source artifact) |
| `get_ticket` | Get ticket with all artifacts and events |
| `list_tickets` | List tickets filtered by status/type/priority/repo |
| `update_ticket` | Update status, priority, title, etc. |
| `search_tickets` | Semantic + BM25 search across all ticket artifacts |
| `next_ticket` | Get highest-priority active ticket |
| `get_similar_tickets` | Find similar completed tickets |
| `create_artifact` | Add plan, build_todo, review_todo, etc. to a ticket |
| `update_artifact` | Update artifact content or status |

### Artifact Types

| Type | Purpose | Key Fields |
|---|---|---|
| `source` | Problem/feature description | Auto-created by `create_ticket` |
| `plan` | Architecture plan | content |
| `build_todo` | Implementation step | title, sequence, status, content |
| `review_todo` | Review finding | title, sequence, status, content |
| `investigation` | Root cause analysis | content |
| `retrospective` | Post-mortem analysis | content |
| `deployment_guide` | Deployment instructions | content |
| `learning_report` | Knowledge/workflow improvements | content |

### Ticket Statuses

```
backlog → active → to_verify → completed
                 → abandoned
```

Use `update_ticket(status="active")` to start work, `update_ticket(status="completed")`
to close, etc.

### Cross-Repository Tickets

When a feature spans multiple repos, create linked tickets using the `related` field:

```
create_ticket(
  project="ts", repo="ts-prefect",
  title="Feature title (ts-prefect side)",
  type="feature",
  description="...",
  related=["ts-scraper/F0004"]
)
```

### Ticket Lifecycle

1. **Create** — `create_ticket(status="backlog")` or `create_ticket(status="active")`
2. **Start** — `update_ticket(status="active")`
3. **Plan** — `create_artifact(artifact_type="plan", content=...)`
4. **Build todos** — `create_artifact(artifact_type="build_todo", sequence=N, ...)`
5. **Build** — `update_artifact(status="in_progress")` then `update_artifact(status="complete")`
6. **Review** — `create_artifact(artifact_type="review_todo", sequence=N, ...)`
7. **Resolve** — `update_artifact(status="resolved")` for each review finding
8. **Verify** — `update_ticket(status="to_verify")`
9. **Close** — `update_ticket(status="completed")`

### Autonomous Workflows

- `/auto-build`: Steps 2-8 + creates PR (for features with approved plans)
- `/lfg`: Also handles bugs — investigate -> hypothesize -> fix -> review -> PR

## Knowledge System

| Tier   | Location                         | Purpose             | Always in Context |
| ------ | -------------------------------- | ------------------- | ----------------- |
| Tier 1 | CLAUDE.md                        | Critical rules      | Yes               |
| Tier 2 | Memory service (autodev-memory)  | Detailed references | Auto-injected     |

Knowledge is stored in the memory service via `mcp__autodev-memory`. Context is auto-injected
by hooks and can be explicitly searched via `mcp__autodev-memory__search`.

### When to Search Memory Service

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

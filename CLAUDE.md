<!-- mem:project=autodev repo=agent-workflows -->

# Universal Development Conventions

Shared conventions for all projects using agent workflows in Claude Code and Codex.

## Agent Rules (Critical - Never Violate)

- Never create markdown files unless explicitly instructed
- Never deploy or run production operations without explicit instruction
- Always include the repo's active schema-deploy artifact when schema changes require it
  (Atlas reviewed plans, Prisma/Alembic migrations, or the repo-specific equivalent).
  Omitting the schema artifact means the column/object may not exist at runtime.
- **Never put MCP-tracked ticket artifacts in `.context/`** - see File Storage Rules below.
  Workflows that run without a ticket (e.g. `/lfg`) may use `.context/` for their own scratch.
- **Never modify `~/dev/*` (main repos) directly** - always work in the Conductor workspace
  that is in your context (e.g., `~/conductor/workspaces/<project>/<workspace-name>/`). The
  `~/dev/*` paths are the main checkouts and must not be touched unless explicitly requested.
- **Visible work requires browser screenshots.** If the work changes or verifies anything visible
  to a user — UI, UX, styling, rendered HTML/email/PDF/markdown/docs, charts, screenshots,
  browser-visible errors, or other visual output — capture screenshots from the actual rendered
  surface in a real browser session (Browser Use/in-app browser, gstack, Playwright, or the
  project-approved browser tool). Do **not** substitute DOM-only checks, generated/mock images,
  code snippets, or descriptions for screenshot evidence.
- **Screenshot paths must be absolute.** Save visible-work screenshots under the workspace
  (prefer `.context/screenshots/<timestamp>-<slug>.png` when no project-specific location exists)
  and include each screenshot as an absolute filesystem path in the final response and any
  durable ticket/PR/review/verification artifact. For multi-state UI work, capture the relevant
  before/after or state-specific screenshots. If a browser screenshot cannot be captured, state the
  exact blocker and the attempted browser command/tool.

## File Storage Rules (Critical)

When running inside Conductor, each workspace has a `.context/` directory. This directory is
**only for ephemeral inter-agent scratch data** (e.g., temporary intermediate results passed
between parallel subagents within a single session). It is gitignored and disposable.

**Ticket artifacts are stored in the MCP ticket system**, not on the local filesystem.
Use `mcp__autodev-memory__create_artifact` to store plans, build todos, review findings, etc.

**Never use `.context/` for:**

- Plans, build todos, review findings, or any artifact that belongs to a tracked ticket
- Anything that needs to survive across sessions

**Only use `.context/` for:**

- Temporary data passed between parallel subagents in a single session
- Scratch computations that are consumed immediately and then discarded
- Scratch state for ticketless autonomous workflows (e.g. `/lfg`) that have no ticket to write to
- Browser screenshot evidence for visible work, saved under `.context/screenshots/` and linked
  by absolute path from the final response and durable artifacts. Treat these files as disposable
  local evidence; the durable artifact stores the paths and context.

## Code Style (All Projects)

- No backwards-compatibility shims - delete unused code completely
- No `Any` types in TypeScript or Python
- No `type: ignore` unless explicitly asked
- Prefer Pydantic models over dataclass (Python projects)
- Always return structured types from functions, never complex dicts
- Imports only at top of file (exception: circular imports with comment)
- All timestamps need server_default with CURRENT_TIMESTAMP

## What I Mean by "Agent Workflows"

Agent workflows are shared skills plus tool-specific agent, hook, MCP, and legacy command
configuration:

1. **Skills** - Portable methodology documents (the HOW)
   - Review checklists, research methods, tool references, testing patterns
   - Universal (unprefixed) skills NEVER contain project-specific details (no table names,
     service IDs, routes) — at most a clearly labeled example (`*Example (ts-prefect):*`)
   - Exception: skills prefixed with a project identifier (e.g. `ts-`, `workflow-`, `amaru-`)
     MAY embed that project's specifics even though they live in agent-workflows — this shares
     one project's skills across its multiple repos. Repo-level skills (in the project repo)
     may always be project-specific.
   - Loaded by agents as reference material
   - File: `skills/<name>/SKILL.md` with optional `templates/` subdirectory

2. **Agents** - Tool-specific role definitions (the WHO)
   - Define a specialized agent's purpose, methodology, skills to load, tool access
   - Get project context from project instructions - not hardcoded
   - Claude (user-level shared): `agents/<name>.md` in agent-workflows
   - Claude (project-level): `.claude/agents/<name>.md` in the project repo
   - Codex: `.codex/agents/<name>.toml`

### User-Level vs Project-Level

| Level   | Location                                                 | Contains                                 |
| ------- | -------------------------------------------------------- | ---------------------------------------- |
| User    | `~/.agents/skills`, `~/.claude/skills`, tool agent dirs  | Universal methodology for ALL projects   |
| Project | `.agents/skills`, `.claude/agents`, `.codex/agents`      | Project-specific overrides and additions |

**Rule:** If a skill or hook is used in 2+ projects, it belongs at user level.
Project-specific context (table names, services, routes) goes in project instructions, not in
shared skill or agent definitions.

Project-level overrides user-level when both have the same filename.

### Agent Workflow Distribution

Shared skills, hooks, tool-specific agents, and this instruction file live in
`simonszalai/agent-workflows`.

| Environment     | Mechanism                                      | Direction |
| --------------- | ---------------------------------------------- | --------- |
| Local dev       | `~/.claude`, `~/.agents`, `~/.codex` symlinks  | Two-way   |
| NanoClaw        | Volume mount from agent-workflows              | Two-way   |
| Cloud sessions  | SessionStart copies agent-workflows            | One-way   |

**Resolution:** shared skills live under `.agents/skills` and are symlinked into Claude where
needed. Agent definitions remain tool-specific because Claude and Codex use different formats.

### Where to Make Changes

| Change type                      | Target                                    | Why                  |
| -------------------------------- | ----------------------------------------- | -------------------- |
| Project-specific skill          | `.agents/skills` in project repo          | Shared by tools      |
| Project-specific agent          | `.claude/agents` or `.codex/agents`       | Tool-specific format |
| Shared skill or hook            | `~/.agents`/`~/.claude`/`~/.codex` symlink | Available everywhere |
| User-level conventions          | agent-workflows instruction files         | Shared rules         |
| Knowledge gotcha/reference      | Autodev-memory MCP                        | Persisted in MCP     |

### Committing User-Level Changes (Critical)

When the `compound` skill, `heal-workflows` skill, or any correction triggers an edit to a
**user-level** file (shared skill, hook, agent, or this instruction file), the edit goes through the symlink
and modifies the `agent-workflows` repo directly. The agent MUST then:

1. `cd ~/dev/agent-workflows` (or wherever the repo is checked out)
2. `git add` the changed files
3. `git commit -m "compound: <description of what changed>"`
4. `git push origin main`

This ensures the improvement propagates to all environments. Without the push, the change
only exists locally and won't reach cloud sessions or other machines.

**Project-level changes** (files in the project's config directories)
do NOT need this — they are committed as part of normal project workflow.

## Proactive Command & Agent Triggers

When the user mentions these activities, proactively use the corresponding skill or agent:

### Investigation & Research

| User says                                                 | Action             |
| --------------------------------------------------------- | ------------------ |
| "investigate", "what's wrong with", "why is this failing" | Use the `investigate` skill |
| "research", "how does X work", "find all instances of"    | Use the `research` skill    |
| "look into", "debug this", "root cause"                   | Use the `investigate` skill |

### Planning & Building

| User says                                      | Action                    |
| ---------------------------------------------- | ------------------------- |
| "plan", "design", "architect", "how should we" | Run `/auto-plan`                   |
| "build", "implement", "start working on"       | Use the `build` skill              |
| "create build todos", "break this down"        | Use the `create-build-todos` skill |

### Review & Quality

| User says                                   | Action                |
| ------------------------------------------- | --------------------- |
| "review", "check my code", "look over this" | Use the `review` skill         |
| "resolve review", "fix review findings"     | Use the `resolve-review` skill |

### Testing

| User says                                                 | Action              |
| --------------------------------------------------------- | ------------------- |
| "write tests", "add tests", "test coverage"               | Use the `write-tests` skill |
| "fix tests", "tests failing", "CI failing", "test broken" | Investigate root cause, then fix (test or code, whichever is wrong) |
| "verify in browser", "check the UI", "smoke test"         | Use browser testing workflow |

### Verification & Deployment

| User says                                       | Action                         |
| ----------------------------------------------- | ------------------------------ |
| "verify staging", "check staging"               | Run `/ticket-verify staging`   |
| "verify production", "verify deployed"          | Run `/ticket-verify production` |
| "create deployment guide"                       | Run `/create-deployment-guide` |
| "create PR", "make a PR", "open PR"             | Run `/create-pr`               |

### Automation

| User says                               | Action            |
| --------------------------------------- | ----------------- |
| "auto-build", "build this ticket end to end" | Run `/ticket-flow` |
| "auto-flow", "ticket flow"              | Run `/ticket-flow` |
| "/goal", "multi-ticket", "batch these related tickets", "hands-off" with multiple tickets | Run `/goal-flow` |
| "milestone flow", "run this milestone"  | Run `/milestone-flow` |
| "epic flow", "run this epic"            | Run `/epic-flow` |
| "auto-fix", "fix this bug autonomously" | Run `/lfg`         |

### Learning & Correction Detection

| User says                                                          | Action                        |
| ------------------------------------------------------------------ | ----------------------------- |
| "save this", "remember this", "store this"                         | Run `/compound`               |
| "compound", "document this", "save this learning"                  | Run `/compound`               |
| "what did we learn", "learn from review", "learn from this"        | Run `/compound`               |
| "wtf", "why didn't you know this", "you should have known"         | Run `/autodev-wtf`            |
| "retrospect", "what went wrong", "post-mortem"                     | Run `/retrospect`             |
| "which workflow stage missed this bug"                             | Run `/autodev-wtf-workflows`  |
| "no, do X instead", "that's wrong", "you should have"              | Proactively offer `/compound` |
| "don't do that", "actually the correct way is", "you keep doing X" | Proactively offer `/compound` |

**Correction detection:** When the user explicitly corrects Claude's approach or output,
proactively ask: "Should I `/compound` this so it sticks?" `/compound` decides whether the
correction becomes a memory entry, a CLAUDE.md change, or a skill/workflow change.

### Maintenance

| User says                                                       | Action                 |
| --------------------------------------------------------------- | ---------------------- |
| "heal workflows", "check agent config"                          | Run `/heal-workflows`  |
| "consolidate memories", "audit memories", "clean up memories", "dream", "deep dream", "whole-system dream", "improve skills from logs/tickets" | Run `/deep-dream` |

### Ticket Management

| User says                                                | Action                |
| -------------------------------------------------------- | --------------------- |
| "exclude from scope", "defer this", "out of scope"       | Spawn ticket-curator  |
| "new ticket", "track this as", "create backlog item"     | Spawn ticket-curator  |
| "add to F003", "update ticket source", "add context to"  | Spawn ticket-curator  |

### Agent Workflow Modification

No dedicated authoring skill exists. When the user wants to add/modify a skill, agent, or
workflow, work directly on the files under `skills/`, `agents/`, or `workflows/` in
agent-workflows. Follow the conventions in this file and the patterns in neighboring skills.

## Parallelism

When spawning multiple independent agents (e.g., `/review` spawns multiple reviewer
instances), ALWAYS issue the `Agent` tool calls in parallel — multiple tool-use blocks in a
single assistant message. Never spawn sequentially when agents don't depend on each other's
output.

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
- Epics: `E0023` (auto-generated by `create_epic`; **project-scoped**, see the Epics section)

Ticket IDs are **repo-scoped** — each repo maintains its own sequence per type prefix.
`create_ticket` auto-generates the next available ID. Use `seq_num` only for migrations.

### MCP Ticket Tools

| Tool | Purpose |
|---|---|
| `create_ticket` | Create a new ticket (description becomes source artifact) |
| `get_ticket` | Get bounded ticket context; use `detail`, `artifact_types`, and `include_events` |
| `list_tickets` | List tickets filtered by status/type/repo |
| `update_ticket` | Update status, title, tags, epic assignment, etc. |
| `search_tickets` | Semantic + BM25 search across all ticket artifacts |
| `next_ticket` | Get the next planned/backlog ticket |
| `get_similar_tickets` | Find similar completed tickets |
| `create_artifact` | Add plan, build_todo, review_todo, etc. to a ticket |
| `update_artifact` | Update artifact content or status |

Ticket reads must request the smallest sufficient context:

- `detail="light", include_events=false` returns ticket metadata plus artifact manifests without
  artifact bodies. Use it for routing, existence checks, status checks, and prerequisite gates.
- `detail="full", artifact_types=[...], include_events=false` returns content only for the named
  artifact types. This is the normal workflow read.
- Full unfiltered artifacts and event history are reserved for audits and retrospectives that
  genuinely need them.
- Cache a ticket response for the workflow run and reuse its artifact IDs and `context_version`.
  Do not call `get_ticket` again unless a relevant artifact changed outside the current workflow.
- Use `detail="compact"` for `search_tickets` and `get_similar_tickets`, then selectively load
  only the artifacts needed from the few tickets that survive relevance screening.
- The orchestrator owns shared ticket retrieval. Delegated agents receive a bounded packet or
  `.context/<workflow>/<run-id>/` file reference; they do not independently reload the same ticket.

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
| `verification_evidence` | Post-deploy evidence collected by `/ticket-verify` | content |
| `html` | Rendered plan/epic explainer page (`/plan-explainer`) | content |

### Status Vocabulary (two enums)

Canonical lifecycles live in `skills/references/ticket-lifecycle.md` and
`skills/references/epic-lifecycle.md`. Short version:

```text
# standalone ticket, direct main
backlog → up_next → in_progress → planned → in_progress → to_verify_prod → completed

# standalone ticket, staging first
backlog → up_next → in_progress → planned → in_progress → to_verify_staging
                                                → staging_verified → ticket-promote
                                                → to_verify_prod → completed

# epic step ticket
backlog → up_next → in_progress → planned → in_progress → merged
                                            → staging_verified → to_verify_prod → completed
```

There is no `approved` ticket status; approval is the decision to leave `planned` and begin
work again by setting `in_progress`. Ticket statuses `planning`, `building`, and `active`
are retired; use the single actual active-work status `in_progress`.
`/ticket-flow` may deploy standalone tickets only through `/auto-deploy` after it chooses the
staging-first or direct-production route. Post-deploy behavior verification remains owned by
`/ticket-verify`; promotion (landing on main **plus** running the production deploy steps) is
owned by `/ticket-promote`, which then invokes `/ticket-verify production`; epic milestone
staging gates are owned by `/milestone-flow`, which must deploy and run the explicit
epic/milestone verifier before it can return success. `to_verify_prod` means "production landing
and deploy steps complete; behavior unverified".

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

1. **Create** — `create_ticket(status="backlog")`
2. **Start** — `update_ticket(status="in_progress")`
3. **Plan** — `create_artifact(artifact_type="plan", content=...)`
4. **Build todos** — `create_artifact(artifact_type="build_todo", sequence=N, ...)`
5. **Build** — `update_artifact(status="in_progress")` then `update_artifact(status="complete")`
6. **Review** — `create_artifact(artifact_type="review_todo", sequence=N, ...)`
7. **Resolve** — `update_artifact(status="resolved")` for each review finding
8. **Deploy/promote** — `/auto-deploy` or `/ticket-promote` sets `to_verify_staging`/`to_verify_prod`
9. **Verify** — `/ticket-verify` collects evidence and sets `completed` (or `verify_*_failed`)

### Autonomous Workflows

- `/ticket-flow`: Autonomous single-ticket execution — context -> route staging vs production -> plan/critique -> build -> review -> local verify -> deploy via `/auto-deploy`; no behavior verification
- `/goal-flow`: Autonomous related-ticket execution — shared context/plan, clustered write scopes,
  integrated review/test/deploy, and coalesced verification with per-ticket lifecycle truth
- `/lfg`: Autonomous end-to-end on the current branch without tickets; keep its existing `.context` behavior
- `/ticket-verify`: Timer-friendly staging/production verification; a low-risk standalone staging PASS auto-calls `/ticket-promote` (auto-promotion gate: FINALIZED contract fully graded, no schema/deploy-config/auth in the diff — riskier scopes rest at `staging_verified` for explicit promotion); explicit epic/milestone mode reports parent gates
- `/ticket-promote`: Promote staging-verified tickets — lands on main AND runs the production
  deploy steps, then invokes `/ticket-verify production`. Modes: single ticket (default,
  auto-invoked by a gate-passing staging PASS), `--all` batch, `--epic <ID>`, `--all-staging`
- `/epic-plan`, `/epic-split`, `/milestone-flow`, `/epic-flow`: Epic/milestone orchestration over ticket-flow; `/milestone-flow` deploys/verifies each staging milestone gate, and `/epic-flow` sequences milestones plus final prod after all gates pass
- `/auto-flow` and `/auto-verify`: Legacy aliases for `/ticket-flow` and `/ticket-verify`

## Knowledge System

| Tier   | Location                              | Purpose                                       | Always in Context |
| ------ | ------------------------------------- | --------------------------------------------- | ----------------- |
| Tier 1 | CLAUDE.md                             | Project conventions (stack, branches, rules)  | Yes — auto-loaded |
| Tier 2 | Starred memory entry (autodev-memory) | Critical gotchas / rules that must always apply | Yes — auto-injected by memory hook |
| Tier 3 | Memory service (unstarred)            | Detailed references, gotchas, solutions       | No — surfaced via `mcp__autodev-memory__search` |

Knowledge lives in the memory service via `mcp__autodev-memory`. Tier 2 entries are
auto-injected with the same authority as CLAUDE.md; Tier 3 entries are pulled in on
demand. The `/compound` skill is the canonical authority on which tier a new piece of
knowledge belongs in.

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

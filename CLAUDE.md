<!-- mem:project=autodev repo=agent-workflows -->
# Universal Development Conventions

Shared conventions for all projects using agent workflows in Claude Code, Codex, and Cursor.

## Agent Rules (Critical - Never Violate)

- Never create markdown files unless explicitly instructed
- Never deploy or run production operations without explicit instruction
- Never print resolved secret values into agent-visible output. Do not run credential/profile/config
  dumps such as `prefect profile inspect`, `env`, or `printenv`. Direct local-shell production DB
  writes are prohibited; use an audited MCP/server-side operation. Authenticated production CLI
  mutations with no remote route must run through `bin/redacted-exec -- ...`, never a raw-output log.
  If a value is emitted anyway, treat the credential as exposed: stop echoing/inspecting it, identify
  only the credential name and affected service, and require rotation of the source and consumers.
- Before any `op://*-sensitive/...` access, load the `sensitive-vault-access` skill and pass a
  concise, operation-specific reason via `SENSITIVE_ACCESS_REASON` or the wrapper's `--reason`.
  The reason must explain why the credential is needed and include the ticket/milestone when
  known. Sensitive access without a reason must fail before Touch ID; never bypass the notifier
  with the real `op` path or `OP_BIN`.
- Always include the repo's active schema-deploy artifact when schema changes require it
  (Atlas reviewed plans, Prisma/Alembic migrations, or the repo-specific equivalent).
  Omitting the schema artifact means the column/object may not exist at runtime.
- **Never put MCP-tracked ticket artifacts in `.context/`** — ticket artifacts live in the MCP
  ticket system (`mcp__autodev-memory__create_artifact`). `.context/` is only for ephemeral
  intra-session scratch and browser screenshot evidence (`.context/screenshots/`).
- **Never modify `~/dev/*` (main repos) directly** - always work in the Conductor workspace
  that is in your context (e.g., `~/conductor/workspaces/<project>/<workspace-name>/`).
- **After an agent confirms that it merged the PR whose head is the current Conductor workspace
  branch, clean up that throwaway branch before continuing.** Delete its remote head, then run
  `align-merged-pr-workspace <pr-number-or-url>`. Never substitute a normal
  `git rebase origin/<base>`: a multi-commit squash merge can conflict or replay old work.
  Does not apply to repository-defined long-lived branches; leave those remote heads intact.
- **Visible work requires browser screenshots.** If the work changes or verifies anything visible
  to a user — UI, UX, styling, rendered HTML/email/PDF/markdown/docs, charts, browser-visible
  errors — capture screenshots from the actual rendered surface in a real browser session.
  Do **not** substitute DOM-only checks, generated/mock images, code snippets, or descriptions.
  Save screenshots under `.context/screenshots/<timestamp>-<slug>.png` and reference each by
  absolute path in the final response and any durable ticket/PR artifact. If a browser screenshot
  cannot be captured, state the exact blocker and the attempted browser command/tool.

## Scope and Response Style

Load and follow the `autism` skill for all communication. Task-specific structured or verbatim
output contracts still win.

**Deliver what was asked, at the scope intended.** Make routine judgment calls yourself, and check
in only when different readings of the request would lead to materially different work. If the
request looks mistaken or a better approach exists, say so in a sentence and continue with the task
as asked. Finish the whole task; stop short of adjacent improvements nobody asked for — name them
in the report instead.

**Answer in the fewest words that fully answer.** Lead with the outcome, then supporting detail.

## Code Style (All Projects)

- No backwards-compatibility shims - delete unused code completely
- No `Any` types in TypeScript or Python
- No `type: ignore` unless explicitly asked
- Prefer Pydantic models over dataclass (Python projects)
- Always return structured types from functions, never complex dicts
- Imports only at top of file (exception: circular imports with comment)
- All timestamps need server_default with CURRENT_TIMESTAMP

## Agent Workflows

Shared skills, hooks, binaries, and this instruction file live in
`simonszalai/agent-workflows`. Skills are portable methodology/reference documents
(`skills/<name>/SKILL.md`); universal (unprefixed) skills never contain project-specific details;
project-prefixed skills (e.g. `ts-`) may. Project-level files override user-level on filename.

| Environment     | Mechanism                                      | Direction |
| --------------- | ---------------------------------------------- | --------- |
| Local dev       | `~/.claude`, `~/.agents`, `~/.codex`, `~/.cursor` symlinks | Two-way |
| NanoClaw        | Volume mount from agent-workflows              | Two-way   |
| Cloud sessions  | SessionStart copies agent-workflows            | One-way   |

**Local dev links point directly at `~/dev/agent-workflows`.** Never run
`bin/install-agent-workflows --version` locally: explicit-version mode pins the links to a frozen
snapshot and merges silently stop reaching live sessions. Running it without `--version` repairs
the live folder-link layout. A merge to remote `main` does not update the live checkout when its
local branch is dirty, ahead, behind, or divergent.

**Committing user-level changes:** edit only the linked/current `agent-workflows` Conductor
workspace, commit, push, merge the PR to `main`, then run
`bin/verify-agent-workflows-live <merge-sha>` after fetching `origin/main`. If the live symlink
checkout is dirty/diverged or missing the merge, report **local propagation pending**. Never
overwrite, reset, stash, or auto-merge unrelated live-checkout work. Only the verifier proves
local propagation.

## Ticket System (MCP-Based)

All tickets and their artifacts are managed via the `mcp__autodev-memory` MCP server.

**Context resolution** (required for all ticket MCP calls):
project from `<!-- mem:project=X -->` in the repo's CLAUDE.md; repo from
`basename -s .git $(git config --get remote.origin.url)`.

**Types/IDs:** Features `F0023`, bugs `B0023`, refactors `R0023` (repo-scoped, auto-generated by
`create_ticket`); epics `E0023` (project-scoped, `create_epic`). Link cross-repo work via the
`related` field (`related=["ts-scraper/F0004"]`).

**Tools:** `create_ticket`, `get_ticket`, `list_tickets`, `update_ticket`, `search_tickets`,
`next_ticket`, `get_similar_tickets`, `create_artifact`, `update_artifact`.

**Bounded reads:** request the smallest sufficient context — `detail="light",
include_events=false` for routing/status checks; `detail="full", artifact_types=[...]` for named
artifact bodies. Cache a ticket response for the run and reuse its artifact IDs.

**Lifecycle:** canonical state machines live in `skills/references/ticket-lifecycle.md` and
`skills/references/epic-lifecycle.md` — statuses, staging-first vs direct-production routes,
promotion and verification gates. There is no `approved` status; leaving `planned` means setting
`in_progress`. `to_verify_prod` means "production landing and deploy steps complete; behavior
unverified". Staging mutation autonomy boundaries are in
`skills/references/staging-autonomy.md`.

## Knowledge System

| Tier   | Location                              | Purpose                                       | Always in Context |
| ------ | ------------------------------------- | --------------------------------------------- | ----------------- |
| Tier 1 | CLAUDE.md                             | Project conventions                           | Yes — auto-loaded |
| Tier 2 | Starred memory entry (autodev-memory) | Critical gotchas that must always apply       | Yes — auto-injected by memory hook |
| Tier 3 | Memory service (unstarred)            | Detailed references, gotchas, solutions       | No — via `mcp__autodev-memory__search` |

Search memory when researching patterns, past solutions, or known gotchas. The `compound` skill
owns saving new knowledge and deciding its tier.

## Delegation

Delegate when the work needs its own context window — a wide multi-file investigation or a
sizeable independent track. Work you could finish in a handful of tool calls is cheaper done
yourself. Dispatch agents in the foreground; background only genuinely fire-and-forget work,
since a backgrounded agent's result is not collected this turn.

## Markdown Formatting

- Line length: 100 characters max (tables and URLs may exceed)

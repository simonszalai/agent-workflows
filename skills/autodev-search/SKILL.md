---
name: autodev-search
description: >-
  How to use the autodev-memory system for knowledge retrieval. Describes what context is
  auto-injected, when to search, and which MCP tools to use. Loaded by reviewer, planner,
  build-planner, investigator, and researcher agents.
user_invocable: false
---

# Autodev Memory Search

Reference for agents that need to retrieve knowledge from the memory system during their work.

## What You Get Automatically

At **session start**, supported parent runners receive one server-rendered bounded packet as
`additionalContext`:

1. **Always/repo-start rules selected by the producer** — treat them with the same authority as
   CLAUDE.md.
2. **Representative handles and scope/fetch instructions** — use search or scoped expansion to
   retrieve detail. The complete corpus is deliberately not injected.

Managed Claude/Codex children receive a separate <=3K task packet containing a critical base and
skill-scoped summaries. Unmanaged or unsupported children may receive no packet; if no
`<autodev-memory-task-context>` is visible, search explicitly rather than assuming delivery.

## When to Search

Scan the representative handles/task summaries. If one looks relevant, use search or the
producer's scoped expansion tool to retrieve its full content.

**Search is warranted when:**

- A representative handle or task summary matches the area you're working on
- You're about to make a decision that past gotchas/solutions might inform
- You're reviewing code and want to check for known recurring issues
- You're investigating a failure and the menu has entries about that subsystem

**Search is NOT warranted when:**

- The injected always-rule cards already cover the topic
- The task is purely mechanical (formatting, renaming)
- No representative handle, task summary, or risk boundary is relevant

The agent decides. The injected packet is deliberately incomplete, so absence from it is not
evidence that the corpus has no relevant knowledge.


## Subagent Bootstrap

Managed children should receive `<autodev-memory-task-context>`. Read it first. If that marker is
absent, delivery is unconfirmed and you must bootstrap with an explicit compact search before
risk-bearing work:

1. **Search for relevant gotchas** — extract 2-4 keywords from your task description and
   search for known issues:

   ```
   mcp__autodev-memory__search(
     queries=[{"keywords": ["<tech>", "<area>"], "text": "<what you're investigating/building>"}],
     project="<project>",
     repo="<current repo>",
     detail="compact",
     limit=5
   )
   ```

2. **Expand only selected results** — choose 2-5 result IDs and pass the exact generation from
   the compact response:

   ```
   mcp__autodev-memory__expand_entries(
     entry_ids=["<id-1>", "<id-2>"],
     project="<project>", repo="<current repo>",
     corpus_generation="<generation from search>", scope_mode="current_repo"
   )
   ```

   Expansion revalidates generation, lifecycle, and repo scope. Do not treat a compact hit as
   proof that its full content was read.

This takes ~5 seconds and prevents re-introducing bugs that were already documented and solved.

## MCP Tools for Search

### `mcp__autodev-memory__search` — Primary search tool

Hybrid semantic + full-text search across all entries.

```
queries: [
  {
    "keywords": ["prefect", "deployment"],       # tag/title matching
    "text": "PREFECT_API_URL not set during flow" # semantic chunk search
  }
]
project: "ts"    # searches project + global entries
repo: "ts-prefect"
detail: "compact"
limit: 5
```

**Query design tips:**

- `keywords` — use 2-4 topical terms (technology, area, pattern name)
- `text` — use a natural language description of what you're looking for
- Multiple queries in one call for different aspects of the same task
- Project searches automatically include global results
- Always pass `repo` for repo-scoped work; omit it only for intentional project-wide search
- Keep `detail="compact"`, then expand 2-5 selected IDs with the returned generation

### `mcp__autodev-memory__get_review_patterns` — For reviewers

Search past review findings for recurring issues.

```
project: "ts"
query: "missing migration"
limit: 10
```

Use this during code review to check if similar code has had issues before.

### `mcp__autodev-memory__get_similar_tickets` — For planners

Find completed tickets similar to the current work item.

```
project: "ts"
ticket_id: "F0023"
repo: "ts-prefect"
```

Use during planning to discover how similar features were built.

### `mcp__autodev-memory__list_entries` — Browse by type

List entries filtered by type and/or repo.

```
project: "ts"
entry_type: "gotcha"    # gotcha, pattern, reference, solution, architecture, etc.
repo: "ts-prefect"      # optional — also includes project-wide entries
```

Use when you want all gotchas for a repo, or all entries of a specific type.

### `mcp__autodev-memory__get_all_tags` — Tag vocabulary

Returns all tags in use for a project. Useful to understand what knowledge areas are covered.

```
project: "ts"
```

## Integration Points

This skill is loaded by agents that benefit from knowledge retrieval:

| Agent | When to search |
|---|---|
| planner | Similar past work, architectural patterns |
| build-planner | Gotchas for each build step's technology area |
| reviewer | Recurring review findings, coding standards, architecture, data integrity |
| investigator | Known failure patterns, past solutions |
| researcher | Accumulated knowledge about a subsystem |

## What NOT to Do

- Do not use `curl` to hit the memory API — always use MCP tools
- Do not search for things already covered by injected always-rule cards
- Do not search mechanically on every task — use representative handles and task risk to decide
- Do not persist findings during search — that's `/compound`'s job

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

## What You Get Automatically (Parent Sessions Only)

At **session start**, hooks inject two things as `additionalContext`:

1. **Starred entries** (full content) — critical rules, architecture, gotchas that apply to
   every task. Treat these with the same authority as CLAUDE.md.
2. **Knowledge menu** — a compact list of ALL entries with their `[type]`, title, and tags.
   This is your index. Use it to decide whether a search is warranted.

**Subagents do NOT receive hook injections.** `PreToolUse` hook output goes to the parent
model, not the spawned subagent. If you are a subagent (your task came from an Agent tool
call, not directly from the user), you must **actively search** for relevant knowledge at
the start of your task — see "Subagent Bootstrap" below.

## When to Search

Scan the knowledge menu. If any entry's title or tags look relevant to your current task,
use `mcp__autodev-memory__search` to retrieve its full content.

**Search is warranted when:**

- An entry title in the menu matches the area you're working on
- You're about to make a decision that past gotchas/solutions might inform
- You're reviewing code and want to check for known recurring issues
- You're investigating a failure and the menu has entries about that subsystem

**Search is NOT warranted when:**

- The starred entries already cover the topic
- The task is purely mechanical (formatting, renaming)
- No menu entry titles/tags are relevant

The agent decides. No need to search on every task — just when the menu suggests useful
knowledge exists.


## Subagent Bootstrap (CRITICAL for subagents)

Since subagents receive NO hook injections, you must bootstrap your own memory context
at the very start of your task. Do this BEFORE any other work:

1. **Search for relevant gotchas** — extract 2-4 keywords from your task description and
   search for known issues:

   ```
   mcp__autodev-memory__search(
     queries=[{"keywords": ["<tech>", "<area>"], "text": "<what you're investigating/building>"}],
     project="<project>",
     limit=5
   )
   ```

2. **Read any results carefully** — gotchas and patterns from the memory system represent
   hard-won production lessons. They override general knowledge.

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
limit: 5
```

**Query design tips:**

- `keywords` — use 2-4 topical terms (technology, area, pattern name)
- `text` — use a natural language description of what you're looking for
- Multiple queries in one call for different aspects of the same task
- Project searches automatically include global results

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
- Do not search for things already in your starred entries
- Do not search on every task — use the knowledge menu to decide
- Do not persist findings during search — that's `/compound`'s job

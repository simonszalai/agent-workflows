---
name: autodev-tags
description: Determine tags for new memory entries. Fetches existing tags and applies consistent tagging conventions.
user_invocable: false
---

# Autodev Tags

Determine the right tags for a memory entry. Tags power two of the four search paths in the
memory system (tag vector search and entry BM25), so good tags directly improve discoverability.

## When to Load

Loaded by autodev-save, autodev-add-memory, and autodev-ingest-knowledge when creating or
updating entries. Use this skill whenever you need to decide what tags to assign.

## How Tags Work in Search

Tags are used in two ways:

1. **Tag vector search**: Tags are joined with commas, embedded as a 1536-dim vector, and
   compared via cosine similarity against search keywords. This means semantically similar tags
   match even if they don't share exact words.
2. **Entry BM25**: Tags get weight 'A' (highest) in the full-text search index. Exact keyword
   matches in tags rank higher than matches in title or summary.

Both properties mean: **use the vocabulary people will naturally search for**.

## Procedure

### Step 1: Get Existing Tags

Fetch all tags currently in use via the MCP tool. Always fetch **both** the target project and
global to get the complete tag vocabulary — this prevents tag fragmentation between scopes.

```
mcp__autodev-memory__get_all_tags(project: <project>)
mcp__autodev-memory__get_all_tags(project: "global")
```

Run both calls in parallel. Merge the results into a single deduplicated tag list. If the target
project IS "global", only one call is needed.

The tool returns all unique tags and their usage counts:

```json
[
  {"tag": "alembic", "count": 3},
  {"tag": "css", "count": 5},
  {"tag": "react-router", "count": 8}
]
```

### Step 2: Determine Tags for the Entry

Apply these rules in order:

**Rule 1 — Reuse existing tags when they fit.** If an existing tag covers the topic, use it
instead of inventing a synonym. This keeps the tag vocabulary tight and improves search
consistency. Example: if `react-router` exists, don't create `react-router-v7` or `routing`.

**Rule 2 — Use 2-5 tags per entry.** Too few tags (0-1) make entries hard to find via tag
search. Too many tags (6+) dilute the tag embedding and weaken BM25 relevance.

**Rule 3 — Tag the technology, not the concept.** Prefer concrete framework/library/tool names
over abstract concepts. People search for "alembic" not "database-migration-tool". People
search for "react-router" not "client-side-routing".

**Rule 4 — Use lowercase kebab-case.** All tags should be lowercase with hyphens for
multi-word tags. Examples: `react-router`, `sql-injection`, `error-handling`.

**Rule 5 — Include the primary topic and the specific subtopic.**
- Primary: the framework, language, or domain (e.g., `sqlalchemy`, `typescript`, `css`)
- Subtopic: the specific area within it (e.g., `async`, `generics`, `flexbox`)

**Rule 6 — Don't tag the entry type.** The `entry_type` field already captures whether this is
a gotcha, pattern, solution, etc. Don't add tags like `gotcha` or `bug-fix`.

**Rule 7 — Don't tag the project or repo.** The `project` and `repos` fields handle scoping.
Don't add tags like `ts-scraper` or `autodev-memory`.

### Step 3: Return Tags

Return the tags as a `list[str]`, sorted alphabetically:

```python
tags = ["alembic", "migration", "sqlalchemy"]
```

## Examples

| Entry Title | Content About | Good Tags | Bad Tags |
|---|---|---|---|
| Alembic batch mode for SQLite | Using batch mode for ALTER TABLE | `["alembic", "migration", "sqlite"]` | `["database", "schema-change", "gotcha"]` |
| React Router loader vs action | When to use loader vs action | `["react-router", "server-components"]` | `["routing", "react", "web-framework"]` |
| Python asyncio gather error handling | How gather propagates exceptions | `["asyncio", "error-handling", "python"]` | `["concurrency", "exceptions", "bug"]` |
| Mantine AppShell responsive layout | Configuring breakpoints in AppShell | `["mantine", "responsive-design"]` | `["ui", "css", "react-components"]` |
| Prefect flow retry behavior | Task retries vs flow retries | `["prefect", "retry", "task-orchestration"]` | `["workflow", "error-recovery"]` |

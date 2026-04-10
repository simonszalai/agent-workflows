# Store Procedure — Search Before Store

Canonical procedure for storing knowledge in autodev-memory. Used by compound, autodev-extract,
autodev-ingest, and any skill that needs to persist entries.

## Step 1: Determine Scope

| Knowledge Type | Scope | Why |
|---|---|---|
| Framework/library behavior | **global** | Any project might use it |
| Language patterns | **global** | Universal |
| CLI tools, dev environment | **global** | Cross-project |
| Agent workflow conventions | **global** | Shared infrastructure |
| CI/CD, deployment patterns | **global** (unless truly unique) | Usually transferable |
| Testing patterns | **global** (unless project-specific) | Usually transferable |
| Business logic, domain rules | **project-scoped** | Specific to one product |
| Project architecture | **project-scoped** | Specific to one codebase |
| Service config, infra | **project-scoped**, optionally repo-tagged | Deployment-specific |
| Single-repo details | **project-scoped** + `repos: ["repo"]` | Narrow scope |

**Bias toward global.** When even 30% unsure, go global. It's easy to scope down later but
hard to discover scattered project-level entries.

## Step 2: Search for Related Entries

```
mcp__autodev-memory__search(
  queries: [{
    "keywords": [<topical tags/keywords>],
    "text": "<title> <first ~200 chars of content>"
  }],
  project: <project>,
  limit: 5
)
```

Also fetch the entry index to catch near-matches the vector search might miss:

```
mcp__autodev-memory__list_entries(project: <project>)
```

If storing project-scoped, also check global entries.

## Step 3: Evaluate Matches

For candidates with similarity > 0.5, fetch full content:

```
mcp__autodev-memory__get_entry(entry_id: <id>, project: <project>)
```

Compare with new knowledge.

## Step 4: Decide Action

| Situation | Action |
|---|---|
| No matches or different topics | **new** — create fresh entry |
| Match covers same topic, new adds info | **append** — merge into existing |
| Match exists but new is better/corrects old | **supersede** — replace |
| Merging would exceed ~1,500 tokens | **rebalance** — split and reorganize |
| Existing fully covers this | **skip** — already captured |
| Existing is wrong, no replacement | **deprecate** — mark outdated |

Use judgment, not just scores. Two entries can have high similarity but cover different
aspects (both should exist).

## Step 5: Execute

**New:**

```
mcp__autodev-memory__add_entry(
  title: <title>,
  content: <content>,
  entry_type: <type>,
  project: <project>,
  summary: <summary>,
  tags: <tags>,
  repos: <repos>,
  source: "captured",
  caller_context: {
    "skill": "<calling skill>",
    "reason": "<why worth persisting>",
    "action_rationale": "No existing entry covers this topic"
  }
)
```

**Append:**

Write a coherent combined version (don't just concatenate). Stay under ~1,500 tokens.

```
mcp__autodev-memory__update_entry(
  entry_id: <existing_id>,
  project: <project>,
  content: "<merged content>",
  summary: "<updated summary>",
  caller_context: {
    "skill": "<calling skill>",
    "reason": "<why worth persisting>",
    "action_rationale": "Appending — new info: <what's new>"
  }
)
```

**Supersede:**

```
mcp__autodev-memory__supersede_entry(
  old_entry_id: <old_id>,
  title: <title>,
  content: "<improved content>",
  entry_type: <type>,
  project: <project>,
  summary: <summary>,
  tags: <tags>,
  repos: <repos>,
  source: "captured",
  caller_context: {
    "skill": "<calling skill>",
    "reason": "<why worth persisting>",
    "action_rationale": "Superseding <old_id> — <why outdated>"
  }
)
```

**Skip:** No MCP calls. Log the decision.

**Deprecate:**

```
mcp__autodev-memory__update_entry(
  entry_id: <id>,
  project: <project>,
  content: "DEPRECATED: <reason>",
  summary: "DEPRECATED — <brief reason>",
  caller_context: { "skill": "<calling skill>", "action_rationale": "Deprecating — <why wrong>" }
)
```

## Batch Processing

When processing multiple entries, go **sequentially**. Each decision is informed by what
happened to previous entries (e.g., if entry 1 was appended to X, entry 3 about the same
topic should know that).

---
name: autodev-add-memory
description: Smart memory ingestion — search before storing, decide whether to create, append, supersede, or skip
user_invocable: false
---

# Autodev Add Memory

Shared ingestion procedure for storing knowledge in the autodev-memory system. Instead of
blindly creating new entries, this skill searches for existing related entries first and
decides the best action: create new, append to existing, supersede, or skip.

**This skill is loaded by other skills** (autodev-extract, autodev-ingest-knowledge,
autodev-ingest-work-items, compound). It is not user-invocable on its own.

## When to Load

Any time you need to store a knowledge entry in autodev-memory. Instead of calling
`add_entry` directly, follow this procedure.

## Input

Each memory to store needs:

| Field | Required | Description |
|---|---|---|
| `title` | Yes | Descriptive title |
| `content` | Yes | Full knowledge content |
| `entry_type` | Yes | gotcha, diagnosis, solution, reference, architecture, pattern |
| `project` | Yes | Project name (e.g., "ts", "global") |
| `repos` | No | List of repo names (null = project-wide) |
| `source` | Yes | "manual", "captured", or "ingested" |
| `source_metadata` | Yes | Rich provenance metadata (file path, session ID, etc.) |
| `summary` | No | 1-sentence search-friendly summary |
| `tags` | No | Use the autodev-tags skill procedure to determine |
| `caller_context` | Yes | Debugging context (skill name, reason, trigger) |

## Procedure

Process entries **one at a time, sequentially**. Each decision is informed by what happened
to previous entries in the same batch (e.g., if entry 1 was appended to X, entry 3 about
the same topic should know that).

### Step 0: Determine scope (global vs project)

Before searching, determine if this knowledge is project-specific or framework/library-level:

- **Global** (`project: "global"`, `repos: null`): Framework gotchas (React Router, Prisma,
  Mantine, SQLAlchemy, Alembic), library behavior, language patterns, cross-project conventions.
  Even if only one project currently uses the framework, store globally — new projects will
  likely use it too.
- **Project-scoped** (`project: "<name>"`, `repos: ["<repo>"]`): Business logic, project
  architecture, deployment specifics, service configurations, data model decisions.

When in doubt, prefer global — it's easier to scope down later than to discover scattered
project-level entries that should have been shared.

If an existing project-level entry should be promoted to global (e.g., a second project now
uses the same framework), supersede the project entry and create a new global entry.

### Step 1: Search for related entries

```
mcp__autodev-memory__search(
  queries: [
    {
      "keywords": [<topical tags/keywords from the entry>],
      "text": "<title> <first ~200 chars of content>"
    }
  ],
  project: <project>,
  limit: 5
)
```

### Step 2: Evaluate matches

If search returns results with similarity > 0.5, fetch full text of the top 1-3 matches:

```
mcp__autodev-memory__get_entry(entry_id: <id>, project: <project>)
```

Read the full content and compare with the new entry.

### Step 3: Decide action

| Situation | Action |
|---|---|
| No matches, or all matches are about different topics | **new** |
| Strong match covers same topic but new entry adds information | **append** |
| Strong match exists but new entry is better/more complete | **supersede** |
| New entry is already fully covered by existing entry | **skip** |

Use judgment, not just similarity scores. Two entries can have high similarity but cover
different aspects of a topic (both should exist). Or low similarity but one clearly
supersedes the other (e.g., updated version of old guidance).

### Step 4: Execute

**New — create fresh entry:**

```
mcp__autodev-memory__add_entry(
  title: <title>,
  content: <content>,
  entry_type: <type>,
  project: <project>,
  summary: <summary>,
  tags: <tags>,
  repos: <repos>,
  source: <source>,
  source_metadata: <source_metadata>,
  caller_context: {
    ...caller_context,
    "action_rationale": "No existing entry covers this topic"
  }
)
```

**Append — merge into existing entry:**

Write a coherent combined version that integrates both pieces of knowledge. Don't just
concatenate — restructure if needed so the entry reads naturally.

```
mcp__autodev-memory__update_entry(
  entry_id: <existing_entry_id>,
  project: <project>,
  content: "<merged content combining existing + new information>",
  summary: "<updated summary reflecting combined knowledge>",
  source_metadata: <source_metadata>,
  caller_context: {
    ...caller_context,
    "action_rationale": "Appending to existing entry — new info: <what's new>"
  }
)
```

**Supersede — replace with better version:**

Use `supersede_entry(old_entry_id, title, content, entry_type, project, summary, tags, repos,
source, source_metadata)` — the tool handles marking the old entry as superseded and creating
the new entry with a proper supersession chain link. Pass the old entry's ID and the new
entry's full details.

```
mcp__autodev-memory__supersede_entry(
  old_entry_id: <old_entry_id>,
  title: <title>,
  content: "<improved content that supersedes the old entry>",
  entry_type: <type>,
  project: <project>,
  summary: <summary>,
  tags: <tags>,
  repos: <repos>,
  source: <source>,
  source_metadata: <source_metadata>,
  caller_context: {
    ...caller_context,
    "action_rationale": "Superseding entry <old_id> — <why old is outdated>"
  }
)
```

**Skip — already covered:**

No MCP calls. Log the decision.

### Step 5: Log the decision

Track each ingestion decision for the caller's summary:

```
{
  "title": <title>,
  "action": "new|append|supersede|skip",
  "target_entry": <entry_id or null>,
  "reason": "<brief explanation>"
}
```

Return this log to the calling skill so it can report results.

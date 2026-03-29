---
description: Save knowledge to the memory system. Replaces the !!! hook trigger.
skills:
  - autodev-save
---

# Save Command

Save a piece of knowledge to the autodev-memory system. Searches existing entries to avoid
duplicates, determines the right scope (global vs project), and creates/updates/supersedes as
appropriate.

## Usage

```
/save                          # Save knowledge from recent conversation context
/save "always use TEXT not VARCHAR in Postgres"  # Save a specific piece of knowledge
```

## When to Use

| Trigger | Example |
|---|---|
| User wants to remember something | "Save this", "remember this" |
| User correction | "No, do X not Y" then `/save` |
| Discovery worth preserving | "TIL that React Router..." then `/save` |
| Explicit preference | "I always want X" then `/save` |

## Behavior

Follow the **autodev-save** skill procedure exactly:

1. **Extract** knowledge from user's message and/or recent conversation
2. **Determine scope** by fetching project topology (`list_projects`, `list_repos`)
3. **Fetch all entries** in the target scope (`list_entries`)
4. **Match** against existing entries, fetch full content of candidates
5. **Decide** action: new, append, supersede, skip, deprecate
6. **Execute** the action via MCP tools
7. **Report** what happened to the user

## Important

- **Bias toward global scope.** See the skill for the full decision matrix. When in doubt, go
  global — new projects will benefit from shared knowledge.
- **Don't skip the entry fetch.** The whole point is deduplication. Always `list_entries` before
  deciding.
- **Content quality matters.** Entries should be self-contained, actionable, and include WHY.
  Target 200-800 tokens.

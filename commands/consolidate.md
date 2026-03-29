---
description: Audit all memories for the current repo. Checks validity, duplicates, scope, and structure. Proposes actions — never auto-modifies.
skills:
  - autodev-consolidate
max_turns: 200
---

# Consolidate Command

Audit every memory entry applicable to the current repository — both global and project-scoped.
Cross-references entries against the actual codebase to find stale, duplicate, contradictory,
or poorly structured entries. Presents a numbered action list for user selection.

## Usage

```
/consolidate              # Full audit of all applicable entries
```

## When to Use

| Situation | Use This? |
|---|---|
| Memory system has grown organically, feels bloated | Yes |
| Suspect stale entries that reference deleted code | Yes |
| Multiple entries seem to cover the same topic | Yes |
| Entries feel too long, too short, or badly scoped | Yes |
| Want to add new knowledge | No — use /save |
| Want to fix a memory search failure | No — use /wtf |
| Want to audit .claude/knowledge/ files | No — use /heal-knowledge |

## Behavior

Follow the **autodev-consolidate** skill procedure exactly:

1. **Identify scope** — determine project from CLAUDE.md mem stub
2. **Fetch all entries** — global + project-scoped, including superseded
3. **Read every entry** — full content, in parallel batches
4. **Audit each entry** — validity, currency, accuracy, scope, size/quality
5. **Cross-entry analysis** — duplicates, merge candidates, splits, contradictions, tag issues
6. **Present numbered action list** — grouped by action type, sorted by impact
7. **Wait for user selection** — never execute without explicit approval
8. **Execute selected actions** — only the ones the user picked

## Important

- **Read-only until user selects.** The audit phase never modifies anything.
- **Verify against code.** Don't just read entries — grep the codebase to check if referenced
  functions, files, and patterns still exist.
- **Be specific.** Every proposed action must explain what's wrong and what will change.
- **Preserve information.** Merges and simplifications must not lose unique content.

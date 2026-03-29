---
name: autodev-glossary
description: Define, update, list, or delete glossary terms in the memory system. Personal vocabulary management.
user_invocable: false
---

# Autodev Glossary

Manage the user's personal glossary — shorthand, coined terms, and project-specific jargon.
Glossary terms are stored as regular entries with `type: glossary` in the memory system.

## Actions

### Define a Term

When the user provides a term and definition (either explicitly or in conversation context):

1. **Determine scope** — Is this term project-specific or global?

   | Term Type | Scope | Example |
   |---|---|---|
   | General shorthand | `global` | "NanoClaw", "the plumbing" |
   | Cross-project jargon | `global` | "ticker", "compound" |
   | Project-specific jargon | project name | "the aggregator" (only in ts-prefect) |

   **Bias toward global.** Most personal vocabulary is used across projects. Only scope to a
   project if the term is genuinely meaningless outside that project.

2. **Check existing terms:**

   ```
   mcp__autodev-memory__list_entries(project: <project>, entry_type: "glossary")
   ```

   If the term already exists (matching title), update it with `update_entry`.

3. **Define the term:**

   ```
   mcp__autodev-memory__add_entry(
     title: "<the term, in the user's natural casing>",
     content: "<clear, self-contained description, 1-3 sentences>",
     entry_type: "glossary",
     project: "<global or project name>",
     tags: ["glossary"],
     summary: "<brief one-line definition>"
   )
   ```

4. **Report:** Tell the user what was defined/updated and its scope.

### Extract from Conversation

When the user invokes `/glossary` without explicit arguments, analyze the recent conversation
to identify what term is being defined:

- Look for patterns like "X is what I call Y", "by X I mean Y", "X = Y"
- Look for the user explaining jargon or shorthand to Claude
- If no clear term can be identified, ask the user what term they want to define

### List Terms

When the user says "list" or wants to see their glossary:

```
mcp__autodev-memory__list_entries(project: <project>, entry_type: "glossary")
```

Display terms grouped by scope (global first, then project-specific).

### Delete a Term

When the user wants to remove a term, find the entry by listing glossary entries and matching
the title, then:

```
mcp__autodev-memory__delete_entry(entry_id: "<id>", project: "<project>")
```

Confirm the deletion to the user.

## Description Quality

Good descriptions are:

- **Self-contained** — Don't reference "the user" or "this project"
- **Contextual** — Include enough context for someone unfamiliar
- **Concise** — 1-3 sentences, not a paragraph
- **Natural** — Written as a definition, not a note

Examples:

- "NanoClaw" -> "Autonomous AI orchestration platform for running Claude Code agents in parallel
  across multiple repositories"
- "the plumbing" -> "The Prefect/dbt pipeline layer that handles data extraction, transformation,
  and loading between services"
- "ticker" -> "Background process that runs on a schedule to check for new data and trigger
  pipeline runs"

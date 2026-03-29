---
description: Define or manage glossary terms. Replaces the >>> hook trigger.
skills:
  - autodev-glossary
---

# Glossary Command

Define, update, list, or delete glossary terms in the memory system. Glossary terms are stored
as regular entries with `type: glossary`. They represent the user's personal vocabulary —
shorthand, coined terms, and project-specific jargon.

## Usage

```
/glossary NanoClaw = autonomous AI orchestration platform    # Define a term
/glossary "the plumbing" = the Prefect/dbt pipeline layer    # Define with quotes
/glossary list                                                # List all terms
/glossary delete NanoClaw                                     # Delete a term
/glossary                                                     # Extract term from conversation
```

## When to Use

| Trigger | Example |
|---|---|
| User defines a term | "NanoClaw is what I call the orchestration platform" |
| User uses unfamiliar jargon | "By 'the plumbing' I mean the pipeline layer" |
| User says "define", "glossary" | "Add this to the glossary" |
| User wants to see terms | "What terms do I have defined?" |

## Behavior

Follow the **autodev-glossary** skill procedure:

1. **Parse** — Determine the action (define, list, delete, or extract from conversation)
2. **Scope** — Determine if the term is global or project-specific
3. **Check** — For definitions, check if the term already exists
4. **Execute** — Call the appropriate MCP tool (`add_entry` with type=glossary)
5. **Report** — Tell the user what happened

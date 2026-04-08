---
description: Investigate why the memory system failed to prevent an error. Replaces the ??? hook trigger.
skills:
  - autodev-wtf
---

# WTF Command

Investigate why the memory system failed to prevent an error the user just encountered. Traces
the search pipeline for the specific failure, diagnoses the root cause, and recommends a fix.
Also saves the correction to the memory system via `/save`.

## Usage

```
/wtf                          # Investigate why memory didn't help with the current error
/wtf "topic that was missed"  # Investigate a specific topic the system should have surfaced
```

## When to Use

| Trigger | Example |
|---|---|
| Memory system missed something | "You should have known this — it's in the KB" |
| Correction not surfaced | User corrects Claude on something that should have been found |
| Repeated mistake | Same error keeps happening despite prior corrections |

## Behavior

Follow the **autodev-wtf** skill procedure:

1. **Collect** — Pull evidence from hook logs and debug logs via MCP
2. **Trace** — Follow the pipeline: user question → query generation → search results
3. **Search** — Check if relevant knowledge exists in the KB
4. **Diagnose** — Classify root cause (no_entry, bad_query, bad_ranking, bad_tags, etc.)
5. **Recommend** — Provide actionable fix for the diagnosed cause
6. **Save** — Store the correction in the memory system (invoke `/save` methodology)

## Important

- This is a **single-failure trace**, not a broad audit. Use `/autodev-improve` for system-wide
  analysis.
- Keep the verdict SHORT. The user is frustrated — give a clear answer and confirmation it
  won't happen again.
- Always save the correction. The investigation diagnoses why the system failed, but the new
  knowledge still needs to be stored.

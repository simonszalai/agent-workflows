---
name: autodev-wtf
description: >-
  Incident-focused investigation skill for when the memory system fails to prevent
  an error. Traces the search pipeline for a single failure, diagnoses the root cause,
  and recommends a fix. Used by /wtf command.
---

# Autodev WTF — Memory System Failure Investigation

When the user runs `/wtf`, the memory system failed to prevent an error they just corrected.
This skill provides the methodology to investigate WHY.

**Scope:** One failure, one trace, one verdict. This is NOT a broad system audit
(use `autodev-improve` for that). This traces a single pipeline execution to find
where it broke.

## Investigation Process

### Step 1: COLLECT — Pull evidence for this session

**Start with the hook log file** — it shows exactly what each hook did and returned:

```bash
# See recent hook activity (what queries were generated, what was returned)
tail -50 ~/.config/autodev-memory/hooks.log

# See the full additionalContext that was sent to Claude
grep "output ->" ~/.config/autodev-memory/hooks.log | tail -5

# Check for errors
grep ERROR ~/.config/autodev-memory/hooks.log | tail -10
```

Then collect additional evidence via MCP tools:

```
mcp__autodev-memory__debug_logs(project="<project>", operation="mcp_search", hours=2, limit=20)
mcp__autodev-memory__debug_logs(project="<project>", operation="mcp_create_entry", hours=2, limit=10)
mcp__autodev-memory__list_entries(project="<project>")
```

Also use the conversation transcript already in context — it shows what the user
asked about that led to the error.

### Step 2: TRACE — Follow the pipeline for the failing interaction

1. **What was the user's question?** — Identify the message that led to the error.
   This is the conversation context before the `/wtf` invocation.

2. **What queries did Haiku generate?** — Check `request.queries` in the search
   operation logs for that timeframe.

3. **What results came back?** — Check `response.results` for each search. Note:
   - Which entries were returned
   - Their similarity scores
   - Their titles and types
   - Whether the relevant topic appeared at all

4. **What scores did results have?** — Were relevant entries present but ranked too
   low? Were irrelevant entries ranked higher?

### Step 3: SEARCH — Check if relevant knowledge exists

Search the KB for the correction topic:

```
mcp__autodev-memory__search(queries=[{"keywords": [...], "text": "..."}], project="<project>")
mcp__autodev-memory__list_entries(project="<project>")
```

- **If found:** Why wasn't it surfaced? Possible causes:
  - Query mismatch (Haiku generated queries that don't match the entry)
  - Bad tags (entry tags don't match the query's semantic space)
  - Low similarity (embedding distance too far despite topic relevance)
  - Below limit (entry was in top-20 per retriever but cut by result limit)

- **If not found:** This is a knowledge gap. Use the `/save` methodology to store the
  correction as a new entry.

### Step 4: DIAGNOSE — Classify root cause

Pick ONE primary root cause:

| Category          | When to use                                                |
| ----------------- | ---------------------------------------------------------- |
| `no_entry`        | Relevant knowledge doesn't exist in KB (gap)               |
| `bad_query`       | Haiku generated wrong/insufficient search queries          |
| `bad_ranking`     | Entry exists, was searched, but ranked too low / below cut |
| `bad_tags`        | Entry exists but tags don't match the query space          |
| `bad_prompt`      | Query generation prompt template is inadequate             |
| `hook_failure`    | Hooks didn't fire (prompt too short, error, config issue)  |
| `formatting_loss` | Results returned but formatted poorly / Claude ignored     |
| `not_preventable` | This error can't reasonably be caught by the memory system |

### Step 5: RECOMMEND — Actionable fix

For each root cause, the standard recommendation:

- **`no_entry`** — Save the correction via `/save` methodology. Knowledge gap filled.
- **`bad_query`** — "Query generation prompt should handle [pattern]. Consider
  adding an example to `hooks/prompts/query-generation.md`."
- **`bad_ranking`** — "Entry exists but scored [X]. Consider updating the entry
  summary to use vocabulary matching how this topic naturally comes up."
- **`bad_tags`** — "Entry tags [X] don't match query space [Y]. Retag the entry."
- **`bad_prompt`** — "Haiku prompt template needs an example for [pattern type]."
- **`hook_failure`** — "Hook didn't fire because [reason]. Fix: [specific fix]."
- **`formatting_loss`** — "Results returned but key info lost in formatting."
- **`not_preventable`** — "This type of error isn't catchable by KB search."

### Step 6: SAVE — Store the correction

After the investigation, always save the correction to the memory system. Follow the
`autodev-save` skill procedure:

1. Determine scope (global vs project) using project topology
2. Fetch existing entries to check for duplicates
3. Decide action (new/append/supersede/skip)
4. Execute via MCP tools

## Output Format

Report your findings as a concise structured verdict:

```
## WTF Investigation Verdict

**Root cause:** `<category>`
**Confidence:** high | medium | low

**What happened:**
<2-3 sentences explaining the failure chain>

**Evidence:**
- <specific data point 1>
- <specific data point 2>

**Fix:**
<actionable recommendation — what to do to prevent recurrence>

**Correction status:** <saved as new entry | appended to X | superseded X>
```

Keep it SHORT. This is a verdict, not a report. The user is frustrated — they
want a clear answer and confirmation it won't happen again.

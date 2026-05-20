---
name: autodev-wtf-memory
description: Investigate why the autodev-memory system failed to prevent an error. Traces the memory search pipeline for a specific failure — query generation, retrieval, ranking, formatting.
---

# WTF Memory

Investigate why the memory system failed to surface knowledge that should have prevented
an error the user just encountered. Traces the search pipeline for the specific failure,
diagnoses the root cause, and recommends a fix.

**Scope:** One failure, one pipeline trace, one verdict. This is NOT a broad system audit
(use `/consolidate` for that) and NOT a workflow gap analysis (use `/autodev-wtf-workflows`
for that). This traces a single memory retrieval execution to find where it broke.

## Usage

```
/autodev-wtf-memory                          # Why didn't memory help with the current error?
/autodev-wtf-memory "topic that was missed"  # Why wasn't this topic surfaced?
```

## When to Use

| Trigger | Example |
|---|---|
| Memory system missed something | "You should have known this — it's in the KB" |
| Correction not surfaced | User corrects Claude on something that was already stored |
| Repeated mistake | Same error keeps happening despite prior corrections |
| Knowledge existed but wasn't used | Entry exists, agent didn't act on it |

## When NOT to Use

| Situation | Use Instead |
|---|---|
| Bug slipped through agent workflows | `/autodev-wtf-workflows` |
| Broad memory system audit | `/consolidate` |
| Bug root cause investigation | `/investigate` |
| Learning moment after a correction | `/compound` |

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

Trace every stage of the memory retrieval pipeline:

1. **What was the user's question?** — Identify the message that led to the error.

2. **Did hooks fire?** — Check hooks.log for activity in that timeframe.
   If no hook activity, the pipeline never started (hook_failure).

3. **What queries did Haiku generate?** — Check `request.queries` in the search
   operation logs.

4. **What results came back?** — Check `response.results` for each search. Note:
   - Which entries were returned
   - Their similarity scores
   - Their titles and types
   - Whether the relevant topic appeared at all

5. **What scores did results have?** — Were relevant entries present but ranked too
   low? Were irrelevant entries ranked higher?

6. **Was the result formatted and injected?** — Check if the hook output included
   the relevant entry in the additionalContext sent to Claude.

7. **Did Claude act on it?** — If the entry was in context, did Claude ignore it?

### Step 3: SEARCH — Check if relevant knowledge exists

Search the KB for the correction topic:

```
mcp__autodev-memory__search(queries=[{"keywords": [...], "text": "..."}], project="<project>")
mcp__autodev-memory__list_entries(project="<project>")
```

- **If found:** Why wasn't it surfaced? Move to Step 4 diagnosis.
- **If not found:** This is a knowledge gap (`no_entry`). Save the correction.

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

- **`no_entry`** — Save the correction via MCP. Knowledge gap filled.
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

After the investigation, always save the correction to the memory system:

1. Determine scope (global vs project) using project topology
2. Fetch existing entries to check for duplicates
3. Decide action (new/append/supersede/skip)
4. Execute via MCP tools

```
mcp__autodev-memory__create_entry(
  project="<project>",
  title="<1-sentence root cause / gotcha summary>",
  content="<Full explanation: what happened, why, how to prevent>",
  entry_type="gotcha",
  summary="<1-sentence summary>",
  tags=["wtf-memory", "<area>", "<technology>"],
  source="captured",
  caller_context={
    "skill": "autodev-wtf-memory",
    "reason": "<why this is worth persisting>",
    "action_rationale": "New entry — memory pipeline failure revealed gap",
    "trigger": "memory pipeline trace"
  }
)
```

## Output Format

Report findings as a concise structured verdict:

```
## WTF Memory Verdict

**Root cause:** `<category>`
**Confidence:** high | medium | low

**Pipeline trace:**
- Hook fired: yes/no
- Queries generated: [list]
- Entry exists: yes/no
- Entry returned: yes/no (score: X.XX)
- Entry in context: yes/no
- Claude acted on it: yes/no/n/a

**What happened:**
<2-3 sentences explaining the failure chain>

**Evidence:**
- <specific data point 1>
- <specific data point 2>

**Fix:**
<actionable recommendation — what to do to prevent recurrence>

**Correction status:** <saved as new entry | appended to X | superseded X | not needed>
```

Keep it SHORT. This is a verdict, not a report. The user wants a clear answer
and confirmation it won't happen again.

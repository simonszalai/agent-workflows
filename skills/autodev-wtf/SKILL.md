---
name: autodev-wtf
description: Investigate how a bug slipped into production. Runs memory system and workflow pipeline analysis in parallel to find all gaps.
---

# WTF

A bug slipped into production. Find out why. This orchestrator runs two investigations
in parallel — one on the memory system, one on the agent workflows — then synthesizes
a unified verdict.

## Usage

```
/autodev-wtf "Bug description: items missing associations"
/autodev-wtf B0009                    # Bug ticket B0009
/autodev-wtf "scraper config broke prod after deploy"
```

## When to Use

| Trigger | Example |
|---|---|
| Bug reached production | Something is broken in prod |
| Known issue recurred | "Didn't we fix this already?" |
| Post-incident review | Want to know where the system failed |

## When NOT to Use

| Situation | Use Instead |
|---|---|
| Only memory system suspected | `/autodev-wtf-memory` directly |
| Only workflow gap suspected | `/autodev-wtf-workflows` directly |
| Need to find the bug's root cause | `/investigate` first, then `/autodev-wtf` |
| Learning moment, not a prod bug | `/compound` |
| Broad system audit | `/deep-dream` |

## Process

### Step 1: Establish Context

If a ticket ID is given, load it:
```
mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

If only a description, search for related tickets:
```
mcp__autodev-memory__search_tickets(project=PROJECT, query="<description>")
```

Gather enough context to brief both investigations: bug description, affected code area,
when it was introduced, what the expected behavior was.

### Step 2: Run Both Investigations in Parallel

Spawn two agents simultaneously:

**Memory investigation:**
```
Agent(subagent_type="general-purpose", name="wtf-memory", prompt="
Run /autodev-wtf-memory for this failure:

Bug: [description]
Affected area: [code area]
Ticket: [ID or 'none']

Trace the memory search pipeline to determine if the autodev-memory system
had knowledge that should have prevented this bug. Follow the full
autodev-wtf-memory skill process, including its Step 6 auto-save/fix
(new entry only for no_entry; per-category fix for ranking/tag/formatting
failures; nothing for not_preventable).

Report your verdict in the WTF Memory Verdict format, including exactly
which entries you created or updated (with entry IDs).
")
```

**Workflow investigation:**
```
Agent(subagent_type="general-purpose", name="wtf-workflows", prompt="
Run /autodev-wtf-workflows for this failure:

Bug: [description]
Affected area: [code area]
Ticket: [ID or 'none']

Trace the agent workflow pipeline (plan -> build -> review -> test -> verify)
to determine which stage should have caught this bug. You are running under
/autodev-wtf: skip the skill's standalone approval stop and apply your
concrete workflow fixes directly (skill edits, checklist items).

Report your findings in the WTF Workflows Analysis format, including exactly
which files you edited.
")
```

### Step 3: Synthesize Unified Verdict

Combine both investigation results into a single report:

```markdown
## WTF Verdict: [Brief title]

**Date:** YYYY-MM-DD
**Bug:** [1-sentence description]
**Ticket:** [ID or 'none']

### Memory System
**Root cause:** `<category>` | **Confidence:** high/medium/low
[2-3 sentence summary from wtf-memory investigation]
**Fix:** [memory system fix or "no gap found"]

### Workflow Pipeline
**Primary gap stage:** [stage name] | **Severity:** PRIMARY
[2-3 sentence summary from wtf-workflows investigation]
**Fix:** [workflow fix]

### Secondary Gaps
| Source | Gap | Fix |
|---|---|---|
| [memory/workflow] | [description] | [fix] |

### Combined Prevention Plan
1. [Most important fix — the one that would have caught this earliest]
2. [Second fix]
3. [Third fix if applicable]
```

### Step 4: Apply Fixes (automatic)

Fixes are applied automatically — no approval gate. The child investigations own their own
saves (`/autodev-wtf-memory` saves/updates memory entries per its verdict; the workflow
analysis applies skill/checklist fixes). Do NOT re-save entries a child already saved — the
parent only applies fixes neither child owns, then synthesizes and reports everything that
was changed.

Write the retrospective artifact:
```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="retrospective",
  content="<unified verdict content>",
  command="/autodev-wtf"
)
```

## Key Principles

- **Both dimensions always.** Even if you suspect only one system failed, run both.
  The point is catching gaps you didn't expect.
- **Propose, don't apply.** Step 3 presents findings. Step 4 only happens after approval.
- **Concrete fixes only.** Every gap must produce a specific, actionable fix — a file to
  edit, an entry to create, a checklist item to add. "Be more careful" is not a fix.
- **One bug, one verdict.** This is not a broad audit. Trace one specific failure through
  both systems.

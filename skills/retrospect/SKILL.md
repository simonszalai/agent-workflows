---
name: retrospect
description: After a mess was just untangled in the current thread, find what memory or workflow gap let it happen and fix that gap. Thread-driven post-mortem — no ticket required.
---

# Retrospect

A mess just got fixed in **this conversation** — a wrong turn, a re-discovered gotcha, a
correction the user had to make, a workflow that produced the wrong thing and had to be
redone. Retrospect looks backward over the current thread and answers one question:

> **What in the memory system or the agent workflows should have prevented this, and why
> didn't it?**

Then it proposes — and after approval, applies — the specific fix so the same mess can't
recur. The distinguishing input is the **live thread**, not a ticket or a production bug.

## Usage

```
/retrospect                         # Analyze the current thread for what went wrong upstream
/retrospect "the enum migration"    # Focus the retro on a specific mess from the thread
```

## When to Use

| Trigger | Example |
|---|---|
| You just corrected a mistake mid-thread | "That's wrong — it should be X" and Claude reworked it |
| A documented gotcha was re-hit live | The fix existed in the KB but didn't surface |
| A workflow produced the wrong thing | Plan/build/review delivered something that had to be redone |
| Wasted effort that a rule would have saved | Went down a path that an existing convention forbids |
| The user says "make sure this doesn't happen again" | About something that happened in this session |

## When NOT to Use

| Situation | Use Instead |
|---|---|
| Bug reached **production** (start from ticket/bug) | `/autodev-wtf` |
| Only the memory pipeline is suspected | `/autodev-wtf-memory` |
| Only a workflow stage is suspected | `/autodev-wtf-workflows` |
| Just save a piece of knowledge | `/compound "<the fact>"` |
| Broad audit of all memories for the repo | `/dream` |
| Audit the whole memory↔workflow pipeline against logs | `/autodev-improve` |
| Need the bug's technical root cause first | `/investigate`, then `/retrospect` |

`/retrospect` is the **thread-driven** sibling of `/autodev-wtf`. WTF starts from a ticket or
a prod incident; Retrospect starts from what just happened in front of you. Both run the same
two-dimension analysis (memory + workflow) and reuse the same sub-skills.

## Process

### Step 1: EXTRACT the incident from the thread

Read back over the current conversation and write a crisp **incident statement**. Do not
guess — quote what actually happened. Capture:

1. **The mess** — what went wrong, in one sentence. (e.g. "Used VARCHAR(32) for a revision id
   that needed widening; CI failed on truncation.")
2. **The fix** — what corrected it, in one sentence.
3. **The signal** — *how* it surfaced. This drives the triage:
   - User correction ("no, do X") → likely a **knowledge/rule gap**
   - Re-discovered the hard way (debugging led back to a known cause) → likely a **memory retrieval gap**
   - A workflow artifact (plan/todos/review) delivered the wrong scope → likely a **workflow gap**
4. **The wasted work** — what had to be thrown away or redone (evidence of cost).
5. **The code/area** touched.

If `/retrospect "<focus>"` was given, scope the incident statement to that mess. If multiple
distinct messes occurred, list them and **retro the most expensive one first** (ask the user
if it's ambiguous which to take).

If the thread contains no real mess — work went smoothly — say so and stop. Not every session
needs a retro.

### Step 2: TRIAGE — both dimensions, always

Even when the signal points clearly at one dimension, run **both**. The point of a retro is
catching the gap you didn't expect. The signal from Step 1 sets which dimension is the
*primary suspect*, not the only one.

### Step 3: Run both investigations in parallel

Spawn two agents simultaneously, each briefed with the **incident statement** from Step 1
(not a ticket — these sub-skills normally take a ticket; give them the thread-derived incident
instead):

**Memory investigation:**
```
Agent(subagent_type="general-purpose", name="retro-memory", prompt="
Run the /autodev-wtf-memory skill process for this incident that occurred in a live session.
There is no ticket — work from this incident statement:

  Mess: [the mess]
  Fix: [the fix]
  How it surfaced: [the signal]
  Area: [code area]

Trace the autodev-memory pipeline: did the KB hold knowledge that should have surfaced and
prevented this? Use hooks.log and debug_logs for THIS session's timeframe. If the knowledge
existed but wasn't surfaced, diagnose why (bad_query / bad_ranking / bad_tags / formatting_loss /
hook_failure). If it didn't exist, that's a no_entry gap.

Report in the WTF Memory Verdict format. Do NOT save anything yet — propose only.
")
```

**Workflow investigation:**
```
Agent(subagent_type="general-purpose", name="retro-workflows", prompt="
Run the /autodev-wtf-workflows skill process for this incident that occurred in a live session.
There is no ticket — work from this incident statement:

  Mess: [the mess]
  Fix: [the fix]
  How it surfaced: [the signal]
  Wasted work: [what was redone]
  Area: [code area]

Trace the agent workflow pipeline (plan -> build_todos -> implementation -> review -> tests ->
verify). Which stage should have caught this before it cost the user effort? If the work was
done ad-hoc with no plan/review, that itself is the gap. Identify the missing test or checklist
item.

Report in the WTF Workflows Analysis format. Propose fixes only — do NOT edit any files yet.
")
```

### Step 4: SYNTHESIZE the verdict

Combine both into one report:

```markdown
## Retrospect: [brief title]

**Date:** YYYY-MM-DD
**Mess:** [1-sentence]
**Fixed by:** [1-sentence]
**Cost:** [what was wasted/redone]

### Memory System
**Root cause:** `<category>` | **Confidence:** high/medium/low
[2-3 sentences from retro-memory]
**Fix:** [save/update entry, retag, star — or "no gap"]

### Workflow Pipeline
**Primary gap stage:** [stage] | **Severity:** PRIMARY
[2-3 sentences from retro-workflows]
**Fix:** [skill/checklist/CLAUDE.md edit — or "no gap"]

### Prevention plan (ordered — earliest catch first)
1. [The single change that would have stopped this soonest]
2. [Next]
3. [If applicable]
```

If both dimensions come back "no gap / not preventable", say so plainly — sometimes a mess is
an honest one-off and the right answer is no change.

### Step 5: STOP for approval

Present the verdict and the prevention plan. **Wait for the user.** Propose, don't apply.

### Step 6: APPLY approved fixes

After approval, apply each approved fix:

- **Memory gaps** — save/update/supersede entries via the autodev-memory MCP. Use the
  `compound` store procedure (search → dedup → store). Star the entry if it's a simple rule
  that was violated. Tag with `retrospect` plus the area/tech tags.
- **Workflow gaps** — edit the target: a skill `SKILL.md`, a review reference, or `CLAUDE.md`
  for a project convention. (Workflow skills live in `~/dev/agent-workflows/skills/`, symlinked
  to `~/.claude/skills/` — edits are live immediately.)
- **Write the retrospective artifact** so the analysis is durable. If a ticket relates to this
  thread, attach it:
  ```
  mcp__autodev-memory__create_artifact(
    project=PROJECT, ticket_id=ID_or_null, repo=REPO,
    artifact_type="retrospective",
    content="<verdict + prevention plan>",
    command="/retrospect"
  )
  ```

## Key Principles

- **Thread is the source.** Quote what happened; don't reconstruct from vibes. The evidence is
  already in context — use it, plus the session's hook/debug logs.
- **Both dimensions, every time.** Memory and workflow. The unexpected gap is the valuable one.
- **One mess, one verdict.** This is a focused post-mortem, not an audit. For breadth use `/dream`
  or `/autodev-improve`.
- **Propose, then apply.** Step 4 presents; Step 6 only runs after approval.
- **Concrete fixes only.** Every gap yields a specific edit — a file to change, an entry to save,
  a checklist line to add, an entry to star. "Be more careful" is not a fix.
- **A clean thread is a valid outcome.** If nothing went wrong, or the mess was a true one-off,
  say so and change nothing.

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

### Step 1.5: IDENTIFY what built it (provenance) — mandatory when the mess is in shipped code

Before triaging the workflow dimension, establish **how the offending code actually got in**.
Never infer "no workflow ran" from missing plan/build/review artifacts on the ticket — a
cross-provider run (Codex/Grok) or any run whose artifacts weren't persisted executes the
pipeline **without leaving artifacts on the ticket**. Confirm from primary evidence:

1. **The commit(s).** `git log --all --format='%h %ad %an <%ae> | %s' --date=iso -- <path>` and
   `git log --all --diff-filter=A -- <path>` for the introducing commit. Read the trailer: a
   `Co-Authored-By: Claude …` line ⇒ Claude Code built it; its absence (especially with a Codex
   session present for that date) ⇒ another provider or ad-hoc.
2. **The ticket events** (if a ticket exists): `get_ticket`, then read each event's
   `actor.command` / `actor.agent` / `actor.session_id` / `actor.machine`. These are the
   authoritative record of which workflow commands actually ran (`/plan`, `/build`, `/review`,
   `/milestone-flow`, …) and by which agent. **The command is nested under `actor`, not
   top-level** — a jq of `.events[].command` returns nothing and will fool you into "no workflow";
   use `.events[].actor.command`. Missing artifacts ≠ skipped workflow.
3. **The build session.** If an event's `actor.session_id` is present, that IS the session
   (Claude logs live at `~/.claude/projects/<slug>/<session_id>.jsonl`). Otherwise run forensics —
   grep **both** stores for the build signature (introducing-commit subject, ticket id, a new
   symbol/file name) and take the session whose timestamp precedes the commit:
   ```bash
   # Claude sessions
   grep -rlE "<commit-subject>|<TICKET>|def <new_symbol>" ~/.claude/projects/*<repo>*/ --include='*.jsonl' 2>/dev/null
   # Codex sessions
   grep -rlE "<commit-subject>|<TICKET>|def <new_symbol>" ~/.codex/sessions/ 2>/dev/null
   ```
   Inside the winning session, grep for the workflow commands it ran (`/plan`, `/build`,
   `/create-build-todos`, `/review`, `/resolve-review`, `/milestone-flow`, `/ticket-flow`,
   `/auto-build`, …) to see what the pipeline actually did.

Record three things — **provider/agent**, **session id + path**, and **the workflow commands that
actually ran** — and pass all three into the retro-workflows brief in Step 3. The workflow
analysis must reason about what the build session *did*, not about which artifacts survived on the
ticket.

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
  Build provenance (from Step 1.5): [provider/agent, session id + path, workflow commands that actually ran]

Trace the agent workflow pipeline (plan -> build_todos -> implementation -> review -> tests ->
verify). Step 1.5 already established which commands actually ran — do NOT conclude 'the pipeline
was skipped' from missing artifacts on the ticket. Reason about the stages that DID run: which one
should have caught this and had nothing to catch it with (e.g. a review that never challenged the
design choice, or a unit test that asserts the buggy behavior as correct)? And treat any artifacts
that ran but did not persist to the ticket as its own observability gap. Identify the missing test
or checklist item.

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
- **Artifacts ≠ provenance.** Missing plan/build/review artifacts on a ticket do NOT mean no
  workflow ran — a Codex/Grok run executes the pipeline without persisting artifacts to the
  ticket. Always establish what built the code from commits + ticket events (`actor.command`) +
  the build session (Step 1.5) before judging the workflow dimension.
- **One mess, one verdict.** This is a focused post-mortem, not an audit. For breadth use `/dream`
  or `/autodev-improve`.
- **Propose, then apply.** Step 4 presents; Step 6 only runs after approval.
- **Concrete fixes only.** Every gap yields a specific edit — a file to change, an entry to save,
  a checklist line to add, an entry to star. "Be more careful" is not a fix.
- **A clean thread is a valid outcome.** If nothing went wrong, or the mess was a true one-off,
  say so and change nothing.

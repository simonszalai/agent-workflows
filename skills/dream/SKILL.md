---
name: dream
description: Audit all memories for the current repo the way an offline "dreaming" consolidator would — check validity, utility, duplicates, scope, and structure, and abstract instances into rules. Proposes changes, runs them past skeptic critic agents over several rounds, and autonomously applies the ones that survive — no human gate.
max_turns: 300
---

# Dream

Audit every memory entry applicable to the current repository — both global and project-scoped.
Cross-references entries against the actual codebase to find stale, duplicate, contradictory,
or poorly structured entries, and compiles a proposed action list. Then runs that list through
several rounds of **adversarial review** by independent skeptic agents and **autonomously applies
the actions that survive** — no human gate.

The audit applies two lenses. **Truth:** is the entry correct against the code (the codebase
is the source of truth)? **Utility:** does the entry *earn its place* — would a future task
fail or regress if it were gone? The second lens is borrowed from offline "memory
consolidation" / agent "dreaming" research (Auto-Dreamer, Active Dreaming Memory), which keeps
a memory only if it stays load-bearing. A correct-but-never-surfaced entry is still pure token
cost. This skill does the full consolidation an autonomous dreamer would do — propose,
self-critique, and commit — end to end.

**Critical rules:**

1. **NEVER change any code, and never touch anything outside the autodev-memory store.** The only
   side effects this skill may produce are memory mutations (create / update / delete entries and
   tags). No file edits, no git, no deploys.
2. **No mutation before scrutiny.** A proposed action may be executed ONLY after it has survived
   the full adversarial review loop (Steps 7–9). Never execute a freshly-generated proposal
   directly — every action must pass the skeptics first.
3. **Bias toward NOT acting.** Doing nothing is always a safe outcome; a wrong destructive edit is
   not. When a round ends with an unrebutted objection against an action, the action is **dropped,
   not applied**. Survival is the exception, not the default.

## Usage

```
/dream              # Audit, adversarially review, and autonomously apply surviving consolidations
```

Runs end to end with no human gate: it audits every applicable entry, compiles proposed
changes, subjects them to several rounds of skeptic-critic review, and applies only the
actions that survive. Nothing outside the autodev-memory store is touched. A run that applies
zero changes (because nothing survived scrutiny) is a normal, successful outcome.

## When to Use

| Situation | Use This? |
|---|---|
| Memory system has grown organically, feels bloated | Yes |
| Suspect stale entries that reference deleted code | Yes |
| Multiple entries seem to cover the same topic | Yes |
| Entries feel too long, too short, or badly scoped | Yes |
| Accurate entries piling up that never seem to surface or matter | Yes |
| Several narrow entries look like instances of one general rule | Yes |
| Want to add new knowledge | No — use /compound |
| Want to fix a memory search failure | No — use /autodev-wtf |

## Procedure

### Step 1: Identify Scope

Determine the current project from the `<!-- mem:project=X -->` stub in CLAUDE.md. If not
found, ask the user.

Fetch the project topology:

```
mcp__autodev-memory__list_projects()
mcp__autodev-memory__list_repos(project_name: <project>)
```

The audit covers TWO scopes:
1. **Global entries** — apply to all projects
2. **Project-scoped entries** — specific to the current project (including repo-tagged ones)

### Step 2: Fetch All Applicable Entries

Fetch the complete entry index for both scopes:

```
mcp__autodev-memory__list_entries(project: "global")
mcp__autodev-memory__list_entries(project: <project>)
```

Also fetch superseded entries to check for orphaned chains:

```
mcp__autodev-memory__list_entries(project: "global", include_superseded: true)
mcp__autodev-memory__list_entries(project: <project>, include_superseded: true)
```

Record the total count. Report to user: "Found N global + M project-scoped entries. Reading
all of them..."

### Step 3: Read Every Entry

Fetch the full content of every active entry:

```
mcp__autodev-memory__get_entry(entry_id: <id>, project: <project>)
```

Batch these calls — run up to 5 in parallel to avoid overwhelming the API. For each entry,
record:

| Field | What to Note |
|---|---|
| `id` | Entry UUID |
| `title` | Entry title |
| `entry_type` | gotcha, pattern, preference, correction, solution, reference, architecture, glossary |
| `summary` | One-line summary |
| `content` | Full content text |
| `tags` | Tag list |
| `repos` | Repo filter (null = project-wide) |
| `scope` | "global" or project name |
| `created_at` | When created |
| `updated_at` | When last modified |
| `token_estimate` | Rough token count (~4 chars per token) |

### Step 4: Audit Each Entry

Evaluate every entry against the audit dimensions in `references/audit-checklist.md`
(dimensions A-F: Validity, Currency, Accuracy, Scope, Size & Quality, Utility & Recall).

### Step 5: Cross-Entry Analysis

After auditing individual entries, analyze across the full set using the cross-entry
dimensions in `references/audit-checklist.md` (dimensions G-M: Duplicates & Overlaps,
Merge Candidates, Split Candidates, Contradiction Detection, Tag & Type Consistency,
Tag Vocabulary Audit, Abstraction Candidates).

### Step 6: Compile Findings

Organize all findings into a structured report. Group by action type and sort by impact
(highest impact first within each group).

### Step 7: Compile the Candidate Action List

Build the structured proposal list (format below). Give every action a stable id (`A1`, `A2`, …)
so the critics and adjudication log can reference it. This list is **round-0 input to the review
loop** — it is not a user menu and nothing here is executed yet.

### Step 8: Adversarial Review Loop

Run the candidate actions through up to **3 rounds** of skeptic review, following
`references/adversarial-review.md` in full. Summary of one round:

1. **Spawn 3 independent skeptic critics in parallel** — a single message with three `Agent`
   tool-use blocks (`subagent_type: "general-purpose"`). Each critic gets a **distinct lens** so
   they catch different failure modes:
   - **Critic 1 — Information-loss skeptic:** attacks every DELETE / MERGE / ABSTRACT / SIMPLIFY /
     SPLIT for discarding load-bearing specifics, exceptions, or provenance.
   - **Critic 2 — Evidence skeptic:** re-verifies each action's stated reason against the actual
     code and the actual entry content. Kills any proposal whose justification doesn't hold up
     ("function was removed" — was it really? grep and check).
   - **Critic 3 — Churn / utility skeptic:** defends the status quo. Attacks changes that don't
     earn their cost — cosmetic retags, risky rescopes, splits that add entries without real
     benefit.
   Brief each critic that flows pull memory facts that influence production code, so a bad
   consolidation has real downstream cost — they should push back hard and default to skepticism.
   Give them the full candidate list, the relevant entry contents, and access to the codebase +
   autodev-memory MCP so they **verify rather than speculate**.
2. **Collect verdicts.** Each critic returns, per action, one of `PASS` / `AMEND` / `KILL` with an
   evidence-backed reason (and a `safer_alternative` for AMEND).
3. **Adjudicate each action** (you, the orchestrator):
   - `KILL` that you cannot rebut with concrete evidence → **drop the action**.
   - `KILL` you *can* rebut (grep result, entry content, provenance) → action survives, but you
     **must log the rebuttal and its evidence**. A rebuttal without cited evidence is not allowed.
   - `AMEND` → rewrite the action to its safer form; it re-enters the next round as a new candidate.
   - `PASS` from all three → action is provisionally accepted for this round.
   - **Higher bar for destructive actions** (DELETE / MERGE / ABSTRACT / SPLIT): a *single*
     unrebutted `KILL` drops them.
4. **Carry forward.** Amended and still-contested actions go into the next round. Cleanly-passed
   actions are re-submitted too — a later round may still surface a new objection.
5. **Converge or cap.** Stop when a full round returns all-`PASS` on the current candidates
   (converged), or after round 3. After the cap, any action still carrying an unrebutted `KILL`
   is dropped; an action left in `AMEND` limbo executes only in its safest proposed form and only
   if it carries no outstanding `KILL`, otherwise it is dropped.

Keep an **adjudication log** across rounds: for each action, the verdicts it drew, your ruling,
and the evidence. This log is the audit trail for the autonomous execution in Step 9.

### Step 9: Execute Surviving Actions

Auto-apply every survivor via the MCP tools mapped in **Executing Surviving Actions** below.
Then emit the final report (format below): rounds run, what each round killed or amended, the
surviving actions, and exactly which memory mutations were made.

## Candidate Action Format

This is the internal round-0 list the skeptics review — not a user menu. Give each action a
stable `A#` id (shown in brackets) so verdicts and the adjudication log can reference it.

```markdown
## Memory Consolidation Audit — Candidate Actions

**Date:** YYYY-MM-DD
**Project:** <project-name>
**Scope:** N global entries + M project-scoped entries (T total)

### Summary

<2-3 sentences on overall health and the most impactful findings>

### Proposed Actions

These go to the skeptic critics next; only survivors are applied.

#### Stale / Invalid / Low-Utility

[A1] **DELETE** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ References `function_x()` which was removed in commit <hash>.
   No replacement needed — the function and its gotcha are gone.

2. **UPDATE** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ Says the API returns XML but it was switched to JSON 3 months ago.
   _Change:_ Update content to reflect JSON response format.

3. **DELETE (low-utility)** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ Still accurate, but earns no place — captured a one-off detail for
   a single closed ticket; no realistic future task would miss it. Deletion is on
   utility grounds, not correctness.

#### Duplicates & Merges

4. **MERGE** entries "<title A>" + "<title B>" -> new entry "<merged title>"
   _Reason:_ Both cover Postgres connection pooling. A has the config details,
   B has the gotchas. Combined they'd be ~600 tokens — well within limits.

5. **DELETE** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ Subset of entry "<other title>" which already covers everything
   this one says plus more.

#### Abstraction

6. **ABSTRACT** entries "<A>" + "<B>" + "<C>" -> new rule entry "<general rule>"
   _Reason:_ Three instances of one underlying rule (server_default on the
   timestamp column of tables A, B, C). One general rule covers all current and
   future cases; the per-table entries add nothing beyond the instance.
   _Preserved:_ No case-specific exception is lost in the generalization.

#### Scope Corrections

7. **RESCOPE** entry "<title>" from project to global
   _Reason:_ Describes a general SQLAlchemy pattern, not specific to this project.
   Other projects would benefit from finding this.

8. **RESCOPE** entry "<title>" from global to project "<name>"
   _Reason:_ References project-specific table names and business logic.
   Not useful to other projects.

#### Content Improvements

9. **SIMPLIFY** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ 1,800 tokens with redundant explanations. Can be cut to ~700
   without losing information.

10. **SPLIT** entry "<title>" into 2 entries
    _Reason:_ Covers both deployment gotchas and local dev setup. These are
    different topics with different audiences.

11. **IMPROVE SUMMARY** entry "<title>" (id: <short-id>, <scope>)
    _Reason:_ Summary says "database stuff" — not search-friendly.
    _Change:_ "Postgres JSONB column indexing patterns for partial key lookups"

#### Tag & Type Fixes

12. **RETYPE** entry "<title>" from "pattern" to "gotcha"
    _Reason:_ Content describes a trap and its workaround, not a pattern.

13. **RETAG** entry "<title>" — add tags: ["postgres", "indexing"]
    _Reason:_ Currently untagged. These tags match the content and improve
    search discoverability.

#### Tag Merges

14. **MERGE TAGS** `pg` + `postgres` + `postgresql` -> `postgres` (N entries affected)
    _Entries:_ "<title A>" (pg), "<title B>" (postgresql), "<title C>" (postgres)
    _Reason:_ Three synonyms for the same technology. `postgres` is the most
    commonly used form. Will retag entries using non-canonical variants.

#### Contradictions

15. **RESOLVE** contradiction between "<title A>" and "<title B>"
    _Reason:_ A says "always use TEXT columns", B says "use VARCHAR(255)
    for indexed columns". Need user decision on which is correct.

#### No Issues Found

- "<title>" — current, accurate, well-scoped
- "<title>" — current, accurate, well-scoped
- ...
```

## Key Principles

1. **Survival, not selection, is the gate.** No human picks actions. An action executes only
   after it survives the full skeptic loop with no outstanding, unrebutted objection. The default
   for any action is *not applied* — survival is earned.
2. **Verify against code, not just memory.** The codebase is the source of truth. If an entry
   says X but the code does Y, the entry is wrong (or outdated). The same standard binds the
   critics and your rebuttals: every claim, attack, and counter must cite concrete evidence.
3. **Be specific in proposals.** Don't say "this entry could be improved" — say exactly what's
   wrong and what the fix looks like.
4. **Preserve information.** When proposing merges, note that all unique content from both
   sources will be preserved. When proposing deletions, explain why no information is lost.
5. **Bias toward fewer, better entries.** Three focused entries beat seven scattered ones.
   Merging is almost always better than keeping near-duplicates.
6. **Short IDs for readability.** Show first 8 chars of UUIDs in the action list.
7. **Group "no issues" entries.** Don't waste space on healthy entries — list them briefly
   at the bottom so the user knows they were reviewed.
8. **Utility, not just truth.** An accurate entry that no future task would miss is still
   cost. Propose removal on utility grounds — and say so in the reason, so the user isn't
   confused by a delete for an entry that is "correct."
9. **Ground rewrites in provenance.** Before MERGE / ABSTRACT / SPLIT, trace each source
   entry back to the ticket, commit, or session that produced it (via its content references
   and `created_at`). This is the same discipline as code-grounding — it prevents a merge from
   silently dropping case-specific context the original author put there on purpose.
10. **Abstract only when omission is safe.** Raising instances to a general rule (the
    "dreaming" move) discards the specifics — do it only when those specifics are truly
    redundant. If any instance carries a real exception, keep it; a flattened rule that hides
    an edge case is worse than three honest instances.
11. **Critics must be adversarial, not agreeable.** The skeptics exist to *kill* proposals, not
    to bless them. A round where every critic passes everything on the first pass is a smell —
    re-read the candidate list yourself for what they missed. Diversity of lens (information-loss
    / evidence / churn) is what makes the panel catch more than a single reviewer would.
12. **Rebuttals are evidence, not opinion.** You may overrule a `KILL` only by citing something
    concrete — a grep result, the entry's own content, provenance. "I think it's fine" is not a
    rebuttal; if you can't produce evidence, the critic wins and the action drops.
13. **Converge honestly; cap hard.** Stop when a round is all-`PASS`, or at round 3. Never keep
    looping to wear the critics down, and never lower the bar just to ship a change. An empty
    survivor set is a perfectly valid outcome — report it as success.

## Executing Surviving Actions

After the loop converges (or hits the round cap), execute every surviving action automatically —
no user selection. Use the MCP tools:

- **DELETE** / **DELETE (low-utility)** -> `mcp__autodev-memory__delete_entry(entry_id, project)`
- **UPDATE** -> `mcp__autodev-memory__update_entry(entry_id, project, content, summary, ...)`
- **MERGE** -> Create new entry with merged content via `mcp__autodev-memory__create_entry()`,
  then delete the source entries
- **ABSTRACT** -> Create new general-rule entry via `mcp__autodev-memory__create_entry()`
  (carry over any exception that still applies), then delete the subsumed instance entries
- **RESCOPE** -> Create new entry in the target scope, then delete the original (scope is
  immutable per entry, so rescoping requires recreate + delete)
- **SPLIT** -> Create 2 new entries, delete the original
- **SIMPLIFY** -> `mcp__autodev-memory__update_entry()` with trimmed content
- **RETYPE/RETAG** -> `mcp__autodev-memory__update_entry()` with corrected type/tags
- **IMPROVE SUMMARY** -> `mcp__autodev-memory__update_entry()` with better summary
- **MERGE TAGS** -> For each affected entry, `mcp__autodev-memory__update_entry()` replacing
  the non-canonical tag with the canonical one in the tags array
- **FIX TAG CASING** -> Same as MERGE TAGS — update each affected entry's tags
- **DROP TAG** -> `mcp__autodev-memory__update_entry()` removing the tag, optionally adding
  a replacement
- **RESOLVE contradiction** -> With no human to arbitrate, the codebase decides: verify both
  entries against the current code and keep/repair the one the code supports, deleting or updating
  the other. If the code is genuinely ambiguous and the skeptics can't break the tie, take **no
  action** — leave both entries and report the unresolved contradiction for a human to settle.

After executing, report what was done. Lead with the loop outcome, then the mutations:

```
Adversarial review: 2 rounds, converged. 12 candidates -> 5 survivors (7 dropped by critics).
Executed 5 surviving actions:
- Deleted 2 stale entries
- Merged 1 pair -> new entry "Postgres Connection Pooling" (id: abc12345)
- Rescoped 1 entry to global
- Simplified 1 entry (1,800 -> 680 tokens)

Dropped by critics (not applied):
- [A4] ABSTRACT 3 timestamp entries -> killed: entry B carries a real exception (server_default
  omitted on the append-only audit table) that the rule would have erased. Evidence: <entry B / commit>.
- [A9] DELETE "<title>" -> killed: evidence skeptic confirmed the function it documents still
  exists at src/foo.py:42; the "removed" justification was wrong.
- ... (5 more)
```

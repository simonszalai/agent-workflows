---
name: compound
description: Save knowledge and learn from what just happened. Handles explicit saves, corrections, review learnings, and workflow improvements.
---

# Compound

Single entry point for persisting knowledge and learning from mistakes. Figures out what to
do based on context:

- **Explicit save** — user says "save this" or provides knowledge to remember → store it
- **Correction** — user corrected Claude → extract and store the correction
- **Improvement analysis** — after a fix, review, or build → analyze gaps and improve workflows

## Usage

```
/compound                              # Analyze recent context, figure out what to do
/compound "always use TEXT not VARCHAR" # Save a specific piece of knowledge
/compound "topic or context"           # Learn from what just happened on this topic
```

## Mode Detection

Compound auto-detects the right mode from context:

| Context | Mode | What Happens |
|---|---|---|
| User provides explicit knowledge | **Save** | Extract, scope, dedup, store |
| User just corrected Claude | **Save** | Extract correction, store |
| User says "save this", "remember this" | **Save** | Extract from conversation, store |
| After review findings resolved | **Improve** | Analyze gaps, store knowledge, update workflows |
| After a bug fix | **Improve** | Analyze root cause, store knowledge |
| Inside `/auto-build` or `/lfg` | **Improve** | Auto-analyze, auto-apply |
| Ambiguous | **Both** | Save explicit knowledge + analyze for improvements |

## Save Mode

### Step 1: Extract Knowledge

Determine what to save from the user's message and conversation context:

| Field | How to Determine |
|---|---|
| `title` | Descriptive — use vocabulary people naturally search for |
| `content` | Self-contained, actionable, includes WHY. Target 200-800 tokens |
| `entry_type` | gotcha, pattern, preference, correction, solution, reference, architecture |
| `summary` | 1-sentence search-friendly summary |
| `tags` | Use the autodev-tags skill procedure |

### Step 2: Store

Use the store procedure in `references/store-procedure.md` to search, dedup, and store.

### Step 3: Report

```
Saved: <action> — "<title>"
Scope: <global | project/repo>
Entry ID: <id>
```

## Improve Mode

### Step 1: Gather Context

1. **Review recent conversation** for what went wrong or what was learned
2. **If review findings exist**: Read resolved review_todo artifacts, classify each
3. **If user correction**: Extract what was wrong vs correct approach
4. **Check existing knowledge** to avoid duplicates:
   - Search memory service via `mcp__autodev-memory__search`
   - Check `AGENTS.md` for existing rules
   - Check relevant skills for existing checklist items

### Step 2: Investigate Root Cause

Before classifying gaps, investigate **why** the mistake happened.

1. **Spawn a researcher or explorer agent** to dig into the actual root cause
2. **Distinguish symptom from cause**: "Prisma rejected the query" is a symptom.
   "The Prisma client caches its DMMF at startup" is the root cause.
3. **Document the full causal chain**

**Skip investigation when**: Root cause is obvious (e.g., user says "don't use X, use Y").

### Step 3: Analyze Gaps

For each learning, determine the upstream gap. See `references/gap-analysis.md` for full
definitions.

| Gap Type           | Question                                          | Fix Target                     |
| ------------------ | ------------------------------------------------- | ------------------------------ |
| Knowledge Gap      | Should this be a documented gotcha/reference?     | Memory service                 |
| Rule Gap           | Is this a simple rule being repeatedly violated?  | `AGENTS.md`                    |
| Plan Gap           | Should planning have researched this?             | `plan` skill                   |
| Build Todos Gap    | Should build todos have found this pattern?       | `create-build-todos` skill     |
| Review Gap         | Should a reviewer have caught this?               | `review/references/*.md`       |
| Workflow Gap       | Is a skill missing a step?                        | `skills/*.md`                  |
| Implementation Gap | One-off mistake, no systemic fix needed           | None                           |

### Step 4: Self-Review for Value

**Apply when ANY are true:**

- Prevents a mistake that wasted significant time or caused a bug
- Documents a non-obvious gotcha that someone would hit again
- Fills a gap in a review checklist for a class of issues
- Captures a pattern that exists but isn't documented
- Addresses a user correction (always high value)
- Security or data integrity concern

**Skip when ALL are true:**

- One-off mistake unlikely to recur
- Already documented elsewhere
- Too vague to be actionable
- Overly specific to one instance
- Trivial

### Step 5: Apply Changes

#### 5a: Store Knowledge

Use the store procedure in `references/store-procedure.md` for each knowledge improvement.

#### 5b: Update Workflow Files

**For AGENTS.md rules** — Append: `- **[Rule name]**: [One-sentence explanation]`

**For skill updates** — Add checklist items: `- [ ] [New check]`

#### 5c: Commit User-Level Changes

If any changes modified **user-level files** (symlinked from `agent-workflows`):

```bash
cd ~/dev/agent-workflows
git add -A
git commit -m "compound: <brief description>"
git push origin main
```

Skip when: only memory service saves, or `$CLAUDE_CODE_REMOTE=true`.

### Step 6: Report

```
## Compound Results

### Applied (N improvements)

| # | Type       | Target                                  | Rationale                        |
|---|------------|-----------------------------------------|----------------------------------|
| 1 | Knowledge  | mem: gotcha "API timeout default"       | Non-obvious timeout default      |
| 2 | Review     | review/references/typescript-standards.md | Class of missing error handling  |

### Skipped (M items)

| # | Type           | Reason                                    |
|---|----------------|-------------------------------------------|
| 1 | Implementation | One-off typo, unlikely to recur           |
```

## 2-Tier Knowledge System

| Tier       | Location                 | Purpose                                 | Always in Context? |
| ---------- | ------------------------ | --------------------------------------- | ------------------ |
| **Tier 1** | `AGENTS.md`              | Critical rules that keep being violated | Yes                |
| **Tier 2** | Memory service (via MCP) | Detailed references, gotchas, solutions | No (searched)      |

### Tier 1 Signals (promote to AGENTS.md)

- User says "you keep getting this wrong" or "you made this mistake again"
- User says "always remember" or "critical rule" or "never forget"
- A gotcha has been violated multiple times
- The rule is simple and can be stated in 1-2 sentences

## Entry Type Mapping

| Source              | Entry Type   |
| ------------------- | ------------ |
| Knowledge gap       | `gotcha`     |
| User correction     | `correction` |
| Pattern discovery   | `pattern`    |
| Solution/fix        | `solution`   |
| Review/workflow gap  | `pattern`    |
| Reference/standard  | `reference`  |
| User preference     | `preference` |

## Relation to Other Skills

| Skill             | Relationship                                                          |
| ----------------- | --------------------------------------------------------------------- |
| `/autodev-retrospect`     | Deep production incident analysis. `/compound` is lighter and broader |
| `/resolve-review` | Fixes review findings. `/compound` learns from those fixes            |
| `/auto-build`     | Calls `/compound` after review resolution                             |
| `/consolidate`    | Audits existing entries. `/compound` adds new ones                    |

---
description: Learn from what just happened and apply improvements to knowledge and workflows.
skills:
  - compound-methodology
  - research-knowledge-base
---

# Compound Command

Analyze what just happened - a fix, a correction, a review - and apply improvements so the same
mistake can't happen again. Updates knowledge docs AND workflow files (skills, agents, commands).

## Usage

```
/compound                    # Analyze recent context, apply improvements
/compound "topic or context" # Compound learnings about a specific topic
```

## When to Use

| Trigger                        | Example                                                     |
| ------------------------------ | ----------------------------------------------------------- |
| User corrected Claude          | "No, do X not Y", "That's wrong", "You should have..."      |
| After a fix is verified        | Bug fix landed, tests pass, want to prevent recurrence      |
| After review findings resolved | `/resolve-review` completed, want systemic improvements     |
| Explicit invocation            | User says "compound", "document this", "save this learning" |
| Inside autonomous workflows    | Called by `/auto-build`, `/lfg`, `/auto-fix` in auto mode   |

## Behavior

All improvements are **self-reviewed and auto-applied**. No user approval step. The AI evaluates
each proposed improvement against the value criteria below, discards low-value noise, and applies
the rest to both local knowledge files and the memory service. A final report shows what was applied and
what was skipped with reasoning.

## What Gets Updated

This is the key difference from the old `/compound` - it updates **everything**, not just
knowledge docs.

| Target                                           | When                               | Example                           |
| ------------------------------------------------ | ---------------------------------- | --------------------------------- |
| `.claude/knowledge/gotchas/`                     | New pitfall discovered             | Gotcha about API timeout behavior |
| `.claude/knowledge/solutions/`                   | Problem resolution worth capturing | How to fix deadlock scenario      |
| `.claude/knowledge/references/`                  | Pattern worth documenting          | Reference for batch processing    |
| `AGENTS.md`                                      | Rule repeatedly violated           | "Always use TEXT not VARCHAR"     |
| `.claude/skills/review-*/SKILL.md`               | Review should have caught this     | New checklist item                |
| `.claude/skills/plan-methodology/SKILL.md`       | Plan should have researched this   | New research req                  |
| `.claude/skills/build-plan-methodology/SKILL.md` | Build todos should have found this | New pattern search                |
| `.claude/commands/*.md`                          | Workflow step was missing          | Add verification step             |

## 2-Tier Knowledge System

| Tier       | Location             | Purpose                                 | Always in Context? |
| ---------- | -------------------- | --------------------------------------- | ------------------ |
| **Tier 1** | `AGENTS.md`          | Critical rules that keep being violated | Yes                |
| **Tier 2** | `.claude/knowledge/` | Detailed references, gotchas, solutions | No (searched)      |

### Tier 1 Signals (promote to AGENTS.md)

- User says "you keep getting this wrong" or "you made this mistake again"
- User says "always remember" or "critical rule" or "never forget"
- A gotcha has been violated multiple times
- The rule is simple and can be stated in 1-2 sentences

### Tier 2 (keep in .claude/knowledge/)

- First occurrence of a gotcha/solution
- Needs detailed code examples
- Reference documentation
- Complex explanation required

## Process

### Step 1: Gather Context

1. **Review recent conversation** for what went wrong or what was learned
2. **If review findings exist** (`review_todos/` with resolved items):
   - Read all resolved findings
   - Classify each: code quality, logic error, missing case, pattern violation
3. **If user correction**: Extract what was wrong and what the correct approach is
4. **Check existing knowledge** to avoid duplicates:
   - Search `.claude/knowledge/` for related docs
   - Check `AGENTS.md` for existing rules
   - Check relevant skills for existing checklist items

### Step 2: Analyze Gaps

For each learning, determine the upstream gap:

| Gap Type           | Question                                         | Fix Target                     |
| ------------------ | ------------------------------------------------ | ------------------------------ |
| Knowledge Gap      | Should this be a documented gotcha/reference?    | `.claude/knowledge/`           |
| Rule Gap           | Is this a simple rule being repeatedly violated? | `AGENTS.md`                    |
| Plan Gap           | Should planning have researched this?            | `plan-methodology` skill       |
| Build Todos Gap    | Should build todos have found this pattern?      | `build-plan-methodology` skill |
| Review Gap         | Should a reviewer have caught this?              | `review-*` skills              |
| Workflow Gap       | Is a command missing a step?                     | `commands/*.md`                |
| Implementation Gap | One-off mistake, no systemic fix needed          | None                           |

### Step 3: Self-Review for Value

For each candidate improvement, evaluate against these criteria. **Apply** if it passes,
**skip** if it doesn't. No user input needed.

**Value criteria — an improvement adds value when ANY of these are true:**

- Prevents a mistake that wasted significant time or caused a bug
- Documents a non-obvious gotcha that someone would hit again
- Fills a gap in a review checklist for a class of issues (not a one-off)
- Captures a pattern that exists but isn't documented anywhere
- Addresses a user correction (always high value — user explicitly said what's wrong)
- Security or data integrity concern

**Skip when ALL of these are true:**

- One-off mistake unlikely to recur
- Already documented elsewhere (duplicate)
- Too vague to be actionable ("be more careful with X")
- Overly specific to one instance (not generalizable)
- Trivial (typo, formatting, naming in one place)

For each improvement, write a one-line rationale: "APPLY: [reason]" or "SKIP: [reason]".

### Step 4: Apply Changes

Apply all improvements that passed self-review:

**For knowledge docs** - Create with YAML frontmatter:

```markdown
---
title: [Descriptive title]
created: YYYY-MM-DD
tags: [tag1, tag2]
---

# [Title]

[Content following template for type]
```

**For AGENTS.md rules** - Append to appropriate section:

```markdown
- **[Rule name]**: [One-sentence explanation]
```

**For skill updates** - Add checklist items or research requirements:

```markdown
- [ ] [New check based on what was learned]
```

**For command updates** - Add workflow steps or verification items.

### Step 4b: Store in Memory Service

For **every** applied improvement, also store in the memory service so it persists across
sessions. The compound-methodology skill has the full API details for storing entries.

Both local files AND memory service must be updated. One is not a substitute for the other —
local files are searchable in context, memory service persists across sessions and environments.

If $MEM_BEARER_TOKEN is unset, skip this step (file-based improvements still apply).

### Step 4c: Commit User-Level Changes

If any applied changes modified **user-level files** (files in `~/.claude/` which are symlinked
to `agent-workflows`), commit and push them so the improvements propagate to all environments:

```bash
cd ~/dev/agent-workflows  # or wherever agent-workflows is checked out
git add -A
git commit -m "compound: <brief description of improvements>"
git push origin main
```

**When to do this:**

- Shared skill updated (e.g., `~/.claude/skills/review-*/SKILL.md`)
- Shared agent updated (e.g., `~/.claude/agents/*.md`)
- Shared command updated (e.g., `~/.claude/commands/*.md`)
- User-level CLAUDE.md updated (e.g., `~/.claude/CLAUDE.md`)

**When NOT to do this:**

- Only project-level files changed (`.claude/knowledge/`, project CLAUDE.md)
- Only memory service saves were made
- Running in cloud (`$CLAUDE_CODE_REMOTE=true`) — file changes are ephemeral anyway

### Step 5: Report

```
## Compound Results

### Applied (N improvements)

| # | Type       | Target                                  | Rationale                        |
|---|------------|-----------------------------------------|----------------------------------|
| 1 | Knowledge  | .claude/knowledge/gotchas/api-timeout.. | Non-obvious timeout default      |
| 2 | Review     | review-typescript-standards/SKILL.md    | Class of missing error handling  |
| 3 | Mem svc    | gotcha: API timeout handling             | Persisted for cloud sessions     |

### Skipped (M items)

| # | Type           | Reason                                    |
|---|----------------|-------------------------------------------|
| 1 | Implementation | One-off typo, unlikely to recur           |
| 2 | Knowledge      | Already documented in gotchas/api-retry.. |
```

## Knowledge Templates

### Solution

```markdown
---
title: [Problem] Resolution
created: YYYY-MM-DD
tags: [area, technology]
---

# [Problem] Resolution

## Problem

[What went wrong]

## Root Cause

[Why it happened]

## Solution

[How it was fixed]

## Prevention

[How to avoid in future]
```

### Gotcha

```markdown
---
title: [Pitfall Title]
created: YYYY-MM-DD
tags: [area, technology]
---

# [Pitfall Title]

## The Gotcha

[What catches people off guard]

## Why It Happens

[Underlying cause]

## The Fix

[How to handle it correctly]
```

### Reference

```markdown
---
title: [Topic] Guide
created: YYYY-MM-DD
tags: [area, technology]
---

# [Topic] Guide

## Overview

[What this covers]

## [Section]

[Content]

## Examples

[Practical examples]
```

## Relation to Other Commands

| Command           | Relationship                                                          |
| ----------------- | --------------------------------------------------------------------- |
| `/retrospect`     | Deep production incident analysis. `/compound` is lighter and broader |
| `/resolve-review` | Fixes review findings. `/compound` learns from those fixes            |
| `/auto-build`     | Calls `/compound` after review resolution                             |
| `/heal-knowledge` | Audits/reorganizes existing knowledge. `/compound` adds new knowledge |

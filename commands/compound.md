---
description: Learn from what just happened and apply improvements to knowledge and workflows.
skills:
  - compound-methodology
---

# Compound Command

Analyze what just happened - a fix, a correction, a review - and apply improvements so the same
mistake can't happen again. Investigates root causes, stores knowledge in the memory service via
MCP, and updates workflow files (skills, agents, commands).

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
| Inside autonomous workflows    | Called by `/auto-build` and `/lfg` in auto mode             |

## Behavior

All improvements are **self-reviewed and auto-applied**. No user approval step. The AI evaluates
each proposed improvement against the value criteria below, discards low-value noise, and applies
the rest to the memory service and workflow files. A final report shows what was applied and what
was skipped with reasoning.

## What Gets Updated

| Target                                           | When                                | Example                           |
| ------------------------------------------------ | ----------------------------------- | --------------------------------- |
| **Memory service** (via MCP)                     | Every applied knowledge improvement | Gotcha, solution, pattern, etc.   |
| `AGENTS.md`                                      | Rule repeatedly violated            | "Always use TEXT not VARCHAR"      |
| `.claude/skills/review-*/SKILL.md`               | Review should have caught this      | New checklist item                 |
| `.claude/skills/plan-methodology/SKILL.md`       | Plan should have researched this    | New research req                   |
| `.claude/skills/build-plan-methodology/SKILL.md` | Build todos should have found this  | New pattern search                 |
| `.claude/commands/*.md`                           | Workflow step was missing           | Add verification step              |

**Knowledge is NOT stored in local `.claude/knowledge/` files.** The memory service is the single
source of truth for gotchas, solutions, references, patterns, and corrections.

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

### Tier 2 (keep in memory service)

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
   - Search memory service via `mcp__autodev-memory__search` for related entries
   - Check `AGENTS.md` for existing rules
   - Check relevant skills for existing checklist items

### Step 2: Investigate Root Cause

Before classifying gaps, investigate **why** the mistake happened. The conversation often shows
symptoms but not the underlying cause.

1. **Spawn a researcher or explorer agent** to dig into the actual root cause:
   - Read relevant source code, configs, and dependencies
   - Check documentation for the technology involved
   - Look at git history for when/how patterns were established
   - Test hypotheses about why the behavior occurred
2. **Distinguish symptom from cause**: "Prisma rejected the query" is a symptom.
   "The Prisma client caches its DMMF at startup and doesn't pick up schema changes via HMR"
   is the root cause.
3. **Document the full causal chain**: What triggered it -> what went wrong at each step ->
   what the actual fix is. This is what gets stored in the memory service.

**Skip investigation when**: The root cause is already obvious from context (e.g., user says
"don't use X, use Y" — no investigation needed, the correction is self-explanatory).

### Step 3: Analyze Gaps

For each learning, determine the upstream gap:

| Gap Type           | Question                                          | Fix Target                     |
| ------------------ | ------------------------------------------------- | ------------------------------ |
| Knowledge Gap      | Should this be a documented gotcha/reference?     | Memory service                 |
| Rule Gap           | Is this a simple rule being repeatedly violated?  | `AGENTS.md`                    |
| Plan Gap           | Should planning have researched this?             | `plan-methodology` skill       |
| Build Todos Gap    | Should build todos have found this pattern?       | `build-plan-methodology` skill |
| Review Gap         | Should a reviewer have caught this?               | `review-*` skills              |
| Workflow Gap       | Is a command missing a step?                      | `commands/*.md`                |
| Implementation Gap | One-off mistake, no systemic fix needed           | None                           |

### Step 4: Self-Review for Value

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

### Step 5: Apply Changes

#### 5a: Store Knowledge in Memory Service (MCP)

For every applied knowledge improvement, store via `mcp__autodev-memory__add_entry`.

**Before adding**, search for duplicates with `mcp__autodev-memory__search`. If a related entry
exists, use `mcp__autodev-memory__update_entry` to supersede or append instead of creating a
duplicate.

**Required parameters:**

| Parameter        | Description                                                   |
| ---------------- | ------------------------------------------------------------- |
| `project`        | From `<!-- mem:project=X -->` in CLAUDE.md                    |
| `title`          | 1-sentence search-friendly summary                            |
| `content`        | Full knowledge content (200-800 tokens target)                |
| `entry_type`     | `gotcha`, `pattern`, `correction`, `solution`, `reference`    |
| `summary`        | 1-sentence summary                                            |
| `tags`           | Array of topical tags for semantic search (e.g., `["css", "flexbox"]`) |
| `source`         | `captured`                                                    |
| `caller_context` | JSON with `skill`, `reason`, `action_rationale`, `trigger`    |

**Entry type mapping:**

| Gap Type            | Entry Type   |
| ------------------- | ------------ |
| Knowledge gap       | `gotcha`     |
| User correction     | `correction` |
| Pattern discovery   | `pattern`    |
| Solution/fix        | `solution`   |
| Review/workflow gap  | `pattern`    |
| Reference/standard  | `reference`  |

#### 5b: Update Workflow Files

**For AGENTS.md rules** — Append to appropriate section:

```markdown
- **[Rule name]**: [One-sentence explanation]
```

**For skill updates** — Add checklist items or research requirements:

```markdown
- [ ] [New check based on what was learned]
```

**For command updates** — Add workflow steps or verification items.

#### 5c: Commit User-Level Changes

If any applied changes modified **user-level files** (files in `~/.claude/` which are symlinked
to `agent-workflows`), commit and push them so the improvements propagate to all environments:

```bash
cd ~/dev/agent-workflows
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

- Only memory service saves were made
- Running in cloud (`$CLAUDE_CODE_REMOTE=true`) — file changes are ephemeral anyway

### Step 6: Report

```
## Compound Results

### Applied (N improvements)

| # | Type       | Target                                  | Rationale                        |
|---|------------|-----------------------------------------|----------------------------------|
| 1 | Knowledge  | mem: gotcha "API timeout default"       | Non-obvious timeout default      |
| 2 | Review     | review-typescript-standards/SKILL.md    | Class of missing error handling  |
| 3 | Rule       | AGENTS.md                               | Repeated violation, promoted     |

### Skipped (M items)

| # | Type           | Reason                                    |
|---|----------------|-------------------------------------------|
| 1 | Implementation | One-off typo, unlikely to recur           |
| 2 | Knowledge      | Already in memory service (key: api-retry)|
```

## Relation to Other Commands

| Command           | Relationship                                                          |
| ----------------- | --------------------------------------------------------------------- |
| `/retrospect`     | Deep production incident analysis. `/compound` is lighter and broader |
| `/resolve-review` | Fixes review findings. `/compound` learns from those fixes            |
| `/auto-build`     | Calls `/compound` after review resolution                             |
| `/heal-knowledge` | Audits/reorganizes existing knowledge. `/compound` adds new knowledge |

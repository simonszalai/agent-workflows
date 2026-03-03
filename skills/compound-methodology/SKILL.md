---
name: compound-methodology
description: Gap analysis and improvement methodology for learning from fixes, corrections, and reviews. Used by /compound command.
---

# Compound Methodology

Systematic analysis of what went wrong and targeted improvements to prevent recurrence. Applied
after fixes, user corrections, and review resolutions.

## Purpose

When something goes wrong - a bug, a user correction, a review finding - the goal is NOT just
to fix it, but to understand:

1. **Which upstream stage failed** - Where should this have been caught earlier?
2. **Why it failed** - What was missing from that stage?
3. **How to prevent recurrence** - What to add to workflows, knowledge, or prompts?

## Input Sources

The compound methodology handles multiple input types:

| Source                   | How to Analyze                             |
| ------------------------ | ------------------------------------------ |
| User correction          | Extract what was wrong vs correct approach |
| Resolved review findings | Read review_todos/ with status: resolved   |
| Bug fix                  | Examine what the fix changed and why       |
| Explicit learning        | User describes what should be documented   |

## Gap Categories

Every learning stems from one of these upstream gaps:

### 1. Knowledge Gap

**Symptoms:**

- A gotcha that should have been documented
- Pattern exists elsewhere in codebase but wasn't followed
- Solution to known issue wasn't captured

**Fix targets:**

- `.claude/knowledge/gotchas/` - Document the pitfall
- `.claude/knowledge/references/` - Document the pattern
- `.claude/knowledge/solutions/` - Document the resolution
- `AGENTS.md` - Add rule if repeatedly violated

### 2. Plan Gap

**Symptoms:**

- Requirement was ambiguous or incomplete
- Edge case wasn't identified during planning
- Constraint wasn't researched

**Fix targets:**

- `.claude/skills/plan-methodology/SKILL.md` - Add research requirement
- `.claude/knowledge/gotchas/` - Document the missed constraint

### 3. Build Todos Gap

**Symptoms:**

- Implementation step was missing or unclear
- Should have referenced existing pattern
- Verification step wasn't included

**Fix targets:**

- `.claude/skills/build-plan-methodology/SKILL.md` - Add research step
- `.claude/knowledge/references/` - Document the pattern to reference

### 4. Review Gap

**Symptoms:**

- Issue should have been caught by a specific review dimension
- Review skill doesn't check for this type of issue
- Review checklist is incomplete

**Fix targets:**

- `.claude/skills/review-*/SKILL.md` - Add checklist item
- `.claude/skills/review/SKILL.md` - Add new review dimension

### 5. Workflow Gap

**Symptoms:**

- A command is missing a verification step
- A workflow doesn't handle a specific scenario
- Process ordering is wrong

**Fix targets:**

- `.claude/commands/*.md` - Add or modify workflow steps

### 6. Implementation Gap (Not Systemic)

**Symptoms:**

- One-off mistake, not a pattern
- Clear code quality issue
- Already well-documented but not followed

**Fix targets:**

- None (the fix itself is sufficient)
- Consider AGENTS.md rule if pattern repeats

## Analysis Process

### Step 1: Classify the Learning

For each item to analyze, determine:

1. **What type of issue?**
   - Code quality (style, naming, structure)
   - Logic error (wrong behavior)
   - Missing case (edge case, error handling)
   - Pattern violation (didn't follow existing conventions)
   - Security/performance (vulnerability, inefficiency)
   - User correction (Claude did X, should have done Y)

2. **Which upstream gap?**
   - Could plan have identified this? → Plan Gap
   - Should build todos have specified this? → Build Todos Gap
   - Is this a known gotcha? → Knowledge Gap
   - Should review prompt check for this? → Review Gap
   - Is a workflow step missing? → Workflow Gap
   - One-off mistake? → Implementation Gap (no systemic fix)

3. **What's the fix target?**
   - Identify specific file and section to update
   - Draft the addition (checklist item, gotcha doc, etc.)

### Step 2: Aggregate and Deduplicate

Multiple items may point to the same gap. Consolidate:

- Group by gap category
- Identify root cause patterns
- Create single improvement for related items
- Check existing knowledge/skills to avoid duplicates

### Step 3: Self-Review for Value

Evaluate each candidate improvement autonomously. No user approval needed — the AI decides
what adds value and what doesn't.

**Value criteria — APPLY when ANY of these are true:**

| Criterion                  | Example                                              |
| -------------------------- | ---------------------------------------------------- |
| Prevented wasted time      | Spent 30min debugging a known asyncpg quirk          |
| Non-obvious gotcha         | TEXT vs VARCHAR in Postgres, timeout defaults         |
| Class of issues            | "All external API calls need timeout handling"        |
| Undocumented pattern       | Pattern used in 5 files but never written down       |
| User correction            | User explicitly said what's wrong — always high value |
| Security/data integrity    | Missing auth check, SQL injection risk               |

**Skip criteria — SKIP when ALL of these are true:**

| Criterion                   | Example                                           |
| --------------------------- | ------------------------------------------------- |
| One-off, won't recur        | Typo in a variable name                           |
| Already documented          | Gotcha already exists in knowledge base            |
| Too vague to be actionable  | "Be more careful with error handling"              |
| Not generalizable           | Specific to one function, no broader lesson        |
| Trivial                     | Formatting, single naming choice                   |

**For each candidate, write a one-line verdict:**

- `APPLY: [specific reason this adds value]`
- `SKIP: [specific reason this is noise]`

### Step 4: Apply Improvements (Dual-Write)

For each improvement that passed self-review, write to BOTH local files AND OpenMemory.
One is not a substitute for the other.

#### 4a: Local Knowledge Files

**Knowledge docs** — Create with YAML frontmatter:

```markdown
---
title: [Descriptive title]
created: YYYY-MM-DD
tags: [tag1, tag2]
---

# [Title]

[Content following template for type]
```

**AGENTS.md rules** — Append to appropriate section:

```markdown
- **[Rule name]**: [One-sentence explanation]
```

**Skill updates** — Add checklist items or research requirements:

```markdown
- [ ] [New check based on what was learned]
```

**Command updates** — Add workflow steps or verification items.

#### 4b: OpenMemory

Store every applied improvement in OpenMemory for cross-session persistence:

| Gap Type            | Memory Pattern                                                        |
| ------------------- | --------------------------------------------------------------------- |
| Knowledge gap       | `add-memory(memory_types: ["debug"], project_id=...)`                 |
| User correction     | `add-memory(memory_types: ["user_preference"], user_preference=true)` |
| Pattern discovery   | `add-memory(memory_types: ["implementation"], project_id=...)`        |
| Review/workflow gap | `add-memory(memory_types: ["implementation"], project_id=...)`        |

If OpenMemory MCP is unavailable, skip this step (file-based improvements still apply).

### Step 5: Commit User-Level Changes

If any applied improvements modified **user-level files** (files resolved via `~/.claude/`
symlinks to `agent-workflows`), commit and push so improvements propagate to all environments:

1. `cd ~/dev/agent-workflows` (or wherever agent-workflows is checked out)
2. `git add` the changed files
3. `git commit -m "compound: <brief description>"`
4. `git push origin main`

**Applies to:** Shared skills, agents, commands, user-level CLAUDE.md.
**Does NOT apply to:** Project `.claude/knowledge/`, project CLAUDE.md, OpenMemory-only saves.
**Skip in cloud:** `$CLAUDE_CODE_REMOTE=true` means file changes are ephemeral anyway.

## Quality Checks

Before finalizing improvements:

- [ ] No duplicate knowledge docs (search existing first)
- [ ] Improvement is specific and actionable
- [ ] Targets the root cause, not the symptom
- [ ] Written concisely (one-liners preferred for checklists)
- [ ] Skill/command updates don't break existing functionality
- [ ] Both local file AND OpenMemory updated for each improvement

## Example Analysis

**User correction:** "No, don't use VARCHAR - always use TEXT for string columns in Postgres"

**Analysis:**

- Type: Pattern violation (wrong column type)
- Upstream gap: Knowledge Gap + possible Rule Gap
- Check: Is this already in CLAUDE.md? → Yes, "Always use TEXT instead of VARCHAR"
- Self-review: `APPLY: User correction, and rule exists but was violated — needs promotion`

**Improvement:**

1. Add to AGENTS.md: "Always use TEXT for string columns - never VARCHAR (see CLAUDE.md)"
2. Store in OpenMemory as user_preference

---

**Review finding:** "Missing error handling for API timeout" (3 similar findings)

**Analysis:**

- Type: Missing case (error handling) - 3 occurrences
- Upstream gap: Plan Gap + Knowledge Gap
- Check: Any gotcha for API timeout? → No
- Self-review: `APPLY: 3 occurrences of same gap, class of issues, not documented`

**Improvements:**

1. Create gotcha: `.claude/knowledge/gotchas/api-timeout-handling-YYYYMMDD.md`
2. Add to plan-methodology: "When planning external API integrations, research timeout/retry
   requirements"
3. Add to review-typescript-standards: "[ ] External API calls have timeout and error handling"
4. Store all three in OpenMemory with appropriate memory types

---

**One-off typo fix:** Variable named `reponse` instead of `response`

**Analysis:**

- Type: Code quality (typo)
- Upstream gap: Implementation Gap
- Self-review: `SKIP: One-off typo, trivial, not generalizable`

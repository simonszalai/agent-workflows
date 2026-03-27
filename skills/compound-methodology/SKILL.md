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

- Memory service via **autodev-add-memory** skill — search, decide, store
- `AGENTS.md` - Add rule if repeatedly violated
- **The codebase itself** - If the gotcha identifies existing violations, fix them (or create a
  work item). Documenting a rule without fixing the known violation means the bug will recur.

### 2. Plan Gap

**Symptoms:**

- Requirement was ambiguous or incomplete
- Edge case wasn't identified during planning
- Constraint wasn't researched

**Fix targets:**

- `.claude/skills/plan-methodology/SKILL.md` - Add research requirement
- Memory service — store the missed constraint as a gotcha

### 3. Build Todos Gap

**Symptoms:**

- Implementation step was missing or unclear
- Should have referenced existing pattern
- Verification step wasn't included

**Fix targets:**

- `.claude/skills/build-plan-methodology/SKILL.md` - Add research step
- Memory service — store the pattern as a reference

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
   - Could plan have identified this? -> Plan Gap
   - Should build todos have specified this? -> Build Todos Gap
   - Is this a known gotcha? -> Knowledge Gap
   - Should review prompt check for this? -> Review Gap
   - Is a workflow step missing? -> Workflow Gap
   - One-off mistake? -> Implementation Gap (no systemic fix)

3. **What's the fix target?**
   - Identify specific file and section to update
   - Draft the addition (checklist item, memory entry, etc.)

### Step 2: Investigate Root Cause

Before aggregating and applying fixes, investigate **why** the mistake happened. The
conversation often shows symptoms but not the underlying cause.

**When to investigate:**

- The root cause is not obvious from the conversation alone
- Multiple failed attempts suggest a deeper misunderstanding
- The fix involved trial-and-error rather than a direct solution

**How to investigate:**

1. **Spawn a researcher or explorer agent** to dig into the actual root cause:
   - Read relevant source code, configs, and dependencies
   - Check documentation for the technology involved
   - Look at git history for when/how patterns were established
   - Test hypotheses about why the behavior occurred
2. **Distinguish symptom from cause**: "Prisma rejected the query" is a symptom.
   "The Prisma client caches its DMMF at startup and doesn't pick up schema changes via HMR"
   is the root cause.
3. **Document the full causal chain**: What triggered it -> what went wrong at each step ->
   what the actual fix is. This chain becomes the knowledge entry content.

**Skip investigation when**: The root cause is already obvious (e.g., a user correction like
"don't use X, use Y" is self-explanatory and needs no further research).

### Step 3: Aggregate and Deduplicate

Multiple items may point to the same gap. Consolidate:

- Group by gap category
- Identify root cause patterns
- Create single improvement for related items
- Check memory service via `mcp__autodev-memory__search` to avoid duplicates

### Step 4: Self-Review for Value

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
| Already documented          | Entry already exists in memory service             |
| Too vague to be actionable  | "Be more careful with error handling"              |
| Not generalizable           | Specific to one function, no broader lesson        |
| Trivial                     | Formatting, single naming choice                   |

**For each candidate, write a one-line verdict:**

- `APPLY: [specific reason this adds value]`
- `SKIP: [specific reason this is noise]`

### Step 5: Apply Improvements

#### 5a: Store Knowledge in Memory Service (MCP)

For every applied knowledge improvement, use the **autodev-add-memory** skill to store it.
Load that skill and follow its search → decide → act procedure, passing:

- `source`: `"captured"`
- `caller_context.skill`: `"compound"`
- `caller_context.trigger`: `"user correction"` or `"review finding"` etc.

The autodev-add-memory skill handles searching for related entries, deciding whether to
create new / append / supersede / skip, and executing the action.

**caller_context fields:**

- `skill`: Always `"compound"`
- `reason`: Extensive explanation of WHY this knowledge is worth persisting
- `action_rationale`: Why `new` vs `supersede` vs `append` was chosen
- `trigger`: What triggered the persistence (e.g., "user correction", "review finding",
  "bug fix investigation")

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

### Step 6: Commit User-Level Changes

If any applied improvements modified **user-level files** (files resolved via `~/.claude/`
symlinks to `agent-workflows`), commit and push so improvements propagate to all environments:

1. `cd ~/dev/agent-workflows` (or wherever agent-workflows is checked out)
2. `git add` the changed files
3. `git commit -m "compound: <brief description>"`
4. `git push origin main`

**Applies to:** Shared skills, agents, commands, user-level CLAUDE.md.
**Does NOT apply to:** Memory-service-only saves, project CLAUDE.md.
**Skip in cloud:** `$CLAUDE_CODE_REMOTE=true` means file changes are ephemeral anyway.

## Quality Checks

Before finalizing improvements:

- [ ] No duplicate entries (searched memory service first)
- [ ] Improvement is specific and actionable
- [ ] Targets the root cause, not the symptom
- [ ] Root cause was investigated when not obvious from conversation
- [ ] Written concisely (one-liners preferred for checklists)
- [ ] Skill/command updates don't break existing functionality
- [ ] Knowledge stored in memory service via MCP tool

## Example Analysis

**User correction:** "No, don't use VARCHAR - always use TEXT for string columns in Postgres"

**Investigation:** Skipped — correction is self-explanatory.

**Analysis:**

- Type: Pattern violation (wrong column type)
- Upstream gap: Knowledge Gap + possible Rule Gap
- Check: Is this already in CLAUDE.md? -> Yes, "Always use TEXT instead of VARCHAR"
- Self-review: `APPLY: User correction, and rule exists but was violated — needs promotion`

**Improvement:**

1. Add to AGENTS.md: "Always use TEXT for string columns - never VARCHAR (see CLAUDE.md)"
2. Store in memory via autodev-add-memory skill as type `correction`

---

**Bug fix: Prisma schema change not picked up at runtime**

**Investigation:** Spawned explorer agent. Found that:
- The Prisma schema had `deleted_at` and `prisma generate` ran successfully
- The generated client files contained `deleted_at` in the DMMF
- But the running dev server rejected `deleted_at` in WHERE clauses
- Root cause: Vite's HMR does not re-import the Prisma client binary — the in-memory DMMF
  remains stale until the dev server process is fully restarted

**Analysis:**

- Type: Missing case (dev tooling interaction)
- Upstream gap: Knowledge Gap — non-obvious interaction between Prisma generate and Vite HMR
- Self-review: `APPLY: Wasted multiple rounds, non-obvious, will recur on any schema change`

**Improvement:**

1. Store in memory service as `gotcha` with key `prisma-schema-change-dev-server-restart`
2. Content documents the full causal chain and the fix (restart dev server after generate)

---

**One-off typo fix:** Variable named `reponse` instead of `response`

**Investigation:** Skipped — trivial.

**Analysis:**

- Type: Code quality (typo)
- Upstream gap: Implementation Gap
- Self-review: `SKIP: One-off typo, trivial, not generalizable`

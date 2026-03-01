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

### Step 3: Prioritize

| Priority | Criteria                   | Action                                     |
| -------- | -------------------------- | ------------------------------------------ |
| **P1**   | 3+ items from same gap     | Apply immediately                          |
| **P1**   | Security or data integrity | Apply immediately                          |
| **P2**   | 2 items from same gap      | Apply                                      |
| **P2**   | Significant time wasted    | Apply                                      |
| **P3**   | Single item, low impact    | Apply knowledge doc, skip workflow updates |

### Step 4: Apply Improvements

For each prioritized improvement:

1. **Knowledge docs** - Create with YAML frontmatter
2. **Skill updates** - Add to checklist or research requirements
3. **AGENTS.md rules** - Only for repeatedly violated simple rules
4. **Command updates** - Add workflow steps or verification items

### Step 5: Store in OpenMemory

After applying file-based improvements, also store the learning in OpenMemory so it persists
across sessions (critical for cloud environments where file changes are ephemeral):

**For knowledge/debug learnings (project facts):**

```
add-memory(
    title="[Gap Type]: [Brief description]",
    content="[What went wrong, root cause, and prevention strategy]",
    metadata={memory_types: ["debug"]},
    project_id="<from CLAUDE.md>"
)
```

**For implementation pattern discoveries:**

```
add-memory(
    title="Pattern: [Description]",
    content="[Pattern details, where it applies, how to follow it]",
    metadata={memory_types: ["implementation"]},
    project_id="<from CLAUDE.md>"
)
```

**For user preference corrections:**

```
add-memory(
    title="[Preference Type]: [Description]",
    content="[What the user corrected and the correct approach]",
    metadata={memory_types: ["user_preference"]},
    user_preference=true
)
```

If OpenMemory MCP is unavailable, skip this step (file-based improvements still apply).

### Step 6: Commit User-Level Changes

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

## Example Analysis

**User correction:** "No, don't use VARCHAR - always use TEXT for string columns in Postgres"

**Analysis:**

- Type: Pattern violation (wrong column type)
- Upstream gap: Knowledge Gap + possible Rule Gap
- Check: Is this already in CLAUDE.md? → Yes, "Always use TEXT instead of VARCHAR"
- Conclusion: Rule exists but was violated → promote to AGENTS.md for project-level emphasis

**Improvement:**

1. Add to AGENTS.md: "Always use TEXT for string columns - never VARCHAR (see CLAUDE.md)"

---

**Review finding:** "Missing error handling for API timeout" (3 similar findings)

**Analysis:**

- Type: Missing case (error handling) - 3 occurrences
- Upstream gap: Plan Gap + Knowledge Gap
- Check: Any gotcha for API timeout? → No

**Improvements:**

1. Create gotcha: `.claude/knowledge/gotchas/api-timeout-handling-YYYYMMDD.md`
2. Add to plan-methodology: "When planning external API integrations, research timeout/retry
   requirements"
3. Add to review-typescript-standards: "[ ] External API calls have timeout and error handling"

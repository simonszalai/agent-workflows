# Gap Categories — Detailed Reference

Every learning stems from one of these upstream gaps. Use this reference to classify issues
and determine the correct fix target.

## 1. Knowledge Gap

**Symptoms:**

- A gotcha that should have been documented
- Pattern exists elsewhere in codebase but wasn't followed
- Solution to known issue wasn't captured

**Fix targets:**

- Memory service via **compound** store procedure (see `store-procedure.md`) — search, decide, store
- Promote to Tier 2 if the rule should always apply: `mcp__autodev-memory__star_entry`
- `CLAUDE.md` (auto-loaded by Claude Code) — only if the rule is a project-level convention,
  not self-contained knowledge. Prefer Tier 2 for gotchas; reserve CLAUDE.md for stack/branch/
  repo conventions
- **The codebase itself** - If the gotcha identifies existing violations, fix them (or create a
  work item). Documenting a rule without fixing the known violation means the bug will recur.

## 2. Workflow Gap

**Symptoms:**

- A command is missing a verification step
- A workflow doesn't handle a specific scenario
- Process ordering is wrong

**Fix targets:**

- `skills/*/SKILL.md` - Add or modify workflow steps in the relevant skill

## 3. Implementation Gap (Not Systemic)

**Symptoms:**

- One-off mistake, not a pattern
- Clear code quality issue
- Already well-documented but not followed

**Fix targets:**

- None (the fix itself is sufficient)
- If the pattern repeats: star the relevant memory entry, or — only if it's a project
  convention — add to `CLAUDE.md`

## Classification Checklist

For each item to analyze, determine:

1. **What type of issue?**
   - Code quality (style, naming, structure)
   - Logic error (wrong behavior)
   - Missing case (edge case, error handling)
   - Pattern violation (didn't follow existing conventions)
   - Security/performance (vulnerability, inefficiency)
   - User correction (Claude did X, should have done Y)

2. **Which upstream gap?**
   - Is this a known gotcha? -> Knowledge Gap
   - Is a workflow/skill step or rule missing? -> Workflow Gap
   - One-off mistake? -> Implementation Gap (no systemic fix)

3. **What's the fix target?**
   - Identify specific file and section to update
   - Draft the addition (checklist item, memory entry, etc.)

## Examples

### User correction: "No, don't use VARCHAR - always use TEXT for string columns in Postgres"

**Investigation:** Skipped — correction is self-explanatory.

**Analysis:**

- Type: Pattern violation (wrong column type)
- Upstream gap: Knowledge Gap + possible Rule Gap
- Check: Is this already in CLAUDE.md or as a starred memory? -> Yes, exists as a memory
  entry but is unstarred — needs promotion since it keeps being violated
- Self-review: `APPLY: User correction, and rule exists but was violated — needs promotion`

**Improvement:**

1. Star the existing memory entry via `mcp__autodev-memory__star_entry` so it auto-injects
   into every session
2. Add or update the entry content to capture this correction (type `correction`)

(Use CLAUDE.md only if "use TEXT not VARCHAR" is the kind of project-wide schema convention
that belongs alongside stack/branch facts. For most cases, the starred memory is enough.)

---

### Bug fix: Prisma schema change not picked up at runtime

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
3. Consider starring if the same trap is hit again — keep it Tier 3 for now

---

### One-off typo fix: Variable named `reponse` instead of `response`

**Investigation:** Skipped — trivial.

**Analysis:**

- Type: Code quality (typo)
- Upstream gap: Implementation Gap
- Self-review: `SKIP: One-off typo, trivial, not generalizable`

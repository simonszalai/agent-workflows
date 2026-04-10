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
- `AGENTS.md` - Add rule if repeatedly violated
- **The codebase itself** - If the gotcha identifies existing violations, fix them (or create a
  work item). Documenting a rule without fixing the known violation means the bug will recur.

## 2. Plan Gap

**Symptoms:**

- Requirement was ambiguous or incomplete
- Edge case wasn't identified during planning
- Constraint wasn't researched

**Fix targets:**

- `.claude/skills/plan/SKILL.md` - Add research requirement
- Memory service — store the missed constraint as a gotcha

## 3. Build Todos Gap

**Symptoms:**

- Implementation step was missing or unclear
- Should have referenced existing pattern
- Verification step wasn't included

**Fix targets:**

- `.claude/skills/create-build-todos/SKILL.md` - Add research step
- Memory service — store the pattern as a reference

## 4. Review Gap

**Symptoms:**

- Issue should have been caught by a specific review dimension
- Review skill doesn't check for this type of issue
- Review checklist is incomplete

**Fix targets:**

- `.claude/skills/review-*/SKILL.md` - Add checklist item
- `.claude/skills/review/SKILL.md` - Add new review dimension

## 5. Workflow Gap

**Symptoms:**

- A command is missing a verification step
- A workflow doesn't handle a specific scenario
- Process ordering is wrong

**Fix targets:**

- `.claude/commands/*.md` - Add or modify workflow steps

## 6. Implementation Gap (Not Systemic)

**Symptoms:**

- One-off mistake, not a pattern
- Clear code quality issue
- Already well-documented but not followed

**Fix targets:**

- None (the fix itself is sufficient)
- Consider AGENTS.md rule if pattern repeats

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
   - Could plan have identified this? -> Plan Gap
   - Should build todos have specified this? -> Build Todos Gap
   - Is this a known gotcha? -> Knowledge Gap
   - Should review prompt check for this? -> Review Gap
   - Is a workflow step missing? -> Workflow Gap
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
- Check: Is this already in CLAUDE.md? -> Yes, "Always use TEXT instead of VARCHAR"
- Self-review: `APPLY: User correction, and rule exists but was violated — needs promotion`

**Improvement:**

1. Add to AGENTS.md: "Always use TEXT for string columns - never VARCHAR (see CLAUDE.md)"
2. Store in memory via compound store procedure (see `store-procedure.md`) as type `correction`

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

---

### One-off typo fix: Variable named `reponse` instead of `response`

**Investigation:** Skipped — trivial.

**Analysis:**

- Type: Code quality (typo)
- Upstream gap: Implementation Gap
- Self-review: `SKIP: One-off typo, trivial, not generalizable`

---
name: build-plan-methodology
description: Deep research methodology for creating detailed build todos. Searches knowledge base, codebase, and git history exhaustively.
---

# Build Plan Methodology

Standards for creating detailed implementation steps (`build_todos/`) from an approved `plan.md`.
This methodology emphasizes **deep research** to ensure all existing patterns and rules are
discovered and followed.

## Output Template

Use the template at `templates/build-todo.md` for each build step.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Research Requirements

**This is the core of build planning.** Before writing any build todo, you MUST thoroughly
research each of these areas:

### 1. Knowledge Base Research (REQUIRED)

Search ALL relevant knowledge:

```bash
# Find all references
ls .claude/knowledge/references/
grep -r "<relevant-keyword>" .claude/knowledge/references/

# Find all gotchas (CRITICAL - these are known pitfalls)
ls .claude/knowledge/gotchas/
grep -r "<relevant-keyword>" .claude/knowledge/gotchas/

# Find past solutions
ls .claude/knowledge/solutions/
grep -r "<relevant-keyword>" .claude/knowledge/solutions/
```

**Document in each build todo:**

- Which gotchas apply to this step
- Which standards must be followed
- Which past solutions inform this step

### 2. Codebase Pattern Research (REQUIRED)

Find existing implementations to follow:

```bash
# Find similar code patterns
grep -r "pattern" src/

# Find how similar features were implemented
git log --all --oneline --grep="similar-feature"

# Find error handling patterns in affected area
grep -r "try:" src/path/to/affected/

# Find test patterns for this type of code
grep -r "def test_\|describe(" tests/
```

**Document in each build todo:**

- Patterns that MUST be followed (with file:line references)
- Conventions specific to the affected area
- Test patterns to match

### 3. Git History Research (REQUIRED)

Understand why code exists as it does:

```bash
# File evolution
git log --follow --oneline -20 <file>

# Code origin
git blame -w -C -C -C <file>

# Related changes
git log -S"keyword" --oneline

# Past issues in this area
git log --grep="fix" -- <path>
```

**Document in each build todo:**

- Why affected code was written this way
- Past issues that inform this implementation
- Recent changes that might conflict

### 4. CLAUDE.md Compliance (REQUIRED)

Check project rules:

- Read CLAUDE.md for any rules that apply
- Document which rules affect this step
- Note specific requirements (e.g., "no Any types", "use TEXT not VARCHAR")

### 5. Memory Service Research (REQUIRED)

The memory service hooks auto-inject relevant knowledge as `additionalContext` on every
prompt and agent dispatch. Check the injected context first. For targeted queries beyond
what was auto-injected:

```bash
curl -sf -X POST \
  -H "Authorization: Bearer $MEM_BEARER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"searches": [
    {"query": "<feature area> implementation patterns"},
    {"query": "<technology/area> gotchas pitfalls"}
  ], "project": "<project>", "limit": 5}' \
  "$MEM_SERVICE_URL/search"
```

**Document in each build todo:**

- Relevant memories found (auto-injected or explicitly searched)
- User preferences that apply to this step
- Past debug learnings for this area

If $MEM_BEARER_TOKEN is unset, mention once and continue with other research.

## Build Todo Creation Process

1. **Read plan.md** - Understand the architecture
2. **Identify steps** - Break into independently completable units
3. **Pre-flight knowledge base audit (MANDATORY):**
   a. List ALL files in `.claude/knowledge/gotchas/` and `.claude/knowledge/references/`
   b. For each build todo's affected area (database, migrations, encryption, API, etc.),
   search for matching gotchas with grep
   c. Read the most relevant 2-3 gotchas/references in full
   d. If a build todo involves database schema changes, ALWAYS read
   `references/database-migrations-*.md` and ALL `gotchas/migration-*.md` files
   e. Document findings in each build todo's "Discovered Patterns" section
4. **For each step:**
   a. Research knowledge base for gotchas/standards
   b. Research codebase for patterns to follow
   c. Research git history for context
   d. Check CLAUDE.md for applicable rules
   e. Write build todo with all findings

## Synthesis Guidelines

### Discovered Patterns Section

Every build todo MUST include a "Discovered Patterns" section:

```markdown
## Discovered Patterns

**From knowledge base:**

- `.claude/knowledge/gotchas/xxx.md`: [How it applies]
- `.claude/knowledge/references/xxx.md`: [Standard to follow]

**From codebase:**

- `src/path/file.py:123`: [Pattern to follow]
- `src/path/other.py:45`: [Convention to match]

**From git history:**

- Commit `abc123`: [Why this matters]
- Past issue: [What to avoid]

**From CLAUDE.md:**

- [Specific rule and how to comply]

**From memory service (auto-injected or explicit search):**

- [Entry title]: [How it informs this step]
```

### Implementation Details Section

After patterns, write implementation that:

- Explicitly follows each discovered pattern
- References pattern sources in comments
- Matches existing code style exactly

### Files to Modify Section

Be specific:

- List exact files to modify
- Estimate lines changed per file
- Note if creating new files

## Elimination Build Todos (CRITICAL)

When the plan includes a "What We're Eliminating" section, create a **dedicated build todo**
for the elimination step. This is NOT optional — it is as mandatory as a migration step.

**The elimination todo must include:**

1. **Migrate all consumers** — list every call site from the plan's consumer grep, with the
   new code each should use
2. **Delete old files** — list every file/module being removed
3. **Verification commands:**
   ```bash
   # Verify zero imports of old system remain
   grep -r "OldSystem\|old_module" src/ --include="*.py" | grep -v __pycache__
   # Expected: no output

   # Verify old files are gone
   ls src/old/path/ 2>/dev/null
   # Expected: "No such file or directory"

   # Run type checker — catches any remaining broken references
   uv run pyright  # or project's type checker
   ```
4. **Position in build order:** Elimination comes AFTER all new code is wired up but BEFORE
   writing tests. Never leave elimination as the last step — it must be verified before the
   build is considered complete.

**Rule:** If a plan replaces system X with system Y, and the build todos don't include an
elimination step for X, the build todos are incomplete.

## Step Dependencies

Order steps by dependencies:

- Steps that create new files come first
- Steps that modify existing code come after
- Elimination steps come after all migrations are done
- Steps that add tests come last

Use `depends_on` field to make dependencies explicit.

## Quality Checklist

Before finalizing each build todo:

- [ ] Searched ALL knowledge base folders (references, gotchas, solutions)
- [ ] Checked memory service results (auto-injected + explicit search if needed)
- [ ] EVERY build todo has "From knowledge base" subsection (even if "none applicable")
- [ ] For database changes: migration gotchas were read and referenced
- [ ] For field modifications: all consumers of modified fields were audited
- [ ] Found and documented relevant codebase patterns
- [ ] Checked git history for context on affected files
- [ ] Verified CLAUDE.md compliance
- [ ] Patterns documented with file:line references
- [ ] Implementation details follow discovered patterns
- [ ] Test requirements match existing test patterns
- [ ] Verification commands included
- [ ] **Elimination step included:** If plan has "What We're Eliminating" section, there is
      a dedicated build todo for deleting old code with grep verification of zero remaining
      imports

## Infrastructure Checklist

When feature involves infrastructure changes, include these steps:

### Database Migrations

If schema changes are needed:

1. Create a **dedicated build todo** for the migration file -- never bundle migration
   creation into a code change step
2. Include both upgrade AND downgrade functions
3. Document rollback procedure in the todo
4. **CRITICAL:** After ANY schema file modification (schema.prisma, models.py, etc.),
   always create a migration (`bun run migrate`, `alembic revision --autogenerate`, etc.).
   Never rely on `prisma db push` or equivalent tools alone -- they only sync the local
   dev database. Deployed environments run migrations, so a missing migration = column not
   found at runtime. See `.claude/knowledge/references/prisma-migration-process.md`.

### Environment Variables

If new API keys or env vars are needed:

1. Document in deployment notes section of plan.md
2. Add to .env.example with placeholder values

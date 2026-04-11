---
name: create-build-todos
description: Create detailed implementation steps from an approved plan. Spawns build-planner agent to create build_todos/.
max_turns: 75
memory:
  tags:
    - migration
    - implementation-pattern
    - $tech_tags
  types:
    - gotcha
    - pattern
    - solution
---

# Create Build Todos

Create detailed implementation steps (`build_todos/`) from an approved `plan.md`. This command
performs **deep research** into the codebase, memory service, and git history to ensure all
existing patterns and rules are discovered and followed.

## Usage

```
/create-build-todos 009                              # Bug/incident #009 (NNN format)
/create-build-todos F001                             # Feature F001 (FNNN format)
/create-build-todos B0009                            # Bug ticket B0009
```

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

```
# 1. Load ticket
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
# If not found: STOP - ticket not found

# 2. Check plan artifact exists
# Look for artifact with type="plan" in ticket response
# If missing: STOP - run /plan first
```

**If any prerequisite fails:**

| Missing             | Action                                 |
| ------------------- | -------------------------------------- |
| Ticket not found    | **STOP** - create ticket first         |
| No plan artifact    | **STOP** - run `/plan [id]` first      |
| Plan not reviewed   | **WARN** - suggest user review plan    |

**Additional requirements:**

- Review and iterate on plan.md before running this command

## What This Command Does

### Phase 1: Deep Research

1. **Knowledge base search** - Find all relevant:
   - References (architecture, patterns, standards)
   - Gotchas (pitfalls that apply to this change)
   - Solutions (past fixes for similar problems)

2. **Codebase pattern search** - Find all:
   - Similar implementations to follow
   - Conventions specific to affected areas
   - Error handling patterns in use
   - Test patterns for this type of code

3. **Git history analysis** - Understand:
   - Why affected code exists in its current form
   - Past issues with similar changes
   - Recent changes that might conflict
   - Contributors who know this area

### Phase 2: Break Down the Plan

4. **Split plan into independently completable steps:**
   - Each step maps to one logical change (one file group, one concept)
   - Order by dependencies
   - Identify which steps can be parallelized

### Phase 3: Deepen Each Step (CRITICAL)

5. **For each step, perform independent deep research:**
   - This is NOT just restating the plan in more detail
   - Each step gets its OWN research pass:
     a. Search autodev-memory for gotchas specific to THIS step's area
     b. Read the actual files that will be modified — understand their
        current state, imports, patterns, and constraints
     c. Find the closest existing implementation to follow (grep for
        similar code, read it, document the pattern with file:line refs)
     d. Check git history for past changes to these specific files
     e. Trace data flow: what produces the input this step needs? What
        consumes this step's output? What breaks if the contract changes?
     f. Identify edge cases: what happens with empty input, null fields,
        concurrent execution, partial failure?

   **The deepened step must contain enough detail that the builder can
   implement it without needing to do additional research.** If the builder
   would need to "figure out" how something works, the deepening was
   insufficient.

### Phase 4: Write Build Todos

6. **Create build_todo artifacts** with detailed steps:
   - Specific files to modify with current line numbers
   - Code examples following discovered patterns
   - Dependencies between steps
   - Test requirements per step
   - Verification commands
   - Edge cases to handle

## Process

1. **Locate work item:**
   - Same ID resolution as `/plan` command
   - Error if plan.md doesn't exist

2. **Read context** from `get_ticket` response:
   - Plan artifact - The approved architecture plan
   - Source artifact - Original problem/feature description
   - Investigation artifact - Production findings (if exists)

3. **Spawn build-planner agent** for deep research:
   - Agent searches memory service exhaustively
   - Agent searches codebase for all relevant patterns
   - Agent analyzes git history for context
   - Agent may spawn additional researcher agents

4. **Write build_todo artifacts:**
   - One artifact per implementation step
   - Steps ordered by dependencies via `sequence` field
   - Each step includes discovered patterns to follow
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="build_todo",
     title="<step title>",
     sequence=N,
     status="pending",
     content="<step content>",
     command="/create-build-todos"
   )
   ```

## Research Depth

The build-planner agent performs thorough research. See
`references/research-requirements.md` for the full research methodology including:

- Memory service search requirements
- Codebase pattern research requirements
- Git history research requirements
- CLAUDE.md compliance checks

| Area            | What It Searches                               | Why                                        |
| --------------- | ---------------------------------------------- | ------------------------------------------ |
| Knowledge base  | All references, gotchas, solutions             | Avoid known pitfalls, follow standards     |
| Codebase        | Similar code, patterns, conventions            | Match existing style and approaches        |
| Git history     | Related commits, past issues, contributor info | Understand context and avoid past mistakes |
| Past work items | Similar build_todos, review findings           | Reuse patterns, avoid past review issues   |
| CLAUDE.md       | Project rules and critical requirements        | Ensure compliance with project rules       |

## Output Template

Use the template at `templates/build-todo.md` for each build step.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Output

Build todo artifacts stored in MCP ticket system:

| Artifact | Type | Sequence |
|---|---|---|
| Step 1: [name] | build_todo | 1 |
| Step 2: [name] | build_todo | 2 |
| ... | build_todo | N |

Each build todo contains:

- **Objective** - What this step accomplishes
- **Files to Modify** - Specific files and line estimates
- **Discovered Patterns** - Patterns found that must be followed
- **Implementation Details** - Code snippets following patterns
- **Tests** - Test cases based on similar code
- **Verification** - Commands to verify step worked

## Agent Selection (if build-planner requests)

| Need                     | Agent          | Why                                |
| ------------------------ | -------------- | ---------------------------------- |
| Deeper pattern search    | `researcher`   | Find more examples in codebase     |
| Framework best practices | `web-searcher` | External docs for complex patterns |

## Build Todo Creation Process

1. **Read plan.md** - Understand the architecture
2. **Identify steps** - Break into independently completable units
3. **Pre-flight memory service audit (MANDATORY):**
   a. Search memory service for gotchas and references relevant to each build step's area
   b. For each build todo's affected area (database, migrations, encryption, API, etc.),
   search with relevant keywords
   c. Review the most relevant memory entries in full
   d. If a build todo involves database schema changes, search for migration-related gotchas
   e. Document findings in each build todo's "Discovered Patterns" section
4. **For each step:**
   a. Search memory service for gotchas/standards
   b. Research codebase for patterns to follow
   c. Research git history for context
   d. Check CLAUDE.md for applicable rules
   e. Write build todo with all findings

## Synthesis Guidelines

### Discovered Patterns Section

Every build todo MUST include a "Discovered Patterns" section:

```markdown
## Discovered Patterns

**From memory service:**

- [Entry title]: [How it applies]
- [Entry title]: [Standard to follow]

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

- [ ] Searched memory service for relevant gotchas, patterns, and solutions
- [ ] Checked memory service results (auto-injected + explicit search if needed)
- [ ] EVERY build todo has "From memory service" subsection (even if "none applicable")
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
   found at runtime. Search memory service for 'prisma migration process' for details.

### Environment Variables

If new API keys or env vars are needed:

1. Document in deployment notes section of plan.md
2. Add to .env.example with placeholder values

## Post-Creation Validation

After all build todos are written, verify memory service compliance by reading back
the ticket artifacts and checking each build_todo content contains memory service
references. If any are missing, go back and add the missing research.

## Next Steps

After build_todos are created and committed:

```
/build F001                   # Execute build in current session
```

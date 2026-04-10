---
name: review
description: Review implementation against the plan. Spawns review agents in parallel, collects findings into review_todos/.
---

# Review

Review implementation by spawning specialized review agents in parallel.

## Usage

```
/review 009                              # Bug/incident #009 (NNN format)
/review F001                             # Feature F001 (FNNN format)
/review B0009                            # Bug ticket B0009
```

## Agent Dispatch

Spawn these agents **in parallel** (single message, multiple Task tool calls):

| Agent    | Review References                                                                                                    | Focus                                |
| -------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| reviewer | references/python-standards.md, references/typescript-standards.md, references/simplicity.md, references/patterns.md | Code quality, YAGNI, design patterns |
| reviewer | references/architecture.md, references/security.md, references/performance.md                                        | Architecture, security, performance  |

**Conditional agent** (based on file changes):

| Condition                        | Agent    | Review References                                                                              |
| -------------------------------- | -------- | ---------------------------------------------------------------------------------------------- |
| Database/model/migration changes | reviewer | references/data-integrity.md, references/migrations.md, references/deployment.md               |

**CRITICAL: reviewer (data) spawn rule.** Always check for model file changes explicitly:
```bash
git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' migrations/versions/
```
If ANY model or migration files appear, spawn reviewer (data). Do NOT rely on build_todos
or plan.md to determine this — check the actual diff. Missing migrations are a p1 finding.

**All reviewer instances** include the `research` skill (references/past-work.md) to find and
reference issues caught in similar past implementations. This helps catch recurring patterns
proactively.

## Process

1. **Gather context:**
   - Load ticket: `mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)`
   - Read plan artifact for intended approach
   - Run `git diff --name-only` to identify changed files
   - Read build_todo artifact completion notes

2. **Check existing review_todo artifacts:**
   - Count existing review_todo artifacts from `get_ticket` response
   - New findings start at `max_sequence + 1` (or 1 if none exist)

3. **Spawn agents** with prompts like:

   ```
   Review these files for [focus area]: [file list]
   Context: [brief summary of what was implemented]
   Return findings with file_path:line_number format.
   ```

4. **Store findings** as review_todo artifacts:
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="review_todo",
     title="<finding title>",
     sequence=N,
     status="pending",
     content="<finding content using review skill template>",
     command="/review"
   )
   ```

5. **Store P1/P2 findings in memory service** (persists beyond session):
   For each P1/P2 finding, first search for duplicates, then store via MCP:

   ```
   # 1. Check for duplicates
   mcp__autodev-memory__search(
     queries=["<finding keywords>"],
     project="<from <!-- mem:project=X --> in CLAUDE.md>"
   )

   # 2. If no duplicate, store the finding
   mcp__autodev-memory__add_entry(
     project="<from <!-- mem:project=X --> in CLAUDE.md>",
     title="Review: [finding summary]",
     content="File: [path], Line: [number]. Issue: [description]. Fix: [fix].",
     entry_type="gotcha",
     summary="[1-sentence summary]",
     tags=["review", "[area]"],
     source="captured",
     caller_context={
       "skill": "review",
       "reason": "P1/P2 review finding that future builds should avoid",
       "action_rationale": "New entry — no existing entry covers this finding",
       "trigger": "review finding [p1/p2]"
     }
   )
   ```

   If a related entry exists, use `mcp__autodev-memory__update_entry` to append instead.

   This is critical for autonomous workflows (LFG, auto-build) in cloud environments
   where review findings would otherwise be lost after the session ends.
   If the MCP tool is unavailable, skip this step silently.

6. **Update plan artifact** with review log entry via `update_artifact`

---

# Review Methodology

Standards for conducting code reviews and producing review_todo files.

## Output Template

Use the template at `templates/review-todo.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Priority Levels

| Priority | Meaning                                          | Examples                               |
| -------- | ------------------------------------------------ | -------------------------------------- |
| **p1**   | Must fix - correctness, security, data integrity | Bugs, vulnerabilities, data loss risk, old system not deleted after replacement added |
| **p2**   | Should fix - maintainability, performance        | YAGNI violations, complexity, patterns |
| **p3**   | Nice to have - style, minor improvements         | Naming, documentation, clarity         |

## Synthesis Methodology

When reviewing code changes:

1. **Understand intent** - Read plan and build_todos to know what was intended
2. **Check completeness** - Verify implementation matches the plan
3. **Apply skill checklists** - Systematically check each dimension
4. **Prioritize findings** - Critical issues first, style last
5. **Provide actionable fixes** - Show current code vs suggested fix

## Finding Quality

**Strong findings:**

- Specific file:line references
- Clear explanation of the issue
- Concrete suggested fix
- Impact assessment (complexity/performance/maintainability)

**Weak findings (improve before reporting):**

- Vague "could be better" without specifics
- Style preferences without justification
- Findings without suggested fixes

## Knowledge Persistence

P1/P2 findings are stored in the memory service by the `/review` command orchestrator via
`mcp__autodev-memory__add_entry`. This ensures future builds learn from past review findings,
even in ephemeral cloud sessions. Individual reviewer agents do NOT call MCP tools directly —
the orchestrator handles persistence after collecting all findings.

## Review Process

1. **Load context** - Read plan and changed files
2. **Apply checklists** - Use loaded skill checklists systematically
3. **Format findings** - Structure findings per template format
4. **Assess impact** - Evaluate complexity/performance/maintainability effects
5. **Prioritize** - Assign p1/p2/p3 based on severity

## Output Format

**For agents:** Return findings grouped by dimension. DO NOT write files - the orchestrator
consolidates findings from all agents and creates review_todo artifacts to avoid duplicates.

```markdown
## [Dimension] Findings

- [p2] src/path/file.py:45 - Issue description
- [p3] src/path/file.py:78 - Another issue
```

**For orchestrator:** After collecting agent outputs, create one review_todo artifact per
unique finding using the template at `templates/review-todo.md`.

**Numbering:** Check existing review_todo artifacts from `get_ticket` response for highest
sequence number. Start new findings at `max_sequence + 1` (or 1 if none exist).

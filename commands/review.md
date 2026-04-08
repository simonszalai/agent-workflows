---
description: Review implementation against the plan. Spawns review agents in parallel, collects findings into review_todos/.
---

# Review Command

Review implementation by spawning specialized review agents in parallel.

## Usage

```
/review 009                              # Bug/incident #009 (NNN format)
/review F001                             # Feature F001 (FNNN format)
/review B0009                              # Bug ticket B0009
```

## Agent Dispatch

Spawn these agents **in parallel** (single message, multiple Task tool calls):

| Agent           | Skills                                                                                                       | Focus                                |
| --------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------ |
| reviewer-code   | review-python-standards, review-typescript-standards, review-simplicity, review-patterns, research-past-work | Code quality, YAGNI, design patterns |
| reviewer-system | review-architecture, review-security, review-performance, research-past-work                                 | Architecture, security, performance  |

**Conditional agent** (based on file changes):

| Condition                        | Agent         | Skills                                                                          |
| -------------------------------- | ------------- | ------------------------------------------------------------------------------- |
| Database/model/migration changes | reviewer-data | review-data-integrity, review-migrations, review-deployment, research-past-work |

**CRITICAL: reviewer-data spawn rule.** Always check for model file changes explicitly:
```bash
git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' migrations/versions/
```
If ANY model or migration files appear, spawn reviewer-data. Do NOT rely on build_todos
or plan.md to determine this — check the actual diff. Missing migrations are a p1 finding.

**All reviewers** now include `research-past-work` skill to find and reference issues caught in
similar past implementations. This helps catch recurring patterns proactively.

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

## Output

See `review` skill for:

- Priority levels (p1, p2, p3)
- Review todo template (`review/templates/review-todo.md`)
- Synthesis methodology

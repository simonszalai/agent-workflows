---
description: Review implementation against the plan. Spawns review agents in parallel, collects findings into review_todos/.
---

# Review Command

Review implementation by spawning specialized review agents in parallel.

## Usage

```
/review 009                              # Bug/incident #009 (NNN format)
/review F001                             # Feature F001 (FNNN format)
/review work_items/active/009-fix-timeout  # Use explicit path
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
   - Read `plan.md` for intended approach
   - Run `git diff --name-only` to identify changed files
   - Read `build_todos/` completion notes

2. **Check existing review_todos:**
   - List files in `review_todos/` directory (if it exists)
   - Extract index numbers from filenames (pattern: `NN-*.md`)
   - Find the highest existing index number
   - New findings start at `max_index + 1` (or 01 if empty)

3. **Spawn agents** with prompts like:

   ```
   Review these files for [focus area]: [file list]
   Context: [brief summary of what was implemented]
   Return findings with file_path:line_number format.
   ```

4. **Collect findings** into `review_todos/` directory
   - Use `review` skill template for output format
   - Number files starting from the next available index (from step 2)

5. **Store P1/P2 findings in memory service** (persists beyond session):
   For each P1/P2 finding, store via the memory service so future builds learn from it:

   ```bash
   curl -sf -X POST \
     -H "Authorization: Bearer $MEM_BEARER_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "action": "new",
       "entry": {
         "title": "Review: [finding summary]",
         "summary": "[1-sentence summary]",
         "content": "File: [path], Line: [number]. Issue: [description]. Recommendation: [fix]. Priority: [p1/p2].",
         "canonical_key": "review-[area]-[issue]",
         "type": "gotcha",
         "source": "captured",
         "project": "<project from CLAUDE.md>"
       }
     }' \
     "$MEM_SERVICE_URL/store"
   ```

   This is critical for autonomous workflows (LFG, auto-build) in cloud environments
   where review findings would otherwise be lost after the session ends.
   If $MEM_BEARER_TOKEN is unset, skip this step.

6. **Update plan.md** work log:
   ```
   | YYYY-MM-DD | review | Ran review agents | N findings (X p1, Y p2, Z p3) |
   ```

## Output

See `review` skill for:

- Priority levels (p1, p2, p3)
- Review todo template (`review/templates/review-todo.md`)
- Synthesis methodology

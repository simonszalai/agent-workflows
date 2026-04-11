---
name: resolve-review
description: Resolve review findings based on decisions. Spawns builder agent to implement fixes from review_todos, captures learnings.
skills:
  - autodev-search
  - compound
---

# Resolve-Review Command

Spawn a `builder` agent to work through review findings and implement accepted fixes.

## Usage

```
/resolve-review 009                              # Bug/incident #009 (NNN format)
/resolve-review F001                             # Feature F001 (FNNN format)
/resolve-review B0009                              # Bug ticket B0009
```

## Prerequisites

- `review_todos/` exists with findings
- (Optional) User has filled Decision sections

## Process

1. **Load ticket** via `get_ticket` — identify pending review_todo artifacts

2. **Spawn builder agent to resolve findings:**

   ```
   Agent(
     subagent_type="builder",
     model="sonnet",
     prompt="
       MODE: resolve
       Ticket: {ticket_id}
       Project: {PROJECT}
       Repo: {REPO}

       Resolve these review findings:

       {for each review_todo artifact:}
       - Finding #{sequence}: {title}
         Priority: {p1/p2/p3}
         Decision: {accept/skip/modify — default accept if empty}
         Suggested Fix: {suggested fix from artifact}
         File: {file_path}:{line_number}
       {end for}

       For each accepted finding:
       - CRITICAL: Before removing any export/class/function, search ALL usages first
       - Implement the suggested fix exactly as written
       - Run linter and type checker after each fix
       - Update artifact status to 'resolved' via update_artifact

       For skipped findings:
       - Update artifact status to 'skipped'

       Return summary of what was resolved and any issues encountered.
     "
   )
   ```

3. **After builder returns — capture learnings:**
   - Run `/compound` to analyze the fixes
   - `/compound` will propose improvements to memory entries AND workflows
   - In interactive mode, it will ask for approval before applying

4. **Apply process improvement recommendations:**

   `/compound` handles all updates — including MCP calls to persist knowledge:

   | Recommendation Type             | Target Location                                     |
   | ------------------------------- | --------------------------------------------------- |
   | Project-specific pitfall        | Memory service via `mcp__autodev-memory__add_entry` |
   | Reusable pattern                | Memory service via `mcp__autodev-memory__add_entry` |
   | Plan research requirement       | `.claude/skills/plan/SKILL.md`                      |
   | Build todo research requirement | `.claude/skills/create-build-todos/SKILL.md`        |
   | Build verification step         | `.claude/skills/build/SKILL.md`                     |

5. **Update plan.md:**

   Add completion summary section (before Work Log):

   ```markdown
   ---

   ## Review Resolution Summary

   **Resolved:** YYYY-MM-DD

   ### What Was Done

   - [Key fix 1: brief description]
   - [Key fix 2: brief description]

   ### Findings Summary

   | Category | Accepted | Skipped | Total |
   | -------- | -------- | ------- | ----- |
   | [type]   | N        | N       | N     |

   ### Files Changed

   | File              | Change              |
   | ----------------- | ------------------- |
   | `path/to/file.py` | [brief description] |

   ### Learnings Captured

   - [Knowledge doc created, or "None"]

   ### Process Improvements Applied

   - [Where improvement was added, or "None"]
   ```

   Add work log entry:

   ```
   | YYYY-MM-DD | resolve-review | Resolved N findings | X accepted, Y skipped |
   ```

6. **Create deployment guide:**

   Run `/create-deployment-guide` to generate deployment instructions:
   - Analyzes changes and creates `deployment-guide.md`
   - Documents deployment steps, verification, rollback plan
   - Identifies affected services and requirements

   This step can be skipped for trivial changes (e.g., doc-only updates).

7. **Commit changes (submodule-aware):** _(no permission needed)_

    Handle submodules first, then main repo:

```bash
# Check for submodule changes
git status --porcelain | grep "^.M"
```

**If submodule has changes:**

```bash
# 1. Commit inside the submodule first
cd submodule_name
git add -A
git commit -m "Update for [work-item-id]: [brief description]"
git push
cd ..

# 2. Stage the submodule reference in main repo
git add submodule_name
```

**Then commit main repo:**

```bash
# Stage all other changes
git add -A

# Commit with standard message
git commit -m "Resolve review findings for [work-item-id]: [summary]"

# Push to remote
git push
```

**Important:** Always commit and push submodule changes BEFORE committing the main repo reference to avoid "new commits" state conflicts.

## Output

- Updated `review_todos/` with resolutions
- Code fixes for accepted findings
- Updated `plan.md` with Review Resolution Summary and work log entry
- `deployment-guide.md` with deployment instructions
- Optional memory entries via `/compound`
- Process improvements applied to:
  - `.claude/skills/plan/SKILL.md` (plan research requirements)
  - `.claude/skills/create-build-todos/SKILL.md` (build todo research requirements)
  - `.claude/commands/build.md` (verification steps)
  - Memory service via MCP (project-specific pitfalls, reusable patterns)

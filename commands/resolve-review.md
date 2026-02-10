---
description: Resolve review findings based on decisions. Implements fixes from review_todos, captures learnings.
skills:
  - research-knowledge-base
  - compound
---

# Resolve-Review Command

Work through review findings and implement accepted fixes.

## Usage

```
/resolve-review 009                              # Bug/incident #009 (NNN format)
/resolve-review F001                             # Feature F001 (FNNN format)
/resolve-review work_items/active/009-fix-timeout  # Use explicit path
```

## Prerequisites

- `review_todos/` exists with findings
- (Optional) User has filled Decision sections

## Process

1. **Read review_todos/** - identify pending items

2. **For each finding, check Decision section:**
   - If Action is empty, missing, or "accept" - execute the **Suggested Fix** as-is
   - If Action is "skip" - document reasoning and mark status: skipped
   - If Action is "modify" - follow the user's notes for the modified approach

3. **For each accepted/default finding:**
   - **CRITICAL: Before removing any export/class/function:**
     - Search for ALL usages across the codebase
     - Update ALL import sites BEFORE removing the export
     - Check related repositories if applicable
   - Implement the suggested fix exactly as written
   - Update Resolution Notes section
   - Mark status: resolved

4. **For skipped findings:**
   - Document reasoning in Resolution Notes
   - Mark status: skipped

5. **Capture learnings:**
   - Search `.claude/knowledge/` for existing docs on the topic (avoid duplicates)
   - Run `/compound` for significant fixes worth documenting
   - Document gotchas, patterns, solutions that aren't already captured

6. **Apply process improvement recommendations:**

   For each finding with Process Improvement Recommendations:

   **Plan Phase improvements:**
   - If recommendation is project-specific - create gotcha in `.claude/knowledge/gotchas/`
   - If recommendation is a general pattern - update `.claude/skills/plan-methodology/SKILL.md`
   - Examples: "Always research error handling patterns before planning async flows"

   **Build Todos Phase improvements:**
   - If recommendation adds a research step - update `.claude/skills/build-plan-methodology/SKILL.md`
   - If recommendation references useful patterns - add to `.claude/knowledge/references/`
   - Examples: "Search for similar models before defining new ones"

   **Build Phase improvements:**
   - If recommendation adds a verification step - update `.claude/commands/build.md` checklist
   - If recommendation is about testing - add to `.claude/knowledge/gotchas/` for test patterns
   - Examples: "Run integration tests against staging data before marking complete"

   **Where to apply:**

   | Recommendation Type             | Target Location                                    |
   | ------------------------------- | -------------------------------------------------- |
   | Project-specific pitfall        | `.claude/knowledge/gotchas/[topic]-YYYYMMDD.md`    |
   | Reusable pattern                | `.claude/knowledge/references/[topic]-YYYYMMDD.md` |
   | Plan research requirement       | `.claude/skills/plan-methodology/SKILL.md`         |
   | Build todo research requirement | `.claude/skills/build-plan-methodology/SKILL.md`   |
   | Build verification step         | `.claude/commands/build.md`                        |

   Use `/compound` to create knowledge docs with proper YAML frontmatter.

7. **Run linter and type checker (REQUIRED after every fix):**
   - Run project's linter - fix any linting errors
   - Run project's type checker - fix any type errors
   - **Do not proceed until all checks pass**
   - This catches broken imports and missing dependencies immediately

8. **Update plan.md:**

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

9. **Create deployment guide:**

   Run `/create-deployment-guide` to generate deployment instructions:
   - Analyzes changes and creates `deployment-guide.md`
   - Documents deployment steps, verification, rollback plan
   - Identifies affected services and requirements

   This step can be skipped for trivial changes (e.g., doc-only updates).

10. **Commit changes (submodule-aware):** _(no permission needed)_

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
- Optional knowledge docs via `/compound`
- Process improvements applied to:
  - `.claude/skills/plan-methodology/SKILL.md` (plan research requirements)
  - `.claude/skills/build-plan-methodology/SKILL.md` (build todo research requirements)
  - `.claude/commands/build.md` (verification steps)
  - `.claude/knowledge/gotchas/` (project-specific pitfalls)
  - `.claude/knowledge/references/` (reusable patterns)

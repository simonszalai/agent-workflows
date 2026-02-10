---
description: Create high-level implementation plan for work items. Spawns planner agent to create plan.md only.
---

# Plan Command

Create a high-level architecture plan for a work item. This command creates `plan.md` which focuses
on **what** we're building and **why** - not implementation details.

## When to Use

| Work Type   | Workflow                                      |
| ----------- | --------------------------------------------- |
| **Feature** | `/plan` directly (includes codebase research) |
| **Bug**     | `/investigate` first, then `/plan`            |

**For features:** This command does codebase research to understand existing patterns before
designing the solution. No separate investigation needed.

**For bugs:** Run `/investigate` first to find root causes, then `/plan` to design the fix.

## Usage

```
/plan                                     # Interactive: asks for details
/plan work_items/active/009-fix-timeout   # Plan existing work item
/plan 009                                 # Bug/incident #009 (NNN format)
/plan F001                                # Feature F001 (FNNN format)
/plan F001 additional context             # Feature with extra context
/plan "Add new integration"               # Create new work item and plan
```

## What plan.md Contains

**Architecture-focused, not implementation-focused:**

- What we're building (high-level description)
- Why this approach (reasoning, alternatives considered)
- Tradeoffs made (what we're optimizing for vs sacrificing)
- Side effects (what else this affects)
- Risks and mitigations
- Verification strategy (how to know it works)

**For features, also includes:**

- Codebase research (existing patterns, integration points)
- Requirements analysis

**Does NOT contain:**

- Specific files to modify
- Code snippets or examples
- Line-by-line implementation details

Those details come later via `/create-build-todos`.

## Naming Schemes

Two naming schemes exist:

- **Bugs/Incidents**: `NNN-slug` (e.g., `009-truth-social-scraper-failures`)
- **Features**: `FNNN-slug` (e.g., `F001-fix-deduplication-system`)

## Process

1. **Set up work item folder:**
   - If given folder path: use that folder
   - **If starts with `F` followed by digits** (e.g., `F001`): search for feature
     1. Extract the ID (e.g., "F001" from "F001 check timeouts...")
     2. Search: `find work_items -maxdepth 2 -type d -name "F001-*"`
     3. If found in **backlog/**: Move to **active/** first, then use that folder
        - `mv work_items/backlog/F001-slug work_items/active/`
     4. If found in **active/** or **closed/**: Use that folder directly
     5. If not found: error - features must exist in backlog first
   - **If starts with a number only** (e.g., `009`): search for bug/incident
     1. Extract the leading number (e.g., "009" from "009 check timeouts...")
     2. Search: `find work_items -maxdepth 2 -type d -name "NNN-*"` (exclude `FNNN`)
     3. If found in **backlog/**: Move to **active/** first
        - `mv work_items/backlog/NNN-slug work_items/active/`
     4. If found in **active/** or **closed/**: Use that folder directly
     5. If not found: create a new bug work item
   - If given prompt (no ID prefix): create new bug/incident folder:
     1. Search active/closed for existing bugs: `find work_items/{active,closed} -maxdepth 1 -type d -name "[0-9][0-9][0-9]-*"`
     2. Extract the numeric prefix from each folder name (e.g., `001`, `009`, `027`)
     3. Find the highest number, add 1
     4. **Pad to 3 digits** (e.g., 3 -> `003`, 42 -> `042`, 100 -> `100`)
     5. Create folder: `work_items/active/NNN-kebab-title/`
     6. Create `source.md` with frontmatter and user's prompt

2. **Gather inputs based on work type:**

   **For features (FNNN):**
   - Read `source.md` (required)
   - Spawn `researcher` agent to analyze codebase patterns, integration points
   - No investigation.md expected (features don't need root cause analysis)

   **For bugs (NNN):**
   - Read `source.md` (required)
   - Read `investigation.md` (expected - if missing, suggest running `/investigate` first)
   - Use root causes from investigation to inform solution design

   **For all work types:**
   - The planner agent now includes `research-past-work` skill
   - It searches for similar past work items automatically
   - Extracts architectural decisions, tradeoffs, and learnings

3. **Spawn planner agent** with all inputs:
   - For features: includes codebase research findings
   - For bugs: includes investigation findings
   - Planner designs architecture and solution approach

4. **Handle additional research needs:**
   - If planner needs more codebase patterns: spawn `researcher` agent
   - If planner needs production state (bugs): spawn investigator agents
   - Collect findings and re-run planner

5. **Write output** to work item folder:
   - `plan.md` - High-level architecture plan

## Agent Selection

**For features:** Always spawn `researcher` to analyze codebase before planning.

**For bugs:** Use investigation.md findings; spawn additional agents only if needed.

**For all:** The planner agent includes `research-past-work` skill and searches past work items
automatically as part of its research phase.

| Need                    | Agent                  | When Used                        |
| ----------------------- | ---------------------- | -------------------------------- |
| Codebase patterns       | `researcher`           | Always for features              |
| Past work learnings     | (built into planner)   | Automatic via research-past-work |
| Production state (bugs) | Investigator agents    | If investigation incomplete      |
| Additional code context | `researcher`           | If planner requests              |
| Deep past work research | `past-work-researcher` | If planner needs more context    |

## Output

```
work_items/active/{NNN|FNNN}-title/
  source.md           # Input (with frontmatter)
  investigation.md    # Input (optional, for bugs)
  plan.md             # Created by planner (architecture doc)
```

## Workflow

After creating plan.md:

1. **Review and iterate:** Read the plan, provide feedback
2. **When satisfied:** `/create-build-todos F001` to create detailed implementation steps

## Next Steps

After plan is approved, create detailed implementation steps:

```
/create-build-todos 009       # Create build_todos for bug #009
/create-build-todos F001      # Create build_todos for feature F001
```

---
name: plan
description: Create high-level implementation plan for work items. Spawns planner agent to create plan.md only.
memory:
  tags:
    - architecture
    - tradeoff
    - constraint
    - $tech_tags
  types:
    - architecture
    - pattern
    - preference
---

# Plan

Create a high-level architecture plan for a ticket. This command creates a `plan` artifact which
focuses on **what** we're building and **why** - not implementation details.

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
/plan F0009                               # Plan existing ticket
/plan B0003                               # Bug ticket B0003
/plan F0009 additional context            # Ticket with extra context
/plan "Add new integration"               # Create new ticket and plan
```

## What the Plan Contains

**Architecture-focused, not implementation-focused:**

- What we're building (high-level description)
- What we're eliminating (old code/systems being replaced — see Elimination Audit below)
- How it works (architectural approach)
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

**Code snippets in plans:**

When a plan DOES include code snippets (e.g., for complex features), you MUST:

1. **Cross-check against exploration findings** - Before writing any code, review what the
   exploration agents found about existing patterns
2. **Use canonical patterns from codebase** - Never invent new patterns; use what exists
3. **Include file:line references** - Show where the pattern comes from
4. **Never use simplified versions** - If the codebase uses a specific abstraction, use it

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## Process

1. **Resolve ticket:**
   - **If ticket ID given** (e.g., `F0009`, `B0003`):
     ```
     mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
     ```
     - Read the source artifact for requirements/context
     - If ticket status is `backlog`, update to `active`:
       ```
       mcp__autodev-memory__update_ticket(
         project=PROJECT, ticket_id=ID, repo=REPO,
         status="active", command="/plan"
       )
       ```
   - **If description given** (no ID): Create a new ticket:
     ```
     mcp__autodev-memory__create_ticket(
       project=PROJECT, repo=REPO,
       title="<synthesized title>",
       type="bug",  # or "feature" based on context
       description="<user's description>",
       status="active",
       command="/plan"
     )
     ```
     - The returned `ticket_id` is used for all subsequent operations

2. **Gather inputs based on work type:**

   **For features (F-prefix):**
   - Read source artifact from `get_ticket` response
   - Spawn `researcher` agent to analyze codebase patterns, integration points
   - No investigation expected (features don't need root cause analysis)

   **For bugs (B-prefix):**
   - Read source artifact from `get_ticket` response
   - Read investigation artifact (expected - if missing, suggest running `/investigate` first)
   - Use root causes from investigation to inform solution design

   **For all work types:**
   - The planner agent includes the `research` skill (references/past-work.md)
   - It searches for similar past tickets automatically via `get_similar_tickets`
   - Extracts architectural decisions, tradeoffs, and learnings

3. **Spawn planner agent** with all inputs:
   - For features: includes codebase research findings
   - For bugs: includes investigation findings
   - Planner designs architecture and solution approach

4. **Handle additional research needs:**
   - If planner needs more codebase patterns: spawn `researcher` agent
   - If planner needs production state (bugs): spawn investigator agents
   - Collect findings and re-run planner

5. **Write output** as a plan artifact:
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="plan",
     content="<plan content>",
     command="/plan"
   )
   ```

## Agent Selection

**For features:** Always spawn `researcher` to analyze codebase before planning.

**For bugs:** Use investigation artifact findings; spawn additional agents only if needed.

**For all:** The planner agent includes the `research` skill (references/past-work.md) and searches past tickets
automatically as part of its research phase.

| Need                    | Agent                  | When Used                        |
| ----------------------- | ---------------------- | -------------------------------- |
| Codebase patterns       | `researcher`           | Always for features              |
| Past work learnings     | (built into planner)   | Automatic via research (references/past-work.md) |
| Production state (bugs) | Investigator agents    | If investigation incomplete      |
| Additional code context | `researcher`           | If planner requests              |
| Deep past work research | `researcher` | If planner needs more context    |

## Next Steps

After plan is approved, create detailed implementation steps:

```
/create-build-todos F0009      # Create build_todos for ticket F0009
/create-build-todos B0003      # Create build_todos for bug B0003
```

---

# Plan Methodology

Standards for creating high-level architecture plans.

## Workflow by Work Type

| Work Type   | Input                        | Research Needed                     |
| ----------- | ---------------------------- | ----------------------------------- |
| **Feature** | source.md + user prompt      | Codebase patterns, existing code    |
| **Bug**     | source.md + investigation.md | Usually none (investigation has it) |

**For features:** Plan includes codebase research to understand existing patterns before
designing.
**For bugs:** Plan uses investigation findings to design the fix.

## Output Template

Use the template at `templates/plan.md` for plan output.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Plan Type Determination

Determine fix vs feature from input content:

**Fix indicators:**

- Keywords: fix, bug, error, broken, failing, issue, debug, crash, timeout
- Problem describes unexpected/incorrect behavior
- Investigation findings point to root cause

**Feature indicators:**

- Keywords: add, new, create, implement, build, feature, enhance, support
- Request describes new functionality
- No existing broken behavior to address

## Input Verification

Before planning, verify inputs are sufficient:

### For Features (FNNN)

| Required           | Check                                              | Source                |
| ------------------ | -------------------------------------------------- | --------------------- |
| Requirements       | Clear description of what to build                 | source.md             |
| Scope boundaries   | Know what's in/out of scope                        | source.md             |
| Integration points | Identified where feature connects to existing code | **Codebase research** |
| Patterns           | Found similar implementations to follow            | **Codebase research** |

**Process:** Spawn `researcher` agent to explore codebase patterns before planning.

### For Bugs (NNN)

| Required        | Check                                              | Source               |
| --------------- | -------------------------------------------------- | -------------------- |
| Problem clarity | Can articulate what's broken and expected behavior | source.md            |
| Root cause      | Investigation identified likely cause(s)           | **investigation.md** |
| Affected scope  | Know which files/components are involved           | **investigation.md** |
| Reproduction    | Understand when/how issue occurs                   | **investigation.md** |

**Process:** Read investigation.md. If missing or incomplete, suggest running `/investigate`
first.

## Complexity Assessment

Assess implementation complexity to determine verification needs:

| Complexity | Criteria                                       | Verification Needed |
| ---------- | ---------------------------------------------- | ------------------- |
| Simple     | Single file change, obvious fix, <30 lines     | No (lint/types OK)  |
| Moderate   | 2-3 files, new logic, integrates with existing | Recommended         |
| Complex    | 4+ files, new model/flow, changes data flow    | Required            |

**Simple examples:** typo fixes, config tweaks, adding logging, small bug fixes

**Complex examples:** new processing pipeline, database schema changes,
new API integrations, changes to alert/notification logic

## Planning Process

### For Features

1. **Read source.md** - Understand requirements and scope
2. **Search memory service** - Find relevant gotchas, patterns, and past solutions:
   ```
   mcp__autodev-memory__search(queries=[
     {"keywords": ["<feature-area>"], "text": "<feature area> architecture patterns"},
     {"keywords": ["<technology>"], "text": "<technology> gotchas pitfalls"}
   ])
   ```
   Also review auto-injected context from the knowledge menu.
3. **First-principles analysis** - State fundamental goal, classify constraints, eliminate
   fake ones
4. **Research codebase** - Spawn `researcher` to find patterns, integration points
5. **Define what we're NOT building** - Explicitly list eliminated scope
6. **Assess complexity** - Determine verification strategy needed
7. **Design architecture** - Choose high-level implementation approach (simplest that works)
8. **Identify tradeoffs** - What we're optimizing for vs accepting
9. **Identify side effects** - What else this change affects
10. **Identify risks** - What could go wrong, how to mitigate
11. **Write plan.md** - Synthesize research into architecture doc

### For Bugs

1. **Read source.md + investigation.md** - Understand problem and root causes
2. **Search memory service** - Find related past fixes and gotchas:
   ```
   mcp__autodev-memory__search(queries=[
     {"keywords": ["<bug-area>"], "text": "<bug area> root cause fix"},
     {"keywords": ["<technology>"], "text": "<technology> gotchas"}
   ])
   ```
3. **Verify investigation complete** - If missing root causes, suggest `/investigate`
4. **First-principles analysis** - Is the root cause in code that should exist? Could we
   eliminate rather than fix?
5. **Assess complexity** - Determine verification strategy needed
6. **Design fix approach** - Choose solution based on root causes (prefer elimination over
   repair)
7. **Identify tradeoffs** - What we're optimizing for vs accepting
8. **Identify side effects** - What else this fix affects
9. **Identify risks** - What could go wrong, how to mitigate
10. **Write plan.md** - Synthesize investigation into fix architecture

## Synthesis Guidelines

**Summary section:**

- 2-3 sentences max
- What we're building and why this approach

**What We're Building:**

- High-level description of the solution
- Answer: What will exist after this that doesn't exist now?
- NO code, NO file paths

**What We're Eliminating (if applicable):**

- Every file, class, and module being replaced or deleted
- All consumer call sites that must be migrated
- Answer: What will be GONE after this that exists now?
- If nothing is being eliminated, explicitly state "No code elimination required"
- **If this section is missing from a replacement plan, the plan is incomplete**

**How It Works:**

- Architectural flow description
- How pieces fit together
- NO implementation details

**Research Findings (features) / Investigation Summary (bugs):**

For features:

- Existing patterns found in codebase
- Integration points identified
- Conventions to follow

For bugs:

- Root causes from investigation
- Affected components
- Evidence summary

**Tradeoffs section:**

- What we're optimizing for
- What we're accepting/sacrificing
- Alternatives considered and why rejected

**Side Effects section:**

- Other components affected
- Data/state changes
- Downstream impacts

**Risks:**

- What could go wrong
- Likelihood and impact
- Mitigation strategies

## Feature Checklist

When planning features, verify these infrastructure needs:

### Field Transformation Audit (CRITICAL)

When a plan involves encrypting, changing format, or removing a database field:

- [ ] **Find all readers:** `grep -r "field_name" src/` to find every file that reads the field
- [ ] **Find all transformers:** Search for `.format(`, f-strings, regex, slicing, parsing
      operations on the field's value
- [ ] **Find all writers:** Identify every code path that writes to the field
- [ ] **Classify compatibility:** For each consumer, document whether the new format is
      compatible or requires changes
- [ ] **Document exceptions:** If some consumers are incompatible, document them explicitly
      in the plan as architectural constraints

### Data Dependencies (CRITICAL)

Before designing, verify data flow is complete:

- [ ] **What data does this feature need?** - List all input data required
- [ ] **Where does that data come from?** - Identify upstream sources/pipelines
- [ ] **Is that data available?** - Verify sources are configured and populated
- [ ] **Is the data sufficient?** - Check content quality matches use case needs

### Elimination Audit (CRITICAL)

When a feature replaces, supersedes, or eliminates an existing system:

- [ ] **List what gets deleted:** Enumerate every file, class, and module the new system
      replaces. This list goes into plan.md under "What We're Eliminating"
- [ ] **Find all consumers:** `grep -r "OldSystem\|old_module" src/` — every import and
      call site must be migrated or removed
- [ ] **Verify zero remaining references:** After migration, grep must return 0 results
      for the old system's imports
- [ ] **Deletion is part of the plan, not a follow-up:** The plan must include elimination
      as a required step, not a "nice to have" or separate PR. Adding a replacement without
      removing the old system is an incomplete plan.

**Rule:** If the plan says "replace X with Y", the deliverable is: Y is wired up at all
call sites AND X is deleted. If the plan only covers adding Y, it is incomplete — send it
back for revision.

### Database Changes

- [ ] New tables or columns needed? - Include migration step
- [ ] New enum values? - Add to migration
- [ ] Seed data needed? - Include in migration or seed script

### API Keys / Environment

- [ ] New API keys required? - Document in deployment notes
- [ ] Environment variables needed? - Add to .env.example

## Ticket System

Work items are tracked in the autodev-memory ticket system via MCP tools.
Use `mcp__autodev-memory__get_ticket` to read ticket details and artifacts.

Each ticket contains artifacts:

- `source` — INPUT: Problem/feature description (auto-created with ticket)
- `investigation` — INPUT (optional): From /investigate
- `plan` — OUTPUT: High-level architecture plan
- `build_todo` — OUTPUT: From /create-build-todos (separate step)

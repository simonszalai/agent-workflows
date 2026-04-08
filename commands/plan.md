---
description: Create high-level implementation plan for work items. Spawns planner agent to create plan.md only.
---

# Plan Command

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
   - The planner agent includes `research-past-work` skill
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

**For all:** The planner agent includes `research-past-work` skill and searches past tickets
automatically as part of its research phase.

| Need                    | Agent                  | When Used                        |
| ----------------------- | ---------------------- | -------------------------------- |
| Codebase patterns       | `researcher`           | Always for features              |
| Past work learnings     | (built into planner)   | Automatic via research-past-work |
| Production state (bugs) | Investigator agents    | If investigation incomplete      |
| Additional code context | `researcher`           | If planner requests              |
| Deep past work research | `past-work-researcher` | If planner needs more context    |

## Workflow

After creating the plan artifact:

1. **Review and iterate:** Read the plan, provide feedback
2. **When satisfied:** `/create-build-todos F0009` to create detailed implementation steps

## Next Steps

After plan is approved, create detailed implementation steps:

```
/create-build-todos F0009      # Create build_todos for ticket F0009
/create-build-todos B0003      # Create build_todos for bug B0003
```

---
name: auto-plan
description: Autonomous planning for backlog tickets. Researches, investigates, creates plan artifact, sets status to planned.
max_turns: 100
---

# Auto-Plan Command

Autonomous planning workflow that picks up a backlog ticket, researches the codebase,
creates a concise plan artifact, and marks the ticket as `planned` for user approval.

## Usage

```
/auto-plan F0009                    # Plan existing backlog ticket
/auto-plan B0003                    # Plan bug ticket (includes investigation)
```

## When to Use

- Scheduled agent picks up `backlog` tickets automatically
- Manual trigger when you want autonomous planning for a specific ticket

## Prerequisites

- Ticket must exist with status `backlog`
- Source artifact must exist (ticket description/requirements)

## Process Overview

```
1.  Validate       -> Check ticket exists, status is backlog
2.  Set Status     -> Update to "planning"
3.  Research       -> /research for features, /investigate for bugs
4.  Plan           -> Spawn planner agent, create plan artifact
5.  Set Status     -> Update to "planned"
```

## Detailed Process

### Phase 1: Validate Ticket

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- If not found: STOP - "Ticket not found"
- If status is not `backlog`: STOP - "Ticket status is {status}, expected backlog"
- Read source artifact for requirements/context

### Phase 2: Set Status to Planning

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="planning",
  command="/auto-plan"
)
```

### Phase 3: Research / Investigate

**For features (F-prefix):**
- Spawn `researcher` agent to analyze codebase patterns, integration points
- Search for similar past tickets via `get_similar_tickets`

**For bugs (B-prefix):**
- Run `/investigate` internally to find root causes
- Spawn `hypothesis-evaluator` if needed
- Create investigation artifact

### Phase 4: Create Plan

Spawn `planner` agent with all gathered context. The plan artifact must be concise and
answer three questions clearly:

1. **What** will be done (high-level, 2-3 sentences)
2. **How** it will be done (approach, key decisions)
3. **Why** this approach (tradeoffs, alternatives considered)

Also include:
- Verification strategy (how to know it works in staging and prod)
- Risks and mitigations
- Side effects

Write the plan artifact:

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="plan",
  content="<plan content>",
  command="/auto-plan"
)
```

### Phase 5: Set Status to Planned

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="planned",
  command="/auto-plan"
)
```

## Output

### On Success

```
Auto-plan complete for {ID}: {title}

Plan artifact created. Review and approve to proceed to build.

Status: planned (waiting for approval)
```

### On Failure

```
Auto-plan failed for {ID} at: {phase}

Reason: {error description}

Status reverted to: backlog
```

On failure, revert status to `backlog`:

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="backlog",
  command="/auto-plan"
)
```

## Error Handling

| Phase     | Error                    | Action                              |
| --------- | ------------------------ | ----------------------------------- |
| Validate  | Ticket not found         | STOP, report                        |
| Validate  | Wrong status             | STOP, report                        |
| Research  | Agent failure            | Log, attempt plan with less context |
| Plan      | Planner failure          | STOP, revert to backlog             |

## Relation to Other Commands

| Command       | Relationship                                        |
| ------------- | --------------------------------------------------- |
| `/plan`       | Manual version — auto-plan wraps this with status   |
| `/auto-build` | Next step after user approves the plan              |
| `/investigate`| Called internally for bug tickets                    |
| `/research`   | Called internally for feature tickets                |

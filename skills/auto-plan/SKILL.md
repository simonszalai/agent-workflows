---
name: auto-plan
description: Autonomous planning for backlog tickets. Researches, investigates, creates plan artifact, sets status to planned.
max_turns: 100
---

# Auto-Plan Command

Autonomous planning workflow that picks up a backlog ticket, researches the codebase,
creates a concise plan artifact, and marks the ticket as `planned` for user approval.

Can be invoked with an existing ticket ID or with a description/issue — if no ticket exists,
one is created automatically.

## Usage

```
/auto-plan F0009                    # Plan existing backlog ticket
/auto-plan B0003                    # Plan bug ticket (includes investigation)
/auto-plan #123                     # Find or create ticket from GitHub issue
/auto-plan                          # Create ticket from conversation context
```

## When to Use

- Scheduled agent picks up `backlog` tickets automatically
- Manual trigger when you want autonomous planning for a specific ticket
- Starting planning from a GitHub issue or conversation (ticket created automatically)

## Process Overview

```
1.  Resolve Ticket -> Find existing ticket OR create one
2.  OUTPUT         -> Print ticket ID immediately (FIRST output line)
3.  Set Status     -> Update to "in_progress"
4.  Research       -> /research for features, /investigate for bugs
5.  Plan           -> Spawn planner agent, create plan artifact
6.  Set Status     -> Update to "planned"
```

## Detailed Process

### Phase 1: Resolve Ticket

Determine whether the input is an existing ticket ID or something that needs a ticket.

**If input is a ticket ID (F/B prefix):**

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- If not found: STOP - "Ticket not found"
- If status is not `backlog`: STOP - "Ticket status is {status}, expected backlog"

**If input is a GitHub issue number or conversation context:**

First, search for an existing ticket that already tracks this work:

```
results = mcp__autodev-memory__search_tickets(
  project=PROJECT, query="<issue title or key terms from context>"
)
```

- If a matching ticket is found with status `backlog`: use that ticket
- If a matching ticket is found with another status: STOP - "Already tracked as {ID} (status: {status})"

If no existing ticket matches, create one:

```
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="<synthesized title>",
  type="bug" | "feature",
  description="<formatted description from issue or conversation>",
  status="backlog",
  tags={"github_issue": issue_number, "source": "conversation"},  # as applicable
  command="/auto-plan"
)
# ticket_id is auto-generated (e.g., F0043, B0012)
```

### Phase 1b: Output Ticket ID

**CRITICAL — this must be the first user-visible output:**

```
{ticket_id}: {title}
```

This single line is emitted immediately so the user (or calling agent) can reference the
ticket while planning proceeds. All subsequent output follows after this line.

### Phase 2: Set Status to In Progress

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="in_progress",
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
{ticket_id}: {title}

Auto-plan complete for {ticket_id}: {title}

Plan artifact created. Review and approve to proceed to build.

Status: planned (waiting for approval)

Next: Review the plan, then approve and run /auto-build {ticket_id}
```

### On Failure

```
{ticket_id}: {title}

Auto-plan failed for {ticket_id} at: {phase}

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
| Resolve   | Ticket not found         | STOP, report                        |
| Resolve   | Already tracked (not backlog) | STOP, report existing ID + status |
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
| `/auto-flow`  | Calls auto-plan as part of end-to-end workflow      |

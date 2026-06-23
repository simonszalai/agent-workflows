---
name: auto-plan
description: Autonomous planning for backlog tickets. Researches, investigates, creates plan artifact, sets status to planned. Re-run on a planned ticket to incorporate and resolve the user's dashboard review comments.
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
/auto-plan F0009                    # Re-run on a planned ticket: revise the plan to address
                                    #   the user's open dashboard review comments, then resolve them
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
5.  Plan           -> Run cross-provider /plan core, converge disagreements, create artifact
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
- If status is `backlog`: proceed with a fresh plan (the normal path).
- If status is `planned` AND `ticket["open_comment_count"] > 0`: enter **revise mode** — the user
  has left review feedback on the plan/source in the dashboard. Skip Phase 2 (leave the status as
  `planned`) and use Phase 4's "Incorporating review feedback" path instead of writing a new plan.
- Any other status (or `planned` with no open comments): STOP - "Ticket status is {status}, nothing to plan"

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

Run the `/plan` methodology with all gathered context. **Do not** bypass `/plan` by spawning
a single planner directly: cross-provider planning is core to this phase. Unless the user
explicitly passed `--solo`, the phase must run the current provider plus the two peer providers
via `external-agent --task plan`, synthesize their contributions, and iterate on material
disagreements until they converge to evidence-backed truth or become explicit blocking
`open_questions`.

The final plan artifact must be concise and answer three questions clearly:

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

**Incorporating review feedback (revise mode).** If you entered revise mode (an existing `planned`
ticket with open review comments), do **not** start a fresh plan — revise the existing one:

1. Fetch the open threads (they sit on the `source` and/or `plan` artifact — `artifact_type`,
   `selected_text`, and `anchor` tell you which part each thread refers to):
   ```
   comments = mcp__autodev-memory__list_artifact_comments(
     project=PROJECT, ticket_id=ID, repo=REPO, status="open"
   )
   ```
2. Revise the existing plan to address every thread, then persist with `update_artifact` (this
   snapshots the prior version) — not `create_artifact`:
   ```
   mcp__autodev-memory__update_artifact(
     project=PROJECT, artifact_id=<plan artifact id>,
     content="<revised plan>",
     change_note="address review comments",
     command="/auto-plan"
   )
   ```
3. Close each addressed thread with a one-line note pointing at what changed:
   ```
   mcp__autodev-memory__resolve_artifact_comment(
     project=PROJECT, comment_id=<id>,
     resolution_note="<how the revised plan addresses this>",
     command="/auto-plan"
   )
   ```
   If a comment is out of scope or you disagree, use `reply_artifact_comment` and leave it open for
   the user rather than resolving it.

### Phase 5: Set Status to Planned

Also set `summary_bullets` — a compact 3–6 bullet summary (what / why / chosen approach) derived
from the plan you just wrote. The dashboard renders these as the ticket header summary; left unset
they default to `[]` and the header stays blank. `update_ticket` **replaces** the list, so pass the
full set each time (including in revise mode, where you refresh them to match the revised plan).

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="planned",
  summary_bullets=[
    "<what the work delivers>",
    "<why / the trigger>",
    "<the chosen approach>",
    "<key risk or dependency, if any>"
  ],
  command="/auto-plan"
)
```

In revise mode the status is already `planned`; this call just refreshes `summary_bullets` (and
confirms the resting status).

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

---
name: auto-flow
description: Autonomous end-to-end workflow with ticket tracking. From GitHub issue, error report, or conversation to PR — with full ticket lifecycle management.
max_turns: 300
---

# Auto-Flow Command

Autonomous end-to-end workflow that takes a GitHub issue, error report, **or conversation
context** and delivers a complete PR — with full ticket lifecycle tracking via the autodev-memory
ticket system. Handles both features and bugs (including production incidents with
hypothesis-driven root cause analysis).

Auto-Flow delegates to `/auto-plan` and `/auto-build` — it does NOT reimplement their logic.
This means improvements to those skills automatically flow through to auto-flow.

## Usage

```
/auto-flow #123                    # GitHub issue number
/auto-flow 123                     # Same thing
/auto-flow https://github.com/org/repo/issues/123   # Full URL
/auto-flow                         # Use current conversation as input
/auto-flow B001                    # Resume existing bug work item
/auto-flow --skip-verify           # Skip local verification step
```

## When to Use

- You want fully autonomous end-to-end execution WITH ticket tracking
- Requirements are clear (from issue or conversation)
- You want the work tracked as a formal ticket (FNNN/BNNN) with status progression
- You want artifacts (plan, build_todos, review_todos) stored in the ticket system

## Relation to /lfg

| Aspect      | `/lfg`                         | `/auto-flow`                          |
| ----------- | ------------------------------ | ------------------------------------- |
| Ticket      | No ticket created              | Creates and manages ticket lifecycle  |
| Status      | No status tracking             | backlog -> planning -> planned -> ... |
| Artifacts   | Filesystem only (.context/)    | Stored in ticket system via MCP       |
| Resume      | Cannot resume                  | Resume via BNNN/FNNN                  |
| Deployment  | PR only                        | PR + `/auto-deploy` + `/auto-verify`  |

## Input Detection

Auto-Flow detects its input source automatically:

| Invocation                | Input Source  | Behavior                            |
| ------------------------- | ------------- | ----------------------------------- |
| `/auto-flow #123` or num  | GitHub issue  | Fetch issue, extract requirements   |
| `/auto-flow B001`         | Existing bug  | Resume existing BNNN work item      |
| `/auto-flow` (no args)    | Conversation  | Extract requirements from thread    |

## Process Overview

```
1.  Parse Input          -> Extract type (bug/feature), requirements from issue OR conversation
2.  Create Ticket        -> Feature (FNNN) or Bug (BNNN) via MCP (status: backlog)
3.  /auto-plan {ID}      -> Research + plan (backlog -> planning -> planned)
4.  Approve Plan         -> Set status to "approved" (auto-approved in auto-flow)
5.  /auto-build {ID}     -> Build todos + build + test + review + PR (approved -> ready_to_deploy)
```

Auto-Flow stops after auto-build. Deployment and verification are separate steps:
`/auto-deploy` and `/auto-verify`.

## Detailed Process

### Phase 1: Parse Input

Determine input source and extract requirements.

**Source A: GitHub Issue** (when invoked with issue number/URL)

1. **Fetch issue details:**

   ```bash
   gh issue view {issue_number} --json title,body,labels,author
   ```

2. **Determine issue type:**

   | Labels/Keywords           | Type    |
   | ------------------------- | ------- |
   | `bug`, `fix`, `error`     | Bug     |
   | `feature`, `enhancement`  | Feature |
   | `refactor`, `improvement` | Feature |
   | (no clear signal)         | Feature |

3. **Extract requirements:**
   - Title -> work item title
   - Body -> acceptance criteria, context
   - Labels -> tags for work item

**Source B: Conversation** (when invoked without args)

1. **Extract from conversation thread:**
   - Scan the full conversation history for the user's request
   - Identify: what they want built/fixed, any constraints, acceptance criteria
   - Determine type: bug (error reports, "fix this") vs feature (new functionality)

2. **Determine issue type:**

   | Conversation signals                          | Type    |
   | --------------------------------------------- | ------- |
   | Error reports, "fix", "broken", "not working" | Bug     |
   | Service failures, OOM, crashes, timeouts      | Bug     |
   | "Add", "build", "create", "implement"         | Feature |
   | Refactoring, cleanup, improvement              | Feature |
   | (ambiguous)                                    | Feature |

3. **For bugs — extract error context** (when available):
   - **Service name** — which service failed
   - **Error type** — crash, timeout, OOM, validation error
   - **Timestamp** — when it failed (UTC)
   - **Error message** — actual error text if available
   - **User hints** — additional context from the triggering comment

4. **Extract requirements:**
   - Synthesize a clear title from the conversation
   - Collect all stated requirements and constraints
   - Infer acceptance criteria from the discussion

5. **If context is insufficient:**

   For features:

   ```markdown
   I need more detail to proceed. Please provide:

   - What should be built or fixed
   - Expected behavior / acceptance criteria
   - Any constraints or preferences
   ```

   For bugs:

   ```markdown
   I need more detail to proceed. Please provide:

   - Service name
   - Approximate time of failure (e.g., "around 2pm UTC")
   - Error type or message if known
   ```

   Then STOP and wait for user response before continuing.

**Source C: Resume existing ticket** (when invoked with BNNN/FNNN)

1. Load the existing ticket:
   ```
   ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
   ```
2. Read the source artifact for context
3. Check ticket status and resume from the appropriate phase:

   | Current Status   | Resume From     |
   | ---------------- | --------------- |
   | `backlog`        | Phase 3 (auto-plan) |
   | `planning`       | Phase 3 (auto-plan — will resume) |
   | `planned`        | Phase 4 (approve) |
   | `approved`       | Phase 5 (auto-build) |
   | `building`       | Phase 5 (auto-build — will resume) |
   | `ready_to_deploy`| STOP — already complete, run /auto-deploy |

### Phase 2: Create Ticket

Resolve project and repo from CLAUDE.md (`<!-- mem:project=X -->`) and git remote.

**Create a ticket via MCP:**

```
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="<synthesized title>",
  type="bug" | "feature",
  description="<formatted description>",
  status="backlog",
  tags={"github_issue": issue_number, "source": "conversation"},  # as applicable
  command="/auto-flow"
)
# ticket_id is auto-generated (e.g., F0043, B0012)
```

**Description content by input source:**

**For GitHub issue input:**
Include issue number, author, labels, body, and extracted acceptance criteria.

**For conversation input (features):**
Include context summary, requirements, and acceptance criteria.

**For conversation input (bugs):**
Include service name, error time, error type, error message, and user context.

### Phase 3: Auto-Plan

Run `/auto-plan {ticket_id}` — this handles:

- Setting status to `planning`
- Running `/research` (features) or `/investigate` (bugs)
- Spawning `planner` agent to create plan artifact
- Setting status to `planned`

**On failure:** STOP, report error. Ticket status reverts to `backlog`.

### Phase 4: Approve Plan

In auto-flow mode, the plan is **auto-approved** (no user confirmation needed).

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="approved",
  command="/auto-flow"
)
```

### Phase 5: Auto-Build

Pass `--skip-verify` flag if `/auto-flow --skip-verify` was used.

Run `/auto-build {ticket_id}` — this handles:

- Setting status to `building`
- Creating branch
- Running `/create-build-todos`
- Running `/build`
- Running `/write-tests` (MANDATORY)
- Running `/review` + `/resolve-review` loop
- Running `/compound`
- Creating deployment guide
- Running `/verify local` (unless --skip-verify)
- Running `/create-pr`
- Setting status to `ready_to_deploy`

**On failure:** STOP, report error. Ticket status reverts to `approved`.

## Error Handling

| Phase        | Error                  | Action                          |
| ------------ | ---------------------- | ------------------------------- |
| Parse Input  | Can't fetch issue      | STOP, report error              |
| Parse Input  | Insufficient context   | Ask user for details, then STOP |
| Create Ticket| Creation fails         | STOP, report error              |
| Auto-Plan    | Any failure            | STOP, report (auto-plan reverts)|
| Auto-Build   | Any failure            | STOP, report (auto-build reverts)|

## Ticket Artifacts

All artifacts are stored in the MCP ticket system, not on the filesystem.
Artifacts are created by the delegated skills (auto-plan, auto-build).

**For features (e.g., F0042):**

| Artifact Type | Created By |
|---|---|
| `source` | /auto-flow (Phase 2) |
| `investigation` | /auto-plan -> /research |
| `plan` | /auto-plan -> /plan |
| `build_todo` (seq 1-N) | /auto-build -> /create-build-todos |
| `review_todo` (seq 1-N) | /auto-build -> /review |
| `learning_report` | /auto-build -> /compound |

**For bugs (e.g., B0001):**

| Artifact Type | Created By |
|---|---|
| `source` | /auto-flow (Phase 2) |
| `investigation` | /auto-plan -> /investigate |
| `plan` | /auto-plan -> /plan |
| `build_todo` (seq 1-N) | /auto-build -> /create-build-todos |
| `review_todo` (seq 1-N) | /auto-build -> /review |
| `learning_report` | /auto-build -> /compound |

## Output

### On Success

```
Auto-flow complete!

PR: https://github.com/org/repo/pull/456
Issue: #123                              # Only shown if source was GitHub issue

Summary:
- Implemented user dashboard feature
- Tests: 12 passing / 12 total (4 unit, 6 integration, 2 e2e)
- Review: 3 iterations, all P1/P2 resolved

Ticket: F0042 (ready_to_deploy)
Next: /auto-deploy F0042
```

### On Partial Success

```
Auto-flow needs attention!

PR: https://github.com/org/repo/pull/456 (marked needs attention)
Issue: #123                              # Only shown if source was GitHub issue

Summary:
- Implemented user dashboard feature
- Tests: 11 passing / 12 total (1 flaky e2e)
- 2 P3 findings remain (not blocking)

Ticket: F0042 (ready_to_deploy)
Next: /auto-deploy F0042
```

### On Failure

```
Auto-flow failed at: {phase}

Issue: #123                              # Only shown if source was GitHub issue
Reason: {error description}

Ticket created: F0042
See ticket F0042 for partial progress
```

## Differences from Running Steps Manually

| Aspect          | Manual steps          | /auto-flow                            |
| --------------- | --------------------- | ------------------------------------- |
| Trigger         | You run each command  | One command does everything            |
| Plan approval   | You review plan first | Auto-approved                         |
| Review handling | You decide on findings| Loop until no P1/P2                   |
| Scope           | Any ticket            | Creates ticket from issue/conversation |
| Stops at        | Wherever you stop     | ready_to_deploy (PR created)          |

## Pipeline Position

```
/auto-flow = /auto-plan + approve + /auto-build

Full pipeline (run separately):
/auto-plan -> [user approves] -> /auto-build -> /auto-deploy -> /auto-verify staging -> /auto-verify prod
```

## Example Flows

### Example A: From GitHub Issue

**GitHub Issue #123:**

```
Title: Add user activity dashboard
Labels: feature, enhancement
Body:
Users should be able to see their recent activity including:
- Documents created in last 30 days
- Recent edits
- Pending approvals

Should integrate with existing analytics.
```

**Auto-flow execution:**

1. Parse: source=github, type=feature, title="Add user activity dashboard"
2. Create: `ticket F0042 via MCP` (status: backlog)
3. /auto-plan F0042: research + plan (backlog -> planning -> planned)
4. Approve: set status to approved
5. /auto-build F0042: build + test + review + PR (approved -> ready_to_deploy)

**Output:**

```
Auto-flow complete!

PR: https://github.com/org/repo/pull/456
Issue: #123

Summary:
- Implemented user activity dashboard
- Tests: 12 passing / 12 total
- Review: 3 iterations, all P1/P2 resolved

Ticket: F0042 (ready_to_deploy)
Next: /auto-deploy F0042
```

### Example B: From Conversation

**Conversation:**

```
User: "I want to add a bulk export button to the invoices list. It should let
users select multiple invoices and download them as a single ZIP of PDFs. Only
finalized invoices should be exportable."
```

**Auto-flow execution:**

1. Parse: source=conversation, type=feature, title="Bulk invoice PDF export"
2. Create: `ticket F0043 via MCP` (status: backlog)
3. /auto-plan F0043: research + plan
4. Approve: auto-approved
5. /auto-build F0043: build + test + review + PR

**Output:**

```
Auto-flow complete!

PR: https://github.com/org/repo/pull/790

Summary:
- Implemented bulk invoice PDF export
- Tests: 6 passing / 6 total (2 unit, 3 integration, 1 e2e)
- Review: 2 iterations, all P1/P2 resolved

Ticket: F0043 (ready_to_deploy)
Next: /auto-deploy F0043
```

### Example C: Bug Fix from Error Report

**Conversation:**

```
User: "Fix this - seeing OOM on large batches lately. Service main-processor
failed at 14:23 UTC with exit code -9"
```

**Auto-flow execution:**

1. Parse: source=conversation, type=bug, service=main-processor, error=OOM
2. Create: `ticket B0001 via MCP` (status: backlog)
3. /auto-plan B0001: investigate (hypotheses + evaluation) + plan
4. Approve: auto-approved
5. /auto-build B0001: build + test + review + PR

**Output:**

```
Auto-flow complete!

PR: https://github.com/org/repo/pull/456

Root cause: Memory exhaustion on large batches (>500 items)
Fix: Added batch size limit of 200 items with chunked processing
Tests: 5 passing / 5 total
Review: No critical findings

Ticket: B0001 (ready_to_deploy)
Next: /auto-deploy B0001
```

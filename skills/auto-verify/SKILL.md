---
name: auto-verify
description: Autonomous verification. Verifies ticket on staging (then merges PR) or local. Takes environment arg.
max_turns: 100
---

# Auto-Verify Command

Autonomous verification that picks up tickets, runs verification against the target environment,
and on success advances the pipeline (merge PR on staging, mark complete on local).

## Usage

```
/auto-verify staging F007           # Verify feature F007 on staging
/auto-verify local B003             # Verify bug fix B003 locally
/auto-verify staging                # (scheduled) Pick up next to_verify_staging ticket
```

First argument is the environment: `staging` or `local`.
Second argument is the ticket ID.

## Environment Config

**Read `.claude/{env}.md`** (e.g., `.claude/staging.md` or `.claude/local.md`) for:
- URL, service IDs, credentials
- DB MCP tool name
- Auth/login flow
- Known console errors to ignore

**Read `.claude/staging.md`** for the shared **project map** (routes, entities, dependencies,
test data templates) — it's the same across all environments.

## When to Use

- Scheduled agent picks up `to_verify_staging` or `to_verify_local` tickets automatically
- Manual trigger after a build has been deployed

## Prerequisites

- Ticket must exist with status `to_verify_{env}`
- Plan artifact must exist with verification strategy
- For staging: PR must exist and be deployed
- For local: local services must be running

## Process Overview

```
1.  Load Config      -> Read .claude/{env}.md + project map from staging.md
2.  Validate         -> Check ticket exists, status is to_verify_{env}
3.  Find PR          -> (staging only) Locate the open PR
4.  Verify           -> Run verification against target environment
5.  On PASS:
    staging: Merge PR -> Deploy to prod -> Set "to_verify_prod"
    local:   Set "to_verify_staging" (ready for staging deploy)
6.  On FAIL:
    Set "verify_{env}_failed"
```

## Detailed Process

### Phase 1: Load Config

Read `.claude/{env}.md` to get:
- Environment URL
- Auth credentials / login method
- DB MCP tool name
- Service IDs (if applicable)

Read `.claude/staging.md` for the project map (routes, entities, dependencies) —
this is shared across all environments.

### Phase 2: Validate Ticket

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- If not found: STOP - "Ticket not found"
- If status is not `to_verify_{env}`: STOP - "Ticket status is {status}, expected to_verify_{env}"
- Read plan artifact for verification strategy

### Phase 3: Find PR (staging only)

```bash
gh pr list --search "auto-build/{ticket-id}" --state open --json number,url
# or
gh pr list --search "lfg/{ticket-id}" --state open --json number,url
```

If no PR found: STOP - "No open PR found for this ticket"

### Phase 4: Verify

Spawn `verifier` agent targeting the environment:

1. **Check service health:**
   - Staging: verify deploy completed, service responsive
   - Local: verify dev server running, DB accessible

2. **Run verification scenarios from plan:**
   - Use the verification strategy from the plan artifact
   - Check database state using the DB MCP tool from env config
   - Verify API endpoints respond correctly
   - For UI changes: browser-based verification using the login flow from env config

3. **Check for errors:**
   - Search logs for errors since deployment (staging) or during test (local)
   - Ignore known console errors listed in `staging.md`
   - Verify no new error patterns appeared

### Phase 5a: On PASS

**Staging:**
1. Merge PR to main: `gh pr merge {pr_number} --merge`
2. Wait for production deploy
3. Set status to `to_verify_prod`

**Local:**
1. Set status to `to_verify_staging` (ready for staging deploy)

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="{next_status}",
  command="/auto-verify"
)
```

### Phase 5b: On FAIL

1. **Create verification report** as artifact documenting what failed
2. **Set status to `verify_{env}_failed`**
3. **Do NOT close/merge the PR** (staging) — leave open for investigation

## Output

### On PASS (staging)

```
Staging verification PASSED for {ID}: {title}

PR #{pr_number} merged to main.
Production deploy initiated.

Status: to_verify_prod (waiting for production verification)
```

### On PASS (local)

```
Local verification PASSED for {ID}: {title}

Status: to_verify_staging (ready for staging deploy)
```

### On FAIL

```
{Env} verification FAILED for {ID}: {title}

Issues found:
- {issue 1}
- {issue 2}

Status: verify_{env}_failed (needs manual triage)
```

## Error Handling

| Phase    | Error                | Action                             |
| -------- | -------------------- | ---------------------------------- |
| Config   | Env file not found   | STOP, report                       |
| Validate | Ticket not found     | STOP, report                       |
| Validate | Wrong status         | STOP, report                       |
| Find PR  | No PR found          | STOP, report (staging only)        |
| Verify   | Environment down     | STOP, report (don't change status) |
| Merge    | Merge conflict       | STOP, set verify_staging_failed    |
| Merge    | CI checks failing    | STOP, set verify_staging_failed    |

## Relation to Other Commands

| Command        | Relationship                                       |
| -------------- | -------------------------------------------------- |
| `/auto-build`  | Previous step — creates the PR deployed to staging |
| `/auto-qa`     | Broader QA — tests entire app, not one ticket      |
| `/verify local`| Manual local verification (no ticket pipeline)     |
| `/verify prod` | Manual production verification                     |

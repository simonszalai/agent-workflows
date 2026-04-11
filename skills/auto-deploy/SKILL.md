---
name: auto-deploy
description: Autonomous deployment. Deploys PR to staging, runs migrations, updates ticket status.
max_turns: 100
---

# Auto-Deploy Command

Autonomous deployment that picks up `ready_to_deploy` tickets, deploys their PR to staging
(running migrations and any required infrastructure changes), and advances the ticket to
`to_verify_staging`.

## Usage

```
/auto-deploy F007                   # Deploy feature F007 to staging
/auto-deploy B003                   # Deploy bug fix B003 to staging
/auto-deploy                        # (scheduled) Pick up next ready_to_deploy ticket
```

## When to Use

- After `/auto-build` completes and PR is ready
- Scheduled agent picks up `ready_to_deploy` tickets automatically
- Manual trigger when you want to deploy a specific ticket

## Prerequisites

- Ticket must exist with status `ready_to_deploy`
- PR must exist for the ticket (on `auto-build/{ID}` or `lfg/{ID}` branch)
- CI checks must be passing on the PR

## Process Overview

```
1.  Validate     -> Check ticket exists, status is ready_to_deploy
2.  Find PR      -> Locate the open PR for this ticket
3.  Check CI     -> Verify CI checks are passing
4.  Merge PR     -> Merge PR to main
5.  Migrations   -> Check if migrations need to run (CI auto-deploys on merge)
6.  Wait Health  -> Verify staging service is healthy after deploy
7.  Set Status   -> Update to "to_verify_staging"
```

## Detailed Process

### Phase 1: Validate Ticket

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- If not found: STOP - "Ticket not found"
- If status is not `ready_to_deploy`: STOP - "Ticket status is {status}, expected ready_to_deploy"
- Read plan artifact for deployment context

### Phase 2: Find PR

```bash
gh pr list --search "auto-build/{ticket-id} OR lfg/{ticket-id}" --state open --json number,url,headRefName
```

If no PR found: STOP - "No open PR found for this ticket"

### Phase 3: Check CI

```bash
gh pr checks {pr_number}
```

- If checks failing: STOP - "CI checks failing, cannot deploy"
- If checks pending: Wait up to 10 minutes, then STOP if still pending

### Phase 4: Merge PR

```bash
gh pr merge {pr_number} --merge
```

This triggers:
- CI `migrate.yml` runs Alembic migrations automatically on merge to main
- For ts-prefect: flows pull latest code from git at runtime (no Render deploy needed)
- For other services: Render auto-deploy if enabled, or manual deploy required

### Phase 5: Check Migrations

Check if the PR includes migration files:

```bash
gh pr diff {pr_number} --name-only | grep -E "alembic/versions/|migrations/"
```

If migrations exist:
- CI handles this automatically via `migrate.yml`
- Log: "Migration detected — CI will auto-apply on merge"

If deployment guide artifact exists:
- Read it and log any manual steps required
- Flag manual steps to user if any exist

### Phase 6: Wait for Health

For services that need Render deploy:
- Check if PR changed pyproject.toml, Dockerfile, or env vars
- If yes: flag that Render redeploy is needed (manual step)
- If no: service picks up code from git on next run

For staging health check:
- Wait for staging service to be responsive
- Verify no new errors in logs since merge

### Phase 7: Set Status

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="to_verify_staging",
  command="/auto-deploy"
)
```

## On Failure — Revert Status

If deploy fails at any phase, revert status:

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="ready_to_deploy",
  command="/auto-deploy"
)
```

## Error Handling

| Phase    | Error                | Action                                   |
| -------- | -------------------- | ---------------------------------------- |
| Validate | Ticket not found     | STOP, report                             |
| Validate | Wrong status         | STOP, report                             |
| Find PR  | No PR found          | STOP, report                             |
| Check CI | Checks failing       | STOP, report (don't change status)       |
| Merge    | Merge conflict       | STOP, report (don't change status)       |
| Merge    | Branch protection    | STOP, report                             |
| Health   | Service unhealthy    | Set verify_staging_failed, report        |
| Health   | Render deploy needed | Flag to user, still set to_verify_staging|

## Output

### On Success

```
Auto-deploy complete for {ID}: {title}

PR #{pr_number} merged to main.
Migrations: {detected/none}
Service health: OK

Status: to_verify_staging (ready for verification)
```

### On Failure

```
Auto-deploy failed for {ID} at: {phase}

Reason: {error description}

Status reverted to: ready_to_deploy
```

## Relation to Other Commands

| Command        | When to Use                                          |
| -------------- | ---------------------------------------------------- |
| `/auto-build`  | Previous step — creates PR, sets ready_to_deploy     |
| `/auto-deploy` | This command — merges PR, deploys to staging         |
| `/auto-verify` | Next step — verifies staging, advances to prod       |
| `/deploy`      | Manual deployment (no ticket pipeline)               |

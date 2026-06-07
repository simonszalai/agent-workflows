---
name: ticket-verify
description: Timer-friendly evidence collection for tickets in staging or production verification states. Takes staging or production as first argument. Read-only while verifying; staging PASS automatically calls ticket-promote unless disabled.
max_turns: 200
---

# Ticket Verify

Verify tickets that are already landed and waiting for environment evidence.

Use this instead of legacy `/auto-verify`.

## Usage

```text
/ticket-verify staging              # verify all tickets in to_verify_staging
/ticket-verify production           # verify all tickets in to_verify_prod
/ticket-verify staging F0123 B0042
/ticket-verify production F0123 --lookback 24h
/ticket-verify staging --no-promote # report staging PASS but do not call ticket-promote
```

First argument must be `staging`, `prod`, or `production`.

## Boundaries

- Verification evidence collection is read-only: no data mutation, no flow triggers, no deploys.
- On staging PASS, this skill normally invokes `/ticket-promote` for that ticket. Promotion is a
  separate landing step, not part of evidence collection.
- On production PASS, set ticket status to `completed`.
- On failure, set `verify_staging_failed` or `verify_prod_failed`.

## Process

### 1. Select tickets

If explicit ticket IDs are provided, load those. Otherwise:

- `staging` -> `list_tickets(status="to_verify_staging")`
- `production` -> `list_tickets(status="to_verify_prod")`

Skip `abandoned`, `completed`, source tickets, and epic step tickets whose parent milestone owns
verification.

### 2. Load context

For each ticket:

- `get_ticket` with artifacts/events;
- read source, plan, deployment guide, review notes;
- find PR/commit/landing branch from events, tags, PR title, or git history;
- read `.claude/environments/{env}.md` when present.

### 3. Determine activation boundary

Do not use naive wall-clock lookback when a commit boundary is available.

- Production: commit landed on `origin/main`.
- Staging: commit landed on `origin/staging`.
- Projects that pull code from git at runtime: activation may be the first run after git land;
  measure feature fill rates from the first post-land evidence row, not just merge time.

### 4. Collect evidence

Spawn/read-only verification work as needed:

- affected flows/jobs since activation;
- service logs since activation;
- database state and data quality using read-only queries;
- feature-specific success-path logs or rows;
- bug hypothesis re-evaluation when investigation artifacts contain confirmed hypotheses.

Every claim must include a reproducible command/query, expected good output, and bad-output
interpretation.

### 5. Verdict

Use:

- `PASS` — acceptance criteria met and no related failures;
- `FAIL` — evidence shows broken behavior or missing expected activity;
- `NEEDS_MORE_TIME` — not enough post-land activity yet.

### 6. Status and promotion

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | call `/ticket-promote <ID>` unless `--no-promote` |
| staging | FAIL | create verification report artifact; status `verify_staging_failed` |
| staging | NEEDS_MORE_TIME | leave status unchanged |
| production | PASS | create verification report artifact; status `completed` |
| production | FAIL | create verification report artifact; status `verify_prod_failed` |
| production | NEEDS_MORE_TIME | leave status unchanged |

When staging PASS calls `/ticket-promote`, the final status should usually become
`to_verify_prod` after promotion lands on `main`.

## Output

Report one table for all selected tickets:

```text
Ticket  Env      Verdict          Action
F0123   staging  PASS             promoted -> to_verify_prod
B0042   staging  NEEDS_MORE_TIME  left to_verify_staging
F0125   staging  FAIL             verify_staging_failed
```

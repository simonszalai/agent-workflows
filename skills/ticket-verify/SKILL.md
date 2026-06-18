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
- read source, plan, review notes;
- read the **`deployment_guide` artifact** — its **Verification Evidence** section is the
  contract you grade against. Each row is one evidence item: a reproducible query/command, an
  expected good output, and a bad-output interpretation, listed per environment (staging / prod).
  Also read its **Activation boundary**. If the artifact is missing or its evidence rows are still
  `TBD`/empty, fall back to deriving evidence from source + plan acceptance criteria, and flag in
  the report that the ticket shipped without a finalized evidence contract;
- find PR/commit/landing branch from events, tags, PR title, or git history;
- read `.claude/environments/{env}.md` when present.

### 3. Determine activation boundary

Do not use naive wall-clock lookback when a commit boundary is available.

- Production: commit landed on `origin/main`.
- Staging: commit landed on `origin/staging`.
- Projects that pull code from git at runtime: activation may be the first run after git land;
  measure feature fill rates from the first post-land evidence row, not just merge time.

### 4. Collect evidence

Run **every** Verification Evidence item listed for the environment being verified (staging items
for staging, prod items for prod) — execute each item's query/command and compare against its
expected good output. Then supplement with read-only checks as needed:

- affected flows/jobs since activation;
- service logs since activation;
- database state and data quality using read-only queries;
- feature-specific success-path logs or rows;
- bug hypothesis re-evaluation when investigation artifacts contain confirmed hypotheses.

Every claim must include a reproducible command/query, expected good output, and bad-output
interpretation. Record, per evidence item, whether it passed, failed, or had no post-activation
data yet.

### 5. Verdict

The deployment_guide evidence contract is the gate — verdict is determined by the env's evidence
items:

- `PASS` — **every** evidence item for this environment passed, and no related failures surfaced;
- `FAIL` — any evidence item shows broken behavior or expected-but-missing activity;
- `NEEDS_MORE_TIME` — one or more evidence items have no post-activation data yet (and none have
  failed).

When the evidence contract was missing/`TBD` and you fell back to acceptance criteria, say so in
the report so the gap is visible rather than silently passing.

### 6. Status and promotion

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | set status `staging_verified` (green "Ready for prod" flag), then call `/ticket-promote <ID>` unless `--no-promote` or the ticket is held for a batched promotion |
| staging | FAIL | create verification report artifact; status `verify_staging_failed` |
| staging | NEEDS_MORE_TIME | leave status unchanged |
| production | PASS | create verification report artifact; status `completed` |
| production | FAIL | create verification report artifact; status `verify_prod_failed` |
| production | NEEDS_MORE_TIME | leave status unchanged |

`staging_verified` is the resting "passed staging, ready for prod" state — the
green-flag counterpart of `verify_staging_failed`. It keeps a verified ticket
visible on the board (Verify-staging lane) instead of leaving it
indistinguishable from one still awaiting verification. Set it on every staging
PASS, **including** tickets that must NOT be promoted individually (e.g. ones
held for a batched epic promotion, or a ticket whose own artifacts forbid a solo
cherry-pick): those rest in `staging_verified` rather than advancing.

When staging PASS then calls `/ticket-promote`, the status advances from
`staging_verified` to `to_verify_prod` once the promotion lands on `main`.

## Output

Report one table for all selected tickets:

```text
Ticket  Env      Verdict          Action
F0123   staging  PASS             promoted -> to_verify_prod
B0042   staging  NEEDS_MORE_TIME  left to_verify_staging
F0125   staging  FAIL             verify_staging_failed
```

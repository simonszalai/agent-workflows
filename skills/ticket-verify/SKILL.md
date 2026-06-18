---
name: ticket-verify
description: Timer-friendly evidence collection for tickets or explicit epic/milestone gates in staging or production. Read-only while verifying; standalone staging PASS promotes unless disabled.
max_turns: 200
---

# Ticket Verify

Verify tickets, or an explicit epic/milestone gate, after code has landed and deployment has
completed. Use this instead of legacy `/auto-verify`.

## Usage

```text
/ticket-verify staging              # verify all standalone tickets in to_verify_staging
/ticket-verify production           # verify all standalone tickets in to_verify_prod
/ticket-verify staging F0123 B0042
/ticket-verify production F0123 --lookback 24h
/ticket-verify staging --no-promote # report staging PASS but do not call ticket-promote

/ticket-verify staging --epic E0007 --milestone M2 --no-promote
/ticket-verify production --epic E0007
/ticket-verify production --epic E0007 --milestone M2
```

First argument must be `staging`, `prod`, or `production`.

## Boundaries

- Verification evidence collection is read-only: no data mutation, no flow triggers, no deploys.
- On standalone staging PASS, this skill normally invokes `/ticket-promote` for that ticket.
  Promotion is a separate landing step, not part of evidence collection.
- In explicit `--epic`/`--milestone` mode, do **not** auto-promote. The parent `/epic-auto`
  controls milestone progression and production promotion.
- On production PASS, set standalone ticket status to `completed`. In epic mode, update the
  parent epic/milestone gate and included step tickets according to the epic lifecycle.
- On failure, set `verify_staging_failed` or `verify_prod_failed` on the standalone ticket, or
  record the failed epic/milestone gate and failed evidence rows for `/epic-auto`'s fix loop.
- Verification stays read-only with ONE exception: on **production PASS**, a ticket may carry a
  deferred post-verification cleanup that runs only after the PASS verdict is recorded (see §8).

## Process

### 1. Select scope

If `--epic` is provided:

1. Load `get_epic(project, epic_id)` with artifacts, milestones, step tickets, events, and
   blockers.
2. If `--milestone` is present, restrict verification to that milestone's step tickets and gate
   package. If not present, verify the final/current production gate for all completed milestones.
3. Include epic step tickets explicitly. The default queue skip for epic steps does not apply
   when the parent epic/milestone is the requested scope.

If explicit ticket IDs are provided, load those. Otherwise:

- `staging` -> `list_tickets(status="to_verify_staging")`
- `production` -> `list_tickets(status="to_verify_prod")`

For the default queue mode, skip `abandoned`, `completed`, source tickets, and epic step tickets
whose parent milestone owns verification.

### 2. Load context

For each standalone ticket, or for the epic/milestone gate as a unit:

- load ticket/epic artifacts and events;
- read source, plan, review notes, and milestone acceptance criteria;
- read the **`deployment_guide` artifact** — its **Verification Evidence** section is the
  contract you grade against. Each row is one evidence item: a reproducible query/command, an
  expected good output, and a bad-output interpretation, listed per environment (staging / prod).
  Also read its **Activation boundary**. If the artifact is missing or its evidence rows are still
  `TBD`/empty, fall back to deriving evidence from source + plan acceptance criteria, and flag in
  the report that the work shipped without a finalized evidence contract;
- find PR/commit/landing branch from events, tags, PR title, or git history;
- read `.claude/environments/{env}.md` when present.

### 3. Determine activation boundary

Do not use naive wall-clock lookback when a commit boundary is available.

- Production: commit landed on `origin/main`.
- Staging: commit landed on `origin/staging`.
- Epic/milestone staging: use the latest included milestone step commit on the staging target and
  the deploy completion time from `/auto-deploy <EPIC_ID> staging`.
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

### 5. Epic/milestone aggregation

In `--epic` mode, produce one gate verdict for the requested scope:

- include every evidence row from the milestone gate package or final epic deployment guide;
- for a non-first staging milestone, include an impact-based regression subset from earlier
  passed milestone gates so later work cannot silently break already-verified epic behavior;
- map each failed row to the most likely step ticket(s) and contract edge(s);
- prove every included step commit is present on the expected branch (`origin/staging` for
  staging, `origin/main` for production);
- do not pass the gate just because individual step tickets look healthy; the milestone's
  acceptance criteria and cross-step contracts must pass as a unit.

### 6. Verdict

The deployment_guide evidence contract is the gate — verdict is determined by the env's evidence
items:

- `PASS` — **every** evidence item for this environment passed, and no related failures surfaced;
- `FAIL` — any evidence item shows broken behavior or expected-but-missing activity;
- `NEEDS_MORE_TIME` — one or more evidence items have no post-activation data yet (and none have
  failed).

When the evidence contract was missing/`TBD` and you fell back to acceptance criteria, say so in
the report so the gap is visible rather than silently passing.

### 7. Status and promotion

Standalone ticket mode:

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | set status `staging_verified` (green "Ready for prod" flag), then call `/ticket-promote <ID>` unless `--no-promote` or the ticket is held for a batched promotion |
| staging | FAIL | create verification report artifact; status `verify_staging_failed` |
| staging | NEEDS_MORE_TIME | leave status unchanged |
| production | PASS | create verification report artifact; status `completed`; then run any deferred post-verification cleanup (see §8) |
| production | FAIL | create verification report artifact; status `verify_prod_failed` |
| production | NEEDS_MORE_TIME | leave status unchanged |

`staging_verified` is the resting "passed staging, ready for prod" state — the green-flag
counterpart of `verify_staging_failed`. Set it on every staging PASS, **including** tickets that
must NOT be promoted individually (e.g. ones held for a batched epic promotion, or a ticket whose
own artifacts forbid a solo cherry-pick): those rest in `staging_verified` rather than advancing.

Epic/milestone mode:

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | create gate report artifact; mark the milestone staging gate passed; set included step tickets to `staging_verified`/ready-for-parent-promotion when the lifecycle supports it; do **not** call `/ticket-promote` |
| staging | FAIL | create gate report artifact with failed evidence-to-step mapping; leave the milestone unpassed for `/epic-auto` fix loop |
| staging | NEEDS_MORE_TIME | create/update gate report artifact; leave milestone and step statuses unchanged |
| production | PASS | create final production gate report; mark included step tickets `completed` when their parent epic owns completion; mark epic complete only if all milestones are done |
| production | FAIL | create gate report artifact; mark epic/affected step production verification failed if supported, otherwise record blocker/failure metadata |
| production | NEEDS_MORE_TIME | leave statuses unchanged |

When staging PASS then calls `/ticket-promote` in standalone mode, the status advances from
`staging_verified` to `to_verify_prod` once the promotion lands on `main`.

### 8. Deferred post-verification cleanup (production PASS only)

Some tickets carry a cleanup action that must run only once the fix is confirmed live in
production — never before. This is the single mutation ticket-verify may perform, and only after
a `PASS` verdict has been recorded for that ticket.

If a production-PASS ticket has a `flow-run-cleanup` artifact:

1. Fetch the artifact and write its JSON body to a temp file.
2. Run its `cleanup_command`, appending `--artifact <temp-file>`, `--fix-time <activation
   boundary from §3>`, `--execute`, and any flag the command documents for non-interactive use
   (e.g. `--yes`).
3. Fold the command's reported counts into the verdict output.

The artifact is the complete, self-describing contract — ticket-verify needs no project-specific
knowledge; it just runs the command the artifact names. A ticket without such an artifact has no
cleanup step, and a non-PASS verdict never triggers one.

## Output

Report one table for all selected tickets or gate scopes:

```text
Scope            Env      Verdict          Action
F0123            staging  PASS             promoted -> to_verify_prod
B0042            staging  NEEDS_MORE_TIME  left to_verify_staging
E0007/M2         staging  PASS             milestone gate passed; held for epic promotion
E0007/final      prod     PASS             epic completed
```

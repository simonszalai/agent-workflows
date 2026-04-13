---
name: auto-verify
description: Observe staging or production to collect evidence that a ticket's changes are deployed and working. Read-only — never modifies data or triggers processes.
max_turns: 100
---

# Auto-Verify

Observe a target environment to collect tangible evidence that a ticket's changes have been
deployed and are working as expected. This command is **strictly read-only** — it never modifies
data, seeds records, runs flows, or triggers any process.

## Usage

```
/auto-verify staging F007           # Verify feature F007 on staging
/auto-verify prod B003              # Verify bug fix B003 in production
/auto-verify staging                # (scheduled) Pick up next to_verify_staging ticket
/auto-verify prod F001 --lookback 24h  # Custom lookback window
```

First argument is the environment: `staging` or `prod`.
Second argument is the ticket ID (or omit for scheduled pickup).

## Core Principle

**Collect evidence. Nothing else.**

- Observe database state (read-only queries)
- Read Prefect flow run statuses and logs
- Read Render service logs
- Read git history to determine deployment boundary
- Produce a report with reproducible commands

**Never:**

- Modify any data (no INSERT, UPDATE, DELETE)
- Seed test records
- Run or trigger flows
- Deploy code
- Start services

## Environment Config

**Read `.claude/environments/{env}.md`** (e.g., `.claude/environments/staging.md` or `.claude/environments/prod.md`) for:

- URL, service IDs, credentials
- DB MCP tool name
- Auth/login flow
- Known console errors to ignore

**Read `.claude/environments/staging.md`** for the shared **project map** (routes, entities, dependencies) —
it's the same across all environments.

## Prerequisites

- Ticket must exist with status `to_verify_staging` or `to_verify_prod`
- Plan artifact must exist with verification strategy
- For staging: PR must exist and be deployed

## Process

### Phase 1: Load Context

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- If not found: STOP - "Ticket not found"
- If status is not `to_verify_{env}`: STOP - "Ticket status is {status}, expected to_verify_{env}"
- Read plan artifact for verification strategy
- Read source artifact for acceptance criteria

### Phase 2: Determine Deployment Boundary

**Do NOT use a naive time-based lookback.** Find the actual deployment time:

```bash
# Find when the relevant commit landed on main
git log origin/main --oneline -10

# The deployment time = when the commit was pushed to main
git log origin/main -1 --format="%H %ci"
```

For staging: Find the PR, check when it was deployed to staging.

**For projects that pull code from git at runtime (e.g., ts-prefect):** Code changes take effect
on the next flow run after the commit is pushed. The deployment boundary is the git push
timestamp.

The `--lookback` flag is a fallback when deployment time can't be determined.

### Phase 3: Find PR (staging only)

```bash
gh pr list --search "auto-build/{ticket-id}" --state open --json number,url
# or
gh pr list --search "lfg/{ticket-id}" --state open --json number,url
```

If no PR found: STOP - "No open PR found for this ticket"

### Phase 4: Collect Evidence

Spawn `verifier` agent(s) to observe different aspects simultaneously. All agents are
**read-only** — they query and report, nothing else.

#### Focus 1: Prefect Flow Health

```
Check Prefect flow runs for affected deployments:
- List all flow runs since $DEPLOY_TIME
- Check states: COMPLETED vs FAILED vs CRASHED
- For failures: get full logs and error tracebacks
- Check task run states within flows
- Calculate success rate
- Provide the exact Prefect CLI commands used so user can re-run them
```

#### Focus 2: Service Logs (Render)

```
Check Render service logs for affected services:
- Search for error-level logs since $DEPLOY_TIME
- Search for warning-level logs mentioning the feature
- Search for success-path log messages (feature-specific keywords)
- If success messages are ABSENT but the service is running, that's a red flag
- Provide log snippets as evidence
```

#### Focus 3: Database State

```
Verify expected database changes exist (READ-ONLY):
- Query tables mentioned in the plan/description
- Check new columns have data
- Verify row counts are growing (if applicable)
- Check for orphaned records or constraint violations
- Provide exact SQL queries so user can re-run them
```

#### Focus 4: Data Quality

```
Validate the quality of new data (READ-ONLY):
- Sample recent records affected by the feature
- Verify values are in expected ranges
- Check for unexpected nulls or empty values
- Compare against historical patterns (before vs after deployment)
```

**CRITICAL: Fill Rate Measurement Boundary**

For projects that pull code from git at runtime, there is a lag between when the commit merges
and when the new code actually starts executing. Using the merge timestamp as the measurement
boundary will include records processed by OLD code, deflating fill rates.

**Correct approach:**

1. Find when the new code actually activated:
   ```sql
   SELECT MIN(created_at) as code_activated_at
   FROM table WHERE new_field IS NOT NULL AND created_at > '[merge_timestamp]';
   ```
2. Measure fill rates only from that activation boundary forward
3. Report: "Code activated at [time]. Since then: N records, X% fill rate"

### Phase 4b: Re-Evaluate Original Hypotheses (Bug Fixes Only)

For bug-fix tickets (B-prefix) that have hypothesis evaluation artifacts, re-evaluate
the confirmed hypothesis against **post-deployment** data to verify the fix addressed the
root cause.

| Condition | Run Phase 4b? |
|---|---|
| `hypothesis-evaluation/` exists with CONFIRMED hypothesis | **Yes** |
| Bug fix without hypothesis evaluation | No |
| Feature work item (FNNN) | No |

Spawn `hypothesis-evaluator` agent in parallel:

```
Post-deployment re-evaluation of previously confirmed hypothesis:

Original hypothesis: [H1 statement]
Original verdict: CONFIRMED
Original evidence: [summary]
Fix deployed: [description]
Deployment time: [timestamp]

Verify the root cause is NO LONGER present:
- The original symptom should be gone
- The testable prediction should now show the FIXED state
- No new related failures should appear

Return verdict: RESOLVED | STILL_PRESENT | INCONCLUSIVE with evidence.
```

### Phase 5: Verify Feature Activity (Not Just Absence of Errors)

**Features with graceful degradation can fail silently.** A feature that catches exceptions and
returns empty/default values will appear to "work" while providing zero value.

1. **Check flow logs for feature-specific messages** — if success messages are absent,
   the feature may not be executing
2. **Check database for evidence of feature activity** — if expected rows are missing,
   the feature is not producing output
3. **Check for warning-level messages** — a warning on every run means the feature is broken

### Phase 6: Synthesize Evidence & Verdict

Collect results from all agents and produce a unified report:

| Focus            | Status | Key Finding                         |
| ---------------- | ------ | ----------------------------------- |
| Prefect Flows    | PASS   | 47 runs, 0 failures (100% success)  |
| Service Logs     | PASS   | No errors, success messages present  |
| Database State   | PASS   | New table has 23 new rows           |
| Data Quality     | PASS   | All new records have valid data     |

Every piece of evidence MUST include:

1. A **reproducible command** — a SQL query, Prefect CLI command, or Render log filter —
   that the user can run themselves to verify the claim
2. **What to look for** — what part of the output matters and why
3. **What "good" looks like** — the expected output if the feature is working correctly
4. **What "bad" looks like** — what the output would show if something is wrong, and what
   that would indicate

**PASS Criteria (all must be true):**

- No failed Prefect flow runs related to the feature
- Service logs show success-path messages (not just absence of errors)
- Expected database changes are present
- Data quality checks pass
- Feature behavior matches expectations

**FAIL Criteria (any triggers failure):**

- Any failed flow runs with feature-related errors
- Expected database state not present
- Data quality issues (nulls, invalid values, missing FKs)
- Feature not executing — expected logs/queries never appear (silent degradation)
- Success-path log messages absent while error/warning messages present

**NEEDS_MORE_TIME if:**

- Deployment is too recent (<1 hour) for meaningful data
- Not enough flow runs to establish success rate
- Feature only activates under specific conditions not yet met

### Phase 7: Update Ticket

**On PASS:**

Staging:
1. Merge PR to main: `gh pr merge {pr_number} --merge`
2. Set status to `to_verify_prod`

Production:
1. Set status to `completed`

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="{next_status}",
  command="/auto-verify"
)
```

**On FAIL:**

1. Create verification report artifact documenting what failed
2. Set status to `verify_{env}_failed`
3. Do NOT close/merge the PR — leave open for investigation

**On NEEDS_MORE_TIME:**

1. Report findings so far
2. Do not change ticket status
3. Suggest when to re-run

## Output Format

````markdown
# ✅ PASS — {ID} ({env}) or 🔴 FAIL — {ID} ({env}) or ⏳ NEEDS_MORE_TIME — {ID} ({env})

**Feature:** [brief description]
**Deployed:** [commit hash + timestamp from git]
**Verified:** [current timestamp]
**Lookback:** Since deploy commit ($DEPLOY_TIME)

[1-2 sentence summary]

### 1. Prefect Flow Health

| Flow/Deployment    | Runs Since Deploy | Completed | Failed | Success Rate | Status |
| ------------------ | ----------------- | --------- | ------ | ------------ | ------ |
| flow-name          | N                 | N         | 0      | 100%         | PASS   |

**Evidence:**

```bash
# Re-run this yourself:
uv run prefect flow-run ls --flow-name <flow> --state COMPLETED --limit 10
uv run prefect flow-run ls --flow-name <flow> --state FAILED --limit 10
```

**What to look for:** COMPLETED runs after deploy time, zero FAILED runs.
**You should see:** [describe expected output]. This confirms [why this means the feature works].
**If instead you see:** [describe failure scenario] — that would mean [interpretation].

### 2. Service Logs

| Check                          | Result              | Status |
| ------------------------------ | ------------------- | ------ |
| Error-level logs               | 0 since deploy      | PASS   |
| Success-path messages present  | Yes, 47 occurrences | PASS   |

**Evidence:** [Render log snippets]

**What to look for:** Absence of error logs AND presence of success-path messages.
**You should see:** [describe expected log patterns]. This confirms [why this means the feature works].
**If instead you see:** [describe failure scenario] — that would mean [interpretation].

### 3. Database State

| Check                         | Expected | Actual | Status |
| ----------------------------- | -------- | ------ | ------ |
| New rows since deployment     | > 0      | 23     | PASS   |

**Evidence:**

```sql
-- Re-run this yourself:
SELECT COUNT(*) FROM table WHERE created_at >= '$DEPLOY_TIME';
```

**What to look for:** Non-zero row count after deploy time.
**You should see:** [describe expected count and growth pattern]. This confirms [why this means the feature works].
**If instead you see:** [describe failure scenario] — that would mean [interpretation].

### 4. Data Quality

| Check              | Result           | Status |
| ------------------ | ---------------- | ------ |
| field_name         | 100% populated   | PASS   |

**What to look for:** Fill rates for new/modified fields.
**You should see:** [describe expected fill rates]. This confirms [why this means the feature works].
**If instead you see:** [describe failure scenario] — that would mean [interpretation].

### 5. Root Cause Resolution (bug fixes only)

| Original Hypothesis | Post-Deploy Verdict |
|---|---|
| [H1 statement] | RESOLVED / STILL_PRESENT |

### Conclusion

[1-2 sentence summary]

**Next step:**

For staging PASS:
```
Next: /auto-verify prod {ID} (verify in production)
```

For prod PASS:
```
Next: Ticket complete! No further action needed.
```

For FAIL:
```
Next: Investigate failures above, fix, and re-run /auto-verify {env} {ID}
```

For NEEDS_MORE_TIME:
```
Next: Re-run /auto-verify {env} {ID} in {suggested timeframe}
```

### Manual Verification Commands

For each command below, we explain **what to run**, **what to look for** in the output,
**what you should see** if the feature is working, and **what it means** if you see
something different.

#### Prefect Flows

```bash
# Check completed runs since deployment:
uv run prefect flow-run ls --flow-name <flow> --state COMPLETED --limit 10
```

**What to look for:** Recent COMPLETED runs with timestamps after the deploy time.
**You should see:** Multiple completed runs — this confirms the new code path executed
successfully end-to-end. If you see zero completed runs, either the flow hasn't been
triggered yet or it's failing before completion.

```bash
# Check for failures:
uv run prefect flow-run ls --flow-name <flow> --state FAILED --limit 10
```

**What to look for:** Any FAILED runs with timestamps after the deploy time.
**You should see:** Zero failures (or only failures unrelated to this feature). If you
see failures, inspect the logs with `uv run prefect flow-run logs <run-id>` — look for
the exception traceback to determine if it's related to this change or pre-existing.

#### Database

```sql
-- Check that expected data exists:
SELECT COUNT(*) FROM <table> WHERE created_at >= '<DEPLOY_TIME>';
```

**What to look for:** A non-zero count of rows created after deployment.
**You should see:** A growing count that reflects the expected volume (e.g., if the flow
runs hourly and processes ~50 records, you'd expect roughly 50 × hours_since_deploy).
Zero rows means the feature isn't producing output — check flow logs for silent failures.

```sql
-- Check data quality / fill rates:
SELECT
  COUNT(*) as total,
  COUNT(<new_field>) as populated,
  ROUND(COUNT(<new_field>)::numeric / NULLIF(COUNT(*), 0) * 100, 1) as fill_pct
FROM <table>
WHERE created_at >= '<CODE_ACTIVATED_AT>';
```

**What to look for:** The `fill_pct` column — this tells you what percentage of new
records have the expected field populated.
**You should see:** A fill rate matching the plan's expectations (often 90%+ for required
fields). A low fill rate means the feature is running but not producing complete data —
investigate the source or transformation logic.

#### Service Logs

```
Use Render dashboard or mcp__render__list_logs to filter by:
- Service: <service-name>
- Level: error
- Time: since <DEPLOY_TIME>
```

**What to look for:** Error-level log entries mentioning the feature, and the presence
of success-path log messages (e.g., "Processed N records", "Scrape completed").
**You should see:** No feature-related errors AND success messages appearing regularly.
If success messages are absent but there are no errors either, the feature may be silently
failing — this is a red flag that needs investigation.
````

## Relation to Other Commands

| Command        | Relationship                                       |
| -------------- | -------------------------------------------------- |
| `/auto-deploy` | Previous step — deploys PR to staging               |
| `/auto-build`  | Creates the PR that auto-deploy deploys             |
| `/auto-qa`     | Broader QA — tests entire app, not one ticket       |

## Required Tools

### Prefect CLI (read-only)

```bash
uv run prefect flow-run ls --flow-name <name> --state COMPLETED --limit N
uv run prefect flow-run ls --flow-name <name> --state FAILED --limit N
uv run prefect flow-run logs <run-id>
```

### Render MCP (read-only)

- `mcp__render__list_logs` — search logs by service, level, and time range
- `mcp__render__list_services` — find affected services
- `mcp__render__get_metrics` — check service health metrics

### Database MCP (read-only)

| Environment | Tool Prefix               |
| ----------- | ------------------------- |
| Production  | `mcp__postgres_prod__`    |
| Staging     | `mcp__postgres_staging__` |

## Error Handling

| Phase    | Error                | Action                             |
| -------- | -------------------- | ---------------------------------- |
| Config   | Env file not found   | STOP, report                       |
| Validate | Ticket not found     | STOP, report                       |
| Validate | Wrong status         | STOP, report                       |
| Find PR  | No PR found          | STOP, report (staging only)        |
| Observe  | Environment down     | STOP, report (don't change status) |
| Merge    | Merge conflict       | STOP, set verify_staging_failed    |
| Merge    | CI checks failing    | STOP, set verify_staging_failed    |

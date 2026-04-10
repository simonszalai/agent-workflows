---
description: Verify a deployed feature is working in production. Monitors services and database state. Read-only.
---

# Verify-Prod Command

Verify that a deployed feature is working correctly in production by monitoring services and
checking database state. This command is **read-only** - it does not modify data or launch processes.

**Use this command after deployment to production. For pre-deployment testing, use `/verify-local`.**

## Usage

Two modes: **ticket mode** (structured) and **freeform mode** (ad-hoc).

```
# Ticket mode — pulls context from ticket artifacts
/verify-prod F001                             # Feature F001
/verify-prod B0009                            # Bug ticket B0009

# Freeform mode — describe what to verify directly
/verify-prod "the new story_type column on news_items is being populated"
/verify-prod "tradable-scheduler flow is running and creating tradable_analyses"

# Options (work with both modes)
/verify-prod F001 --lookback 24h              # Check last 24 hours
/verify-prod "..." --lookback 7d              # Check last 7 days
```

## Prerequisites

### Ticket Mode

If a ticket ID is provided, load it and use artifacts for context:

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- If ticket has a plan artifact with "Verification Strategy" → use it to guide checks
- If ticket exists but no plan → proceed using ticket description + code diff as context
- If ticket not found → fall back to freeform mode using the ID as a search hint

### Freeform Mode

If a quoted description is provided instead of a ticket ID:

1. Use the description to identify what tables, flows, services, and columns to check
2. Read recent git history (`git log origin/main -10`) to understand what was deployed
3. Read the diff of the relevant commit(s) to understand what code changed
4. Proceed directly to verification — no ticket required

### Deployment Boundary (CRITICAL — Both Modes)

**Do NOT use a naive time-based lookback.** Determine the actual deployment boundary:

```bash
# Find when the relevant commit landed on main
git log origin/main --oneline -10

# The deployment time = when the commit was pushed to main
# Use this timestamp as the "since" boundary for all queries
git log origin/main -1 --format="%H %ci"
```

The `--lookback` flag is a fallback for when deployment time can't be determined.
Always prefer the actual commit timestamp over a guessed window.

**IMPORTANT for projects that pull code from git at runtime (e.g., ts-prefect):** Code changes
take effect on the next flow run after the commit is pushed to main. There is NO Render deploy
step. The deployment boundary is the git push timestamp.

## What This Command Does

1. **Determines deployment boundary** - From git, not guesswork
2. **Checks Prefect flow runs** - States, logs, task results since deployment
3. **Checks service logs** - Render logs for errors, warnings, success messages
4. **Verifies database state** - Expected records/columns exist and have correct data
5. **Detects silent failures** - Features that look OK but are actually broken
6. **Produces evidence** - SQL queries, log snippets, and CLI output you can re-run yourself

## Process

### Phase 1: Load Context & Determine Deployment Boundary

**Step 1: Identify what to verify**

In ticket mode: read plan/source/investigation artifacts from the ticket.
In freeform mode: use the description + recent git diffs.

From this context, determine:

- Which Prefect flows/deployments are affected
- What database tables/columns should have changed
- What Render services to check logs for
- Expected behavior patterns (what does "working" look like?)

**Step 2: Find the deployment boundary**

```bash
# Find the commit that deployed the feature
git log origin/main --oneline -10

# Get its exact timestamp
git show <commit> --format="%ci" --no-patch
```

All subsequent queries use this timestamp as `$DEPLOY_TIME`.

### Phase 2: Launch Parallel Verification Agents

Spawn `verifier-production` agent(s) to verify different aspects simultaneously:

```
+-----------------------------------------------------------------------+
|                      VERIFICATION AGENTS                               |
+-----------------------------------------------------------------------+
|                                                                        |
|  +--------------+  +--------------+  +--------------+  +----------+   |
|  | Prefect      |  | DB State     |  | Service      |  | Data     |   |
|  | Flows        |  | Verification |  | Logs         |  | Quality  |   |
|  +--------------+  +--------------+  +--------------+  +----------+   |
|  | - Flow runs  |  | - New tables |  | - Render logs|  | - Counts |   |
|  | - Task states|  | - New columns|  | - Errors     |  | - Nulls  |   |
|  | - Run logs   |  | - FK refs    |  | - Warnings   |  | - FKs    |   |
|  +--------------+  +--------------+  +--------------+  +----------+   |
|                                                                        |
+-----------------------------------------------------------------------+
```

**Focus 1: Prefect Flow Health**

```
Check Prefect flow runs for affected deployments:
- List all flow runs since $DEPLOY_TIME
- Check states: COMPLETED vs FAILED vs CRASHED
- For failures: get full logs and error tracebacks
- Check task run states within flows
- Calculate success rate
- Provide the exact Prefect CLI commands used so user can re-run them
```

**Focus 2: Service Logs (Render)**

```
Check Render service logs for affected services:
- Search for error-level logs since $DEPLOY_TIME
- Search for warning-level logs mentioning the feature
- Search for success-path log messages (feature-specific keywords)
- If success-path messages are ABSENT but the service is running, that's a red flag
- Provide log snippets as evidence
```

**Focus 3: Database State**

```
Verify expected database changes exist:
- Query tables mentioned in the plan/description
- Check new columns have data
- Verify row counts are growing (if applicable)
- Check for orphaned records or constraint violations
- Provide exact SQL queries so user can re-run them
```

**Focus 4: Data Quality**

```
Validate the quality of new data:
- Sample recent records affected by the feature
- Verify values are in expected ranges
- Check for unexpected nulls or empty values
- Compare against historical patterns (before vs after deployment)
```

**CRITICAL: Fill Rate Measurement Boundary**

For projects that pull code from git at runtime (e.g., ts-prefect), there is a lag between
when the commit merges and when the new code actually starts executing. Using the merge
timestamp as the measurement boundary will include records processed by OLD code, deflating
fill rates and making a working feature look broken.

**Correct approach:**

1. Find when the new code actually activated by querying for the first record with the new
   field populated:
   ```sql
   SELECT MIN(created_at) as code_activated_at
   FROM table WHERE new_field IS NOT NULL AND created_at > '[merge_timestamp]';
   ```
2. Measure fill rates only from that activation boundary forward
3. Report: "Code activated at [time]. Since then: N records, X% fill rate"

### Phase 2b: Re-Evaluate Original Hypotheses (Bug Fixes Only)

For bug-fix tickets (B-prefix) that have hypothesis evaluation artifacts, re-evaluate
the confirmed hypothesis against **post-deployment** production data to verify the fix actually
addressed the root cause.

**When to run:**

| Condition | Run Phase 2b? |
|---|---|
| `hypothesis-evaluation/` exists with CONFIRMED hypothesis | **Yes** |
| Bug fix without hypothesis evaluation | No |
| Feature work item (FNNN) | No |
| Freeform mode | No |

**Process:**

1. Read the original confirmed hypothesis from `hypothesis-evaluation/`
2. Spawn `hypothesis-evaluator` agent in parallel with Phase 2 agents:

   ```
   Task(subagent_type="hypothesis-evaluator", prompt="
   Post-deployment re-evaluation of previously confirmed hypothesis:

   Original hypothesis: [H1 statement]
   Original verdict: CONFIRMED
   Original evidence: [summary of what was found]

   Fix deployed: [brief description of what was changed]
   Deployment time: [timestamp or 'unknown']

   Verify that the root cause is NO LONGER present in production:
   - The original symptom should be gone
   - The testable prediction should now show the FIXED state
   - No new related failures should appear

   Return verdict: RESOLVED | STILL_PRESENT | INCONCLUSIVE with evidence.
   ")
   ```

3. Include result in the synthesis report as a "Root Cause Resolution" section.

### Phase 3: Synthesize Results

Collect results from all agents and produce a unified report:

| Focus            | Status | Key Finding                         |
| ---------------- | ------ | ----------------------------------- |
| Prefect Flows    | PASS   | 47 runs, 0 failures (100% success)  |
| Service Logs     | PASS   | No errors, success messages present  |
| Database State   | PASS   | New table has 23 new rows           |
| Data Quality     | PASS   | All new records have valid data     |

### Phase 4: Verdict

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
- **Feature not executing** - expected logs/queries never appear (silent degradation)
- Success-path log messages absent while error/warning messages present

## Output Format

Every piece of evidence MUST include a **reproducible command** — a SQL query, Prefect CLI
command, or Render log filter — that the user can run themselves to verify the claim.

````markdown
## Production Verification Report

**Feature:** [brief description]
**Deployed:** [commit hash + timestamp from git]
**Verified:** [current timestamp]
**Lookback:** Since deploy commit ($DEPLOY_TIME)

### Executive Summary

**Result: PASS**

The feature is working correctly in production.
23 new records have been created since deployment.

### 1. Prefect Flow Health

| Flow/Deployment      | Runs Since Deploy | Completed | Failed | Success Rate |
| -------------------- | ----------------- | --------- | ------ | ------------ |
| main-news-pipeline   | 47                | 47        | 0      | 100%         |
| tradable-scheduler   | 12                | 12        | 0      | 100%         |

**Evidence:**

```bash
# Re-run this yourself:
uv run prefect flow-run ls --flow-name main-news-pipeline --state COMPLETED --limit 10
uv run prefect flow-run ls --flow-name main-news-pipeline --state FAILED --limit 10
```

**No failures detected.**

### 2. Service Logs

| Check                          | Result              | Status |
| ------------------------------ | ------------------- | ------ |
| Error-level logs               | 0 since deploy      | PASS   |
| Warning-level logs             | 2 (unrelated)       | PASS   |
| Success-path messages present  | Yes, 47 occurrences | PASS   |

**Evidence:** [Render log snippets showing success messages]

### 3. Database State

| Check                         | Expected | Actual | Status |
| ----------------------------- | -------- | ------ | ------ |
| New table exists              | Yes      | Yes    | PASS   |
| New rows since deployment     | > 0      | 23     | PASS   |
| All rows have valid record_id | Yes      | Yes    | PASS   |
| All rows have field populated | Yes      | Yes    | PASS   |

**Evidence:**

```sql
-- Re-run this yourself:
SELECT COUNT(*) as count,
       MIN(created_at) as first,
       MAX(created_at) as last
FROM new_table
WHERE created_at >= '2026-01-19 14:30:00';

-- Result: 23 rows, first: 2026-01-19 14:45:12, last: 2026-01-20 08:52:33
```

### 4. Data Quality

| Check              | Result                   | Status |
| ------------------ | ------------------------ | ------ |
| explanation field  | 100% populated           | PASS   |
| reference_id field | 91% populated (expected) | PASS   |
| values             | All valid                | PASS   |

### 5. Verification Scenarios

| Scenario                  | Evidence              | Status |
| ------------------------- | --------------------- | ------ |
| New records are created   | 23 records found      | PASS   |
| Existing flow still works | 824 unchanged records | PASS   |
| New field is populated    | All have values       | PASS   |

### Manual Verification Commands

All evidence above can be independently verified. Key commands:

```bash
# Prefect flow runs
uv run prefect flow-run ls --flow-name <flow> --state COMPLETED --limit 10
uv run prefect flow-run ls --flow-name <flow> --state FAILED --limit 10

# Prefect flow run logs (for a specific run)
uv run prefect flow-run logs <flow-run-id>
```

```sql
-- Database checks (run against production)
SELECT ... ;  -- [specific queries from above]
```

### Conclusion

Feature is working as designed. Recommend moving to closed.
````

## Agent Dispatch

The verify command spawns `verifier-production` agents in parallel with different focus areas:

| Agent                 | Focus           | Purpose                              | Tools Used                              |
| --------------------- | --------------- | ------------------------------------ | --------------------------------------- |
| `verifier-production` | Prefect flows   | Check flow/task run states and logs  | Bash (Prefect CLI)                      |
| `verifier-production` | Service logs    | Search Render logs for evidence      | Render MCP                              |
| `verifier-production` | Database state  | Query database state and schema      | Production database MCP                 |
| `verifier-production` | Data quality    | Validate data correctness            | Production database MCP                 |

## On Verification PASS

1. **If ticket mode:** Create conclusion artifact and update ticket status to `completed`
2. **If freeform mode:** Just report the results — no ticket to update
3. **Report:** Include the full verification report with all evidence and manual commands

## On Verification FAIL

1. **Document issues** - Capture specific failures with evidence
2. **If ticket mode:** Keep ticket status as `to_verify` — do not change
3. **Report:** "Verification FAILED: [issues]. Investigation needed."

Provide specific guidance on what to investigate next.

## Important Notes

- **Read-only**: This command only monitors - it never modifies data or triggers processes
- **Production access**: Uses production database MCP, Render MCP, and Prefect CLI
- **Be thorough**: Launch multiple agents, verify from multiple angles
- **Evidence-based**: Every claim must have a reproducible command the user can re-run
- **Zero assumptions**: Don't infer success from absence of errors — verify the success path

## Critical: Verify Feature Activity (Not Just Absence of Errors)

**Features with graceful degradation can fail silently.** A feature that catches exceptions and
returns empty/default values will appear to "work" while providing zero value.

### Check Feature is Actually Executing

For new features, verify the **success path** is being hit:

1. **Check Prefect flow run logs for feature-specific messages:**

   ```bash
   # Get recent flow run IDs
   uv run prefect flow-run ls --flow-name <flow> --limit 5

   # Check logs for a specific run
   uv run prefect flow-run logs <run-id>

   # Look for feature-specific log messages in the output
   ```

2. **Check Render service logs for success-path messages:**

   Use Render MCP `list_logs` to search for feature-specific keywords.
   If success messages are ABSENT but the service is running, the feature may not be executing.

3. **Check database for evidence of feature activity:**

   ```sql
   -- If the feature writes to a table, verify rows are appearing
   SELECT COUNT(*) FROM table WHERE created_at >= $DEPLOY_TIME;

   -- If count is 0, the feature is not producing output
   ```

### Example: Silent Failure Pattern

A feature may have this pattern:

```python
try:
    result = await feature_function(data)
    return result
except Exception as e:
    logger.warning(f"Failed: {e}")  # Logged but not investigated
    return []  # Silent degradation
```

**What can happen:**

- Services complete successfully (100% success rate)
- Database table exists with data
- But **every single execution fails** due to a bug
- The warning is logged but nobody checks for it

**How to catch this:**

- Search Render logs for "Failed" — if it appears on every run, feature is broken
- Search Prefect task logs for warning-level messages
- Verify success log ("Processed N items") appears — if never, feature isn't working

## Required Tools

### Prefect CLI

Use `uv run prefect` commands via Bash to check flow runs, task runs, and logs.
Key commands:

```bash
uv run prefect flow-run ls --flow-name <name> --state COMPLETED --limit N
uv run prefect flow-run ls --flow-name <name> --state FAILED --limit N
uv run prefect flow-run logs <run-id>
```

### Render MCP

Use Render MCP tools to search service logs:

- `mcp__render__list_logs` — search logs by service, level, and time range
- `mcp__render__list_services` — find affected services
- `mcp__render__get_metrics` — check service health metrics

### Production Database MCP

Use production database MCP tools for all database verification.
These are read-only and safe to use.

**CRITICAL**: Always use production MCP for production verification. Never use dev MCP.

| Environment | Tool Prefix               |
| ----------- | ------------------------- |
| Production  | `mcp__postgres_prod__`    |
| Staging     | `mcp__postgres_staging__` |

Always use production tools unless explicitly told otherwise.

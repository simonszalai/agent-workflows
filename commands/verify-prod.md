---
description: Verify a deployed feature is working in production. Monitors services and database state. Read-only.
---

# Verify-Prod Command

Verify that a deployed feature is working correctly in production by monitoring services and
checking database state. This command is **read-only** - it does not modify data or launch processes.

**Use this command after deployment to production. For pre-deployment testing, use `/verify-local`.**

## Usage

```
/verify-prod 009                              # Bug/incident #009 (NNN format)
/verify-prod F001                             # Feature F001 (FNNN format)
/verify-prod work_items/to_verify/009-fix-timeout  # Use explicit path
/verify-prod --lookback 24h                   # Check last 24 hours (default: 6h)
/verify-prod --lookback 7d                    # Check last 7 days
```

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

```bash
# 1. Locate work item (prefer to_verify/ folder)
find work_items/to_verify -maxdepth 1 -type d -name "*[id]*" | head -1
# If empty, check all folders:
find work_items -maxdepth 2 -type d -name "*[id]*" | head -1
# If still empty: STOP - work item not found

# 2. Check plan.md exists with verification strategy
test -f work_items/*/[id]*/plan.md && grep -q "Verification Strategy" work_items/*/[id]*/plan.md
# If missing: STOP - need plan.md with verification strategy

# 3. Check deployment happened (work item should be in to_verify/)
ls -d work_items/to_verify/*[id]* 2>/dev/null
# If not in to_verify/: WARN - may be verifying undeployed code
```

**If any prerequisite fails:**

| Missing                  | Action                                       |
| ------------------------ | -------------------------------------------- |
| Work item not found      | **STOP** - create work item first            |
| No plan.md               | **STOP** - run `/plan [id]` first            |
| No verification strategy | **STOP** - add verification strategy to plan |
| Not in to_verify/        | **WARN** - verify deployment happened first  |

## Finding Work Items

**Prefer `to_verify/` folder** - deployed items awaiting verification:

```bash
find work_items/to_verify -maxdepth 1 -type d -name "*{id}*"
```

If not found, search all folders:

```bash
find work_items -maxdepth 2 -type d -name "*{id}*"
```

## What This Command Does

1. **Checks for service failures** - Any failed runs/jobs indicate problems
2. **Verifies database changes** - Expected records/columns from the feature exist
3. **Cross-references plan** - Uses verification strategy from `plan.md`
4. **Produces evidence** - SQL results and logs proving the feature works

## Process

### Phase 1: Load Context

Read from the work item folder:

- `plan.md` - Verification strategy section defines what to check
- `source.md` - Feature requirements to verify against
- `investigation.md` - Context about the problem/feature (if exists)

Identify:

- Which services/processes are affected by this feature
- What database tables/columns should have changed
- Expected behavior patterns to verify

### Phase 2: Launch Parallel Verification Agents

Spawn multiple specialized subagents to verify different aspects simultaneously:

```
+-------------------------------------------------------------+
|                    VERIFICATION AGENTS                       |
+-------------------------------------------------------------+
|                                                              |
|  +--------------+  +--------------+  +--------------+       |
|  | Service      |  | DB State     |  | Data Quality |       |
|  | Monitor      |  | Checker      |  | Agent        |       |
|  +--------------+  +--------------+  +--------------+       |
|  | - Failed runs|  | - New tables |  | - Row counts |       |
|  | - Error logs |  | - New columns|  | - Data shape |       |
|  | - Run stats  |  | - FK refs    |  | - Null rates |       |
|  +--------------+  +--------------+  +--------------+       |
|                                                              |
+-------------------------------------------------------------+
```

**Agent 1: Service Health Monitor**

```
Check service runs for affected processes:
- List all runs since deployment (or lookback period)
- Count successful vs failed states
- For failures: capture error messages and affected record IDs
- Calculate success rate percentage
```

**Agent 2: Database State Checker**

```
Verify expected database changes exist:
- Query tables mentioned in the plan
- Check new columns have data
- Verify row counts are growing (if applicable)
- Check for orphaned records or constraint violations
```

**Agent 3: Data Quality Agent**

```
Validate the quality of new data:
- Sample recent records affected by the feature
- Verify values are in expected ranges
- Check for unexpected nulls or empty values
- Compare against historical patterns
```

### Phase 3: Synthesize Results

Collect results from all agents and produce a unified report:

| Agent          | Status | Key Finding                         |
| -------------- | ------ | ----------------------------------- |
| Service Health | PASS   | 847 runs, 0 failures (100% success) |
| Database State | PASS   | New table has 23 new rows           |
| Data Quality   | PASS   | All new records have valid data     |

### Phase 4: Verdict

**PASS Criteria (all must be true):**

- No failed runs for affected services
- Expected database changes are present
- Data quality checks pass
- Feature behavior matches plan expectations

**FAIL Criteria (any triggers failure):**

- Any failed runs with feature-related errors
- Expected database state not present
- Data quality issues (nulls, invalid values, missing FKs)
- **Feature not executing** - expected logs/queries never appear (silent degradation)

## Output Format

````markdown
## Production Verification Report

**Work Item:** work_items/to_verify/F002-feature-name
**Deployed:** 2026-01-19 14:30 UTC
**Verified:** 2026-01-20 09:15 UTC
**Lookback Period:** 6 hours

### Executive Summary

**Result: PASS**

The feature is working correctly in production.
23 new records have been created since deployment.

### Service Health

| Service  | Runs | Completed | Failed | Success Rate |
| -------- | ---- | --------- | ------ | ------------ |
| main-job | 847  | 847       | 0      | 100%         |

**No failures detected.**

### Database State

| Check                         | Expected | Actual | Status |
| ----------------------------- | -------- | ------ | ------ |
| New table exists              | Yes      | Yes    | PASS   |
| New rows since deployment     | > 0      | 23     | PASS   |
| All rows have valid record_id | Yes      | Yes    | PASS   |
| All rows have field populated | Yes      | Yes    | PASS   |

**Evidence:**

```sql
SELECT COUNT(*) as count,
       MIN(created_at) as first,
       MAX(created_at) as last
FROM new_table
WHERE created_at >= '2026-01-19 14:30:00';

-- Result: 23 rows, first: 2026-01-19 14:45:12, last: 2026-01-20 08:52:33
```
````

### Data Quality

| Check              | Result                   | Status |
| ------------------ | ------------------------ | ------ |
| explanation field  | 100% populated           | PASS   |
| reference_id field | 91% populated (expected) | PASS   |
| values             | All valid                | PASS   |

### Verification Scenarios (from plan.md)

| Scenario                  | Evidence              | Status |
| ------------------------- | --------------------- | ------ |
| New records are created   | 23 records found      | PASS   |
| Existing flow still works | 824 unchanged records | PASS   |
| New field is populated    | All have values       | PASS   |

### Conclusion

Feature is working as designed. Recommend moving to closed.

````

## Agent Dispatch

The verify command spawns multiple Task agents in parallel:

| Agent Type            | Subagent | Purpose                               | Tools Used                    |
| --------------------- | -------- | ------------------------------------- | ----------------------------- |
| Investigator agents   | haiku    | Check service status                  | Project-specific CLI          |
| Database investigator | haiku    | Query database state                  | Production database MCP       |
| Verifier              | sonnet   | Synthesize results and produce report | Both CLI and database MCP     |

## On Verification PASS

1. **Create `conclusion.md`:**

   ```markdown
   ---
   status: closed
   closed: YYYY-MM-DD
   outcome: completed
   ---

   # Conclusion

   ## What Was Done
   [Summary from plan.md]

   ## Verification
   Verified in production on YYYY-MM-DD.
   - Service success rate: 100%
   - Database changes confirmed: [details]
   - Data quality: [details]

   ## Outcome
   Implementation working as expected in production.
````

3. **Move to closed:**

   ```bash
   git mv work_items/to_verify/{id}-slug work_items/closed/
   ```

4. **Report:** "Verification PASSED. Moved {id} to closed/"

## On Verification FAIL

1. **Document issues** - Capture specific failures
2. **Keep in to_verify/** - Do not move
3. **Report:** "Verification FAILED: [issues]. Investigation needed."

Provide specific guidance on what to investigate next.

## Important Notes

- **Read-only**: This command only monitors - it never modifies data or triggers processes
- **Production access**: Uses production database MCP and project-specific CLI tools
- **Be thorough**: Launch multiple agents, verify from multiple angles
- **Evidence-based**: Every claim must have SQL results or logs to back it up

## Critical: Verify Feature Activity (Not Just Absence of Errors)

**Features with graceful degradation can fail silently.** A feature that catches exceptions and
returns empty/default values will appear to "work" while providing zero value.

### Check Feature is Actually Executing

For new features, verify the **success path** is being hit:

1. **Check for expected log messages:**

   ```bash
   # Search service logs for feature-specific messages
   # Use project-specific log access tools
   ```

2. **Check for warnings/errors related to the feature:**

   ```bash
   # Look for caught exceptions that indicate silent failures
   # Check for warning messages
   ```

3. **Check database query patterns (if feature reads from new tables):**

   ```sql
   -- Check for queries to feature tables (if stats available)
   -- If query count is 0 or very low, feature may not be executing
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

- Search logs for "Failed" - if it appears on every run, feature is broken
- Verify success log ("Processed N items") appears - if never, feature isn't working

## Required Tools

### Project CLI

Use project-specific CLI tools to verify deployments and check run status.
Refer to AGENTS.md for project-specific commands.

### Production Database MCP

Use production database MCP tools for all database verification.
These are typically read-only and safe to use.

**CRITICAL**: Always use production MCP for production verification. Never use dev MCP.

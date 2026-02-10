---
description: Autonomous local verification with write DB access. Seeds test data, runs tests, mocks external services, produces evidence reports.
max_turns: 100
---

# Verify Local Command

Autonomous local verification that can seed test data, execute code with mocked external services,
and produce detailed evidence reports. Use when you need controlled testing before production deployment.

## Usage

```
/verify-local F002                    # Verify feature F002 locally
/verify-local 009                     # Verify work item 009 locally
/verify-local F002 --skip-cleanup     # Keep test data for debugging
/verify-local F005 --ui               # Include UI verification (if applicable)
```

## When to Use

| Scenario                 | Use This Command                                   |
| ------------------------ | -------------------------------------------------- |
| Defense-in-depth testing | Yes - can test edge cases that need real DB state  |
| External service mocking | Yes - external services are mocked, safe to test   |
| Deduplication testing    | Yes - can seed similar records, verify suppression |
| Pre-deploy verification  | Yes - catch issues before production               |
| Dashboard UI changes     | Yes with `--ui` - test UI pages                    |
| Quick production check   | No - use `/verify-prod` instead                    |

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

```bash
# 1. Locate work item
find work_items -maxdepth 2 -type d -name "*[id]*" | head -1
# If empty: STOP - work item not found

# 2. Check plan.md exists with verification strategy
test -f work_items/*/[id]*/plan.md && grep -q "Verification Strategy" work_items/*/[id]*/plan.md
# If missing: STOP - need plan.md with verification strategy

# 3. Check local services are running (project-specific)
# Examples: database, API server, etc.

# 4. Check database is accessible
# Run project-specific database health check
```

**If any prerequisite fails:**

| Missing                  | Action                                       |
| ------------------------ | -------------------------------------------- |
| Work item not found      | **STOP** - create work item first            |
| No plan.md               | **STOP** - run `/plan [id]` first            |
| No verification strategy | **STOP** - add verification strategy to plan |
| Services not running     | **STOP** - start required services           |
| Database not accessible  | **STOP** - start database                    |

**Must have:**

- Local database with test schema
- Environment file with valid API keys (external services will be mocked)
- Project-specific services running

## Process

### 1. Locate Work Item

```bash
find work_items -maxdepth 2 -type d -name "*{id}*"
```

Read:

- `source.md` - Feature requirements, acceptance criteria
- `plan.md` - Verification strategy section

### 2. Environment Setup

Dispatch to `verifier-local` agent with:

```
Verify the implementation for: [work item path]

Phase 1: Environment Setup
- Check services running
- Verify test database accessible
- Verify environment configuration
```

### 3. Apply Database Migrations

**IMPORTANT:** Always apply migrations before verification.

```bash
# Run project's migration command
# Example: alembic upgrade head, prisma migrate deploy, etc.
```

If migrations fail or conflict:

- Check current migration state
- If needed, apply schema manually and stamp

### 4. Seed Database with Test Data

**Use the project's seed script (if available):**

```bash
# Run project's seed script
# Example: python scripts/seed_local_db.py, bun run db:seed, etc.
```

The seed script should:

- Clear test-related data (FK-safe order)
- Seed metadata tables
- Create test records with unique prefixes (e.g., `TEST_VERIFY_*`)
- Have safety check refusing to run against production database

### 5. Create Additional Test Records (If Needed)

For scenario-specific test data beyond the seed script, use project-appropriate methods.

### 6. Execute Tests

**Environment Setup:**

Set environment variables to mock external services (e.g., `MOCK_ALERTS=true`, `DRY_RUN=true`).

**Run test scenarios:**

Use project's test runner or manually execute the feature being verified.

### 7. Verify Results

Query local database to check expected state:

```sql
-- Check expected outcomes
-- Use project-specific queries based on what the feature should have done
```

### 8. Cleanup (Unless --skip-cleanup)

```sql
-- Remove test data with the test prefix
DELETE FROM table_name WHERE id LIKE 'TEST_VERIFY_%';

-- Verify cleanup
SELECT 'table' as tbl, COUNT(*) FROM table_name WHERE id LIKE 'TEST_VERIFY_%';
```

### 9. Generate Report

Create report in work item folder using template at
`.claude/skills/verify-flow/templates/verification-report.md`

Save to: `work_items/{folder}/{id}-name/verification-report.md`

## Agent Dispatch

```
Task(
    subagent_type="verifier-local",
    prompt="""
Verify the implementation for: {work_item_path}

Read the verification strategy from plan.md and:
1. Set up local environment (check prerequisites)
2. Apply migrations
3. Run seed script
4. Create additional test records if needed
5. Execute tests/scenarios with mocked external services
6. Verify results against expected outcomes
7. [Unless --skip-cleanup] Clean up test data
8. Generate verification report

IMPORTANT: If ANY issue requires adjusting your approach, log it to:
  {work_item_path}/local_verification_logs.md

Log format: Issue, Context, Error, Solution, Prevention
This builds knowledge to improve future verification runs.

Work item context:
- Feature: {feature_description}
- Key scenarios: {scenarios_from_plan}
- Expected outcomes: {expected_outcomes}

Use the verification report template for output.
""")
```

## Output

### On PASS

1. Create `verification-report.md` in work item folder
2. Update `plan.md` work log:
   ```
   | YYYY-MM-DD | verify-local | Local verification | PASS: [scenarios passed] |
   ```
3. Report: "Local verification PASSED for {id}. Report saved."

### On FAIL

1. Create `verification-report.md` with failure details
2. Update `plan.md` work log:
   ```
   | YYYY-MM-DD | verify-local | Local verification | FAIL: [failure reason] |
   ```
3. Report: "Local verification FAILED for {id}. See report for details."
4. Suggest: "Run `/investigate {id}` for root cause analysis"

## UI Verification (--ui flag)

When the feature affects the UI, use `--ui` flag to include browser-based verification.

### Prerequisites for UI Verification

- UI project running locally
- `agent-browser` CLI installed (`npm install -g agent-browser`)

### Starting UI Server

```bash
# In a separate terminal
cd path/to/ui/project
npm install  # First time only
npm run dev
# UI runs at http://localhost:PORT
```

### UI Verification with agent-browser

Use the `agent-browser` CLI for automated UI testing.

```bash
# Open the UI
agent-browser open http://localhost:PORT

# Login (if needed)
agent-browser snapshot -i
agent-browser fill @e1 'test@example.com'
agent-browser fill @e2 'testpassword'
agent-browser click @e3
agent-browser wait 2000

# Navigate to specific page
agent-browser open http://localhost:PORT/path

# Take screenshot for evidence
agent-browser screenshot verification-screenshot.png

# Get accessibility snapshot for AI analysis
agent-browser snapshot
```

### Common UI Verification Patterns

```bash
# Check a list has items
agent-browser get count '[data-testid="item-card"]'

# Verify specific text appears
agent-browser is visible 'text=No entries yet'

# Click into detail view
agent-browser click 'a[href*="/details/"]'
agent-browser wait 1000
agent-browser snapshot

# Fill and submit form
agent-browser fill @e1 'Test Title'
agent-browser fill @e2 'Test description'
agent-browser click 'button:has-text("Create")'
agent-browser wait 2000

# Check success message
agent-browser is visible 'text=Saved successfully'
```

### UI Verification Checklist

- [ ] UI starts successfully
- [ ] Login works with test credentials
- [ ] Feature pages load without errors
- [ ] Data seeded by tests appears in UI
- [ ] CRUD operations work (create/read/update/delete)
- [ ] Screenshots captured for evidence

## Troubleshooting

| Issue                     | Solution                                           |
| ------------------------- | -------------------------------------------------- |
| Server not running        | Start required services, wait for ready            |
| Database connection error | Check database is running, check connection string |
| Test data not cleaned     | Run cleanup SQL manually                           |
| "relation does not exist" | Run migrations                                     |
| UI won't start            | Check npm install ran, node version compatible     |
| agent-browser not found   | Run `npm install -g agent-browser`                 |
| Login fails               | Check credentials, UI may need database connected  |

## Issue Logging (Required)

**CRITICAL:** Any issue encountered that requires adjusting the approach MUST be logged to
`{work_item_path}/local_verification_logs.md`. This captures learnings for workflow improvement.

### Log Format

```markdown
## YYYY-MM-DD HH:MM - [Issue Category]

**Issue:** [Brief description]
**Context:** [What was being attempted]
**Error/Symptom:**
\`\`\`
[Error message or behavior]
\`\`\`
**Solution:** [How it was resolved]
**Prevention:** [How to avoid in future]

---
```

### Purpose

- Refine verification workflow to be efficient, fast, and accurate
- Build knowledge base of common issues and solutions
- Fine-tune agent prompts based on real-world problems
- Identify missing documentation or gotchas

### Post-Verification

Review logs and flag significant learnings:

- New gotchas -> `.claude/knowledge/gotchas/`
- Skill improvements -> update `verify-flow` skill
- Agent improvements -> update `verifier-local` agent

## Database Access

| Database    | Method                        | Access     | Purpose                    |
| ----------- | ----------------------------- | ---------- | -------------------------- |
| Production  | Production MCP (if available) | Read-only  | Pull reference data        |
| Local (dev) | Project's seed scripts        | Read-write | Reset and seed all tables  |
| Local (dev) | Direct SQL or ORM             | Read-write | Custom test record inserts |

**Note:** Local write operations use direct database connection (not MCP). This is more reliable and supports proper model validation.

---
name: verifier-local
description: Autonomous local verification with write DB access. Seeds test data, runs flows, verifies results, produces reports.
model: inherit
max_turns: 50
tools: [Bash, Read, Write, Edit, Glob, Grep, mcp__postgres__execute_sql]
skills: [browser-testing]
---

# Local Verifier Agent (Autonomous)

Full autonomous verification through local environment with **write database access**. This agent
can seed test data, execute workflows, and verify results without manual intervention.

**Use for:** Features requiring controlled test scenarios, defense-in-depth testing, or verification
of complex multi-step processes before production deployment.

## Key Differences from verifier-production

| Aspect          | verifier-production     | verifier-local                      |
| --------------- | ----------------------- | ----------------------------------- |
| DB access       | Read-only (MCP)         | Read-write (local)                  |
| Alert sending   | May trigger real alerts | Always mocked                       |
| Test data       | Manual insertion        | Autonomous seeding                  |
| Production data | Cannot pull             | Can pull via MCP and insert locally |
| Report format   | Simple pass/fail        | Detailed evidence report            |

## Prerequisites

Read AGENTS.md for project-specific prerequisites including:

- Local database setup requirements
- Environment configuration (.env)
- Server/worker startup commands
- Test account credentials

## Process

### Phase 1: Environment Setup

1. Verify local server is running
2. Verify database connection
3. Set up any required local services

### Phase 2: Load Verification Spec

Read from work item:

- `plan.md` - Verification strategy section
- `source.md` - Feature requirements and acceptance criteria

Identify:

- What components need to run
- What test scenarios to cover
- Expected outcomes for each scenario

### Phase 3: Seed Test Data (If Needed)

Use project-specific seed scripts or write custom data setup.

Transform any production data pulled for testing:

- Change IDs to test prefixes (e.g., `TEST_VERIFY_{id}`)
- Clear sensitive fields
- Keep content structure intact

### Phase 4: Execute Test Scenarios

For each test scenario:

1. **Setup**: Seed or create test data
2. **Execute**: Run the workflow being tested
3. **Wait**: Poll status until complete
4. **Verify**: Query database for expected state
5. **Record**: Capture evidence for report

### Phase 5: Cleanup

```sql
-- Delete all test data with prefix
DELETE FROM table WHERE id LIKE 'TEST_VERIFY_%';
```

### Phase 6: Generate Report

Produce evidence-backed results covering:

- Executive Summary (PASS/FAIL)
- Environment Setup Evidence
- Test Scenarios with Evidence
- Database State Verification
- Recommendations (if FAIL)

## UI Verification with agent-browser

For features affecting a web UI, include browser-based verification using the `agent-browser` CLI.

### Standard Login Sequence

```bash
agent-browser open http://localhost:3000/login
agent-browser snapshot -i
agent-browser fill @e1 "test@example.com"  # email field ref
agent-browser fill @e2 "password123"        # password field ref
agent-browser click @e3                      # submit button ref
agent-browser wait --url "**/dashboard"
```

### Verify UI State

```bash
# Navigate to feature page
agent-browser open http://localhost:3000/feature-page
agent-browser wait --load networkidle

# Get accessibility snapshot for AI analysis
agent-browser snapshot -i

# Take screenshot for evidence
agent-browser screenshot evidence/feature-state.png

# Verify expected elements exist
agent-browser is visible @e1
agent-browser get text @e1
agent-browser get count "[data-testid='item-card']"
```

Read AGENTS.md for project-specific:

- Login credentials
- Page URLs and routes
- Data-testid selectors

### Close Browser

```bash
agent-browser close
```

## Issue Logging for Workflow Improvement

**CRITICAL:** When you encounter any issue that requires adjusting your approach, log it to
`local_verification_logs.md` in the work item folder.

### When to Log

- Environment setup failures and their fixes
- Unexpected errors and workarounds
- Missing prerequisites discovered during execution
- Commands that needed modification
- Approach changes mid-verification

### Log Format

Create or append to `{work_item_path}/local_verification_logs.md`:

```markdown
## YYYY-MM-DD HH:MM - [Issue Category]

**Issue:** [Brief description of what went wrong]

**Context:** [What you were trying to do when it happened]

**Error/Symptom:**
[Actual error message or unexpected behavior]

**Solution:** [How you resolved or worked around it]

**Prevention:** [How this could be avoided in future]

---
```

## Error Handling

| Issue                     | Action                                              |
| ------------------------- | --------------------------------------------------- |
| Server not running        | Report error, stop verification                     |
| Database connection fails | Check .env, report error                            |
| External API error        | Capture error, note in report, continue if possible |
| Workflow crashes          | Capture traceback, record as scenario FAIL          |
| Cleanup fails             | Warn, provide manual cleanup SQL                    |

## Limitations

- External APIs may be called with real credentials (costs money)
- Cannot test time-sensitive behavior without mocking
- Long-running processes may timeout
- UI verification requires agent-browser installed

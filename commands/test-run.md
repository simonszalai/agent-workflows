---
description: Execute browser tests from the test-paths library. Runs tests via agent-browser CLI with database verification.
---

# Test Run Command

Execute browser-based test paths with full UI automation and database verification.

## Usage

```
/test-run critical                    # Run all critical tests
/test-run important                   # Run all important tests
/test-run regular                     # Run all regular tests
/test-run all                         # Run all tests (critical -> important -> regular)
/test-run test-paths/critical/login-flow.md   # Run specific test
/test-run critical --cleanup          # Run with cleanup before/after
/test-run login                       # Fuzzy match test by name
```

## Prerequisites

Before running tests, ensure:

1. **Database reset and seeded:**

   ```bash
   # Run project's database seed command
   ```

2. **Dev server running:**

   ```bash
   # Run project's dev server command
   # Wait until server is ready (shows ready message)
   ```

3. **agent-browser CLI installed:**
   ```bash
   npm install -g agent-browser
   ```

## Process

### 1. Parse Arguments

Determine what to run:

- If importance level: find all tests in that folder
- If specific path: load that test
- If fuzzy name: search test-paths/ for matching file

### 2. Verify Environment

```bash
# Check dev server (adjust port/path to project)
curl -s http://localhost:PORT/api/health
```

```sql
-- Check database (via postgres MCP if available)
SELECT COUNT(*) FROM "User";
```

### 3. Load Tests

Read test files from:

- `test-paths/critical/` - Must pass tests
- `test-paths/important/` - Should pass tests
- `test-paths/regular/` - Nice to pass tests

### 4. Execute Tests with agent-browser

For each test, use `agent-browser` CLI for browser automation:

```bash
# Navigate to starting URL
agent-browser open http://localhost:PORT[route]

# Get interactive elements
agent-browser snapshot -i

# Use refs from snapshot to interact
agent-browser fill @e1 "test@example.com"
agent-browser fill @e2 "password123"
agent-browser click @e3

# Wait for navigation/loading
agent-browser wait --load networkidle

# Verify results
agent-browser snapshot -i
agent-browser is visible 'text=Success'

# Take screenshot for evidence
agent-browser screenshot step-3.png
```

### 5. Database Verification

Use database MCP tools (if available) for:

1. **Precondition verification:**

   ```sql
   -- Check user exists for login test
   SELECT id FROM "User" WHERE email = 'test@example.com';
   ```

2. **Data assertions:**

   ```sql
   -- Verify record was created
   SELECT COUNT(*) FROM "Item"
   WHERE name LIKE 'test-%';
   ```

3. **Cleanup:**
   ```sql
   -- Remove test data
   DELETE FROM "Item" WHERE name LIKE 'test-%';
   ```

### 6. Collect Results

Aggregate results from all executed tests:

```markdown
## Test Run Summary

**Run ID:** [timestamp]
**Level:** critical
**Tests:** 3
**Passed:** 2
**Failed:** 1

### Results

| Test            | Status | Duration | Notes          |
| --------------- | ------ | -------- | -------------- |
| login-flow      | PASS   | 12s      |                |
| client-creation | PASS   | 18s      |                |
| onboarding      | FAIL   | 8s       | Step 3 timeout |

### Failed Tests

#### onboarding

- **Failed Step:** 3 - Complete Profile Section
- **Error:** Element not found: Profile section
- **Screenshot:** [available]
```

## Options

| Option      | Description                            |
| ----------- | -------------------------------------- |
| `--cleanup` | Run cleanup SQL before and after tests |
| `--stop`    | Stop on first failure                  |
| `--verbose` | Show all step details                  |
| `--dry-run` | List tests without executing           |

## Agent-Browser Commands Reference

### Navigation

```bash
agent-browser open <url>         # Navigate to URL
agent-browser back               # Go back
agent-browser reload             # Reload page
```

### Snapshot (page analysis)

```bash
agent-browser snapshot           # Full accessibility tree
agent-browser snapshot -i        # Interactive elements only (recommended)
```

### Interactions (use @refs from snapshot)

```bash
agent-browser click @e1          # Click element
agent-browser fill @e1 "text"    # Clear and type
agent-browser type @e1 "text"    # Type without clearing
agent-browser press Enter        # Press key
agent-browser select @e1 "value" # Select dropdown
agent-browser check @e1          # Check checkbox
```

### Get Information

```bash
agent-browser get text @e1       # Get element text
agent-browser get value @e1      # Get input value
agent-browser get url            # Get current URL
agent-browser get count ".item"  # Count matching elements
```

### Check State

```bash
agent-browser is visible @e1     # Check if visible
agent-browser is enabled @e1     # Check if enabled
```

### Wait

```bash
agent-browser wait @e1           # Wait for element
agent-browser wait 2000          # Wait milliseconds
agent-browser wait --text "Success"  # Wait for text
agent-browser wait --load networkidle  # Wait for network idle
```

### Screenshots

```bash
agent-browser screenshot         # Screenshot to stdout
agent-browser screenshot path.png  # Save to file
agent-browser screenshot --full  # Full page
```

## Troubleshooting

| Issue                     | Solution                             |
| ------------------------- | ------------------------------------ |
| "Dev server not running"  | Run project's dev server command     |
| "Database error"          | Run project's seed command           |
| "Element not found"       | Check selectors in test, update test |
| "agent-browser not found" | Run `npm install -g agent-browser`   |
| "Timeout"                 | Increase wait times in test          |

## Output

Update test-paths/INDEX.md with latest run results (optional).

Create run log at: `test-paths/runs/[timestamp].md` (optional).

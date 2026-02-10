---
name: browser-testing
description: Browser automation testing patterns and best practices for executing test paths using agent-browser CLI.
---

# Browser Testing Skill

Patterns and practices for browser automation testing using the `agent-browser` CLI tool.

## Test Environment Setup

### Before Running Tests

1. Reset database to known state (project-specific command)
2. Start dev server
3. Wait for server to be ready

### Verify Environment

```bash
# Check server is running
curl -s http://localhost:3000/api/health
```

Use the database MCP tool to verify seed data exists.

## Test Execution Patterns

### Login Before Tests

Most tests require authentication. Use demo accounts defined in AGENTS.md for the
specific project.

### Standard Login Sequence

```bash
# 1. Navigate to login page
agent-browser open http://localhost:3000/login

# 2. Get interactive elements
agent-browser snapshot -i

# 3. Fill credentials (using refs from snapshot)
agent-browser fill @e1 "user@example.com"
agent-browser fill @e2 "password123"

# 4. Submit
agent-browser click @e3

# 5. Wait for redirect
agent-browser wait --url "**/dashboard"
agent-browser wait --load networkidle

# 6. Verify dashboard loads
agent-browser snapshot -i
```

## Element Finding Strategies

### By Snapshot Refs (Preferred)

```bash
# Get all interactive elements with refs
agent-browser snapshot -i

# Use refs from output
agent-browser click @e1
agent-browser fill @e2 "text"
```

### By Semantic Locators

```bash
# Find by role and name
agent-browser find role button click --name "Submit"
agent-browser find text "Sign In" click
agent-browser find label "Email" fill "user@test.com"
```

### By CSS Selector Scope

```bash
# Scope snapshot to specific section
agent-browser snapshot -i -s "#main-content"
agent-browser snapshot -i -s ".sidebar"
```

## Form Interaction Patterns

### Text Input

```bash
agent-browser fill @e1 "test@example.com"    # Clear and type
agent-browser type @e1 "additional text"      # Type without clearing
```

### Dropdowns/Selects

```bash
# Open dropdown
agent-browser click @e1
agent-browser wait 500

# Select option
agent-browser select @e1 "California"
# Or find and click option
agent-browser snapshot -i
agent-browser click @e5  # option ref from snapshot
```

### Checkboxes/Toggles

```bash
agent-browser check @e1      # Check
agent-browser uncheck @e1    # Uncheck
```

### Date Pickers

```bash
# Open picker
agent-browser click @e1
agent-browser wait 500

# Navigate and select (snapshot to find date elements)
agent-browser snapshot -i
agent-browser click @e8  # specific date ref
```

## Assertion Patterns

### UI Assertions

```bash
# Check element exists and has text
agent-browser get text @e1
# Verify output matches expected

# Check URL changed
agent-browser get url
# Verify contains expected path

# Check element visibility
agent-browser is visible @e1

# Count matching elements
agent-browser get count ".success-message"
```

### Database Assertions

Use the database MCP tool to verify data state:

```sql
-- Record exists
SELECT COUNT(*) as count FROM "Table" WHERE condition = 'value';
-- Assert: count >= 1

-- Recent creation
SELECT id FROM "Record" WHERE "createdAt" > NOW() - INTERVAL '1 minute';
-- Assert: returns row
```

### Console Error Check

```bash
agent-browser errors
# Should return no errors for passing test
```

## Wait Strategies

### Fixed Wait

```bash
agent-browser wait 2000    # Wait 2 seconds
```

### Wait for Element

```bash
agent-browser wait @e1                  # Wait for element to appear
agent-browser wait --text "Success"     # Wait for text
```

### Wait After Navigation

Always wait after navigation for page to fully load:

```bash
agent-browser open http://localhost:3000/settings
agent-browser wait --load networkidle
```

## Screenshot Best Practices

### When to Capture

- Before and after key actions
- On test failure
- At verification points
- Final state

### How to Capture

```bash
agent-browser screenshot                    # To stdout
agent-browser screenshot evidence/step1.png # To file
agent-browser screenshot --full             # Full page
```

## Error Handling

### Element Not Found

1. Wait and retry (up to 3 times)
2. Re-snapshot to get fresh refs
3. Try broader search with semantic locators
4. Check if page loaded correctly
5. Mark test as FAIL with details

### Page Timeout

1. Check dev server is running
2. Check for console errors: `agent-browser errors`
3. Retry navigation once
4. Mark as FAIL if still times out

### Form Submission Error

1. Check for validation messages via snapshot
2. Take screenshot of error state
3. Check console for JavaScript errors
4. Check database for partial saves

## Data Cleanup

### Before Test

Use database MCP to remove stale test data:

```sql
DELETE FROM "Record" WHERE email LIKE 'test-%';
```

### After Test

```sql
-- Clean up created data
DELETE FROM "Record" WHERE email = 'testclient@example.com';
```

## Common Gotchas

1. **Hydration timing:** Wait for framework hydration after page load
2. **Modal animations:** Wait 500ms after modal opens before interacting
3. **Toast auto-dismiss:** Capture success messages quickly
4. **Soft deletes:** Check `deletedAt` is NULL in database queries
5. **Stale refs:** Re-snapshot after any navigation or significant DOM change
6. **Portal elements:** Modals/dialogs may need full page snapshot, not scoped

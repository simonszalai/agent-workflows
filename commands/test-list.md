---
description: List all browser tests in the test-paths library with status and metadata.
---

# Test List Command

Display all tests in the browser testing library with filtering and status.

## Usage

```
/test-list                    # List all tests
/test-list critical           # List only critical tests
/test-list --tags auth        # Filter by tag
/test-list --status active    # Filter by status
/test-list --route /login     # Filter by route
```

## Process

### 1. Scan Test Paths

Read all `.md` files from:

- `test-paths/critical/`
- `test-paths/important/`
- `test-paths/regular/`

### 2. Parse Frontmatter

Extract from each file:

```yaml
name: Test Name
importance: critical
route: /login
roles: [guest]
tags: [auth, login]
status: active
created: 2026-01-13
```

### 3. Apply Filters

If arguments provided, filter by:

- Importance level
- Tags (any match)
- Status
- Route (partial match)
- Role (any match)

### 4. Display Results

```markdown
## Test Paths Library

**Total:** 8 tests
**Critical:** 3 | **Important:** 3 | **Regular:** 2

### Critical Tests

| Test             | Route             | Roles | Tags          | Status |
| ---------------- | ----------------- | ----- | ------------- | ------ |
| Login Flow       | /login            | guest | auth, login   | active |
| Client Creation  | /settings/clients | coach | clients, crud | active |
| Coach Onboarding | /settings/setup   | coach | onboarding    | active |

### Important Tests

| Test            | Route              | Roles | Tags     | Status |
| --------------- | ------------------ | ----- | -------- | ------ |
| Session Booking | /settings/bookings | coach | booking  | active |
| Settings Update | /settings/prefs    | coach | settings | active |

### Regular Tests

| Test            | Route     | Roles | Tags       | Status |
| --------------- | --------- | ----- | ---------- | ------ |
| Theme Toggle    | /settings | any   | ui, theme  | active |
| Navigation Flow | /         | coach | navigation | active |
```

## Options

| Option    | Description                    |
| --------- | ------------------------------ |
| `--json`  | Output as JSON                 |
| `--brief` | Show only names and importance |
| `--count` | Show only counts per level     |

## Statistics View

With `--count`:

```
Test Library Statistics
-----------------------
Critical:  3 tests (3 active, 0 draft)
Important: 3 tests (2 active, 1 draft)
Regular:   2 tests (2 active, 0 draft)
-----------------------
Total:     8 tests
```

## Tag Index

Optionally show test distribution by tag:

```
Tags:
  auth (2): login-flow, password-reset
  crud (3): client-creation, session-booking, settings-update
  booking (1): session-booking
  ui (2): theme-toggle, navigation-flow
```

## File Locations

For each test, the file path is:

```
test-paths/[importance]/[kebab-name].md
```

## Quick Commands

After listing, suggest:

```
Quick actions:
  /test-run critical              # Run all critical tests
  /test-run login-flow            # Run specific test
  /test-add "New Test" important  # Add new test
```

## Output Formats

**Default:** Markdown tables (human-readable)

**JSON (--json):**

```json
{
  "total": 8,
  "tests": [
    {
      "name": "Login Flow",
      "importance": "critical",
      "path": "test-paths/critical/login-flow.md",
      "route": "/login",
      "roles": ["guest"],
      "tags": ["auth", "login"],
      "status": "active"
    }
  ]
}
```

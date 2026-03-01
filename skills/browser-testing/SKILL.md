---
name: browser-testing
description: AI-assisted browser exploration patterns using agent-browser CLI. For visual
  verification and test discovery, NOT automated testing.
---

# Browser Testing Skill

Patterns for AI-assisted browser exploration using the `agent-browser` CLI tool.

**Purpose:** Visual verification and test discovery. Use this to confirm features work and
figure out how to write proper playwright e2e tests.

**This is NOT test automation.** For automated tests, use:
- **vitest** for unit and integration tests
- **playwright** for e2e test suites
- See the `testing-strategy` skill for when to use each

**See also:** `webapp-testing` skill for Playwright-based testing (Python scripts).

## When to Use agent-browser

| Scenario | Use agent-browser? | Instead |
|---|---|---|
| Initial smoke test of a feature | Yes | - |
| Discover UI elements before writing e2e tests | Yes | - |
| Visual verification (screenshots) | Yes | - |
| Debug UI issues | Yes | - |
| CI/CD test pipeline | **No** | Playwright |
| Regression testing | **No** | Playwright / vitest |
| Automated test suite | **No** | Playwright / vitest |
| Performance testing | **No** | Lighthouse / vitest benchmarks |

## Environment Setup

### Before Exploring

1. Start dev server (project-specific command from AGENTS.md)
2. Wait for server to be ready

### Verify Environment

```bash
agent-browser open http://localhost:3000
agent-browser snapshot -i
```

## Exploration Patterns

### Login Before Exploring

Most pages require authentication. Use demo accounts from AGENTS.md.

```bash
agent-browser open http://localhost:3000/login
agent-browser snapshot -i
agent-browser fill @e1 "user@example.com"
agent-browser fill @e2 "password123"
agent-browser click @e3
agent-browser wait --url "**/dashboard"
agent-browser wait --load networkidle
```

### Page Verification

```bash
# Navigate
agent-browser open http://localhost:3000/route
agent-browser wait --load networkidle

# Check what's on the page
agent-browser snapshot -i

# Take screenshot for evidence
agent-browser screenshot route-name.png
```

### Form Interaction

```bash
agent-browser fill @e1 "text"           # Clear and type
agent-browser type @e1 "additional"     # Type without clearing
agent-browser click @e1                 # Click button/link
agent-browser select @e1 "value"        # Select dropdown
agent-browser check @e1                 # Check checkbox
agent-browser press Enter               # Press key
```

### Element Finding

```bash
# By snapshot refs (preferred)
agent-browser snapshot -i
agent-browser click @e1

# Scoped to section
agent-browser snapshot -i -s "#main-content"
agent-browser snapshot -i -s ".sidebar"
```

### Wait Strategies

```bash
agent-browser wait @e1                  # Wait for element
agent-browser wait --text "Success"     # Wait for text
agent-browser wait --load networkidle   # Wait for network idle
agent-browser wait 2000                 # Fixed wait (last resort)
```

## Screenshot Best Practices

- Capture before and after key actions
- Always capture on failure
- Capture at verification points
- Use descriptive filenames: `settings-after-save.png`, not `screenshot1.png`

```bash
agent-browser screenshot step-name.png       # Viewport
agent-browser screenshot --full page-name.png # Full page
```

## Error Handling

### Element Not Found

1. Wait and retry (up to 3 times)
2. Re-snapshot to get fresh refs
3. Check if page loaded correctly
4. Take screenshot of current state

### Page Timeout

1. Check dev server is running
2. Check for console errors: `agent-browser errors`
3. Retry navigation once

## Translating to Playwright Tests

The main output of browser exploration should be information for writing proper e2e tests.
When exploring, note:

1. **Selectors that work:** What `getByRole`, `getByLabel`, `getByText` values to use
2. **Wait conditions:** What to wait for after actions (URL changes, elements appearing)
3. **Flow steps:** The sequence of actions for a user journey
4. **Edge cases discovered:** Unexpected behavior to test for

This information feeds directly into `/write-tests` when creating playwright e2e tests.

## CLI Reference

```bash
# Navigation
agent-browser open <url>
agent-browser back
agent-browser close

# Snapshots
agent-browser snapshot              # Full accessibility tree
agent-browser snapshot -i           # Interactive elements only

# Interactions
agent-browser click @e1
agent-browser fill @e1 "text"
agent-browser type @e1 "text"
agent-browser press Enter
agent-browser select @e1 "value"
agent-browser check @e1

# Information
agent-browser get text @e1
agent-browser get value @e1
agent-browser get url
agent-browser get count ".item"
agent-browser is visible @e1
agent-browser is enabled @e1
agent-browser errors

# Screenshots
agent-browser screenshot out.png
agent-browser screenshot --full out.png

# Wait
agent-browser wait @e1
agent-browser wait 2000
agent-browser wait --text "Success"
agent-browser wait --load networkidle

# Options
agent-browser --headed open <url>   # Visible browser window
```

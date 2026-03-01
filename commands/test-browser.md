---
description: AI-assisted browser verification. Visually confirm features work before writing automated tests.
argument-hint: "[URL, route, or 'current' for current branch changes]"
skills:
  - browser-testing
---

# Browser Verification Command

Use agent-browser to visually verify a feature works. This is an AI exploration tool, NOT
test automation. Use it to smoke-test features and discover UI behavior before writing proper
playwright e2e tests.

## Usage

```
/test-browser                    # Verify pages affected by current branch
/test-browser /settings          # Verify a specific route
/test-browser 847                # Verify pages affected by PR #847
```

## When to Use

- Initial smoke test after implementing a feature
- Discover UI elements and behavior before writing playwright tests
- Visual verification that can't be done programmatically
- Debugging UI issues with screenshots
- Figuring out how to automate an e2e test (what selectors to use, what flows look like)

## When NOT to Use

- **Never for CI or automated test suites** - use playwright for that
- **Never as a replacement for real tests** - this is exploration, not testing
- **Never for regression testing** - write proper e2e tests instead

## Prerequisites

- Local development server running (check AGENTS.md for start command)
- agent-browser CLI installed (`npm install -g agent-browser && agent-browser install`)

## Process

### 1. Determine What to Verify

**If route provided:** Verify that specific page.

**If PR number or current branch:**

```bash
# Get changed files
git diff --name-only main...HEAD
```

Map changed files to routes (check AGENTS.md for project routing conventions).

### 2. Verify Server is Running

```bash
agent-browser open http://localhost:3000
agent-browser snapshot -i
```

If server is not running, inform user and stop.

### 3. Verify Each Affected Page

For each route:

**Navigate and capture snapshot:**

```bash
agent-browser open "http://localhost:3000/[route]"
agent-browser snapshot -i
```

**Check for:**
- Page loads without errors
- Key content is rendered
- No error messages visible
- Forms have expected fields
- Interactive elements are present

**Test critical interactions:**

```bash
agent-browser click @e1
agent-browser snapshot -i
```

**Take screenshots for evidence:**

```bash
agent-browser screenshot step-name.png
```

### 4. Handle Auth-Required Pages

Use demo accounts from AGENTS.md to log in before verifying protected routes.

### 5. Report Results

```markdown
## Browser Verification Results

**Scope:** [route / PR / branch]
**Server:** http://localhost:3000

| Route | Status | Notes |
|---|---|---|
| /settings | OK | All elements render correctly |
| /dashboard | Issue | Missing chart component |

### Issues Found
- [Description of any problems]

### Screenshots
- [References to captured screenshots]

### Suggestions for E2E Tests
- [Routes/flows that should have playwright e2e tests]
- [Key selectors and interaction patterns discovered]
```

The "Suggestions for E2E Tests" section is the main value - it informs what proper automated
tests should be written with `/write-tests`.

## agent-browser Quick Reference

```bash
# Navigation
agent-browser open <url>
agent-browser back
agent-browser close

# Snapshots
agent-browser snapshot -i          # Interactive elements with refs

# Interactions
agent-browser click @e1
agent-browser fill @e1 "text"
agent-browser press Enter

# Screenshots
agent-browser screenshot out.png
agent-browser screenshot --full out.png

# Checks
agent-browser is visible @e1
agent-browser get text @e1
agent-browser get url
agent-browser errors
```

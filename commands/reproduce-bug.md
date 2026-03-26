---
description: Reproduce and investigate a bug using browser automation, logs, and screenshots.
argument-hint: "[GitHub issue number or description]"
---

# Reproduce Bug Command

Reproduce a reported bug visually using browser automation, gather evidence, and document
findings. Integrates with `/investigate` for deeper root cause analysis.

## Usage

```
/reproduce-bug 42                    # Reproduce bug from GitHub issue #42
/reproduce-bug "login form breaks"   # Reproduce from description
```

## When to Use

| Situation                           | Use `/reproduce-bug`? | Instead Use    |
| ----------------------------------- | --------------------- | -------------- |
| UI bug with visual symptoms         | Yes                   | -              |
| User-reported flow breakage         | Yes                   | -              |
| Backend/data issue (no UI)          | **No**                | `/investigate` |
| Understanding code (not a bug)      | **No**                | `/research`    |

**This command focuses on visual reproduction.** For backend investigation (database, logs,
infrastructure), use `/investigate` instead -- or use both together.

## Process

### Phase 1: Gather Bug Context

**If GitHub issue number provided:**

```bash
gh issue view $ARGUMENTS --json title,body,comments
```

**If description provided:** Use it directly as the bug report.

Extract:

- **Reproduction steps** from the issue
- **Expected vs actual behavior**
- **Affected routes/pages**
- **Environment details** (browser, screen size, etc.)

### Phase 2: Investigate Code

Spawn investigator agents in parallel based on the bug symptoms:

| Symptoms                                  | Agent                   | Why                   |
| ----------------------------------------- | ----------------------- | --------------------- |
| crash, OOM, timeout, deploy               | `investigator-render`   | Infrastructure issues |
| connection, query, data, records, missing  | `investigator-postgres` | Database state        |
| code, bug, pattern, logic error            | `researcher`            | Codebase analysis     |

Think about where the bug could originate. Look for logging output, error handlers, and
relevant code paths.

### Phase 3: Visual Reproduction with agent-browser

If the bug is UI-related or involves user flows, reproduce it visually.

**Step 1: Verify server is running**

```bash
agent-browser open http://localhost:3000
agent-browser snapshot -i
```

If server is not running, inform user to start their dev server (check AGENTS.md).

**Step 2: Navigate to affected area**

```bash
agent-browser open "http://localhost:3000/[affected_route]"
agent-browser snapshot -i
```

**Step 3: Follow reproduction steps from the issue**

Execute each step:

```bash
agent-browser snapshot -i          # Get element refs
agent-browser click @e1            # Click element
agent-browser fill @e2 "text"      # Fill form field
agent-browser screenshot bug-step-1.png  # Capture evidence
```

**Step 4: Capture bug state**

When the bug is reproduced:

```bash
agent-browser screenshot bug-reproduced.png
```

Document:

- The exact steps that triggered the bug
- What the user sees (from snapshot)
- Any console errors visible in the page

### Phase 4: Document Findings

Create or update `investigation.md` in the work item folder with:

- **Reproduction steps** - Exact steps verified to reproduce
- **Screenshots** - Visual evidence of the bug
- **Relevant code** - File paths and line numbers (`file:line` format)
- **Root cause hypothesis** - What you think is causing it
- **Suggested fix** - If apparent from investigation

### Phase 5: Report Back

**If GitHub issue was provided**, add a comment with findings:

```bash
gh issue comment $ISSUE_NUMBER --body "$(cat <<'EOF'
## Bug Investigation

**Reproduced:** Yes/No

### Reproduction Steps (Verified)
1. Navigate to /[route]
2. [Step 2]
3. [Step 3]

### Root Cause
[Description of what's causing the bug]

### Relevant Code
- `file:line` - [description]

### Suggested Fix
[High-level fix description]
EOF
)"
```

**If no issue**, present findings to the user and suggest next steps:

- `/investigate` for deeper root cause analysis
- `/plan` to design a fix
- `/lfg` for autonomous fix workflow

## Integration with Existing Workflows

This command complements `/investigate`:

| Command           | Focus              | Output              |
| ----------------- | ------------------ | ------------------- |
| `/reproduce-bug`  | Visual reproduction | Screenshots, steps  |
| `/investigate`    | Root cause analysis | investigation.md    |

For comprehensive bug handling, run both:

1. `/reproduce-bug 42` - Confirm and document the bug visually
2. `/investigate 42` - Deep dive into root cause
3. `/plan 42` - Design the fix

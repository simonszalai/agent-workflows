---
name: create-pr
description: Generate summary report and create PR from a work item. Collects what was done, test results, verification status.
---

# Create PR Command

Generate a summary of all work done, create a commit, push, and open a pull request. This is
the final step of autonomous workflows (`/lfg`, `/auto-build`) and can also be called manually.

## Usage

```
/create-pr F007                     # Create PR for feature F007
/create-pr B001                     # Create PR for bug fix B001
/create-pr F007 --draft             # Create as draft PR
/create-pr F007 --issue 123         # Link to GitHub issue #123
```

## Process

### 1. Gather Context

Load the ticket with all artifacts:

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

**Read these artifacts from the ticket response:**

| Artifact Type | What It Provides |
|---|---|
| `source` | Title, type, requirements, GitHub issue number |
| `plan` | Approach summary, what was planned |
| `build_todo` (multiple) | Count of steps, what was implemented |
| `review_todo` (multiple) | Review findings and their resolution status |
| `investigation` | Root cause (for bugs) |
| `learning_report` | Knowledge/workflow improvements made |
| `deployment_guide` | Deployment steps |

### 2. Collect Test Results

Run the project's test suite and capture results:

```bash
# Run tests (project-specific command from AGENTS.md)
bun run test 2>&1
```

Record:
- Total tests run
- Tests passing
- Tests failing
- Test types (unit, integration, e2e)

If tests were already run recently (within this workflow), use those results instead of
re-running.

### 3. Collect Verification Status

Check for verification evidence:
- Was `/verify local` run? What was the result?
- Were there any manual verifications?
- Was `/test-browser` used for visual verification?

### 4. Get Files Changed

```bash
# Files changed on this branch vs main
git diff --stat main...HEAD
git diff --name-only main...HEAD
```

### 5. Generate Summary

Create the PR summary with this structure:

```markdown
## Summary

{1-3 sentences: what this PR does and why}

## What Was Done

{For features: what was implemented}
{For bugs: root cause and fix approach}

- Build steps completed: N/N
- Files changed: N

## Test Results

| Type | Count | Status |
|---|---|---|
| Unit tests | N | PASS |
| Integration tests | N | PASS |
| E2E tests | N | PASS |
| **Total** | **N** | **{PASS/FAIL}** |

{If tests were written as part of this work:}
### Tests Written
- {test file}: {what it tests} (N tests)

{If any tests were intentionally skipped:}
### Not Tested (with reasons)
- {thing}: {reason}

## Verification

**Status:** {PASS | FAIL | SKIPPED}

{If verified:}
- {How it was verified: local tests, browser verification, etc.}
- {Key scenarios checked}

{If skipped:}
- Reason: {why verification was skipped}

## Review

- Review iterations: N
- Findings resolved: N (P1: X, P2: Y, P3: Z)
- Remaining P3 findings: N

## Files Changed

| File | Change |
|---|---|
| `path/to/file` | {brief description} |

{If pyproject.toml, Dockerfile, or requirements.txt changed (check with git diff --name-only main...HEAD):}
## Dependency Changes

> **Manual Render deploy required.** Dependencies changed ({list files}), which requires
> rebuilding the worker image. Trigger a manual deploy on Render after merging.

{If deployment guide exists:}
## Deployment Notes

{Key deployment steps or "No special deployment steps required"}

{If GitHub issue:}
---
Closes #{issue_number}
```

### 6. Commit All Changes

```bash
git add -A
git commit -m "$(cat <<'EOF'
{work-item-id}: {title}

{For bugs: "Root cause: {root cause summary}"}
{For features: "Implements {brief description}"}

- Tests: {N passing, N total}
- Review: {N findings resolved}

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>
EOF
)"
```

### 7. Push and Create PR

```bash
git push -u origin {branch-name}

gh pr create \
  --title "{work-item-id}: {title}" \
  --body "$(cat <<'EOF'
{generated summary from step 5}

---
Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

**If `--draft`:** Add `--draft` flag to `gh pr create`.

**If `--issue` or GitHub issue in source.md:**

```bash
# Link PR to issue
gh issue comment {issue_number} -b "PR ready for review: #{pr_number}"
```

### 8. Output

Always output the PR link clearly:

**On success:**

```
PR created: {pr_url}

Summary:
- {What was done in 1 sentence}
- Tests: {N passing} / {N total}
- Verification: {PASS/FAIL/SKIPPED}
- Review: {N findings resolved, N remaining P3}

Work item: {work-item-id}
```

**On push failure:**

```
Could not push to remote.

Branch: {branch-name}
Error: {error message}

Manual steps:
1. git push -u origin {branch-name}
2. gh pr create --title "{title}" --body-file {report-path}
```

## When Called from Autonomous Workflows

### From /lfg

- No ticket — reads context from `.context/` directory
- Branch name from conversation context
- May have GitHub issue (link and comment)
- Summary includes research/investigation phase

### From /auto-flow

- Branch: `auto-flow/{work-item-id}`
- Full ticket artifacts available via MCP
- May have GitHub issue (link and comment)
- Summary includes research/investigation phase

### From /auto-build

- Branch: `auto-build/{work-item-id}`
- May or may not have GitHub issue
- Summary includes deployment guide

## When Called Manually

- User must be on a feature branch (not main)
- Reads work item artifacts if a work item ID is provided
- If no work item: generates summary from git diff and recent test results
- Asks user to confirm before pushing

## Summary Quality Rules

1. **Be specific, not generic.** "Added batch size limit of 200 with chunked processing" not
   "Fixed the issue"
2. **Include numbers.** Test counts, file counts, review iteration counts
3. **State verification clearly.** Don't bury test results - they should be prominent
4. **Link to issue when available.** Use "Closes #N" for automatic GitHub linking
5. **Keep it scannable.** Use tables and bullet points, not paragraphs

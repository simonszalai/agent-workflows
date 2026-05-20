---
name: auto-polish-web
description: Autonomous UI/UX polish loop for web projects. Runs as a sibling step between /auto-build and /auto-deploy (orchestrated by /auto-flow). Iteratively critiques and refines the built feature in a real browser on the pushed branch until converged or iteration cap is hit. Composes a repo-level plugin for all repo-specific knowledge.
max_turns: 200
---

# Auto-Polish-Web

Web-app-scoped polish loop. After a feature has been implemented and reviewed, this skill
opens the built feature in a real browser, critiques the UI/UX against repo-specific design
rules, applies refinements, verifies they do not break anything, and repeats until the UI
converges or the iteration cap is hit.

**Platform scope:** web only. Mobile/desktop/native polish would be separate skills that do
not exist yet.

## Composition Pattern

This skill OWNS the loop. Repo-specific knowledge (dev command, login flow, design rules,
scope of things to polish) comes from a repo-level plugin invoked via slash-command.

- Plugin location: `.claude/skills/repo-plugin/SKILL.md` in the target repo
- Invocation: `/repo-plugin <subcommand> [args]`
- If the plugin is absent, this skill EXITS cleanly with status `skipped` — it never falls
  back to generic defaults. Polish without repo-specific rules produces generic churn, not
  quality.

## Usage

```
/auto-polish-web F007                     # Polish the feature from ticket F007
/auto-polish-web B001                     # Polish a bug fix's UI changes
/auto-polish-web F007 --max-iterations=5  # Override default iteration cap (default 10)
```

Standard invocation happens inside `/auto-build`, after review resolution and before PR
creation. Polish commits land on the existing build branch so the initial PR already
reflects the polished state.

Can also be invoked standalone against any ticket whose feature is on the current branch.

## Prerequisites

- Ticket exists with an approved plan artifact
- Build phase has completed (code compiles)
- Repo has `.claude/skills/repo-plugin/SKILL.md`
- Working directory is on a feature branch (polish commits land here)

## Process

### Phase 1: Gating

1. Verify plugin exists: `.claude/skills/repo-plugin/SKILL.md`
   - If missing: emit `skipped: no repo-plugin in repo`, exit 0, create no artifact
2. Invoke `/repo-plugin polish-should-run {ticketId}`:
   - Plugin analyzes `git diff` against the merge base and the ticket's plan
   - Returns `{run, reason, ui_files_changed}`
   - If `run=false`: create `polish_report` with status `skipped` and reason, exit 0
3. Invoke `/repo-plugin dev-env`:
   - Returns `{dev_cmd, url, ready_signal, login_flow}`
4. Invoke `/repo-plugin polish-scope {ticketId}`:
   - Returns ordered list of `{route, purpose}` derived from plan + diff
5. Invoke `/repo-plugin design-rules`:
   - Returns narrative rubric (surface hierarchy, theme tokens, repo preferences)

### Phase 2: Start Dev Server

Use `nohup` — never Node `spawn()` — so the server survives shell detachment.

```bash
nohup <dev_cmd> > /tmp/polish-dev.log 2>&1 &
echo $! > /tmp/polish-dev.pid
```

Wait up to 60s for the `ready_signal` to appear in the log or the URL to respond 200.

**If the server fails to start:**

1. Read last 50 lines of `/tmp/polish-dev.log`
2. Diagnose the error (missing dep, port in use, config error, etc.)
3. Make ONE repair attempt — fix the root cause in code or config, not the symptom
4. Kill any stale process on the port, retry the start
5. If still failing: STOP. Create `polish_report` with status `dev_server_failure` and the
   repair steps attempted. Do not proceed. Build flow continues without polish.

If login flow is defined, execute it via gstack navigation before the loop begins.

### Phase 3: Polish Loop (up to 10 iterations)

Track per iteration:
- findings captured (count + list)
- findings resolved (acted on in this iteration)
- changes applied (file:line list)
- verify result
- commit sha
- screenshot refs

For iteration N (1..max_iterations):

1. **Capture state.** For each `scope` entry, navigate via gstack, snapshot, save screenshot
   reference.
2. **Critique.** Compose findings from three sources:
   - Generic web UX heuristics: accessibility, contrast, spacing, alignment, typographic
     rhythm, focus order, loading states, empty states, error states, responsive behavior
   - Plugin-returned `design-rules` (repo-specific)
   - Diff against previous iteration's screenshots — do not re-surface already-acted-on
     findings as new
3. **Prioritize.** Score findings by `severity (1-3) * impact (1-3)`. Pick top 3-5. Defer
   the rest to later iterations (or to the `final_findings_remaining` list if skipped).
4. **Apply changes.** Edit files to address prioritized findings. Keep each iteration's
   changes scoped — do not spread into unrelated files.
5. **Verify.** Invoke `/repo-plugin verify`:
   - Returns `{pass, errors, duration_ms}`
   - **If fail:** `git restore .` to revert iteration's edits, log to iteration record,
     mark as `verify_failed`, do NOT commit. Continue to next iteration only if failure
     cause looks different from previous iteration.
   - **If fail on two adjacent iterations with overlapping changed files:** STOP. Status
     `verify_failure`. Report in artifact.
6. **Commit.** If verify passed and changes were made:
   ```bash
   git add -A
   git commit -m "polish: <1-line summary of this iteration's changes>"
   ```
7. **Convergence check.**
   - If the iteration produced no new findings AND the previous iteration produced no new
     findings: STOP. Status `converged`.
   - If iteration counter == max_iterations: STOP. Status `iteration_cap`.
   - Else: continue.

### Phase 4: Cleanup & Report

1. Kill dev server:
   ```bash
   kill $(cat /tmp/polish-dev.pid) 2>/dev/null || true
   rm -f /tmp/polish-dev.pid
   ```
2. Create `polish_report` artifact on the ticket:
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="polish_report",
     content=<JSON, see below>
   )
   ```
3. Emit console summary.

## Artifact: polish_report

```json
{
  "status": "converged | iteration_cap | verify_failure | dev_server_failure | skipped",
  "reason": "<short explanation, required if non-converged>",
  "iterations_run": 3,
  "max_iterations": 10,
  "scope": [{"route": "/clients", "purpose": "new filter UI"}],
  "dev_server": {
    "started": true,
    "repair_attempts": 0,
    "log_excerpt": "<last 10 lines on failure>"
  },
  "iterations": [
    {
      "index": 1,
      "findings_captured": 7,
      "findings_resolved": ["contrast on filter chip", "heading spacing off"],
      "findings_deferred": ["tooltip delay feels slow"],
      "changes": ["app/components/ClientFilters.tsx:45", "app/routes/clients+/_index.tsx:112"],
      "verify": "pass",
      "verify_duration_ms": 12340,
      "commit": "abc1234"
    }
  ],
  "final_findings_remaining": [],
  "commits": ["abc1234", "def5678"],
  "stopped_reason": "two consecutive iterations produced no new findings"
}
```

## Failure Modes

| Failure                              | Behavior                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------- |
| Plugin missing                       | Skip silently. Exit 0. No artifact.                                       |
| `should-run=false`                   | Skip. Create artifact (`status=skipped`). Exit 0.                         |
| Dev server won't start, repair fails | STOP. Artifact (`status=dev_server_failure`). Build continues, no polish. |
| Verify fails on one iteration        | Revert iteration. Continue.                                               |
| Verify fails on two adjacent iters   | STOP. Artifact (`status=verify_failure`).                                 |
| Ticket plan artifact missing         | STOP. Report. (Cannot scope without plan.)                                |
| Max iterations reached               | STOP. Artifact (`status=iteration_cap`).                                  |

## Stop Criteria (success or benign failure)

- **Converged:** two consecutive iterations produced no new findings
- **Iteration cap:** reached `max_iterations` (default 10)
- **Verify failure:** two adjacent iterations broke the build on overlapping files
- **Dev server failure:** could not start + one repair attempt failed
- **Skipped:** gating said no

## Key Tools

- **gstack** (`$B = ~/.claude/skills/gstack/browse/dist/browse`) — browser automation
- **interface-craft Design Critique** methodology — composing findings
- **Repo plugin** `/repo-plugin <subcommand>` — all repo specifics
- **autodev-memory MCP** — artifact creation

## Integration with /auto-build

`/auto-build` invokes this skill between review resolution and compound. The polish phase
is skipped silently if no plugin exists. Failures inside polish do NOT fail the overall
build — they produce a `polish_report` and the build continues without the polish changes.

## Output

### On convergence
```
Polish complete — converged at iteration N.
- Scope: R routes
- Findings resolved: X
- Commits added: N
- Artifact: polish_report on {ticketId}
```

### On iteration cap
```
Polish complete — iteration cap (10) reached.
- Findings resolved: X
- Findings remaining (deferred): Y — see artifact
- Commits added: N
```

### On verify failure
```
Polish stopped — verify failed on two adjacent iterations.
- Polish commits created: N (kept, last iteration reverted)
- Artifact: polish_report on {ticketId} (status=verify_failure)

Build continues. PR reflects polish commits that did pass verify.
```

### On dev server failure
```
Polish skipped — dev server could not start.
- Repair attempt: {what was tried}
- Artifact: polish_report on {ticketId} (status=dev_server_failure)

Build continues without polish. PR reflects pre-polish state.
```

### On skipped
```
Polish skipped — {reason from plugin or "no polish plugin in repo"}.
```

## Work Log Entry

Add one line to the ticket's plan work log:

```
| YYYY-MM-DD | auto-polish-web | {status} | Iterations: N, Findings resolved: X, Commits: N |
```

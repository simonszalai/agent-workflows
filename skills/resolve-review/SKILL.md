---
name: resolve-review
description: Resolve review findings based on decisions. Spawns builder agent to implement fixes from review_todo artifacts, captures learnings.
skills:
  - autodev-search
  - compound
---

# Resolve-Review Command

Spawn a `builder` agent to work through review findings and implement accepted fixes.
Routes findings by autofix classification — safe fixes are applied automatically, gated
fixes use the caller's approval scope, and genuinely undecided manual findings are handed off.

## Usage

```
/resolve-review 009                              # Bug/incident #009 (NNN format)
/resolve-review F001                             # Feature F001 (FNNN format)
/resolve-review B0009                            # Bug ticket B0009
/resolve-review F001 --builder codex             # Fixes via bin/external-build --task resolve
```

With `--builder codex`, approved fixes are dispatched through `bin/external-build --task
resolve` (gpt-5.6 / `medium` by default) with a self-contained findings file and context
blob — the Codex side has no MCP access. Create the bounded memory packet first:

```bash
mkdir -p .context/resolve
if ! cat .context/resolve/findings.md | \
    autodev-memory-task-packet --cwd "$PWD" --session-id "${SESSION_ID:-}" \
      --agent-type builder --provider codex --mechanism external_build \
      --task-prompt-stdin --allow-unavailable > .context/resolve/memory.md; then
  cat > .context/resolve/memory.md <<'EOF'
<autodev-memory-task-context>
Memory context is unavailable. Do not infer that critical memories were loaded.
This external builder has no memory tool; proceed only from the findings file and report the limitation.
</autodev-memory-task-context>
EOF
fi
external-build --task resolve --findings-file .context/resolve/findings.md \
  --context-file .context/resolve/context.md \
  --memory-context-file .context/resolve/memory.md \
  --repo "$(pwd)" --out .context/resolve/result.json
```

Validate the returned JSON array against the resolve-mode contract before setting
artifact statuses; the orchestrator still owns all statuses and commits.

## Prerequisites

- Pending review_todo artifacts exist on the ticket (or, in ticketless lfg mode, finding
  files exist in `.context/review_todos/`)
- (Optional) User has filled Decision sections

## Autofix Classification Routing

Review findings are classified by the `/review` orchestrator. Each class has a different
resolution path:

| autofix_class | Default owner | Resolution |
| ------------- | ------------- | ---------- |
| `safe_auto` | `review-fixer` | **Auto-apply.** Builder implements fix without asking. Local, deterministic changes. |
| `gated_auto` | `downstream-resolver` | **Check approval scope.** Concrete deterministic fix that changes behavior/contracts or a sensitive surface. |
| `manual` | `downstream-resolver` | **Hand off only while undecided.** A genuine product, scope, tradeoff, secret/schema/infrastructure/cost, or conflict decision remains. |
| `advisory` | `human` | **Skip.** Already reported during review. No code fix needed. |

**Autonomous runs (ticket-flow / lfg / ticket-deploy).** Severity does not determine
decision ownership. Reclassify an incorrectly labeled `manual` finding as `gated_auto` when the
approved plan and repository rules determine one concrete fix. An autonomous runner may apply a
`gated_auto` fix when it is plan-conformant and corroborated — skeptic-upheld
(`requires_verification: false` after the verify pass) or multi-reviewer consensus. An explicit
`/ticket-flow prod` (or `/ticket-deploy prod|full`) invocation is standing approval for that queue and for bounded
resolve/re-review rounds. Do not interrupt full-auto for another approval merely because the
finding is p1, behavioral, destructive-path, or security-sensitive. Defer uncorroborated or
scope-expanding work. Stop for `manual` only when the human choice is genuinely absent from the
ticket and current conversation; a recorded user decision moves the finding into the approved
builder queue.

## Process

1. **Load ticket** via `get_ticket(detail="full", artifact_types=["review_todo"],
   include_events=false)` — identify pending review_todo artifacts

2. **Partition findings by autofix_class:**

   Read all review_todo artifacts. Group by autofix_class:

   - **safe_auto queue:** Implement immediately (no approval needed)
   - **gated_auto queue:** Apply when covered by the caller's approval scope; otherwise present it
   - **manual queue:** First check whether the decision is already recorded; otherwise present options
   - **advisory:** Mark as skipped (already reported)

3. **Spawn builder for safe_auto fixes** (model `sonnet` — safe_auto stays cheap):

   ```
   Agent(
     subagent_type="builder",
     fork_turns="none",
     model="sonnet",
     prompt="
       MODE: resolve
       Ticket: {ticket_id}
       Project: {PROJECT}
       Repo: {REPO}

       Apply these SAFE AUTO fixes (no approval needed):

       {for each safe_auto review_todo artifact:}
       - Finding #{sequence}: {title}
         Severity: {p1/p2/p3}
         Confidence: {confidence}
         Suggested Fix: {suggested fix from artifact}
         File: {file_path}:{line_number}
       {end for}

       For each fix:
       - CRITICAL: Before removing any export/class/function, search ALL usages first
       - Implement the suggested fix exactly as written
       - Do NOT run tests, validation, typecheck, lint, builds, schema pulls/migrations,
         browser verification, or health commands
       - Report risks and exact suggested orchestrator validation commands without executing them
       - For each p1 correctness fix: add a regression test (failing-then-passing)
         or state an explicit reason why it is untestable
       - Do NOT set review_todo artifact status — return structured JSON instead

       Return the resolve-mode JSON array defined in agents/builder.md.
     "
   )
   ```

4. **Resolve gated_auto approval:**

   In full-auto runs (`/ticket-flow prod`, `/ticket-deploy full`), add each plan-conformant corroborated finding directly to the approved
   builder queue. In other modes, use any explicit approval already present in the ticket or current
   conversation. Only when neither applies, present the fix and ask:

   ```
   Gated fix: {title}
   File: {file}:{line}
   Why: {why_it_matters}
   Confidence: {confidence}
   Suggested fix: {suggested_fix}

   This changes behavior/contracts. Apply? (yes / no / modify)
   ```

   - **yes:** Add to builder queue, implement fix
   - **no:** Mark as skipped with reason
   - **modify:** User provides alternative fix, add to builder queue

5. **Resolve genuine manual decisions:**

   First check the ticket and current conversation for a recorded decision. If it supplies the
   missing choice, add the finding to the approved builder queue. Otherwise present options:

   ```
   Manual finding: {title}
   File: {file}:{line}
   Why: {why_it_matters}
   Confidence: {confidence}

   This requires a design decision. Options:
   1. Implement suggested fix: {suggested_fix}
   2. Provide alternative approach
   3. Defer to a separate work item
   4. Skip — not worth fixing
   ```

6. **Spawn builder for approved gated/manual fixes** (model `opus` — gated_auto/manual fixes
   change behavior/contracts and warrant the stronger model):

   ```
   Agent(
     subagent_type="builder",
     fork_turns="none",
     model="opus",
     prompt="
       MODE: resolve
       Ticket: {ticket_id}
       Project: {PROJECT}
       Repo: {REPO}

       Apply these APPROVED fixes:

       {for each approved finding:}
       - Finding #{sequence}: {title}
         Decision: {accept/modify}
         Fix: {suggested fix or user-provided alternative}
         File: {file_path}:{line_number}
       {end for}

       For each fix:
       - CRITICAL: Before removing any export/class/function, search ALL usages first
       - Implement the fix as specified
       - Do NOT run tests, validation, typecheck, lint, builds, schema pulls/migrations,
         browser verification, or health commands
       - Report risks and exact suggested orchestrator validation commands without executing them
       - For each p1 correctness fix: add a regression test (failing-then-passing)
         or state an explicit reason why it is untestable
       - Do NOT set review_todo artifact status — return structured JSON instead

       Return the resolve-mode JSON array defined in agents/builder.md.
     "
   )
   ```

6a. **Validate builder JSON and set artifact statuses (orchestrator-owned):**

   The builder does NOT set review_todo artifact status. For each builder that returns,
   parse its resolve-mode JSON array (`{finding_id, status, files_changed,
   risks_unverified, suggested_validation, regression_test}` per entry) and validate it:

   - every dispatched finding has an entry;
   - `status` is `resolved`, `skipped`, or `deferred`;
   - `resolved` entries identify changed files plus risks/unverified items and suggested
     orchestrator validation;
   - `resolved` p1 entries have a `regression_test` (or an explicit untestable reason).

   Only then set each review_todo artifact's status via `update_artifact` (`resolved` /
   `skipped`). Entries that fail validation stay `pending` and are re-dispatched or surfaced
   to the user. Same trust model as build mode: an artifact is never marked resolved on the
   builder's say-so alone. These statuses record that the accepted fix was applied; the caller's
   final health gate owns validation truth for the changed tree.

7. **After builder returns — capture learnings:**
   - Run `/compound` to analyze the fixes
   - `/compound` will propose improvements to memory entries AND workflows
   - In interactive mode, it will ask for approval before applying

8. **Apply process improvement recommendations:**

   `/compound` handles all updates — including MCP calls to persist knowledge:

   | Recommendation Type             | Target Location                                        |
   | ------------------------------- | ------------------------------------------------------ |
   | Project-specific pitfall        | Memory service via `mcp__autodev-memory__create_entry` |
   | Reusable pattern                | Memory service via `mcp__autodev-memory__create_entry` |
   | Plan research requirement       | `skills/ticket-plan/SKILL.md`                             |
   | Build todo research requirement | `skills/create-build-todos/SKILL.md`                    |
   | Build verification step         | `skills/build/SKILL.md`                                 |

9. **Update the plan artifact:**

   Append a completion summary to the ticket's `plan` artifact via
   `mcp__autodev-memory__update_artifact` (the plan lives in MCP, not on disk).
   Insert the section below before the existing Work Log:

   ```markdown
   ---

   ## Review Resolution Summary

   **Resolved:** YYYY-MM-DD

   ### What Was Done

   - [Key fix 1: brief description]
   - [Key fix 2: brief description]

   ### Findings Summary

   | Category    | safe_auto | gated_auto | manual | advisory | Total |
   | ----------- | --------- | ---------- | ------ | -------- | ----- |
   | Applied     | N         | N          | N      | -        | N     |
   | Skipped     | -         | N          | N      | N        | N     |

   ### Files Changed

   | File              | Change              |
   | ----------------- | ------------------- |
   | `path/to/file.py` | [brief description] |

   ### Learnings Captured

   - [Knowledge doc created, or "None"]

   ### Process Improvements Applied

   - [Where improvement was added, or "None"]
   ```

   Add work log entry:

   ```
   | YYYY-MM-DD | resolve-review | Resolved N findings | X applied, Y skipped |
   ```

10. **Create deployment guide:**

   Run `/create-deployment-guide` to generate deployment instructions:
   - Analyzes changes and creates the `deployment_guide` artifact on the ticket
   - Documents deployment steps, verification, rollback plan
   - Identifies affected services and requirements
   - **Pass the review's coverage exhaust into it:** the final review round's
     `testing_gaps` and `residual_risks` become candidate **Verification Evidence rows**
     (staging section) — each gap/risk turned into a reproducible check with expected
     good output. This is what converts "risk I couldn't confirm at review time" into a
     graded staging obligation instead of prose that evaporates. Drop a gap/risk only
     with a stated reason (e.g. already covered by an existing row).

   This step can be skipped for trivial changes (e.g., doc-only updates).

11. **Commit changes (ticketed standalone runs only, submodule-aware):** _(no permission
    needed)_

    **Ticketless (lfg) runs skip this step entirely** — lfg forbids pushing and owns its own
    commits. The commit/push below applies only to ticketed standalone runs.

    Handle submodules first, then main repo:

```bash
# Check for submodule changes
git status --porcelain | grep "^.M"
```

**If submodule has changes:**

```bash
# 1. Commit inside the submodule first
cd submodule_name
git add -A
git commit -m "Update for [work-item-id]: [brief description]"
git push
cd ..

# 2. Stage the submodule reference in main repo
git add submodule_name
```

**Then commit main repo:**

```bash
# Stage all other changes
git add -A

# Commit with standard message
git commit -m "Resolve review findings for [work-item-id]: [summary]"

# Push to remote
git push
```

**Important:** Always commit and push submodule changes BEFORE committing the main repo reference to avoid "new commits" state conflicts.

## Ticketless Mode (lfg)

When resolve-review runs without a ticket (e.g. under `/lfg`):

- Findings live as files in `.context/review_todos/` instead of MCP review_todo artifacts.
- Routing is identical (safe_auto / gated_auto / manual / advisory), and the orchestrator
  still validates the builder's resolve JSON — it records outcomes in the finding files
  instead of via `update_artifact`.
- **No commit/push.** lfg forbids pushing and owns its own commits; step 11 applies only to
  ticketed standalone runs.

## Output

### On Success

```
Review resolved for {ID}: {title}

Applied: {N} fixes ({safe_auto} auto, {gated_auto} gated, {manual} manual)
Skipped: {N} ({advisory} advisory)

Next: deploy via /ticket-flow (/auto-deploy) — or done, if this run is ticketless (lfg)
or no deployment is needed
```

Step 11 already committed and pushed (ticketed runs), so the next step is the deploy path,
not PR creation.

### Artifacts Produced

- Updated review_todo artifacts (statuses set by the orchestrator after validating the
  builder's resolve JSON)
- Code fixes for accepted findings
- Updated the `plan` artifact (via `update_artifact`) with Review Resolution Summary and work log entry
- `deployment_guide` artifact with deployment instructions
- Optional memory entries via `/compound`
- Process improvements applied to:
  - `skills/ticket-plan/SKILL.md` (plan research requirements)
  - `skills/create-build-todos/SKILL.md` (build todo research requirements)
  - `skills/build/SKILL.md` (verification steps)
  - Memory service via MCP (project-specific pitfalls, reusable patterns)

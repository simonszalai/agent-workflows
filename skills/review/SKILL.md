---
name: review
description: Review implementation against the plan. Spawns review agents in parallel, collects findings into review_todos/.
---

# Review

Review implementation by spawning specialized review agents in parallel. Supports multiple
modes for different contexts (interactive, autonomous, read-only, programmatic).

## Usage

```
/review 009                              # Bug/incident #009 (NNN format)
/review F001                             # Feature F001 (FNNN format)
/review B0009                            # Bug ticket B0009
/review F001 mode:autofix                # Autonomous — apply safe fixes only
/review F001 mode:report-only            # Read-only — no mutations
/review F001 mode:headless               # Programmatic — structured output for callers
/review F001 mode:cross                  # Add external Codex + Grok reviewers, merge with Claude's
/review F001 --deep                      # Force heavyweight workflow path (overrides gate)
/review F001 --light                     # Force inline path (overrides gate, skips verify)
```

## Mode Detection

Parse `mode:` token from arguments. Default is interactive.

| Mode | When | Behavior |
| ---- | ---- | -------- |
| **Interactive** (default) | No mode token | Review, apply safe_auto fixes, present findings, ask about gated/manual |
| **Autofix** | `mode:autofix` | No user interaction. Apply safe_auto only, write artifacts, never commit/push |
| **Report-only** | `mode:report-only` | Read-only. Review and report, no edits or artifacts |
| **Headless** | `mode:headless` | Programmatic. Structured text output for skill-to-skill composition |
| **Cross** | `mode:cross` | Autofix-style synthesis, but the reviewer set is extended with external Codex + Grok reviewers. See Cross-Provider Reviewers below. |

### Autofix mode rules

- Skip all user questions. Never pause for approval.
- Apply only `safe_auto -> review-fixer` findings.
- Write review_todo artifacts for unresolved `gated_auto`/`manual` findings.
- Never commit, push, or create a PR. Parent workflows own those decisions.

### Report-only mode rules

- Skip all user questions.
- Never edit files or create artifacts.
- Safe for parallel read-only verification alongside other operations.

### Headless mode rules

- Skip all user questions.
- Apply `safe_auto -> review-fixer` findings in a single pass (no re-review).
- Return structured text envelope (see Headless Output below).
- Write review_todo artifacts but do not create todos.
- Never commit, push, or create a PR.
- End with "Review complete" as terminal signal for caller detection.

---

## Agent Dispatch

### Step 1: Analyze the Diff

Before spawning any reviewers, analyze the diff to determine which reviewers to spawn:

```bash
# Get changed files
git diff --name-only main

# Categorize changes
git diff --name-only main -- '*.py'                              # Python files
git diff --name-only main -- '*.ts' '*.tsx'                      # TypeScript files
git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' migrations/versions/  # Data
git diff --name-only main -- '*/flows/*.py' '*/tasks/*.py'       # Pipeline/flow code
git diff --name-only main -- '*/scrapers/*' '*/scraper*'         # Scraper code
git diff --name-only main -- 'prefect.*.yaml'                    # Prefect deployment config
git diff --name-only main -- '*/prompts/*' '*/contracts/*'       # LLM prompts/contracts
git diff --name-only main -- '*.md' '*.json' '*.yaml' '*.toml'  # Config/docs only
```

### Step 2: Select Reviewers

**Always-on reviewers** (spawn for every review):

| Agent    | Model    | Review References                                                                    | Focus                                |
| -------- | -------- | ------------------------------------------------------------------------------------ | ------------------------------------ |
| reviewer | `sonnet` | references/python-standards.md or typescript-standards.md, references/simplicity.md, references/patterns.md | Code quality, YAGNI, design patterns |
<!-- TODO: revert `opus` reviewer spawns below back to `fable` once available -->
| reviewer | `opus`  | references/architecture.md, references/security.md, references/performance.md        | Architecture, security, performance  |

**Conditional reviewers** (spawn based on diff analysis — agent judgment, not keyword matching):

| Condition                        | Agent    | Model  | Review References                                                  | Select when diff touches...                |
| -------------------------------- | -------- | ------ | ------------------------------------------------------------------ | ------------------------------------------ |
| Database/model/migration changes | reviewer | `opus` | references/data-integrity.md, references/migrations.md, references/deployment.md | Model files, migrations, schema changes    |
| React/frontend changes           | reviewer | `sonnet` | references/react-router.md, references/react-performance.md       | React components, routes, hooks, UI state  |
| Data pipeline changes            | reviewer | `sonnet` | references/data-adequacy.md                                       | Pipeline contracts, DAG nodes, data flow   |

**CRITICAL: data reviewer spawn rule.** Always check for model file changes explicitly:
```bash
git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' migrations/versions/
```
If ANY model or migration files appear, spawn the data reviewer. Do NOT rely on build_todos
or plan.md to determine this — check the actual diff. Missing migrations are a p1 finding.

**Project-specific persona reviewers** (discovered dynamically):

```bash
# Discover project-level persona reviewers
ls .claude/agents/*-reviewer.md 2>/dev/null
```

For each `*-reviewer.md` found in the project's `.claude/agents/`, spawn it as an
additional reviewer. These are project-specific personas with domain heuristics
(e.g., `pipeline-reviewer.md`, `prefect-ops-reviewer.md`).

**Activation rules for persona reviewers:**
- Read each persona's activation conditions (in its frontmatter or body)
- Only spawn if the diff touches files relevant to that persona
- When uncertain whether a persona is relevant, **spawn it** — prefer thoroughness

### Step 3: Announce the Review Team

Before spawning, announce which reviewers were selected and why:

```
Review team:
- code-quality (always) [sonnet]
- architecture-security-performance (always) [opus]
- data-integrity — migration file in migrations/versions/ [opus]
- react — components changed in app/components/ [sonnet]
- pipeline-reviewer — DAG node declarations modified [project persona]
```

This is progress reporting, not a blocking confirmation.

**All reviewer instances** include the `research` skill (references/past-work.md) to find and
reference issues caught in similar past implementations.

**All reviewer instances** return structured JSON per `references/findings-schema.json`.

### Cross-Provider Reviewers (mode:cross)

`mode:cross` keeps Claude as the orchestrator and self-reviewer (the native reviewers above
run exactly as in any other mode) and **adds two external reviewers — Codex and Grok — that
review the same diff by this same skill.** This catches model-specific blind spots: a finding
all three providers independently surface is far more likely real, and the cross-reviewer
confidence boost rewards that agreement automatically.

External reviewers are not Claude subagents (Claude must stay in-process on the subscription —
never shell out to `claude -p`). They are invoked through the `external-review` adapter
(`bin/external-review` in agent-workflows; symlink it onto `PATH`). The adapter feeds the
provider this skill (`SKILL.md` + the relevant `references/`) and the diff, and returns a
**reviewer-output envelope** (`{reviewer_key, findings, residual_risks, testing_gaps}`) whose
finding items match `references/findings-schema.json` — the exact shape Claude's own reviewers
return, so external findings flow through the *same* synthesis path with no special-casing.

Dispatch both providers **in parallel** with the Claude native reviewers (they each take
1–3 minutes, so never serialize them):

```bash
base=$(git merge-base HEAD origin/main 2>/dev/null || echo origin/main)
mkdir -p .context/review
external-review --provider codex --base "$base" --out .context/review/codex.json \
  2>.context/review/codex.log &
external-review --provider grok  --base "$base" --out .context/review/grok.json \
  2>.context/review/grok.log &
wait
```

Then fold the two envelopes into the reviewer set:

1. Read `.context/review/codex.json` and `.context/review/grok.json`. Each is one reviewer
   output (`reviewer_key` = `codex` / `grok`). A provider that failed still returns a valid
   envelope with empty `findings` and a `residual_risks` note (adapter exit 2) — it simply
   contributes no findings; surface its note but do not block.
2. Add codex and grok to the reviewer list passed into synthesis alongside the Claude native
   reviewers. **Do not run a separate synthesis for them** — they are reviewers, not a second
   review.
3. Run the normal synthesis (light inline or heavy `review-fanout`): dedup by
   `(file, normalized title, |line diff| ≤ 3)`, then the cross-reviewer boost
   `confidence += 0.10 * (reviewers.length - 1)` now counts Codex and Grok as reviewers, so a
   finding Claude + Codex + Grok all report is boosted by +0.20. Gate, partition, route as usual.

Finding handling follows the **autofix** rules (apply `safe_auto`, write artifacts for the
rest, never commit). `mode:cross` is the per-round review used by the Cross-Review Iteration
Loop below.

`.context/review/*.json` are ephemeral inter-agent scratch consumed immediately by synthesis —
correct use of `.context/` per the File Storage Rules. The merged findings are persisted as
review artifacts exactly as in any other mode.

### Cross-Review Iteration Loop

The loop autonomous orchestrators use to drive build → review → fix → re-review with external
providers. Provider-neutral; lives here so `auto-build`, `ticket-flow`
(via `references/execution-phases.md`), and `lfg` all share one definition.

```
round = 1
while round <= 3:
    run /review mode:cross          # Claude self-review ∥ Codex ∥ Grok, merged + deduped + boosted
    actionable = partitions.inSkillFixer + partitions.residualActionable
                 # i.e. findings routed to review-fixer (safe_auto) or
                 #      downstream-resolver (gated_auto | manual)
    if actionable is empty:
        break                       # converged — only advisory / gate-suppressed nits remain
    Claude resolves actionable findings (apply safe_auto inline; resolve gated_auto/manual)
    re-run affected tests + type check
    round += 1
```

**Termination — break when EITHER holds:**

- the merged result has **no actionable findings** — actionable means at or above the
  autofix/gated tiers (`safe_auto`, `gated_auto`, `manual`). `advisory` findings and
  confidence-gate-suppressed (<0.60) nits do **not** keep the loop alive; or
- **3 rounds** have run. Do not loop forever chasing literal agreement — after round 3, stop
  and surface any remaining `gated_auto`/`manual` findings for a human.

**Cost note:** each round spawns 2 external CLI agents (run in parallel). The loop is the
expensive part of the workflow, which is why termination is aggressive — only genuinely
actionable findings re-trigger a round.

## Process

1. **Gather context:**
   - Load ticket: `mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)`
   - Read plan artifact for intended approach
   - Run `git diff --name-only` to identify changed files
   - Read build_todo artifact completion notes

2. **Check existing review_todo artifacts:**
   - Count existing review_todo artifacts from `get_ticket` response
   - New findings start at `max_sequence + 1` (or 1 if none exist)

3. **Select reviewers** based on diff analysis (see Agent Dispatch above).

4. **Decide the execution path — complexity gate:**

   The mechanical fan-out, dedup, cross-reviewer boost, adversarial verify, and partition
   logic lives in the `review-fanout` workflow at `workflows/review-fanout.js`. Workflows
   have non-trivial token overhead (spawning many subagents, structured-output enforcement,
   2-skeptic verification per borderline finding). They pay off only when there is enough
   material to dedup and verify across. For small diffs the orchestration cost dwarfs the work.

   Use this gate (evaluated top-to-bottom — first match wins):

   | Condition                                                        | Path    |
   | ---------------------------------------------------------------- | ------- |
   | User passed `--deep`                                             | Heavy   |
   | User passed `--light`                                            | Light   |
   | ≥1 conditional or project-persona reviewer fires                 | Heavy   |
   | ≥5 files changed                                                 | Heavy   |
   | ≥200 LOC changed (added + removed via `git diff --shortstat`)    | Heavy   |
   | Otherwise (only the always-on pair fires on a small diff)        | Light   |

   The "conditional or persona reviewer fires" signal is what previously read as
   "≥3 reviewers" — it's the same trigger expressed honestly (the always-on pair is
   always 2, so any third reviewer means a conditional or persona qualified).

   Announce the chosen path alongside the review team:

   ```
   Review team: code-quality [sonnet], architecture-security-performance [opus]
   Path: light (2 reviewers, 1 file, 18 LOC) — inline parallel Agent calls, no verify
   ```

   or:

   ```
   Review team: code-quality, arch-sec-perf, data-integrity, react, pipeline-reviewer
   Path: heavy (5 reviewers, 12 files, 340 LOC) — review-fanout workflow with verify
   ```

5. **Fan out — light path (inline):**

   When the gate selects "Light", issue the reviewer `Agent` calls in parallel (one assistant
   message, multiple tool-use blocks). No workflow, no skeptics. Each reviewer returns the
   reviewer-output JSON shape documented in `workflows/review-fanout.js`
   (`reviewerOutputSchema`).

   The light path does **not** get schema enforcement at the tool layer (the `Agent` tool
   has no `schema:` parameter). Validate manually: for each reviewer's findings, drop any
   that don't have all of `title`, `severity`, `file`, `line`, `confidence`, `autofix_class`,
   `owner`, `requires_verification`, `pre_existing`, `evidence` (non-empty array),
   `why_it_matters`. Count dropped findings into `suppressed`. Mirror the `validFinding`
   function in `workflows/review-fanout.js`.

   Then do minimal synthesis inline:
   1. Dedupe by `(file, normalized title, |line diff| ≤ 3)` pairwise comparison — match
      against any existing group member, not just the first (keep highest severity and
      confidence, union evidence, AND-merge `pre_existing`).
   2. Apply cross-reviewer boost: for each merged finding, `confidence += 0.10 *
      (reviewers.length - 1)`, capped at 1.0. With 2 reviewers this only fires on
      consensus findings (rare in light path) but preserves the same-shape contract
      with the heavy path.
   3. Apply the confidence gate (suppress <0.60, rescue p1 at ≥0.50).
   4. Separate `pre_existing: true`.
   5. Sort by severity → confidence → file → line.
   6. Normalize routing: `safe_auto` → owner=review-fixer; `gated_auto|manual` →
      owner=downstream-resolver; `advisory` → owner=human.
   7. Partition into `{inSkillFixer, residualActionable, reportOnly}`.

   Skip steps 5a-5c below — they are for the heavy path only.

5a. **Fan out — heavy path (workflow):**

   When the gate selects "Heavy", invoke the workflow by name. The runtime resolves
   `name:` against `~/.claude/workflows/`, where agent-workflows is symlinked in every
   environment (local, NanoClaw, cloud SessionStart copy):

   ```
   result = Workflow({
     name: "review-fanout",
     args: {
       reviewers: [
         { key: "code-quality", model: "sonnet", focus: "...",
           references: ["references/python-standards.md", ...] },
         // TODO: revert model back to "fable" once available
         { key: "architecture-security-performance", model: "opus", focus: "...",
           references: ["references/architecture.md", ...] },
         // ...plus conditional + project-persona reviewers from step 3
       ],
       intent: "<2-3 line intent from plan/commits>",
       files: ["<changed files>"],
       diffSummary: "<git diff --stat output or short narrative>",
       mode: "interactive" | "autofix" | "report-only" | "headless"
     }
   })
   ```

5b. **Result shape (both paths must produce this object):**

   ```
   {
     findings: [...],               // current-diff findings, sorted
     pre_existing: [...],           // segregated
     pre_gate_suppressed: [...],    // in [0.50, gate-threshold) — for memory upgrade
     partitions: {                  // drives step 6 routing
       inSkillFixer: [...],         // safe_auto → review-fixer
       residualActionable: [...],   // gated_auto|manual → downstream-resolver
       reportOnly: [...]            // advisory + human-owned
     },
     suppressed: <N>,               // sum of invalid + dedup + gate + verify drops
     coverage: { residual_risks, testing_gaps },
     stats: {                       // diagnostic counters
       reviewers, reviewer_errors, raw_findings, invalid_dropped,
       dedup_collapsed, after_dedup, after_gate, suppressed_by_gate,
       borderline_verified, verify_dropped, skeptic_failures,
       contested_kept, final
     }
   }
   ```

   The light path must assemble this same object after its inline synthesis — populate
   the fields it computes (`findings`, `pre_existing`, `pre_gate_suppressed`, `partitions`,
   `suppressed`, `coverage`) and zero-fill the verify-related stats fields
   (`borderline_verified: 0`, `verify_dropped: 0`, `skeptic_failures: 0`,
   `contested_kept: 0`). Downstream steps (6–8) must not branch on path.

5c. **What the heavy path adds over the light path:**

   - Structured output enforced at the tool layer (schema retry on mismatch)
   - Cross-reviewer agreement boost (+0.10 confidence per additional reviewer)
   - Adversarial 2-skeptic verify on every gated finding below 0.80 confidence
     — consensus-boosted findings ≥0.80 skip verify entirely, saving tokens
   - Skeptic verdict handling: unanimous refute drops, unanimous uphold boosts +0.10
     and clears `requires_verification`, mixed verdict or <2 skeptics keeps the finding
     with `requires_verification: true` so downstream can surface it
   - Workflow journal (developer-only): can resume with `resumeFromRunId` when iterating on the script itself
   - Diagnostic stats: `raw_findings`, `after_dedup`, `after_gate`, `borderline_verified`,
     `verify_dropped`, `skeptic_failures`, `contested_kept`, `final`

6. **Store findings** as review_todo artifacts:
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="review_todo",
     title="<finding title>",
     sequence=N,
     status="pending",
     content="<finding content using review skill template>",
     command="/review"
   )
   ```

   **Routing by mode and autofix_class:**

   | Mode | safe_auto | gated_auto | manual | advisory |
   | ---- | --------- | ---------- | ------ | -------- |
   | Interactive | Auto-apply fix, store as resolved | Store as pending, ask user | Store as pending | Report only, no artifact |
   | Autofix | Auto-apply fix, store as resolved | Store as pending | Store as pending | Skip |
   | Report-only | Report only | Report only | Report only | Report only |
   | Headless | Auto-apply fix (single pass), store as resolved | Store as pending | Store as pending | Include in output |

7. **Store P1/P2 findings in memory service** (persists beyond session):
   For each P1/P2 finding, first search for duplicates, then store via MCP:

   ```
   # 1. Check for duplicates
   mcp__autodev-memory__search(
     queries=["<finding keywords>"],
     project="<from <!-- mem:project=X --> in CLAUDE.md>"
   )

   # 2. If no duplicate, store the finding
   mcp__autodev-memory__add_entry(
     project="<from <!-- mem:project=X --> in CLAUDE.md>",
     title="Review: [finding summary]",
     content="File: [path], Line: [number]. Issue: [description]. Fix: [fix].",
     entry_type="gotcha",
     summary="[1-sentence summary]",
     tags=["review", "[area]"],
     source="captured",
     caller_context={
       "skill": "review",
       "reason": "P1/P2 review finding that future builds should avoid",
       "action_rationale": "New entry — no existing entry covers this finding",
       "trigger": "review finding [p1/p2]"
     }
   )
   ```

   If a related entry exists, use `mcp__autodev-memory__update_entry` to append instead.

   This is critical for autonomous workflows (LFG, auto-build) in cloud environments
   where review findings would otherwise be lost after the session ends.
   If the MCP tool is unavailable, skip this step silently.

8. **Update plan artifact** with review log entry via `update_artifact`

---

## Synthesis Methodology

Synthesis (validate → confidence gate → dedup → cross-reviewer boost → separate pre-existing
→ normalize routing → partition → sort → coverage union) lives in
`workflows/review-fanout.js`. The heavy path runs it inside the workflow; the light path
runs an inlined subset in this skill (see step 5).

**Memory-assisted confidence upgrade (skill-side, both paths):** Iterate
`result.pre_gate_suppressed` (findings in [0.50, gate-threshold) that the gate dropped).
For each one, search the memory service:

```
mcp__autodev-memory__search(
  queries=[
    {"keywords": ["<finding area>"], "text": "<issue description>"},
    {"keywords": ["<technology>"], "text": "<issue type> gotcha pitfall"}
  ],
  project=PROJECT
)
```

If memory confirms the pattern (past incident, known gotcha), upgrade the finding's
confidence to 0.80+, include the memory entry as evidence, and re-admit it into
`result.findings` + `result.partitions` (re-run sort + normalizeRouting). Decrement
`result.suppressed` and `result.stats.suppressed_by_gate` accordingly so the Coverage
output reflects what actually shipped.

This step runs in the skill, not the workflow, because the workflow doesn't have MCP
access. The workflow surfaces the rescue candidates via `pre_gate_suppressed` so this
isn't dead code.

---

## Priority Levels

| Priority | Meaning                                          | Examples                               |
| -------- | ------------------------------------------------ | -------------------------------------- |
| **p1**   | Must fix - correctness, security, data integrity | Bugs, vulnerabilities, data loss risk, old system not deleted after replacement added |
| **p2**   | Should fix - maintainability, performance        | YAGNI violations, complexity, patterns |
| **p3**   | Nice to have - style, minor improvements         | Naming, documentation, clarity         |

## Output Template

Use the template at `templates/review-todo.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Finding Quality

**Strong findings:**

- Specific file:line references
- Clear `why_it_matters` (what breaks, not what's wrong)
- Concrete suggested fix (or null if no good fix exists)
- Confidence score backed by evidence
- Correct autofix classification

**Weak findings (improve before reporting):**

- Vague "could be better" without specifics
- Style preferences without justification
- Findings without evidence array
- Confidence > 0.80 without code-grounded evidence

## Knowledge Persistence

P1/P2 findings are stored in the memory service by the `/review` command orchestrator via
`mcp__autodev-memory__add_entry`. This ensures future builds learn from past review findings,
even in ephemeral cloud sessions. Individual reviewer agents do NOT call MCP tools directly —
the orchestrator handles persistence after collecting all findings.

## Output Format

### Interactive mode

Present findings as a table:

```markdown
## Review Findings

| # | File | Issue | Reviewer(s) | Confidence | Route |
|---|------|-------|-------------|------------|-------|
| 1 | `src/api/endpoints.py:23` | SQL injection via unescaped input | architecture, code-quality | 0.95 | `safe_auto -> review-fixer` |
| 2 | `src/models/user.py:45` | Missing migration for new column | data-integrity | 0.90 | `gated_auto -> downstream-resolver` |

### Applied Fixes (safe_auto)
- #1: Parameterized query in endpoints.py

### Residual Work (gated_auto / manual)
- #2: Missing migration — needs design decision on column default

### Pre-existing Issues
[Separate from verdict]

### Coverage
- Suppressed: 2 findings below 0.60 confidence
- Residual risks: [list]
- Testing gaps: [list]

### Verdict
Ready with fixes / Ready to merge / Not ready
```

After presenting: ask policy question only if gated_auto or manual findings remain.

**Next step line (always include at the end of interactive output):**

If findings remain:
```
Next: /resolve-review {ID} (resolve gated/manual findings)
```

If no actionable findings:
```
Next: /create-pr {ID} (create PR with summary)
```

### Headless output

```
Code review complete (headless mode).

Scope: [file list summary]
Intent: [intent summary]
Verdict: Ready to merge | Ready with fixes | Not ready
Applied N safe_auto fixes.

Gated-auto findings:
[p1][gated_auto -> downstream-resolver][needs-verification] File: <file:line> -- <title> (confidence <N>)
  Why: <why_it_matters>
  Evidence: <evidence[0]>

Manual findings:
[p1][manual -> downstream-resolver] File: <file:line> -- <title> (confidence <N>)
  Why: <why_it_matters>

Advisory findings:
[p2][advisory -> human] File: <file:line> -- <title> (confidence <N>)

Pre-existing issues:
[p2] File: <file:line> -- <title> (confidence <N>)

Residual risks:
- <risk>

Testing gaps:
- <gap>

Coverage:
- Suppressed: <N> findings below 0.60 confidence (p1 at 0.50+ retained)

Review complete
```

## Scope Completeness Check (CRITICAL)

For every review, compare the source document's scope against the implementation:

1. **Read the source artifact** from the ticket — enumerate every deliverable it lists
2. **Read the plan artifact** — verify every source item has a plan step
3. **Diff against implementation** — for each planned item, verify code exists
4. **Flag missing items as P1** — scope items that were planned but not implemented
   are correctness issues, not style nits

| Source Item | Plan Step | Implemented? | Finding |
|---|---|---|---|
| [item from source] | Step N | Yes / **No** | [p1] if missing |

**Why:** F0076 listed 4 deliverables in the source. The plan marked one as "TBD".
Implementation skipped it entirely. Review never ran, so no one caught the gap.
The ticket was marked complete with $110/month in unnecessary cost still running.

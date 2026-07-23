---
name: review
description: Review implementation with light native or escalated safety coverage and persist findings.
---

# Review

Follow `../references/execution-economy.md`; economy never suppresses a safety-critical reviewer,
test, finding, or fail-loud gate.

Before any conditional external peer call, create its bounded memory packet (once per provider):

```bash
if ! printf 'Review bounded diff against %s\n' "$base" | \
  autodev-memory-task-packet --cwd "$PWD" --session-id "${SESSION_ID:-}" \
    --agent-type reviewer --provider "$provider" --mechanism external_peer \
    --task-prompt-stdin --allow-unavailable > "$MEMORY_PACKET"; then
  printf '%s\n' '<autodev-memory-task-context>Memory context is unavailable.</autodev-memory-task-context>' \
    > "$MEMORY_PACKET"
fi
```

Pass `--memory-context-file "$MEMORY_PACKET"` to `external-agent --task review`.

Review implementation with a genuinely light native path and conditional specialized fanout.
Supports multiple
modes for different contexts (interactive, autonomous, read-only, programmatic).

## Usage

```
/review 009                              # Bug/incident #009 (NNN format)
/review F001                             # Feature F001 (FNNN format)
/review B0009                            # Bug ticket B0009
/review F001 mode:autofix                # Autonomous — apply safe fixes only
/review F001 mode:report-only            # Read-only — no mutations
/review F001 mode:headless               # Programmatic — structured output for callers
/review F001 mode:cross                  # Explicit runner + two-peer escalation
/review F001 mode:solo                   # Disable conditional peers; keep native safety gates
/review F001 --deep                      # Force heavyweight workflow path (overrides gate)
/review F001 --light                     # Force inline path (overrides gate, skips verify)
```

## Mode Detection

Two orthogonal axes:

1. **Synthesis style** — parse the `mode:` token. Default is interactive.
2. **Reviewer escalation** — a plain review starts native-only. `mode:cross` explicitly requests
   both peer providers; `mode:solo` forbids conditional peer escalation. Without either token,
   peers run only when the risk/uncertainty/disagreement gate below fires.

| Mode | When | Behavior |
| --- | --- | --- |
| **Interactive** | No synthesis token | Review, apply safe fixes, route gated/manual findings by decision ownership |
| **Autofix** | `mode:autofix` | Apply safe fixes, write unresolved artifacts, never commit/push |
| **Report-only** | `mode:report-only` | Read-only; no edits or artifacts |
| **Headless** | `mode:headless` | Structured skill-to-skill result |
| **Cross** | `mode:cross` | Explicitly add the other two providers |
| **Solo** | `mode:solo` | Native-only; required native safety critics still run |

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

**Write the diff ONCE** as a shared artifact — every native reviewer prompt, skeptic prompt,
and peer dispatch references these paths instead of re-discovering the diff:

```bash
mkdir -p .context/review
git diff main > .context/review/diff.patch
git diff --name-only main > .context/review/files.txt
```

Then analyze the diff to determine which reviewers to spawn:

```bash
# Get changed files
git diff --name-only main

# Categorize changes
git diff --name-only main -- '*.py'                              # Python files
git diff --name-only main -- '*.ts' '*.tsx'                      # TypeScript files
git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' atlas.hcl atlas/plans/ cli_tools/atlas/ migrations/db_object_manifest.py migrations/versions/  # Data/schema
git diff --name-only main -- '*/flows/*.py' '*/tasks/*.py'       # Pipeline/flow code
git diff --name-only main -- '*/scrapers/*' '*/scraper*'         # Scraper code
git diff --name-only main -- '*poll*' '*observer*' '*scheduler*' 'prefect.*.yaml'  # Repeated writers
git diff --name-only main -- 'prefect.*.yaml'                    # Prefect deployment config
git diff --name-only main -- '*/prompts/*' '*/contracts/*'       # LLM prompts/contracts
git diff --name-only main -- '*.md' '*.json' '*.yaml' '*.toml'  # Config/docs only
```

### Step 2: Select Reviewers

**Heavy-path core reviewers** (spawn together when the path gate selects heavy review):

| Agent    | Model    | Review References                                                                    | Focus                                |
| -------- | -------- | ------------------------------------------------------------------------------------ | ------------------------------------ |
| reviewer | `sonnet` | references/python-standards.md or typescript-standards.md, references/simplicity.md, references/patterns.md | Code quality, YAGNI, design patterns |
<!-- stay on opus — fable is not available on the subscription plan after 2026-07-07 -->
| reviewer | `opus`  | references/architecture.md, references/security.md, references/performance.md        | Architecture, security, performance  |
| reviewer | `sonnet` | (context injected — see Plan-Conformance Reviewer below)                              | Plan/scope conformance, deviations   |

**Small heavy-diff model downgrade:** when a safety/domain trigger selects the heavy path but the
total diff is < 50 LOC (added + removed via `git diff --shortstat`), run both code-focused core
reviewers on `sonnet` (the plan-conformance reviewer is already `sonnet`). Routine small diffs use
the single-reviewer light path in Process step 5 instead.

**Plan-conformance reviewer (heavy path).** The code-focused reviewers deliberately see only
the diff — fresh eyes, no plan anchoring. This reviewer exists to close the gap that leaves:
it is the ONE agent that reviews the implementation *against the contract*. Its prompt gets
context the others don't (pass it via `extraContext` on the heavy path, or inline on the
light path):

- the **source artifact's deliverable list** (raw, not a summary — a summary written by the
  build orchestrator inherits the build's blind spots);
- the **plan's** `what` / `how` / `elimination` scope and its `assumptions`;
- the **builders' Deviations** entries collected from build_todo Completion Notes;
- the **deliverable → build_todo coverage map** emitted by `/create-build-todos` (in the first
  build_todo), including any `DEFERRED — needs user approval` lines.

This reviewer reads the **raw** plan/source deliverables list as its primary check (as today)
**and additionally** cross-checks the coverage map. The map is a convenience cross-reference,
not a replacement: a deliverable that the raw list contains but the map omits — or a map entry
with no code in the diff — is still a missing-scope finding.

Its charter is the Scope Completeness Check (see the section at the end of this skill for
the method/table): every source deliverable must map to a plan step and to code in the diff;
every plan elimination must actually be deleted; every builder deviation must be sound
against the plan's intent. Missing scope items are **p1 findings with `absence: true`**
(anchor to the closest related file, evidence = the grep commands that should find the missing
code). Classify them `gated_auto` when the approved plan determines the implementation; use
`manual` only when completing the scope requires a genuine unresolved human choice. Unsound
deviations are p1/p2 per impact. Findings flow
through the same schema, dedup, gate, and partitions as every other reviewer.

In ticketless mode (lfg) the inputs come from `.context/source.md`, `.context/plan.md`, and
`.context/build_todos/` status headers instead of MCP artifacts.

**Conditional reviewers** (spawn based on diff analysis — agent judgment, not keyword matching):

| Condition                        | Agent    | Model  | Review References                                                  | Select when diff touches...                |
| -------------------------------- | -------- | ------ | ------------------------------------------------------------------ | ------------------------------------------ |
| Database/model/migration changes | reviewer | `opus` | references/data-integrity.md, references/migrations.md, references/deployment.md | Model files, migrations, schema changes    |
| React/frontend changes           | reviewer | `sonnet` | references/react-router.md, references/react-performance.md       | React components, routes, hooks, UI state  |
| Data pipeline changes            | reviewer | `sonnet` | references/data-adequacy.md                                       | Pipeline contracts, DAG nodes, data flow   |
| Polling/storage repeated writes  | reviewer | `opus` | references/data-integrity.md, references/performance.md, references/deployment.md | Pollers, observers, schedulers, queues, webhooks, scrapers that persist rows |

**CRITICAL: data reviewer spawn rule.** Always check for model file changes explicitly:
```bash
git diff --name-only main -- '*/models/*.py' 'ts_schemas/models/' atlas.hcl atlas/plans/ cli_tools/atlas/ migrations/db_object_manifest.py migrations/versions/
```
If ANY model or migration files appear, spawn the data reviewer. Do NOT rely on build_todos
or plan.md to determine this — check the actual diff. Missing migrations are a p1 finding.

**CRITICAL: polling/storage amplification rule.** If the diff adds or changes a repeated
writer (poller, observer, scheduler, queue consumer, webhook, scraper, supervisor flow, or
Prefect deployment) that persists data, spawn the data/performance reviewer even if no model
file changed. The reviewer must check:

- whether unchanged source data creates new durable rows on every run;
- whether "lossless" is being used to justify duplicate per-poll payload/item storage;
- row/day, bytes/day, index/WAL impact, and retention/partitioning;
- dedupe/change-gating keys across runs, not only within a fresh fetch/run id;
- whether the plan's consumers need full per-poll history or only canonical entries,
  first/last-seen timestamps, health metadata, or changed events.

Unbounded redundant persistence that scales linearly with polling frequency is a p1 finding
unless a named consumer, retention policy, and volume budget make it intentional.

**CRITICAL: removal closure rule.** If the diff replaces/decommissions an old structure, compare it
to the plan's before inventory. Review must require bounded zero-match searches across code and
deploy/config paths, explicit deletion commands for old live registrations, and a surviving-path
smoke check. Any scoped legacy entrypoint/writer/flag/deployment left unexplained, or any removal
claim without a negative postcondition, is a p1 completeness finding.

**CRITICAL: external cache temporal-finality rule.** If the diff reads from or writes to a
provider-backed cache, market/reference data table, prompt-context price table, evaluation
label, or ground-truth outcome table, spawn the data-integrity reviewer even if no model file
changed. The reviewer must check:

- every cached value is classified as `live`, `provisional`, or `final`;
- all writers and readers of the cache/table are listed, especially prompt/live context
  writers versus outcome/label readers;
- provider endpoint names are not treated as proof of finality;
- finality is enforced using the source timestamp, exchange/calendar/timezone where relevant,
  and a validity window;
- `ON CONFLICT DO NOTHING` / first-write-wins is not used for mutable or provisional provider
  data unless immutability is proven;
- tests cover cache-hit behavior with an already-stored stale/provisional row, not only the
  provider-miss path.

Using live/provisional context data as final ground truth, or letting one writer poison a
shared cache for a different semantic lifecycle, is a p1 data-integrity finding.

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

After applying the path gate in Process step 4, announce which reviewers were selected and why.
For light review, announce the single general reviewer. For example, a heavy review might say:

```
Review team:
- code-quality (heavy core) [sonnet]
- architecture-security-performance (heavy core) [opus]
- plan-conformance (heavy core) [sonnet]
- data-integrity — model/schema/Atlas/migration files changed [opus]
- react — components changed in app/components/ [sonnet]
- pipeline-reviewer — DAG node declarations modified [project persona]
```

This is progress reporting, not a blocking confirmation.

Heavy-path reviewer instances include the `research` skill (references/past-work.md) when past
work is material to the changed surface. The light reviewer receives only a bounded relevant
memory/context packet; it does not launch a separate broad history search.

**All reviewer instances** return structured JSON per `references/findings-schema.json`.

Every native, Workflow, and provider reviewer dispatch uses `fork_turns: "none"` with a bounded,
self-contained packet. A history fork is allowed only when that packet is genuinely impossible;
record the reason before dispatch and use the smallest explicit numeric count of recent turns that
contains the missing fact. Never use an all-history fork, and never treat convenience or a large
existing conversation as an exception.

### Conditional cross-provider reviewers

External peers are not a default reviewer set. Escalate to the other two providers only when:

- the caller passed `mode:cross` or explicitly requested independent/cross-provider review;
- the diff is safety-critical: security, auth, billing, destructive data/schema migration,
  secrets, deploy configuration, or another project-declared high-blast-radius surface;
- native reviewers expose a material uncertainty that repository/test evidence cannot settle; or
- native reviewer/skeptic verdicts materially disagree on an actionable finding.

`mode:solo` disables peers but never removes native safety-critical personas, adversarial checks,
or project-required review. Announce the trigger. If none fires, do not create provider packets or
calls.

When escalation fires, run both peer providers in parallel. Provider subagents use
`fork_turns: "none"` and a bounded self-contained packet referencing the shared diff/file artifacts,
plan/deviation summary, required output schema, and output cap. Store full envelopes/logs under
`.context/review/<run-id>/`; consume compact reviewer-output envelopes only. Wait for all required
native and peer results before one synthesis. Never simulate a failed peer. For safety-critical
scope, peer failure is explicit residual risk and the report cannot claim independent agreement.

Merge native and peer findings semantically, then apply cross-reviewer confidence boost only to
actual independent agreement. Peer dispatch changes coverage, not finding truth: evidence,
confidence gates, skeptic checks, ownership, and fail-loud behavior still apply.

### Review iteration loop

Autonomous callers run one review/fix round by default. A second (maximum third on heavy scope) is
allowed only when an adversarial verdict or independent peer materially disagreed, not merely to
re-confirm fixes. Re-run affected tests after every fix. Carry only contested findings, unresolved
advisories, and residual risks into the next bounded packet. Use a blocking bounded wait or a
single resume command; never model-drive provider polling.

## Process

1. **Gather context:**
   - Load ticket once with `detail="full"`,
     `artifact_types=["source", "plan", "build_todo", "review_todo"]`, and
     `include_events=false`; cache and reuse that response throughout the review.
   - Read plan artifact for intended approach
   - Run `git diff --name-only` to identify changed files
   - Read build_todo artifact completion notes — collect every **Deviations** entry; the
     deviations, the plan's what/how/elimination/assumptions, and the raw source deliverable
     list are the input package for the plan-conformance reviewer (Step 2)

2. **Check existing review_todo artifacts:**
   - Count existing review_todo artifacts from `get_ticket` response
   - New findings start at `max_sequence + 1` (or 1 if none exist)

3. **Select reviewers** based on diff analysis (see Agent Dispatch above).

4. **Decide execution path and peer escalation:**

   Light is one native general reviewer, inline synthesis, no workflow, no skeptics, and no peers.
   Heavy uses native specialized personas, structured collection/synthesis, and adversarial
   verification. Peer escalation remains conditional and is not implied by diff size alone.

   | Condition | Path |
   | --- | --- |
   | User passed `--deep` | Heavy |
   | User passed `--light` and no safety-critical surface is present | Light |
   | Safety-critical surface or project persona requirement | Heavy |
   | ≥5 files, ≥200 changed LOC, or conditional domain reviewer fires | Heavy |
   | Otherwise | Light |

   A safety-critical signal overrides `--light` for native coverage. Apply the peer gate from
   **Conditional cross-provider reviewers** separately and announce both decisions.

5. **Light path:**

   Spawn exactly ONE native general reviewer with `fork_turns: "none"`. Its bounded packet points
   to `.context/review/diff.patch` and `.context/review/files.txt`, includes intent, plan
   conformance/deviations, required schema, relevant project rules, and exact test evidence. It
   reviews correctness, plan conformance, security, and testing within that bounded diff; it does
   not recruit specialists or peers.

   Validate findings, exact/semantic deduplicate within the single envelope, confidence-gate,
   segregate pre-existing findings, normalize ownership, and partition. Zero-fill skeptic/peer
   stats. If the reviewer surfaces a safety-critical concern, material uncertainty, or internal
   contradiction, upgrade to heavy and apply the peer escalation gate rather than improvising a
   second light reviewer.

5a. **Heavy path:**

   Run native `review-collect` with only the specialized personas selected by the diff, then one
   `review-synthesize` pass with adversarial verification. If Workflow is unavailable, execute the
   same bounded algorithm inline. Add peer reviewer envelopes only when the escalation gate fires;
   otherwise `raw` contains native envelopes only. Finish every required collection call before
   synthesis. Use `fork_turns: "none"`, shared diff artifacts, output caps, and full logs on disk.

   Safety-critical scope always retains the relevant native persona and adversarial checks even
   under `mode:solo` or peer failure. Do not downgrade a heavy review merely because provider or
   Workflow tooling is unavailable; surface missing independent coverage as residual risk.

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

   - A hard barrier across every required native and conditionally escalated peer result before
     synthesis
   - Structured native output enforced at the tool layer (schema retry on mismatch)
   - Semantic same-issue dedup (one cheap judge call) so cross-provider agreement is
     detected even when titles differ, before the boost
   - Cross-reviewer agreement boost (+0.10 confidence per additional reviewer)
   - Tiered adversarial verify — confidence alone cannot buy a skip (it is self-reported):
     <0.80 gets 2 skeptics; ≥0.80 p1 or single-reviewer findings get a 1-skeptic
     spot-check; only ≥0.80 multi-reviewer p2/p3 findings skip verify entirely
   - Skeptic verdict handling (2-skeptic tier): unanimous refute drops, unanimous uphold
     boosts +0.10 and clears `requires_verification`, mixed verdict or missing verdicts
     keeps the finding with `requires_verification: true`. Spot-check tier: uphold clears
     `requires_verification`; refute/unsure contests (never a silent drop on one dissent)
   - Absence findings (`absence: true`) get a search-based skeptic protocol (grep for the
     missing artifact) instead of read-around-the-anchor, and semantic-only dedup
   - Workflow journals for native collection and synthesis (developer-only)
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
   mcp__autodev-memory__create_entry(
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

   This is critical for autonomous workflows (lfg, ticket-flow) in cloud environments
   where review findings would otherwise be lost after the session ends.
   If the MCP tool is unavailable, skip this step silently.

8. **Update plan artifact** with review log entry via `update_artifact`

### Ticketless Mode (lfg)

When the review runs without a ticket (e.g. under `/lfg`), there is no MCP ticket to attach
review_todo artifacts to. Store findings as files in `.context/review_todos/` instead (one
file per finding, using `templates/review-todo.md`). Everything else is unchanged — the
memory-persistence step (`create_entry` for P1/P2 findings) still applies.

---

## Synthesis Methodology

Synthesis (validate → dedup → cross-reviewer boost → confidence gate → adversarial verify →
separate pre-existing → normalize routing → partition → sort → coverage union) lives in
`workflows/review-synthesize.js`. The heavy path invokes it only after `review-collect` and every
external peer have returned raw envelopes; the light path runs an inlined subset in this skill.

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
| **p1**   | Must fix - correctness, security, data integrity | Bugs, vulnerabilities, data loss risk, unbounded redundant per-poll persistence, old system not deleted after replacement added |
| **p2**   | Should fix - maintainability, performance        | YAGNI violations, complexity, patterns |
| **p3**   | Nice to have - style, minor improvements         | Naming, documentation, clarity         |

## Output Template

Use the template at `templates/review-todo.md` for output format.

**Formatting:** keep lines ≤100 chars; tables exempt.

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
`mcp__autodev-memory__create_entry`. This ensures future builds learn from past review findings,
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

This check is the **charter of the always-on plan-conformance reviewer** (see Step 2). It is
part of the reviewer fan-out — not an optional post-pass — so it runs on every review by
construction. The method:

1. **Read the source artifact** from the ticket — enumerate every deliverable it lists
2. **Read the plan artifact** — verify every source item has a plan step
3. **Diff against implementation** — for each planned item, verify code exists
4. **Flag missing items as P1 with `absence: true`** — scope items that were planned but not
   implemented are correctness issues, not style nits. Use `gated_auto` when the plan determines
   the fix and `manual` only when product/scope/tradeoff intent is genuinely unresolved. Anchor to
   the closest related file and put the grep commands that should find the missing code in
   `evidence` (skeptics verify absences by searching)
5. **Audit builder deviations** — every Deviations entry from the build must be sound
   against the plan's intent; unsound deviations are findings
6. **Re-run the call-site sweep for shared-primitive rollouts** — if the ticket rolls out
   or extends a cross-cutting primitive for a failure class (retry/backoff, timeouts,
   error classification, rate limiting, redaction, boundary encoding), independently
   re-enumerate ALL call sites of the underlying operation repo-wide (e.g., grep every
   `httpx`/`requests` GET/POST) and diff against the plan's enumeration table. Any call
   site absent from the table, and any pre-existing bespoke equivalent (e.g., a local
   retryable-error predicate) not audited for the same failure class, is a P1 `absence`
   finding. Do not trust the plan's sweep — B0278/B0306 scoped retry to the generic
   pollers only; the unenumerated Bloomberg sitemap and FT RSS pollers and the unaudited
   Discord 522 predicate all failed in prod (B0322/B0323/B0324).

| Source Item | Plan Step | Implemented? | Finding |
|---|---|---|---|
| [item from source] | Step N | Yes / **No** | [p1, absence] if missing |

**Why:** F0076 listed 4 deliverables in the source. The plan marked one as "TBD".
Implementation skipped it entirely. Review never ran, so no one caught the gap.
The ticket was marked complete with $110/month in unnecessary cost still running. This
check was previously a standalone section outside the numbered process, so orchestrators
skipped it — it is now a mandatory always-on reviewer.

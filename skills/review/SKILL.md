---
name: review
description: Review implementation against the plan. Spawns review agents in parallel, collects findings into review_todo artifacts.
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
/review F001 mode:cross                  # Explicit alias for the default (runner + other two providers)
/review F001 mode:solo                   # Opt OUT of peer reviewers — current runner only (fast/cheap)
/review F001 --deep                      # Force heavyweight workflow path (overrides gate)
/review F001 --light                     # Force inline path (overrides gate, skips verify)
```

## Mode Detection

Two orthogonal axes:

1. **Synthesis style** — parse the `mode:` token. Default is interactive.
2. **Reviewer set** — external cross-provider reviewers are **ON by default** in every
   synthesis style. The main workflow runner is one provider (`claude`, `codex`, or `grok`);
   the peer reviewers are the other two. `mode:solo` turns peers off (current runner only).
   `mode:cross` is an explicit alias for the default and exists only so callers can be
   explicit; it is identical to passing no reviewer-set token.

So a plain `/review` runs the current agent's native/self-review **plus** the other two
providers, merged through one synthesis path. See **Cross-Provider Reviewers** below for the
mechanics. Use `mode:solo` when you want a fast, cheap, single-provider pass (e.g. a quick
manual sanity check).

| Mode | When | Behavior |
| ---- | ---- | -------- |
| **Interactive** (default) | No mode token | Review, apply safe_auto fixes, present findings, ask about gated/manual |
| **Autofix** | `mode:autofix` | No user interaction. Apply safe_auto only, write artifacts, never commit/push |
| **Report-only** | `mode:report-only` | Read-only. Review and report, no edits or artifacts |
| **Headless** | `mode:headless` | Programmatic. Structured text output for skill-to-skill composition |
| **Cross** (default reviewer set) | `mode:cross` or no token | Extend the reviewer set with the other two providers. See Cross-Provider Reviewers below. **On by default.** |
| **Solo** | `mode:solo` | Opt OUT of peer reviewers — current runner only. Fast/cheap. |

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

**Always-on reviewers** (spawn for every review):

| Agent    | Model    | Review References                                                                    | Focus                                |
| -------- | -------- | ------------------------------------------------------------------------------------ | ------------------------------------ |
| reviewer | `sonnet` | references/python-standards.md or typescript-standards.md, references/simplicity.md, references/patterns.md | Code quality, YAGNI, design patterns |
<!-- stay on opus — fable is not available on the subscription plan after 2026-07-07 -->
| reviewer | `opus`  | references/architecture.md, references/security.md, references/performance.md        | Architecture, security, performance  |
| reviewer | `sonnet` | (context injected — see Plan-Conformance Reviewer below)                              | Plan/scope conformance, deviations   |

**Light-diff model downgrade:** when the total diff is < 50 LOC (added + removed via
`git diff --shortstat`), spawn BOTH code-focused always-on reviewers on `sonnet` (the
plan-conformance reviewer is already `sonnet`).

**Plan-conformance reviewer (always-on).** The code-focused reviewers deliberately see only
the diff — fresh eyes, no plan anchoring. This reviewer exists to close the gap that leaves:
it is the ONE agent that reviews the implementation *against the contract*. Its prompt gets
context the others don't (pass it via `extraContext` on the heavy path, or inline on the
light path):

- the **source artifact's deliverable list** (raw, not a summary — a summary written by the
  build orchestrator inherits the build's blind spots);
- the **plan's** `what` / `how` / `elimination` scope and its `assumptions`;
- the **builders' Deviations** entries collected from build_todo Completion Notes.

Its charter is the Scope Completeness Check (see the section at the end of this skill for
the method/table): every source deliverable must map to a plan step and to code in the diff;
every plan elimination must actually be deleted; every builder deviation must be sound
against the plan's intent. Missing scope items are **p1 `manual` findings with
`absence: true`** (anchor to the closest related file, evidence = the grep commands that
should find the missing code). Unsound deviations are p1/p2 per impact. Findings flow
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

Before spawning, announce which reviewers were selected and why:

```
Review team:
- code-quality (always) [sonnet]
- architecture-security-performance (always) [opus]
- plan-conformance (always) [sonnet]
- data-integrity — model/schema/Atlas/migration files changed [opus]
- react — components changed in app/components/ [sonnet]
- pipeline-reviewer — DAG node declarations modified [project persona]
```

This is progress reporting, not a blocking confirmation.

**All reviewer instances** include the `research` skill (references/past-work.md) to find and
reference issues caught in similar past implementations.

**All reviewer instances** return structured JSON per `references/findings-schema.json`.

### Cross-Provider Reviewers (default; opt out with `mode:solo`)

External peer reviewers are **on by default**. Unless the caller passed `mode:solo`, you MUST
run the two providers that are not the current main workflow runner — it is a required step of
the review, not an optional enhancement. Do not skip it, summarize it, or simulate its output
by reasoning about what another provider "would" say; the only valid way to add peer findings
is to actually run the providers and read the envelopes they return. Skipping the dispatch is
the one failure mode that silently drops cross-provider coverage.

The provider roles are symmetric:

| Main workflow runner | Peer reviewers to run |
| -------------------- | --------------------- |
| `claude`             | `codex`, `grok`       |
| `codex`              | `claude`, `grok`      |
| `grok`               | `claude`, `codex`     |

Determine the current runner with `agent-workflow-provider`; it autodetects Claude/Codex/Grok
from environment and process ancestry, with `AGENT_WORKFLOW_PROVIDER` as an escape-hatch
override. This catches model-specific blind spots: a finding all three providers independently
surface is far more likely real, and the cross-reviewer confidence boost rewards that agreement
automatically.

**Claude Code dispatch:** when Claude Code is the main runner, use `external-reviewer`
subagents for `codex` and `grok`. On the heavy path, issue those two calls in the same assistant
message as the `review-collect` Workflow call; on the light path, issue them with the native
reviewer Agent calls. This keeps slow peers out of the foreground shell timeout while preserving
one collection barrier.

**Codex/Grok dispatch:** when Codex or Grok is the main runner, call `external-agent` directly
for the two peer providers (including `--provider claude` when Claude is a peer). The Claude
peer uses subscription-backed `claude -p`, never a direct Anthropic API call.

```bash
mkdir -p .context/review
# Prepare one <=3K `<autodev-memory-task-context>` file from the current session's child base
# plus review-relevant summaries (use autodev-memory-task-packet when SESSION_ID is available).
MEMORY_PACKET=.context/review/memory-task.md
base="$(git merge-base HEAD origin/main 2>/dev/null || echo origin/main)"
for provider in $(agent-workflow-provider --peers); do
  external-agent --task review --provider "$provider" --base "$base" \
    --memory-context-file "$MEMORY_PACKET" \
    --out ".context/review/${provider}.json" 2>".context/review/${provider}.log" &
done
wait
```

Peer dispatches (and the `external-reviewer` subagent prompts) reference the shared diff
artifact from Step 1 — `Diff at: .context/review/diff.patch`, files at
`.context/review/files.txt` — and the bounded memory task file. The adapter call must pass
`--memory-context-file`; ambient SessionStart is deliberately suppressed instead of duplicated.

**Why a subagent/background process and not a serial foreground shell-out:** the providers are
slow — Codex at xhigh reasoning takes ~9 minutes for a single review. A serial foreground
`external-agent` call can exceed the shell tool's hard timeout cap and get SIGKILLed mid-run,
silently dropping the provider's findings (this was the original "Codex/Grok never produce
output" bug). Spawning each provider
inside a dedicated `external-reviewer` **subagent** sidesteps that cap entirely — an `Agent`
call is not bound by the Bash timeout, so the subagent can launch the adapter in the background
and wait the full ~9 minutes. When the orchestrator does not have Claude's `Agent` tool, use
the direct shell loop above and ensure the harness timeout is long enough for both peers.

Each `external-reviewer` subagent runs the `external-agent` adapter (`bin/external-agent` in
agent-workflows, symlinked onto `PATH`; the legacy `external-review` name still works as a
`--task review` shim). The adapter feeds the provider this skill (`SKILL.md` + the relevant
`references/`) and the diff, and the subagent returns a **reviewer-output envelope**
(`{reviewer_key, findings, residual_risks, testing_gaps}`) whose finding items match
`references/findings-schema.json` — the exact shape the native reviewers return, so external
findings flow through the *same* synthesis path with no special-casing.

**Claude Code dispatch details:** in one assistant message, spawn two `external-reviewer`
subagents plus the heavy-path `review-collect` Workflow call (or the light-path native reviewer
Agent calls). Never serialize independent collection:

- `external-reviewer` with prompt `provider=<first peer>` (plus the diff `base` if you already
  computed it; otherwise the agent computes `git merge-base HEAD origin/main`).
- `external-reviewer` with prompt `provider=<second peer>`.

Each subagent launches the adapter in the background, waits for it to finish (~1–9 min), and
returns the envelope JSON as its final message. Read each subagent's returned envelope directly
(it also writes `.context/review/<provider>.json` as a side effect).

Then fold the two envelopes into the reviewer set:

1. Take the envelope returned by each peer (`reviewer_key` = provider key). A provider that
   failed still returns a valid envelope with empty `findings` and a
   `residual_risks` note — it simply contributes no findings; surface its note but do not block.
2. Finish collection before any gate: heavy mode runs native `review-collect` concurrently with
   the two peer dispatches; light mode runs all native and peer calls in one parallel batch.
3. Concatenate the raw native and peer envelopes, then run exactly one synthesis (light inline
   or heavy `review-synthesize`): exact dedup by
   `(file, normalized title, |line diff| ≤ 3)` **plus the semantic same-issue merge** —
   providers never word the same defect identically, so without the semantic pass
   cross-provider agreement is invisible. The cross-reviewer boost
   `confidence += 0.10 * (reviewers.length - 1)` then counts both peer providers as reviewers,
   so a finding reported by all three providers is boosted by +0.20. Gate, partition, route as
   usual.

Finding handling follows the **autofix** rules (apply `safe_auto`, write artifacts for the
rest, never commit). `mode:cross` is the per-round review used by the Cross-Review Iteration
Loop below.

`.context/review/*.json` are ephemeral inter-agent scratch consumed immediately by synthesis —
correct use of `.context/` per the File Storage Rules. The merged findings are persisted as
review artifacts exactly as in any other mode.

### Cross-Review Iteration Loop

The loop autonomous orchestrators use to drive build → review → fix → re-review with external
providers. **This is the canonical definition** — provider-neutral; consumers are `ticket-flow`
(via `../references/execution-phases.md`) and `lfg`.

**Round budget follows the complexity gate:** the light path (small diffs) runs a **single
round** — still cross-provider; the heavy path allows up to 3, but **a second round only
runs when the adversarial verify actually disagreed this round.** Extra rounds that merely
re-confirm already-agreed fixes cost two external CLI agents and, in practice, converge
without changing the actionable set — so they are spent only to resolve genuine disagreement,
never as a routine confirmation pass.

```
round = 1
max_rounds = 1 if light path else 3
carried = []                        # contested + unresolved advisory findings from prior rounds
while round <= max_rounds:
    run /review mode:cross          # runner self-review ∥ two peer providers, merged + deduped + boosted
                                    # include `carried` in each reviewer's prompt context
    actionable = partitions.inSkillFixer + partitions.residualActionable
                 # i.e. findings routed to review-fixer (safe_auto) or
                 #      downstream-resolver (gated_auto | manual)
    contested  = findings where the 2-skeptic adversarial verify DISAGREED —
                 requires_verification: true after verify (mixed or missing skeptic verdicts),
                 or reviewers split on the same finding. (Light path never verifies, so
                 contested is always empty there — it stays single-round.)
    if actionable is empty:
        break                       # converged — only advisory / gate-suppressed nits remain
    current runner resolves actionable findings (apply safe_auto inline; resolve gated_auto/manual)
    re-run affected tests + type check
    if contested is empty:
        break                       # verify agreed — fixes are trusted; do NOT spend a confirmation round
    carried = contested + unresolved advisory + residual_risks from this round's coverage
    round += 1                       # another round ONLY because the adversarial reviews disagreed
```

**Carry-forward:** unresolved `advisory` findings, contested (`requires_verification: true`)
findings, AND the round's `residual_risks` coverage entries MUST be passed into the next
round's reviewer context, so skeptic outputs, advisory notes, and unconfirmed risks are not
dropped between rounds. On the heavy path, pass them as the workflow's `args.carried`
(review-collect renders them into every native reviewer prompt); on the light path, include them in
the inline reviewer prompts. Render a residual-risk entry as a pseudo-finding
(`title` = the risk text, `severity`/`file`/`line` unknown is fine).

**Termination — break when ANY holds:**

- the merged result has **no actionable findings** — actionable means at or above the
  autofix/gated tiers (`safe_auto`, `gated_auto`, `manual`). `advisory` findings and
  confidence-gate-suppressed (<0.60) nits do **not** keep the loop alive; or
- the actionable findings were resolved and **the adversarial verify produced no contested
  findings** (every finding was unanimously upheld or refuted) — the fixes are trusted, so a
  confirmation round is not spent; or
- **max_rounds** have run (1 on the light path, 3 on the heavy path). Do not loop forever
  chasing literal agreement — after the final round, stop and surface any remaining
  `gated_auto`/`manual` findings for a human.

**Cost note:** each round spawns 2 external CLI agents (run in parallel). The loop is the
expensive part of the workflow, which is why termination is aggressive — a round is re-spent
**only** to resolve genuine adversarial disagreement (contested findings), never to
re-confirm fixes the verify already agreed on.

## Process

1. **Gather context:**
   - Load ticket: `mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)`
   - Read plan artifact for intended approach
   - Run `git diff --name-only` to identify changed files
   - Read build_todo artifact completion notes — collect every **Deviations** entry; the
     deviations, the plan's what/how/elimination/assumptions, and the raw source deliverable
     list are the input package for the plan-conformance reviewer (Step 2)

2. **Check existing review_todo artifacts:**
   - Count existing review_todo artifacts from `get_ticket` response
   - New findings start at `max_sequence + 1` (or 1 if none exist)

3. **Select reviewers** based on diff analysis (see Agent Dispatch above).

4. **Decide the execution path — complexity gate:**

   The mechanical fan-out, dedup, cross-reviewer boost, adversarial verify, and partition
   logic lives in the `review-synthesize` workflow at `workflows/review-synthesize.js`; native
   raw-envelope collection lives separately in `workflows/review-collect.js`. Workflows
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
   | Otherwise (only the always-on set fires on a small diff)         | Light   |

   The "conditional or persona reviewer fires" signal means a reviewer beyond the
   always-on set (code-quality, arch-sec-perf, plan-conformance) qualified from the
   diff analysis.

   Announce the chosen path alongside the review team:

   ```
   Review team: code-quality [sonnet], architecture-security-performance [opus], plan-conformance [sonnet]
   Path: light (3 reviewers, 1 file, 18 LOC) — inline parallel Agent calls, no verify
   ```

   or:

   ```
   Review team: code-quality, arch-sec-perf, data-integrity, react, pipeline-reviewer
   Path: heavy (5 reviewers, 12 files, 340 LOC) — collect all providers, then one synthesis with verify
   ```

5. **Fan out — light path (inline):**

   When the gate selects "Light", issue the reviewer `Agent` calls in parallel (one assistant
   message, multiple tool-use blocks). No workflow, no skeptics. Every reviewer prompt includes
   `Diff at: .context/review/diff.patch` (the shared artifact from Step 1) so reviewers read
   the diff instead of re-computing it. Each reviewer returns the
   reviewer-output JSON shape documented in `workflows/review-collect.js`
   (`reviewerOutputSchema`). **Unless `mode:solo`, include the two peer providers in this same
   parallel batch** — see Cross-Provider Reviewers above. In Claude Code that means
   `external-reviewer` subagents; in Codex/Grok that means direct `external-agent` peer calls.
   They return the identical envelope shape and merge with no special-casing.

   The light path does **not** get schema enforcement at the tool layer (the `Agent` tool
   has no `schema:` parameter). Validate manually: for each reviewer's findings, drop any
   that don't have all of `title`, `severity`, `file`, `line`, `confidence`, `autofix_class`,
   `owner`, `requires_verification`, `pre_existing`, `evidence` (non-empty array),
   `why_it_matters`. Count dropped findings into `suppressed`. Mirror the `validFinding`
   function in `workflows/review-synthesize.js`.

   Then do minimal synthesis inline:
   1. Dedupe in two passes. First exact: `(file, normalized title, |line diff| ≤ 3)`
      pairwise comparison — match against any existing group member, not just the first
      (keep highest severity and confidence, union evidence, AND-merge `pre_existing`).
      Then **semantic**: for same-file findings within ±5 lines whose titles differ (and
      for any pair of `absence: true` findings regardless of file), judge whether they
      describe the same underlying defect and merge if so. Do NOT rely on title-string
      equality to detect cross-reviewer/cross-provider agreement — providers never word
      the same defect identically, and the confidence boost in step 2 depends on these
      merges.
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

5a. **Collect, then synthesize — heavy path (two workflows):**

   When the gate selects "Heavy", collection and synthesis are separate barriers. The runtime
   resolves `name:` against `~/.claude/workflows/`, where agent-workflows is symlinked in every
   environment (local, NanoClaw, cloud SessionStart copy).

   If the current host tool does not expose Claude's `Workflow` tool (for example a
   Codex/Grok-orchestrated run), execute the equivalent heavy-path algorithm inline but preserve
   the same barrier: finish all native/self-review + peer provider calls first, then validate,
   dedup, boost, gate, verify, and partition once. Do **not** downgrade a heavy review to a
   one-provider review because the Claude `Workflow` primitive is absent.

   ```
   native = Workflow({
     name: "review-collect",
     args: {
       reviewers: [
         { key: "code-quality", model: "sonnet", focus: "...",
           references: ["references/python-standards.md", ...] },
         // stay on opus — fable is not available on the subscription plan after 2026-07-07
         { key: "architecture-security-performance", model: "opus", focus: "...",
           references: ["references/architecture.md", ...] },
         { key: "plan-conformance", model: "sonnet",
           focus: "implementation vs source deliverables, plan scope/elimination, builder deviations",
           extraContext: "<raw source deliverable list + plan what/how/elimination/assumptions + builder Deviations entries>" },
         // ...plus conditional + project-persona reviewers from step 3
       ],
       intent: "<2-3 line intent from plan/commits>",
       files: ["<changed files from .context/review/files.txt>"],
       diffSummary: "<git diff --stat output or short narrative>",
       diffPath: ".context/review/diff.patch",
       mode: "interactive" | "autofix" | "report-only" | "headless",
       carried: [ /* rounds ≥2 only: unresolved advisory + contested + residual-risk
                     carry-overs from the previous round (see Carry-forward below) */ ]
     }
   })
   // Unless mode:solo, run this Workflow call and the two external-reviewer dispatches
   // concurrently. Wait for all three operations to finish.
   raw = [
     ...native.reviewer_results,
     peerCodexEnvelope,
     peerGrokEnvelope,
   ]

   result = Workflow({
     name: "review-synthesize",
     args: {
       reviewerResults: raw,
       intent: "<same intent>",
       diffSummary: "<same summary>",
       diffPath: ".context/review/diff.patch"
     }
   })
   ```

   Under `mode:solo`, `raw` contains only `native.reviewer_results`; synthesis is otherwise
   identical. A failed provider contributes its valid empty envelope plus `residual_risks` note.
   Never call `review-synthesize` while a peer is still running, and never synthesize native
   findings first and append peers afterward.

   **Pass `args` as actual JSON objects, never stringified blobs.** Both workflows parse a
   stringified blob defensively only to return a clear error; callers must use real objects.

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

   - A hard all-provider collection barrier before any synthesis decision
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
4. **Flag missing items as P1 `manual` with `absence: true`** — scope items that were
   planned but not implemented are correctness issues, not style nits. Anchor to the
   closest related file and put the grep commands that should find the missing code in
   `evidence` (skeptics verify absences by searching)
5. **Audit builder deviations** — every Deviations entry from the build must be sound
   against the plan's intent; unsound deviations are findings

| Source Item | Plan Step | Implemented? | Finding |
|---|---|---|---|
| [item from source] | Step N | Yes / **No** | [p1, absence] if missing |

**Why:** F0076 listed 4 deliverables in the source. The plan marked one as "TBD".
Implementation skipped it entirely. Review never ran, so no one caught the gap.
The ticket was marked complete with $110/month in unnecessary cost still running. This
check was previously a standalone section outside the numbered process, so orchestrators
skipped it — it is now a mandatory always-on reviewer.

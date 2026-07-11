---
name: review-fable
description: Fable-variant review. Fable reviewers judge the Codex-built diff against the plan; cross-provider by default; same findings schema, synthesis, and routing contracts as /review.
---

# Review (Fable variant)

Review the implementation against the plan (style: `skills/references/fable-prompting.md`).
Same contracts as the base `/review` — findings schema, synthesis math, routing, artifact
shapes — with the Fable-tier reviewers spawned as `reviewer-fable` (Fable 5, effort high).
Structurally cross-provider: the diff was written by Codex GPT 5.5, so the native Fable
review is already a second model's eyes, and the peer dispatch adds the rest.

References and templates are shared with the base skill: `../review/references/*`
(including `findings-schema.json`), `../review/templates/review-todo.md`.

## Usage and modes

```
/review-fable F001                      # default: interactive, cross-provider
/review-fable F001 mode:autofix         # autonomous: apply safe_auto only, never commit
/review-fable F001 mode:report-only     # read-only, no edits or artifacts
/review-fable F001 mode:headless        # structured output for skill-to-skill composition
/review-fable F001 mode:solo            # opt OUT of peer providers (fast/cheap)
/review-fable F001 --deep | --light     # force heavy/light path
```

Mode rules are identical to the base skill: autofix/report-only/headless never ask the user;
autofix and headless apply only `safe_auto -> review-fixer` findings and write review_todo
artifacts for the rest; nothing in this skill ever commits, pushes, or opens a PR. Headless
output ends with the terminal line `Review complete`.

## Shared diff artifact (first step, always)

```bash
mkdir -p .context/review
git diff main > .context/review/diff.patch
git diff --name-only main > .context/review/files.txt
```

Every reviewer, skeptic, and peer dispatch references these paths (`Diff at:
.context/review/diff.patch`) instead of re-discovering the diff.

## Reviewer selection

Always-on pair:

| Reviewer | Agent / model | References |
| --- | --- | --- |
| code-quality (quality, YAGNI, patterns) | `reviewer` on `sonnet` | python-standards.md or typescript-standards.md, simplicity.md, patterns.md |
| architecture-security-performance | `reviewer-fable` (fable) | architecture.md, security.md, performance.md |

Light-diff downgrade: total diff < 50 LOC (`git diff --shortstat`) → both always-on reviewers
on `sonnet`.

Conditional reviewers — decide from the actual diff (`git diff --name-only main -- …`), never
from build_todos or the plan:

| Diff touches | Reviewer | References |
| --- | --- | --- |
| Models/migrations/schema (any hit on the repo's schema paths — missing migration is p1) | `reviewer-fable` | data-integrity.md, migrations.md, deployment.md |
| Repeated writers that persist rows (pollers, observers, schedulers, queues, webhooks, scrapers — even with no model change) | `reviewer-fable` | data-integrity.md, performance.md, deployment.md |
| Provider-backed caches / reference data / prompt-context tables / ground-truth labels (even with no model change) | `reviewer-fable` | data-integrity.md |
| React/frontend | `reviewer` on `sonnet` | react-router.md, react-performance.md |
| Data pipelines / DAG nodes | `reviewer` on `sonnet` | data-adequacy.md |

The polling reviewer must check write amplification (new durable rows for unchanged source
data, rows/day + bytes/day, dedupe keys across runs, retention) — unbounded redundant
persistence scaling with polling frequency is p1 unless a named consumer, retention policy,
and volume budget make it intentional. The cache reviewer must check temporal finality
(`live`/`provisional`/`final` classification, writer/reader inventory, no first-write-wins
for mutable provider data, cache-hit tests with a pre-existing stale row) — live data trusted
as final ground truth is p1.

Also discover project persona reviewers (`ls .claude/agents/*-reviewer.md`), spawn those
whose activation conditions match the diff; when uncertain, spawn.

Announce the team and the chosen path (one line each) before spawning — progress reporting,
not a confirmation gate.

## Cross-provider reviewers (default; `mode:solo` opts out)

Required, not optional: unless `mode:solo`, actually run the two providers that are not the
current runner (`agent-workflow-provider`; peers table is symmetric across
claude/codex/grok). Never simulate a provider's findings by reasoning about what it "would"
say — the only valid peer contribution is the envelope its process returned.

- **Claude Code runner:** spawn two `external-reviewer` subagents (prompt: `provider=<peer>`,
  plus the diff base and bounded memory-packet path) **in the same parallel Agent batch** as the native reviewers — the
  adapter can take ~9 minutes at xhigh and a foreground shell-out would hit the Bash timeout
  and silently drop the provider.
- **Codex/Grok runner:** background `external-agent --task review --provider <peer> --base
  <merge-base> --memory-context-file <bounded-task-packet> --out
  .context/review/<provider>.json` loops, then wait. Use one <=3K task envelope; never rely on
  ambient child SessionStart.

Each peer returns the same envelope shape as native reviewers
(`{reviewer_key, findings, residual_risks, testing_gaps}` per `findings-schema.json`); a
failed provider returns a valid empty envelope with a `residual_risks` note — surface it,
don't block. Fold peers into the same synthesis as two more reviewers (never a separate
synthesis) so the cross-reviewer boost rewards three-provider consensus (+0.20).
`.context/review/*.json` is ephemeral scratch; merged findings persist as artifacts.

## Complexity gate

| Condition (first match) | Path |
| --- | --- |
| `--deep` | Heavy |
| `--light` | Light |
| ≥1 conditional or persona reviewer fires | Heavy |
| ≥5 files changed | Heavy |
| ≥200 LOC changed | Heavy |
| Otherwise | Light |

**Light path:** spawn the reviewers (plus peers) in one parallel batch, then synthesize
inline. Validate findings manually (drop any missing `title, severity, file, line,
confidence, autofix_class, owner, requires_verification, pre_existing, evidence[≥1],
why_it_matters`; count drops into `suppressed`), dedupe by `(file, normalized title,
|line diff| ≤ 3)` against any group member (keep highest severity/confidence, union
evidence, AND-merge `pre_existing`), boost `confidence += 0.10 × (reviewers − 1)` capped at
1.0, gate (suppress <0.60, rescue p1 ≥0.50), separate `pre_existing`, sort severity →
confidence → file → line, route (`safe_auto`→review-fixer, `gated_auto|manual`→
downstream-resolver, `advisory`→human), partition into
`{inSkillFixer, residualActionable, reportOnly}`.

**Heavy path:** invoke `review-collect` with the native reviewer list (pass `model: "fable"`
for reviewer-fable-tier entries, `"sonnet"` for the rest), intent, files, diffSummary,
`diffPath: ".context/review/diff.patch"`, and mode. Run that collection concurrently with both
peer dispatches. After all return, concatenate `native.reviewer_results` plus the peer envelopes
and invoke `review-synthesize` exactly once. No boost, gate, or skeptic may run before the peer
barrier. `review-synthesize` adds semantic dedup and tiered adversarial verify. No `Workflow`
primitive in the host → run the equivalent two-stage algorithm inline; never downgrade to one
provider.

**Both paths produce the same result object** (`findings, pre_existing,
pre_gate_suppressed, partitions, suppressed, coverage, stats` — light path zero-fills the
verify stats). Downstream must not branch on path.

## After synthesis

1. **Memory-assisted rescue:** for each `pre_gate_suppressed` finding ([0.50, gate)), search
   memory; a confirming gotcha/incident upgrades it to 0.80+ with the entry as evidence —
   re-admit into findings/partitions and decrement the suppressed counters.
2. **Store findings** as `review_todo` artifacts (`create_artifact`, sequence continuing
   from `max_sequence + 1`, `command="/review-fable"`), routed by mode exactly as the base
   skill: interactive/autofix/headless auto-apply `safe_auto` (store resolved), store
   `gated_auto`/`manual` pending, advisory report-only; report-only mode writes nothing.
3. **Persist p1/p2 findings to memory** (`create_entry` after a duplicate-check search;
   `update_entry` to append when a related entry exists; skip silently if MCP unavailable) —
   this is what lets future builds avoid the same finding.
4. **Update the plan artifact** with a review log entry (`update_artifact`).

**Scope completeness check (every review):** enumerate the source artifact's deliverables,
verify each has a plan step and an implementation in the diff; a planned-but-missing scope
item is a **p1 finding**, not a nit.

Ticketless (lfg) mode: findings go to `.context/review_todos/` files instead of MCP
artifacts; the memory persistence step still applies.

## Cross-review iteration loop (canonical for the -fable chain)

Used by `/ticket-flow-fable` and `/lfg-fable`:

```
round = 1;  max_rounds = 1 if light path else 3;  carried = []
while round <= max_rounds:
    run /review-fable mode:cross          # include `carried` in reviewer context
    actionable = partitions.inSkillFixer + partitions.residualActionable
    contested  = findings the adversarial verify DISAGREED on (requires_verification: true —
                 mixed/missing skeptic verdicts, or reviewers split). Light path never
                 verifies, so contested is always empty there — it stays single-round.
    if actionable is empty: break         # advisory + gate-suppressed nits don't count
    resolve actionable findings (/resolve-review-fable routing)
    re-run affected tests + type check
    if contested is empty: break          # verify agreed — fixes trusted; no confirmation round
    carried = contested + unresolved advisory findings
    round += 1                            # another round ONLY because the adversarial reviews disagreed
```

A round is complete only when all three providers contributed — confirm both
`.context/review/<provider>.json` peer files exist and were folded in (a valid empty
envelope counts; a *missing* file means dispatch was skipped — go back and spawn it). A
one-provider round is a failed round. After the final round, stop and surface remaining
`gated_auto`/`manual` findings for a human rather than looping for literal agreement.

## Output

Interactive: the base skill's findings table (file/issue/reviewers/confidence/route),
applied-fixes list, residual work, pre-existing issues, coverage (suppressed count, residual
risks, testing gaps), verdict (`Ready to merge | Ready with fixes | Not ready`), then
`Next: /resolve-review-fable {ID}` if actionable findings remain, else `/create-pr {ID}`.

Headless: the base skill's envelope — scope, intent, verdict, applied count, then
`[severity][class -> owner] File: <file:line> -- <title> (confidence N)` blocks for
gated/manual/advisory/pre-existing, residual risks, testing gaps, suppressed count, ending
with the terminal line `Review complete`.

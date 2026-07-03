---
name: resolve-review-fable
description: Fable-variant review resolution. Routes findings by autofix class; the orchestrator makes the judgment calls, the Codex (GPT 5.5) builder implements every approved fix via bin/external-build.
skills:
  - autodev-search
  - compound
---

# Resolve Review (Fable variant)

Resolve pending review_todo findings (style: `skills/references/fable-prompting.md`). The
division of labor is strict: **judgment lives here** (the Fable orchestrator decides what to
apply, presents gated/manual findings, validates results, owns artifact statuses and
commits); **implementation lives in Codex** — every approved fix is applied by
`bin/external-build --task resolve` (GPT 5.5, xhigh). No Claude builder agent is spawned.

## Usage

```
/resolve-review-fable F001 | B0009 | 009
```

Prerequisite: pending review_todo artifacts on the ticket (ticketless lfg mode: finding
files in `.context/review_todos/`).

## Routing (same classes as the base system)

| autofix_class | Resolution |
| --- | --- |
| `safe_auto` | Apply without asking — dispatch immediately |
| `gated_auto` | Ask first: present title, file:line, why_it_matters, confidence, suggested fix — "This changes behavior/contracts. Apply? (yes / no / modify)" |
| `manual` | Present with options: apply suggested fix / user provides alternative / defer to a separate work item / skip |
| `advisory` | Skip — already reported during review |

In autonomous contexts (invoked by `/ticket-flow-fable` or `/lfg-fable`), the calling
workflow's policy stands in for the user on gated/manual findings; do not invent approvals
here.

## Dispatch to the Codex builder

Batch the approved findings (safe_auto immediately; gated/manual after decisions) into a
findings file, then:

```bash
mkdir -p .context/review
# .context/review/fixes.md — one block per finding:
#   Finding #{sequence}: {title}
#   Severity: {p1|p2|p3}  Confidence: {c}  Decision: {accept|modify: <notes>}
#   File: {file}:{line}
#   Fix: {suggested fix, or the user's alternative}
external-build --task resolve \
  --findings-file .context/review/fixes.md \
  --context-file .context/review/resolve-context.md \
  --repo "$(pwd)" \
  --out .context/review/resolve-result.json
```

The context file carries the project health commands and any memory-service gotchas relevant
to the touched areas (the Codex side cannot search memory). Run in the background and read
the `--out` file — xhigh runs can exceed the foreground shell timeout. The adapter's
embedded rules already require: usage search before removing any export, lint + typecheck
per fix, tests covering each touched file re-run, and a regression test (or explicit
untestable reason) for every p1 correctness fix.

## Validate and set statuses (orchestrator-owned — the trust model)

Parse the returned JSON array (`{finding_id, status, files_changed, verification_output,
regression_test}` per entry) and validate before touching any artifact:

- every dispatched finding has an entry;
- `status` ∈ `resolved | skipped | deferred`;
- `resolved` entries show passing verification for their touched files;
- `resolved` p1 entries carry a `regression_test` or an explicit untestable reason.

Only then set each review_todo's status via `update_artifact` (`resolved`/`skipped`,
`command="/resolve-review-fable"`). Entries that fail validation stay `pending` — re-dispatch
(≤2 retries with the failure appended to the context file) or surface to the user. An
artifact is never marked resolved on the builder's say-so alone. An empty result array
(adapter exit 2) means nothing was resolved — report it, don't guess.

## After the fixes

1. **Capture learnings:** run `/compound` on the resolved findings — it decides what becomes
   memory entries vs skill/workflow changes and asks for approval in interactive mode.
   Corrections that target workflow files follow the drift rule in
   `../references/fable-prompting.md`: a gap in this chain fixes the `-fable` file.
2. **Update the plan artifact** (`update_artifact`): insert a Review Resolution Summary
   (what was done; applied/skipped counts per class; files changed; learnings captured)
   before the Work Log, plus a work-log line
   (`| YYYY-MM-DD | resolve-review-fable | Resolved N findings | X applied, Y skipped |`).
3. **Deployment guide:** run `/create-deployment-guide` if the ticket doesn't already have a
   finalized one (skippable for trivial/doc-only changes).
4. **Commit and push (ticketed standalone runs only):** submodule-aware — commit and push
   inside changed submodules first, then stage the submodule ref. Before every commit run
   `git status --porcelain` + `git diff --staged --stat` and confirm only intended files are
   staged (no `.context/` scratch, no unrelated working-tree state). Commit
   `Resolve review findings for {ID}: {summary}`, push.

**Ticketless (lfg) mode:** outcomes are recorded in the `.context/review_todos/` finding
files instead of artifacts; **no commit/push here** — lfg owns its own commits and never
pushes.

## Output

```
Review resolved for {ID}: {title}

Applied: {N} fixes ({safe_auto} auto, {gated_auto} gated, {manual} manual) — Codex GPT 5.5
Skipped: {N} ({advisory} advisory)

Next: deploy via /ticket-flow-fable (/auto-deploy) — or done if ticketless/no deploy needed
```

Report faithfully: applied counts must match validated `resolved` entries, not dispatched
ones; name any finding left `pending` and why.

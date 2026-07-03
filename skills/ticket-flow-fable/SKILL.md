---
name: ticket-flow-fable
description: Fable-variant autonomous single-ticket execution. Same lifecycle and deployment contracts as /ticket-flow, running the -fable chain — Fable planning/review, Codex GPT 5.5 building — and sharing /auto-deploy and /ticket-verify unchanged.
max_turns: 300
---

# Ticket Flow (Fable variant)

Autonomously execute **one ticket** end to end using the `-fable` chain (style:
`skills/references/fable-prompting.md`): gather context → `/auto-plan-fable` →
`/create-build-todos-fable` → `/build-fable` (Codex GPT 5.5 via `bin/external-build`) →
`/write-tests` → `/review-fable mode:cross` loop → `/resolve-review-fable` → local verify →
`/auto-deploy`. Behavior verification stays owned by `/ticket-verify`.

You are operating autonomously. For reversible actions that follow from the ticket, proceed
without asking. Before ending your turn, check your last paragraph: if it is a plan, a
question, or a promise about work not yet done, do that work now. End only when the flow is
complete or blocked on input only the user can provide (a destructive/irreversible action, a
real scope change, an unresolved design decision).

Before reporting progress, audit each claim against a tool result from this session. Only
report work you can point to evidence for; if tests fail, say so with the output; if a step
was skipped, say that. Your final message is the user's first look at the run: lead with the
outcome, complete sentences, no working shorthand.

## Hard boundaries (identical to /ticket-flow)

- May create/resume exactly one ticket.
- Owns the standalone delivery decision: **staging-first** for complex/risky/uncertain work,
  **direct-production** only for tiny safe work.
- Deploys standalone tickets **only** by invoking `/auto-deploy` (shared with the base
  system — not forked); never ad-hoc deployment commands.
- Never performs staging/production behavior verification (`/ticket-verify` owns it) and
  never advances an epic/milestone gate (epic skills own those).
- Ticket artifacts live in MCP, never `.context/`.

## References (shared, read before acting)

`../references/ticket-lifecycle.md`, `../references/landing-policy.md`,
`../references/execution-phases.md` (**mapping rule:** where it names `/auto-plan`,
`/create-build-todos`, `/build`, `/review`, `/resolve-review`, use the `-fable` equivalents;
everything else applies as written), `../references/epic-lifecycle.md` for epic steps,
`../references/conductor-multi-repo.md` for epic/cross-repo/linked-directory contexts.

## Usage

```
/ticket-flow-fable F0123
/ticket-flow-fable B0042 --target staging
/ticket-flow-fable F0123 --target production
/ticket-flow-fable #123
/ticket-flow-fable                       # create ticket from conversation
/ticket-flow-fable F0123 --no-land       # build/review only
/ticket-flow-fable F0123 --skip-local-verify
```

## Delivery target (decide before planning)

Precedence: explicit `--target staging|production|prod|main|none`/`--no-land` → existing PR
base/branch ancestry → epic milestone target (epic steps) → landing-policy risk
classification. The Conductor workspace target branch is a hint, not permission: if the
workspace targets `main` but the ticket is not tiny/safe, route to staging unless the user
explicitly asked for direct production.

## Process

**0. Resolve.** Project from `<!-- mem:project=X -->`, repo from git remote. If the ticket's
repo isn't the current repo, switch only to a verified linked Conductor directory for it —
never implement one repo's ticket inside another. Load via `get_ticket`, or search-then-create
for issue/conversation input (no new ticket when a matching non-terminal one exists). Detect
epic-step context (epic membership, `related`, `tags.related_epic`, source text) and load
`get_epic` + milestone contracts when found. Record the delivery target.

**1. Context — knowledge retrieval gate (hard gate).** Before planning or editing, run
`mcp__autodev-memory__search` on the ticket's actual risk boundaries (source terms, touched
subsystem, integration boundary, deployment path), read the entries, and carry applicable
rules forward; state explicitly when nothing applies. Similar-ticket search alone does not
satisfy this. Features/refactors: codebase research. Bugs: investigate root cause first.
Epic steps: include the parent epic plan, milestone acceptance criteria, contracts, and the
repo/path/branch mapping in everything passed to planning/build.

**2. Plan.** Run `/auto-plan-fable` (its complexity gate decides light/heavy; force deep for
epic steps, cross-repo contracts, schema/data changes, and other high-risk work). Store the
plan artifact, set `summary_bullets`. There is no `approved` status — leaving `planned`
means setting `in_progress`. **Honor dashboard comments:** if `open_comment_count > 0` on
the plan/source, fetch (`list_artifact_comments`), revise (`update_artifact`), and resolve
(`resolve_artifact_comment`) before building — never build past unresolved feedback.

**3. Build, test, review, resolve.** `/create-build-todos-fable` → `/build-fable` (one Codex
builder per todo, orchestrator checkpoints, health gate) → keep unrelated lint/type fixes in
a separate commit → `/write-tests` → the cross-review iteration loop by invoking
`/review-fable mode:cross` each round (canonical loop lives in that skill; ≤3 rounds heavy,
1 light; a round without both peer `.context/review/<provider>.json` files is a failed
round) with `/resolve-review-fable` resolving actionable findings. Stop for unresolved
design decisions.

**Persistence gate (before landing):** confirm via `get_ticket` that the ticket now carries
its `build_todo` and `review_todo` artifacts — in-session work is not the record. Re-issue
any `create_artifact` that silently no-op'd. A ticket must not land with only a `source`
artifact.

**4. Local verification.** Project-local checks only — no staging/prod queries, no triggered
flows. Failure blocks landing unless the user explicitly accepts a no-land partial result.

**5. Deploy / land.** `--no-land`/target `none`: stop after local verification and report
remaining commands. Standalone tickets: invoke `/auto-deploy {ticket_id} {staging|production}`
— the canonical path for PR creation, merge, deploy steps, mechanics checks, manual
blockers, and status updates; do not duplicate its logic. If auto-deploy is unavailable or
blocked by a manual dependency, stop and report — never silently downgrade a deploy-required
run to land-only.

Epic steps: land onto the milestone integration branch and set `merged`; the milestone
deploy + cross-step gate is `/milestone-flow`'s, never per-step. Delegated run
(`--epic-context`): stop at `merged`. Direct run: if this landing completes the milestone
(all sibling steps `merged`), hand off to `/milestone-flow <EPIC_ID> <MILESTONE>` so the run
includes the deploy + gate; if siblings are still open, stop at `merged` and say loudly that
the milestone is NOT deployed yet. Epic-step production promotion belongs to
`/epic-flow`//`ticket-promote --epic` after all gates pass. (Note: `/milestone-flow` itself
drives steps through base `/ticket-flow`; running epic steps through the fable chain happens
via direct `/ticket-flow-fable <step>` runs, which must honor all the same invariants.)

**6. Status.** Trust the owning workflow: standalone via `/auto-deploy` →
`to_verify_prod` (production) / `to_verify_staging` (staging); epic step → `merged`
(gate PASS later advances steps via `/milestone-flow`). A manual/external deploy dependency
still advances to the verification state, with the blocker captured in ticket blocker
metadata, not as a lifecycle status.

## Output

Use the base `/ticket-flow` output shapes (standalone / epic-direct-complete /
epic-partial), with the summary naming this chain, e.g.:

```
Ticket flow (fable) complete: F0123
Target: staging
Landed: PR #456 -> staging
Status: to_verify_staging

Summary:
- planned (auto-plan-fable), built via Codex GPT 5.5 (external-build), tested,
  cross-reviewed (fable + 2 peers), findings resolved
- local verification: PASS
- deploy: PASS via /auto-deploy staging
- behavior verification: not run
- screenshots: {absolute paths if UI/visual; otherwise "not applicable"}

Next:
- /ticket-verify staging F0123
```

Every claim in the summary must trace to a tool result from this run.

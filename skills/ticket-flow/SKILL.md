---
name: ticket-flow
description: >-
  Ticket ceremony for autonomous single-ticket execution: resolve or create the MCP ticket,
  persist the plan artifact, track statuses, implement and review the change, then hand deploy
  and verification to /ticket-deploy.
max_turns: 100
---

# Ticket Flow

Execute **one ticket** — from an existing F/B/R ID, a GitHub issue, or conversation context —
with correct MCP ticket ceremony around the work. The model does the work; this skill defines
the bookkeeping and hand-offs:

```text
resolve/create ticket -> plan artifact -> implement -> review + local health
  -> /ticket-deploy <ID> staging      # default: stop after staging verify
  -> /ticket-deploy <ID> full         # when invoked as /ticket-flow <ID> prod
```

## Usage

```text
/ticket-flow F0123            # through staging verify, then stop
/ticket-flow F0123 prod       # continue through production to completed
/ticket-flow #123             # from GitHub issue
/ticket-flow                  # create ticket from conversation
/ticket-flow F0123 --no-land  # build/review only; do not merge or deploy
```

Invoking with `prod` is the explicit human authorization for production promotion/deploy after
an exact staging `PASS` (it maps to `/ticket-deploy <ID> full`). It does not authorize
product-intent changes, destructive scope expansion, materially different tradeoffs, or new
secrets/schema/infrastructure/cost beyond the accepted plan.

## Hard boundaries

- Exactly one ticket per run: create or resume it, never several.
- A plan MCP artifact must exist **before the first edit**, however small the change.
- Ticket artifacts live in MCP (`create_artifact`), never in `.context/`.
- Statuses follow `../references/ticket-lifecycle.md`; deploy/verify statuses are set by
  `/ticket-deploy`, `/ticket-verify`, and `/ticket-promote`, never duplicated here.
- Staging-first by default. Direct-production only for tiny safe work, and only through
  `/ticket-deploy <ID> prod`, whose gate re-checks the risk classification. The Conductor
  workspace target branch is a hint, not permission to bypass that classification.
- Epic step tickets: honor the parent epic's milestone contracts
  (`../references/epic-lifecycle.md`), land on the milestone integration branch, set `merged`,
  and stop — `/epic-flow` owns milestone progression; the epic/milestone gate (`/ticket-verify
  --epic`) owns verification and promotion.
  Never deploy or promote a partial milestone from a single step.

## Process

### 1. Resolve ticket and target

- Project from `<!-- mem:project=X -->` in the repo's CLAUDE.md; repo from the git remote. If
  the ticket's repo does not match the current repo, stop and report — never implement a ticket
  for one repo inside another.
- Ticket ID given: `get_ticket(detail="light", include_events=false)`, then fetch only the
  artifact bodies the work needs. Issue/conversation input: search existing tickets first
  (`search_tickets`, `get_similar_tickets`); create a new ticket only when no matching
  non-terminal ticket exists.
- Detect epic membership (epic link, `related`, tags, source text); if present, load the epic
  once and honor its milestone contracts.
- Decide the delivery target (staging default; direct-production only for tiny/safe; `--no-land`
  means build/review only) and record it in the ticket.
- **Resume from lifecycle truth**: skip phases whose artifacts and status already exist — a
  `planned` ticket with a plan artifact enters at implementation; a built ticket with health
  evidence enters at deploy; `verify_staging_failed` resumes inside `/ticket-deploy`'s repair
  loop, not here.

### 2. Plan

Set `in_progress`. Investigate as much as the change warrants (a confirmed bug needs a root
cause before a fix), then persist a plan artifact: intent, approach, files, risks, and
acceptance criteria concrete enough for `/ticket-verify` to grade later. Scale the plan to the
work — a direct fix gets a short plan, not a skipped one.

### 3. Implement, review, verify locally

Implement the planned change with focused behavior tests, running only the targeted tests and
lint for the files you touch while iterating. Then, for non-trivial diffs, run **one** review
pass against the plan — self-review, `/code-review`, or at most two forked reviewers with
disjoint scopes, never a nested review CLI on top of forked reviewers — and fold accepted
findings into **one** repair pass, re-running targeted tests only. Only then run the repo's
full health gate, once, on the final tree; inventory and fix all failures, re-running the full
gate only when the tree changed. The tree that passes the full gate is the tree you push, so
the gate runs at most twice per landing (final tree, and once more after a rebase that changed
files). Record deviations from the plan in the ticket.

Read CLAUDE.md, this skill, and the plan artifact once; after a context compaction, continue
from the compaction summary and the plan rather than re-reading them. When you have enough
information to act, act.

If the work turns out to cross a boundary the plan didn't accept — schema, auth, destructive
migration, new infrastructure — stop before the risky edit, update the plan artifact, and
surface the decision instead of absorbing it silently.

If `--no-land`: stop here and report the remaining commands.

### 4. Deploy and verify

Standalone tickets:

```text
/ticket-deploy <ID> staging        # default
/ticket-deploy <ID> full           # with the prod argument
```

`/ticket-deploy` owns the entire leg — staging deploy, evidence verification, repair loop, and
(`full` only, gated on exact staging `PASS`) promotion, production deploy, production
verification, and `completed`. Relay its terminal report verbatim; do not convert a documented
staging repair or deterministic wait into a request for the user to run a command.

Epic steps: land on the milestone integration branch, set `merged`, report which sibling steps
remain, and stop.

## Output

Report phases run, PR/commit identifiers, evidence artifact IDs, and final ticket status.
Preserve the distinction between staging success and production success — only a production
verification PASS with canonical `completed` status is complete. End with a "Not verified:"
line naming anything claimed but not exercised in this run, e.g.:

```text
Ticket flow complete: F0123
Plan: artifact <id> -> implemented -> health PASS -> /ticket-deploy staging
Landed: PR #456 -> staging
Staging verification: PASS (evidence artifact <id>)
Status: staging_verified

Not verified: production behavior (run /ticket-flow F0123 prod or /ticket-deploy F0123 prod)
```

---
name: ticket-flow
description: Autonomous single-ticket execution with MCP ticket tracking. Gathers context, plans, critiques, builds, reviews, resolves, locally verifies, and hands off to auto-deploy when policy allows. No environment verification.
max_turns: 300
---

# Ticket Flow

Autonomously execute **one ticket** from GitHub issue, existing F/B/R ticket, or conversation
context. This is the renamed/coherent successor to legacy `/auto-flow`.

Ticket Flow is ticket-level only. It is not an epic orchestrator, but if the ticket is an epic
step it must load the parent epic context and honor the milestone contracts.

## Hard boundaries

- May create/resume exactly one ticket.
- May prepare/land a completed branch when landing policy allows, but prefer the integrated
  `/auto-deploy` handoff for PR creation/merge/deploy/status transitions.
- Must not perform ad-hoc deployment commands itself; if deployment is in scope, invoke/follow
  `/auto-deploy` so deployment, manual blockers, and status updates happen in one place.
- Must not perform staging/production verification.
- Must not advance an epic/milestone gate; epic skills own that.
- Must not use `.context/` for ticket artifacts; use MCP artifacts.
- `/lfg` remains the ticketless/current-branch workflow and is not changed by this skill.

## References

Read before acting:

- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/execution-phases.md`
- `../references/epic-lifecycle.md` when the ticket is an epic step

## Usage

```text
/ticket-flow F0123
/ticket-flow B0042 --target staging
/ticket-flow #123
/ticket-flow                       # create ticket from conversation
/ticket-flow F0123 --no-land       # build/review only; do not merge
/ticket-flow F0123 --skip-local-verify
```

Legacy alias: `/auto-flow` should delegate to this skill.

## Target selection

Target is chosen in this order:

1. explicit `--target main|staging|none` or `--no-land`;
2. Conductor workspace target branch, if trustworthy;
3. branch ancestry / PR base if a PR already exists;
4. landing policy risk classification.

If the apparent target is `main` but the ticket is not tiny/safe, stop before building and ask
the user to retarget to `staging` or explicitly approve direct-main landing.

## Process

### 0. Resolve ticket and target

- Resolve project from `<!-- mem:project=X -->` and repo from git remote.
- If input is a ticket ID, load it via `get_ticket`.
- If input is an issue/conversation, search existing tickets first; create a new ticket only
  when no matching non-terminal ticket exists.
- Detect epic-step context from explicit epic membership, `related`, `tags.related_epic`, or
  source text. If found, load `get_epic` and the step's milestone/contracts.
- Decide target using `landing-policy.md`.

### 1. Gather context

- Feature/refactor: run codebase research and similar-ticket search.
- Bug: investigate root cause first; for production incidents use hypothesis evaluation.
- Epic step: include the parent epic plan, milestone acceptance criteria, blockers, and
  contracts in the context passed to planning/build agents.

### 2. Plan and criticize

- Run the existing plan workflow with its light/heavy gate for standalone tickets.
- Force deep planning when the ticket is an epic step, cross-repo contract consumer/provider,
  schema/data change, or otherwise high risk.
- Run adversarial plan critique until no critical unresolved findings remain.
- Store the final plan as an MCP `plan` artifact.
- There is no `approved` status; leaving `planned` means setting `in_progress`.

### 3. Build, test, review, resolve

Follow `execution-phases.md`:

- create MCP `build_todo` artifacts;
- implement each step;
- keep unrelated lint/type/review fixes in a separate commit;
- write focused tests;
- run the cross-review iteration loop (review skill, `mode:cross`): each round adds external
  Codex + Grok reviewers to Claude's self-review and resolves actionable findings, up to 3
  rounds or until none remain;
- stop for unresolved design decisions.

### 4. Local verification

Run project-local checks only. Do not query staging/prod as verification and do not trigger
flows/processes. Local verification failure blocks landing unless the user explicitly chooses a
no-land partial result.

### 5. Deploy handoff / Land

If `--no-land` or target `none`, stop after local verification and report remaining commands.

Otherwise hand off to `/auto-deploy {ticket_id} {target}` as the canonical path for PR creation,
merge, deploy steps, manual deployment blockers, and status updates. Do not duplicate
auto-deploy's status logic in ticket-flow.

Use these target mappings:

- target `main` for tiny safe direct-production tickets;
- target `staging` for risky/uncertain standalone tickets;
- target selected by the epic milestone orchestrator for epic-step tickets.

If auto-deploy is unavailable or explicitly disabled, ticket-flow may create/find a PR, wait for
required checks, and merge to the selected branch, but it must then report that deployment/status
handoff is incomplete rather than guessing deployment state.

### 6. Status update

After successful `/auto-deploy` handoff, trust auto-deploy's status update:

| Ticket kind | Target | Status |
|---|---|---|
| Standalone | `main` | `to_verify_prod` |
| Standalone | `staging` | `to_verify_staging` |
| Epic step | milestone/staging target | `merged` |

If auto-deploy reports an external/manual deploy dependency (for example a Thomas-only
`ts-decrypt-proxy` production deploy), the ticket status should still reflect the next verification
state (`to_verify_prod` for production) and the blocker should be captured in the ticket's
independent blocker metadata, not as a lifecycle status.

If the MCP server rejects `to_verify_staging`, stop and report that the ticket lifecycle enum is
missing the staging verification statuses.

## Output

```text
Ticket flow complete: F0123
Target: staging
Landed: PR #456 -> staging
Status: to_verify_staging

Summary:
- planned, critiqued, built, tested, reviewed, and resolved findings
- local verification: PASS
- deploy: not run
- environment verify: not run

Next:
- /ticket-verify staging F0123
```

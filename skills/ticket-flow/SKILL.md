---
name: ticket-flow
description: Autonomous single-ticket execution with MCP ticket tracking. Gathers context, chooses staging-first vs direct-production delivery, plans, critiques, builds, reviews, resolves, locally verifies, and deploys via auto-deploy. No environment behavior verification.
max_turns: 300
---

# Ticket Flow

Autonomously execute **one ticket** from GitHub issue, existing F/B/R ticket, or conversation
context. This is the renamed/coherent successor to legacy `/auto-flow`.

Ticket Flow is ticket-level only. It is not an epic orchestrator, but if the ticket is an epic
step it must load the parent epic context and honor the milestone contracts.

## Hard boundaries

- May create/resume exactly one ticket.
- Owns the standalone ticket delivery decision: **staging-first** for complex/risky/uncertain
  work, **direct-production** only for tiny safe work.
- Must deploy standalone tickets by invoking/following `/auto-deploy`; treat auto-deploy as the
  deployment subroutine for PR creation, merge, deploy steps, deployment-mechanics checks,
  manual blockers, and status updates.
- Must not perform ad-hoc deployment commands itself outside `/auto-deploy`.
- Must not perform staging/production **behavior verification**; `/ticket-verify` owns the
  post-deploy evidence/testing gate.
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
/ticket-flow F0123 --target production
/ticket-flow #123
/ticket-flow                       # create ticket from conversation
/ticket-flow F0123 --no-land       # build/review only; do not merge or deploy
/ticket-flow F0123 --skip-local-verify
```

Legacy alias: `/auto-flow` should delegate to this skill.

## Delivery target selection

Choose the intended delivery target **before planning/building** so the verification strategy,
deployment guide, and risk controls match the path:

1. explicit `--target staging|production|prod|main|none` or `--no-land`;
2. existing PR base / branch ancestry, if a PR already exists;
3. epic milestone/integration target, for epic-step tickets only;
4. landing policy risk classification.

Target meanings:

- `staging` = merge/deploy to staging first, then `/ticket-verify staging` tests it before any
  production promotion.
- `production`, `prod`, or `main` = merge/deploy straight to production/main.
- `none` / `--no-land` = build/review/local-verify only.

The Conductor workspace target branch is a hint, not permission to bypass risk classification.
If the workspace appears to target `main` but the ticket is not tiny/safe, **route the standalone
ticket to staging automatically** unless the user explicitly requested direct production.

## Process

### 0. Resolve ticket and target

- Resolve project from `<!-- mem:project=X -->` and repo from git remote.
- If input is a ticket ID, load it via `get_ticket`.
- If input is an issue/conversation, search existing tickets first; create a new ticket only
  when no matching non-terminal ticket exists.
- Detect epic-step context from explicit epic membership, `related`, `tags.related_epic`, or
  source text. If found, load `get_epic` and the step's milestone/contracts.
- Decide and record the delivery target using `landing-policy.md`: staging-first for
  complex/risky/uncertain standalone work, direct-production only for tiny safe standalone work.

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
- run the cross-review iteration loop by **invoking the `review` skill in `mode:cross`** (do not
  hand-roll review here): the skill orchestrates native/self-review by the main runner plus the
  other two providers via `external-agent`, distills them into one set, then the main runner
  resolves actionable findings, up to 3 rounds or until none remain. A round is only complete
  when all three providers contributed — confirm the two `.context/review/<provider>.json` peer
  files exist per the cross-coverage gate in `execution-phases.md`; a one-provider-only round is
  a failed round;
- stop for unresolved design decisions.

### 4. Local verification

Run project-local checks only. Do not query staging/prod as verification and do not trigger
flows/processes. Local verification failure blocks landing unless the user explicitly chooses a
no-land partial result.

### 5. Deploy / Land

If `--no-land` or target `none`, stop after local verification and report remaining commands.

For standalone tickets, invoke `/auto-deploy {ticket_id} {target}` as the canonical path for PR
creation, merge, deployment steps, deployment-mechanics checks, manual deployment blockers, and
status updates. This is not an optional handoff: a normal `/ticket-flow` run includes deployment
unless `--no-land`/`target none` was selected.

Use `/auto-deploy` target arguments:

- ticket-flow target `staging` -> `/auto-deploy {ticket_id} staging`;
- ticket-flow target `production`/`prod`/`main` -> `/auto-deploy {ticket_id} production`.

Do not duplicate auto-deploy's status logic in ticket-flow.

Use these target mappings:

- `production`/`main` only for tiny safe direct-production standalone tickets;
- `staging` for risky/uncertain/complex standalone tickets;
- target selected by the epic milestone orchestrator for epic-step tickets.

If auto-deploy is unavailable, explicitly disabled, or blocked by a manual deploy dependency,
stop and report the blocker. Do not silently downgrade a deploy-required ticket-flow run to a
land-only result unless the user explicitly approves that fallback.

Epic-step exception: an epic step is not a standalone deploy unit. `/ticket-flow` may land an
epic step to the milestone/integration target and set it `merged`, but parent `/epic-flow` owns
milestone deployment, staging verification, and promotion.

### 6. Status update

After successful `/auto-deploy`, trust auto-deploy's status update:

| Ticket kind | Target | Status |
|---|---|---|
| Standalone | `production`/`main` | `to_verify_prod` |
| Standalone | `staging` | `to_verify_staging` |
| Epic step | milestone/integration target | `merged` |

For epic steps, `merged` is a handoff to the parent milestone. Do not call `/ticket-verify` for
the step directly; `/epic-flow` will invoke `/ticket-verify staging --epic <EPIC_ID> --milestone
<MILESTONE> --no-promote` after the full milestone has landed and deployed.

If auto-deploy reports an external/manual deploy dependency (for example a Thomas-only
`ts-decrypt-proxy` production deploy), the ticket status should still reflect the next verification
state (`to_verify_prod` for production) and the blocker should be captured in the ticket's
independent blocker metadata, not as a lifecycle status.

The staging verification statuses (`to_verify_staging`, `verify_staging_failed`) exist on the
ticket lifecycle enum as of migration 025, so a standalone staging landing advances the ticket
to `to_verify_staging` directly — no epic required.

## Output

```text
Ticket flow complete: F0123
Target: staging
Landed: PR #456 -> staging
Status: to_verify_staging

Summary:
- planned, critiqued, built, tested, reviewed, and resolved findings
- local verification: PASS
- deploy: PASS via /auto-deploy staging
- behavior verification: not run

Next:
- /ticket-verify staging F0123
```

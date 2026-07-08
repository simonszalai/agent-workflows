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
- `../references/conductor-multi-repo.md` when the ticket is an epic step, cross-repo
  contract provider/consumer, or the repo is a linked Conductor directory

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
- If the ticket's `repo` does not match the current repo, switch only to an available linked
  Conductor directory for that repo after checking its git remote; otherwise stop and report the
  missing repo workspace. Do not implement a ticket for one repo inside another repo.
- If input is a ticket ID, load it via `get_ticket`.
- If input is an issue/conversation, search existing tickets first; create a new ticket only
  when no matching non-terminal ticket exists.
- Detect epic-step context from explicit epic membership, `related`, `tags.related_epic`, or
  source text. If found, load `get_epic` and the step's milestone/contracts.
- Decide and record the delivery target using `landing-policy.md`: staging-first for
  complex/risky/uncertain standalone work, direct-production only for tiny safe standalone work.

### 1. Gather context

- **Knowledge retrieval gate (hard gate, especially for Codex/Grok).** Before planning or
  editing, run `mcp__autodev-memory__search` for the ticket's actual risk boundaries, not just
  `search_tickets` / `get_similar_tickets`. Use terms from the source artifact, error, touched
  subsystem, integration boundary, and likely deployment path (examples: schema/defaults/raw SQL,
  decrypt-proxy/tailnet/auth, Prefect deployment/runtime, encryption/plaintext fields, external
  API contracts). Read the returned entries and carry applicable rules into the plan. If no entry
  is relevant, state that in the plan/build note. A Codex run that only loads tickets or similar
  tickets has **not** satisfied the Knowledge Menu rule.
- Feature/refactor: run codebase research and similar-ticket search.
- Bug: investigate root cause first; for production incidents use hypothesis evaluation.
- Epic step: include the parent epic plan, milestone acceptance criteria, blockers, contracts,
  and the repo/path/branch mapping from `conductor-multi-repo.md` in the context passed to
  planning/build agents.

### 2. Plan and criticize

- Run `/auto-plan` (the single planning skill) with its complexity-based light/heavy gate
  for standalone tickets.
- Force deep planning when the ticket is an epic step, cross-repo contract consumer/provider,
  schema/data change, or otherwise high risk.
- Heavy path only: run adversarial plan critique until no critical unresolved findings
  remain. The light path skips the critic panel and relies on single-round cross-provider
  convergence.
- Store the final plan as an MCP `plan` artifact.
- Set `summary_bullets` on the ticket (compact what/why/approach) so the dashboard header is not blank.
- There is no `approved` status; leaving `planned` means setting `in_progress`.
- **Honor dashboard review comments.** Before moving to build, check `open_comment_count` from
  `get_ticket` (also surfaced per-artifact). If the user left open review comments on the plan/source,
  fetch them with `list_artifact_comments`, revise the plan via `update_artifact`, and close each with
  `resolve_artifact_comment` (or `reply_artifact_comment` if out of scope). Do not build past
  unresolved feedback.

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

**Persistence gate (before landing).** Confirm via `get_ticket` that this step now carries its
`build_todo` artifacts and the `review_todo` artifacts the cross-review wrote — building and
reviewing in-session is **not** enough; those artifacts are the durable, auditable record and must
be on the ticket. If a `create_artifact` call silently no-op'd (common on cross-provider/Codex MCP
paths), re-issue it now. A step must not land or merge with only a `source` artifact — that leaves
it unauditable and makes later `/retrospect` / `/autodev-wtf` misread it as "no workflow ran".

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

For standalone tickets, if auto-deploy is unavailable, explicitly disabled, or blocked by a manual
deploy dependency, stop and report the blocker. Do not silently downgrade a deploy-required
standalone ticket-flow run to a land-only result unless the user explicitly approves that fallback.

Epic step: land/merge the step into the milestone integration branch and set the step to
`merged`. A milestone may contain multiple steps whose runtime surfaces must be deployed
**together**, so the deploy + cross-step gate is a **milestone-level operation owned by
`/milestone-flow`**, never a per-step one. ticket-flow does not deploy a single step's runtime
surface in isolation (that could expose a half-built milestone) and does not run the milestone
gate itself.

The deploy must still happen, though — a direct `/ticket-flow` run on an epic step must **not**
dead-end at `merged` with the milestone left undeployed:

- **Delegated run** (invoked by `/milestone-flow` with `--epic-context`): land + set `merged` and
  stop. `/milestone-flow` owns the whole-milestone deploy + gate once every step is merged.
- **Direct run** (a human runs `/ticket-flow <step>` itself, no `--epic-context`): land + set
  `merged`, then **continue into the deploy instead of stopping**. If this landing makes the
  milestone complete (every sibling step ticket in the milestone is now `merged`), invoke
  `/milestone-flow <EPIC_ID> <MILESTONE>` — which deploys the milestone to staging and runs the
  gate — so the `/ticket-flow` run includes the deploy. If sibling steps are still open, do
  **not** deploy a partial milestone: stop at `merged` and report that `/milestone-flow` will
  deploy + verify once the remaining steps land.

Epic-specific invariants (hold on both paths):

- the target is the milestone/integration branch (usually `staging`), never a solo production
  landing — production promotion of epic steps is owned by `/epic-flow` /
  `/ticket-promote --epic` after all milestone gates pass;
- the runtime deploy steps that produce milestone evidence (`prefect deploy`, scheduler/worker
  registration, canary/observer runs, DAG syncs, runtime blocks) and the cross-step gate
  (`/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote`) run **inside
  `/milestone-flow`**, whether it was reached via `/epic-flow` or via the direct-run hand-off
  above. ticket-flow never runs them directly.

A `merged` epic step alone is not proof the milestone is deployed or verified; only the
`/milestone-flow` gate PASS proves that. The direct-run hand-off exists so a human who runs
`/ticket-flow` on a milestone's final step still gets the deploy + gate, instead of a silently
undeployed `merged` step.

### 6. Status update

After successful landing/deployment, trust the owning workflow's status update:

| Ticket kind | Target | Status |
|---|---|---|
| Standalone | `production`/`main` via `/auto-deploy` | `to_verify_prod` |
| Standalone | `staging` via `/auto-deploy` | `to_verify_staging` |
| Epic step | milestone integration branch | `merged` |

For epic steps, `merged` means the step is landed on the integration branch and ready for the
parent milestone deploy+verify gate. Do not run that milestone gate from ticket-flow;
`/milestone-flow` invokes `/auto-deploy <EPIC_ID> staging` and
`/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote` once the whole
milestone has landed. A standalone `/ticket-verify` of the step does not substitute for the
authoritative milestone gate and may have no runtime evidence before milestone-flow deploys.

When a **direct** `/ticket-flow` run completes the milestone and hands off to `/milestone-flow`
(§5), the milestone deploy + gate run inside that same invocation and statuses advance per
`/milestone-flow` (gate PASS → steps `staging_verified`); ticket-flow does not set those itself.
The step still passes through `merged` first.

If auto-deploy reports an external/manual deploy dependency (for example a Thomas-only
`ts-decrypt-proxy` production deploy), the ticket status should still reflect the next verification
state (`to_verify_prod` for production) and the blocker should be captured in the ticket's
independent blocker metadata, not as a lifecycle status.

The staging verification statuses (`to_verify_staging`, `verify_staging_failed`) exist on the
ticket lifecycle enum as of migration 025, so a standalone staging landing advances the ticket
to `to_verify_staging` directly — no epic required.

## Output

**Evidence rules (apply to every variant below):** each PASS/complete line must be traceable
to concrete evidence — the command run, test counts, PR link, deploy output, artifact id.
End every report with an explicit "Not verified:" line listing anything claimed but not
exercised in this run (behavior verification is always listed there for standalone tickets,
since ticket-flow never runs it). The user must never have to ask "did you actually do X?" —
if X lacks evidence, the report says so first.

Standalone ticket:

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
- screenshots: {absolute paths to actual-browser screenshots, required if work is UI/visual; otherwise "not applicable"}

Next:
- /ticket-verify staging F0123
```

Epic step, **direct run that completes the milestone** — ticket-flow lands the step, then hands
off to `/milestone-flow`, which deploys + runs the gate, so the run includes the deploy:

```text
Ticket flow complete: F0178 (epic step of E0014/M2 — final step)
Target: staging integration branch
Landed: PR #430 -> staging  (step set to merged)
Milestone: E0014/M2 now fully merged -> handed off to /milestone-flow

/milestone-flow E0014 M2:
- deployed milestone to staging via /auto-deploy (prefect deploy + migrations/blocks/DAG)
- staging milestone gate: {PASS|FAIL|NEEDS_MORE_TIME|BLOCKED}

Summary:
- planned, critiqued, built, tested, reviewed, resolved findings; local verification: PASS
- step landed (merged) + milestone deployed + gate run via /milestone-flow

Next:
- {gate PASS} /epic-flow E0014 to continue remaining milestones / production promotion
- {gate not PASS} address the gate findings, then re-run /milestone-flow E0014 M2
```

Epic step, **partial milestone or delegated run** (`--epic-context`, or sibling steps still open)
— land only; do not deploy a half-built milestone. Make the incompleteness loud so `merged` is
not mistaken for "shipped":

```text
Ticket flow complete: F0181 (epic step of E0020/M1)
Target: staging integration branch
Landed: PR #999 -> staging
Status: merged
Milestone: E0020/M1 has 2 of 3 steps merged — NOT deployed yet

Summary:
- local verification: PASS; landed to staging integration branch: PASS
- milestone DEPLOY + gate: NOT run — owned by /milestone-flow, runs once all M1 steps are merged

Next:
- land the remaining M1 step(s); /milestone-flow E0020 M1 then deploys + verifies the milestone
- a standalone /ticket-verify of this step returns BLOCKED until the milestone is deployed
```

---
name: auto-plan-fable
description: Fable-variant autonomous planning. Same lifecycle contract as /auto-plan (research, cross-provider planning, plan + DRAFT deployment guide, status planned), with a Fable planner and a higher bar for the heavy path. Re-run on a planned ticket to resolve dashboard review comments.
max_turns: 100
memory:
  tags:
    - architecture
    - tradeoff
    - constraint
    - $tech_tags
  types:
    - architecture
    - pattern
    - preference
---

# Auto-Plan (Fable variant)

The planning entry point of the `-fable` workflow chain (style:
`skills/references/fable-prompting.md`). Behaviorally equivalent to `/auto-plan` — same ticket
lifecycle, same artifact contracts, same cross-provider requirement — but the native planner is
`planner-fable` (Fable 5, effort high) and the complexity gate leans on Fable's first-shot
strength: the light path is the norm, the heavy fanout the exception.

Methodology standards live in `../auto-plan/references/plan-methodology.md`; the output
template is `../auto-plan/templates/plan.md`. Both are shared with the base skill — do not
fork them.

When you have enough information to act, act. Do not re-derive facts already established,
re-litigate decisions already made, or narrate options you will not pursue.

## Usage

```
/auto-plan-fable F0009                    # Plan existing backlog/up_next ticket
/auto-plan-fable B0003                    # Bug ticket (includes investigation)
/auto-plan-fable #123                     # Find or create ticket from GitHub issue
/auto-plan-fable                          # Create ticket from conversation context
/auto-plan-fable F0009 --deep | --light   # Force heavy/light path
/auto-plan-fable F0009 --solo             # Emergency opt-out: skip peer providers AND
                                          #   convergence (only when the adapter is broken)
/auto-plan-fable F0009                    # On a planned ticket: revise mode — address the
                                          #   user's open dashboard review comments
```

## Context resolution

Project from `<!-- mem:project=X -->` in CLAUDE.md; repo from
`basename -s .git $(git config --get remote.origin.url)`. Both required for every MCP call.
Pass `command="/auto-plan-fable"` on every ticket/artifact mutation.

## Ticket resolution (contract)

**Ticket ID input:** `get_ticket`. Not found → STOP. Status `backlog`/`up_next` → fresh plan.
Status `planned` with `open_comment_count > 0` → **revise mode** (leave status as `planned`,
revise the existing plan — see Persist below). Anything else → STOP, "Ticket status is
{status}, nothing to plan".

**Issue/conversation input:** `search_tickets` first. Match with status `backlog`/`up_next` →
use it; match in another status → STOP, report the existing ID. No match → `create_ticket`
(`status="backlog"`, tags for `github_issue`/`source` as applicable).

**Record `STARTING_STATUS`** (`backlog`, `up_next`, or `planned`). Every failure path reverts
to it — never unconditionally to `backlog`.

**First user-visible output line, before anything else:**

```
{ticket_id}: {title}
```

Then set `status="in_progress"` (skip in revise mode).

## Gather context

- Features: spawn `researcher` for codebase patterns and integration points.
- Bugs: read the investigation artifact; if none exists, run `/investigate` to establish root
  causes (spawn `hypothesis-evaluator` for production incidents) and persist the
  `investigation` artifact first. Design against root causes, not symptoms.
- **Prior-knowledge blob:** the fanout workflow's subagents get no knowledge-menu injection,
  so gather it here once and pass it everywhere: `mcp__autodev-memory__search` on the
  feature/bug area and its technologies, `get_similar_tickets(status="completed")`,
  `search_tickets`. Render hits into a compact markdown blob (`## Related memories`,
  `## Related past work`); pass the same blob to every provider planner and as
  `args.priorKnowledge` on the heavy path. Pass `null` when nothing relevant turns up —
  never fabricate entries.

## Complexity gate

The work, not the words: prompt/source length is not a signal. The Fable planner at high
effort handles ambiguity and pattern-free design well, so heavy is reserved for genuinely
wide solution spaces or high-blast-radius work. Top-to-bottom, first match wins:

| Condition | Path |
| --- | --- |
| `--deep` | Heavy |
| `--light` | Light |
| New system/app built from scratch | Heavy |
| Multi-component or cross-repo work | Heavy |
| Schema change or data migration involved | Heavy |
| Ticket is an epic step | Heavy |
| High blast radius (shared infra, auth, billing, data pipelines) | Heavy |
| Conflicting or ambiguous requirements | Heavy |
| Otherwise | Light |

Announce the path with a one-line reason (`Plan path: light (bug fix, investigation in
place) — inline planner-fable`).

## Cross-provider planning and convergence (both paths — non-negotiable)

A plan artifact is not valid until **all three providers** (claude/codex/grok) contributed
independent planning judgment and material disagreements were driven to evidence-backed
convergence. Determine the runner with `agent-workflow-provider`; the other two are peers.
Actually run them — never summarize what a provider "would" say:

- **Claude Code runner:** spawn two `external-planner` subagents in the same parallel `Agent`
  batch as the native planner; each calls `external-agent --task plan` for one peer and
  returns the planner envelope (`{planner_key, plan{…}, assumptions, disagreements, evidence,
  open_questions, notes}`). Include the bounded memory-packet path; the adapter call passes it
  via `--memory-context-file`.
- **Codex/Grok runner:** call `external-agent --task plan` directly for both peers with one
  explicit <=3K `--memory-context-file` (Claude peer via subscription-backed `claude -p`,
  never a direct API call). Write inputs to
  `.context/plan/` (question, source, codebase research, prior knowledge) and pass them as
  files, `--out .context/plan/<provider>.json`.

A failed provider contributes an empty envelope with a note — surface it, don't block. But if
fewer than **two** providers return usable plans, STOP, revert to `STARTING_STATUS`, and
report the provider failure rather than accepting a one-provider plan.

**Convergence rule:** iterate on disagreements until every material factual/architectural
disagreement is (1) resolved by evidence from code/artifacts/memory/environment facts,
(2) converted into an `open_questions` item that blocks build planning, or (3) rejected as
preference/YAGNI with a recorded reason. Completeness claims beat YAGNI only with concrete
evidence. Round budget: light path exactly 1 round; heavy path ≤3 (owned by the workflow).

### Light path

Spawn ONE `planner-fable` agent with all inputs (source, research/investigation, prior
knowledge) in the same parallel batch as the two peer planners. Validate the returned plan
covers the template's required sections (`title, what, why, how, tradeoffs,
alternatives_considered, risks, verification_strategy, side_effects, elimination,
open_questions, assumptions`) — re-prompt with the template rather than accepting a partial
plan. Synthesize native + peer plans, run one convergence round, and assemble the same result
shape as the heavy path with critic-only fields zero-filled (`critic_findings: []`,
`critics_succeeded: 0`, `total_findings: 0`, …). Downstream persistence must not branch on
path.

### Heavy path

Invoke the shared `plan-fanout` workflow by name (resolved via `~/.claude/workflows/`) with
`{question, sourceArtifact, codebaseResearch, priorKnowledge, providerDrafts, framings,
repoRoot, mode}` — peer envelopes go in as `providerDrafts`. Its internal drafter/critic
stages are tuned for the base system; that is fine — the converged output shape is identical.
If the host tool has no `Workflow` primitive, run the equivalent loop inline (multiple
framings, completeness/correctness/YAGNI critics, bounded revision) — do not silently skip
critics or convergence.

If the returned plan has `open_questions` answerable by codebase research or production
state, satisfy them (spawn `researcher`/investigators) and re-run the path with the new
findings — for the heavy path, satisfy them BEFORE re-running (the workflow is not cheap and
not idempotent).

## Persist (orchestrator writes; the planner never persists)

Render the converged plan per `../auto-plan/templates/plan.md` — concise, leading with
what/how/why — and:

```
mcp__autodev-memory__create_artifact(project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="plan", content=<plan markdown>, command="/auto-plan-fable")
```

**Revise mode instead:** fetch open threads via `list_artifact_comments(status="open")`
(they sit on `source`/`plan` artifacts; `selected_text`/`anchor` locate each), revise the
existing plan to address every thread, persist with `update_artifact` (snapshots the prior
version — never `create_artifact`), then `resolve_artifact_comment` each addressed thread
with a one-line note pointing at what changed. If a comment is out of scope or wrong, reply
via `reply_artifact_comment` and leave it open for the user.

## DRAFT deployment guide (mandatory — do not skip, even for one-line fixes)

Create a `deployment_guide` artifact (Status: DRAFT, template from the
`create-deployment-guide` skill). The architecture already determines the *shape* of deploy
and verification; exact commands come later at build time (`/create-build-todos-fable`
finalizes it; `/ticket-verify` grades against it). Capture:

- **Deploy shape:** repos/components touched and in what order (and which contract forces
  it); migration or not; scheduler/worker/service deploys; secrets/env vars; how code reaches
  runtime. Name the project's *real* deploy primitives (from project CLAUDE.md/AGENTS.md +
  a memory search) — never generic placeholders; mark unknowns `TBD — finalize at build`.
  If a DB migration is involved, name the **migration lane**: schema-first
  backward-compatible PR off current `main` with immediate `main→staging` sync, full
  `staging→main` parity merge, or "no migration". Ordinary selective cherry-pick promotion is
  never the plan for migration-bearing work (emergency exception only).
- **Verification Evidence contract, per environment (staging AND production):** what evidence
  proves this works including edge cases — each item a reproducible read-only query/command
  with expected good output and bad-output interpretation — plus the **activation boundary**
  (how to know the new code is live). Polling/observer/storage features additionally get
  write-rate evidence: expected rows/day and bytes/day, dedupe/change-gating behavior on
  identical polls, retention/TTL for raw or append-only data.

## Finish

Set `status="planned"` with `summary_bullets` (3–6 compact bullets: what / why / approach /
key risk — the dashboard header renders these; `update_ticket` replaces the whole list, so
always pass the full set, including in revise mode).

Output on success:

```
{ticket_id}: {title}

Auto-plan complete for {ticket_id}: {title}

Plan path: {light|heavy} — {one-line reason}
Plan artifact created. Review and approve to proceed to build.

Status: planned (waiting for approval)

Next: Review the plan, then approve and run /ticket-flow-fable {ticket_id}
```

On any failure: report the phase and reason, and revert status to `STARTING_STATUS` via
`update_ticket`. Hard stops: ticket not found; not plannable (wrong status / already
tracked); fewer than two usable provider plans; native planner failure. A research-agent
failure is soft — log it and plan with less context.

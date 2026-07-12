---
name: epic-split
description: >-
  Idempotently reconcile an approved epic plan into milestone-assigned step tickets with
  dependency edges and cross-repo contracts. Turns an epic's pile of iterative design artifacts
  into an ordered, cross-repo set of execution-step tickets: consolidates
  redundant/contradictory design notes into one plan, sequences the work into a DAG, creates one
  step ticket per repo, and defines the cross-repo contracts. Use when an epic has design
  artifacts (and/or absorbed sources) but no clean steps yet, or when its steps need to be
  (re)derived.
user_invocable: true
max_turns: 150
---

# Epic Split

An epic in autodev-memory is **the ordered, cross-repo execution plan for one coherent feature
within a single project** (1–3 repos; it carries the staging gate). It relates to tickets two
ways:

- **Sources** — *existing* tickets absorbed into the epic (parked in `absorbed_into_epic`,
  hidden from the board, never deploy). They *motivate* the epic.
- **Steps** — *new* tickets that break the work into ordered execution units. Each step lives
  in **exactly one repo**. Ordering is a blocker→blocked DAG.

Alongside those, an epic accumulates **artifacts**: design specs, sequencing notes, scope
amendments, decision logs. These are written *iteratively over many sessions*, so they are
redundant, overlapping, and sometimes contradictory (a later "extends X" / "supersedes Y" /
"added scope" note silently amends an earlier spec).

**This skill's job:** consolidate that iterative design material into one clean plan, sequence
it, and idempotently reconcile the steps — one per repo, ordered, with cross-repo contracts
spelled out — **including a ticket-level `plan` artifact for every non-completed step ticket**.
It does **not** invent product scope; it crystallises what the artifacts already decided and
surfaces genuine gaps to the user rather than guessing.

Default reruns are **idempotent**: reuse and update matching existing step tickets rather than
creating duplicates, and update the existing epic `plan` artifact rather than duplicating it.
Treat the current plan/steps as the baseline unless the user explicitly asks for a from-scratch
rederive.

## Boundaries

- Does not build, land, deploy, or verify.
- Creates/updates step tickets only after the epic plan is sufficiently settled.
- Source tickets remain parked as `absorbed_into_epic`.
- Does not detach, abandon, or delete stale existing steps unless explicitly requested via a
  from-scratch/rederive cleanup instruction. By default, reports stale steps as proposed removals.

## Usage

```text
/epic-split E0007
/epic-split E0007 --reconcile
/epic-split E0007 --milestone M3
/epic-split E0007 --rederive
/epic-split E0007 --from-scratch
```

## Step identity: `E000N-k`

A step's canonical reference is **`{EPIC_ID}-{execution-order index}`** — `E0007-1`, `E0007-2`,
… The index is the step's position in the epic's ordered walk (the per-epic planning board
renders steps as a waterfall numbered `1, 2, 3…` down the rows). This label is *positional*,
not a stored ID: the underlying ticket keeps its repo-scoped ID (`F0112`, `B0007`, …). Always
present steps as **`E0007-1 → F0112 (ts-prefect)`** so both the order and the real ticket are
visible. Re-deriving steps can renumber them; the ticket IDs are the stable handle.

## When to use

- An epic has design artifacts and/or absorbed sources but **no steps**, or only a rough draft.
- Steps exist but the design has moved on (new "added scope" / "supersedes" artifacts) and they
  need reconciling.

If the epic doesn't exist yet, create it first (`create_epic`) and absorb its motivating tickets
(`absorb_ticket_into_epic`) — that is upstream of this skill.

## Inputs

- `project` — resolve from `<!-- mem:project=X -->` in the repo's CLAUDE.md, or ask.
- `epic_id` — e.g. `E0007` (display id) or uuid.

---

## References

Read before planning or reconciling cross-repo steps:

- `../references/conductor-multi-repo.md`

## Phase 0 — Load everything

```
get_epic(project, epic_id)        # sources, existing steps, artifacts, involved_repos, warnings
list_repos(project)               # canonical repo set; resolve paths via Conductor linked dirs/workspaces
get_ticket(project, id, repo, detail="full", artifact_types=["source"], include_events=false)
                                      # full body of each absorbed SOURCE ticket only
```

`get_epic` is often large (tens of KB) and gets spilled to a file — read it with `jq` /
offsets, don't try to swallow it whole. Pull, at minimum:

- `.artifacts[]` — `id`, `title`, `created_at`, full `content` (the design material to consolidate)
- `.sources[]` — absorbed tickets (then `get_ticket` each for its source artifact)
- `.milestones[]` — milestone checkpoints (`id`, `position`, visible `M1`/`M2`/`M3` label,
  title, acceptance criteria, gate flag)
- `.steps[]` — any existing steps (`ticket_id`, `repo`, `uuid`, position, `milestone_id`)
- `.step_deps[]` — existing ordering edges (uuid blocker→blocked)
- `.involved_repos`, `.warnings`

Read **all** of it. The whole point is that no single artifact is the truth.

Resolve every involved repo to a real workspace path using `conductor-multi-repo.md`. Do not
assume `~/dev/{repo}`. If a planned step needs a repo that is not present, still create/reconcile
the repo-specific step ticket and record the missing workspace as an execution blocker; do not fold
that work into another repo's step.

If the user asked to break source/design material into a specific milestone (for example
"M3 steps"), resolve that milestone from `.milestones[]` before creating tickets. If the named
milestone **does not exist yet** but the consolidated plan makes its scope and gate-status clear,
create it with `create_epic_milestone` (see Phase 4) rather than blocking — milestone creation is
part of this workflow, not a human prerequisite. Only stop and ask if the milestone the user named
is genuinely ambiguous (e.g. two plausible checkpoints and the plan doesn't disambiguate).

## Phase 1 — Consolidate the design (the hard part)

The artifacts are an iterative pile. Reduce them to **one** coherent design:

1. **Order by `created_at`.** The timeline is the amendment order.
2. **Apply amendments.** Notes that say *extends / supersedes / added scope / retire / merge*
   rewrite earlier specs. Carry the **latest** statement forward; mark what it replaced.
3. **Deduplicate.** Multiple artifacts restating the same requirement → one requirement.
4. **Resolve contradictions by recency + confirmation.** A later **confirmed** decision
   (dated, attributed — "confirmed 2026-06-06, Simon") beats an earlier draft. If two
   statements genuinely conflict and neither is clearly later/confirmed, **do not pick** —
   list it as an open question for the user.
5. **Separate locked from open.** Pull out: the goal; the **gated first deliverable** (many
   epics name one — "gate everything else on it"); confirmed decisions; and open questions.

**Write the result back as the canonical `plan` artifact on the epic** so there is a single
source of truth going forward (the iterative source artifacts stay for provenance — don't delete
them). This write is **update-if-exists**:

- if a live/current epic `plan` artifact already exists (including one written by `/epic-plan`
  or a previous `/epic-split` run), update it via `update_artifact(...)` with a change note —
  never create a duplicate plan artifact on rerun;
- only when the epic has no live `plan` artifact, create one:

```
create_epic_artifact(project, epic_id, artifact_type="plan",
  title="Consolidated execution plan (YYYY-MM-DD)",
  content="<goal · gated first deliverable · locked decisions · the ordered steps · open questions>")
```

If consolidation surfaces real contradictions or missing decisions, **stop and ask the user**
before creating tickets — steps built on a guessed decision are worse than no steps.

## Phase 2 — Sequence into desired steps

Decompose the consolidated plan into the **minimal** set of ordered execution units:

- **One step = one coherent, independently-deployable unit in exactly one repo.** If a unit
  needs work in two repos, **split it per repo** and connect the halves with a cross-repo
  contract edge (Phase 3). A step never spans repos. If the user later identifies another required
  repo, add/reconcile another step for that repo rather than expanding an existing repo's ticket.
- **Honour the gate.** If the plan names a first deliverable everything depends on, make it the
  root of the DAG (`E000N-1`).
- **DB/schema-owning changes go in the repo that owns those migrations.** Whoever creates the
  column/table is the blocker; consumers in other repos depend on it. (In `autodev`, DDL is
  owned by autodev-memory's Alembic migrations — never originate scalar columns in a Prisma
  client repo.)
- Build the **blocker→blocked DAG**. Cycles are rejected by the tool; keep it acyclic. The
  execution-order index (`E000N-k`) is a topological position in this DAG.
- Run the **runtime evidence closure** check before creating tickets: if a milestone's
  acceptance criteria require runtime/staging evidence (canary run, observer, flow, deployment,
  stored rows, polling, scheduler, worker, Prefect, supervisor, webhook, live readback), the
  same milestone's desired step set must include the code/config/command that will produce that
  evidence. Do not leave a gate requiring stored rows or a flow run while splitting only
  schema/parser/model tickets and deferring the runtime surface to a later milestone.

Before creating anything, compare the desired step set against existing `.steps[]` from
`get_epic`:

- Match existing steps by repo, milestone, title/intent, source artifact content, and cross-repo
  contract.
- Reuse the ticket ID for a still-valid step even if its position or milestone assignment changed.
- Update backlog/planned matching tickets whose scope, milestone, summary, contract, or
  ticket-level plan changed.
- Do not duplicate a step intent that already exists in the epic.
- Never rewrite merged/completed steps; create a follow-up step if the new plan requires more work.

## Phase 3 — Define cross-repo contracts

For **every dependency edge whose endpoints are in different repos**, the blocker (shipped
first) exposes an interface the blocked ticket consumes — that handoff is a **contract** and
must be written explicitly. Name the concrete surface: table/column, endpoint + payload shape,
field, function signature, env/config key. Put it in **both** tickets:

- Blocker: *"Exposes: `companies.market_etf_symbol` / `sector_etf_symbol` (resolver + populate)."*
- Blocked: *"Reads: `companies.market_etf_symbol` / `sector_etf_symbol`; snapshots them onto …"*

Same-repo edges only order the waterfall — they don't need a contract. The dashboard derives
the cross-repo contract list automatically from the cross-repo edges, so getting the **repo
assignment** and the **edges** right is what makes contracts appear.

## Phase 4 — Reconcile/create the steps

Before creating tickets, decide the milestone for each step:

- If the user named a milestone (`M3`, "milestone 3", "the M3 checkpoint"), assign every
  newly-created step in this breakout to that milestone unless the consolidated plan clearly
  says otherwise.
- If the epic already has milestones and a step naturally belongs under one, assign it.
- If the milestone the steps belong to **does not exist yet** (a fresh epic, or the plan defines
  a checkpoint the epic has no row for), create it — don't leave the steps unassigned by default:
  ```
  create_epic_milestone(
    project, epic_id="E000N",
    title="M3 — <gated deliverable>",   # the visible M-label comes from position
    position=k,                          # 1-based order among milestones
    acceptance_criteria="<what proves this checkpoint is done / deployable>",
    is_gate=True,                        # True for a deployable gate; False for a soft grouping
    command="/epic-split"
  )
  ```
  Then re-`get_epic` to pick up the new milestone's UUID before assigning steps to it.
- If an existing milestone row has stale `acceptance_criteria`, update it from the canonical
  plan before assigning steps. Do not create criteria-free gates.
- Only leave a step unassigned when the plan genuinely defines no checkpoint for it — and say so
  in the report.

For each desired step, in DAG order:

- If it matches an existing step, update/reassign it as needed and preserve its ticket ID.
- If it does not match any existing step, create it.

Create only missing tickets:

```
create_ticket(
  project, repo,                       # the ONE repo this step lands in
  title="Concrete, scoped deliverable",
  type="feature" | "bug" | "refactor",
  description="<step body — see references/step-template.md>",
  epic_id="E000N",                     # adds the new ticket to the epic AS A STEP
  milestone_id="M3",                   # REQUIRED when breaking work out under a named milestone
  depends_on=["F0112", ...],           # blocker ticket IDs (same project)
  related=["E000N"],
  tags={"area": "...", "related_epic": "E000N"},
  size="xs|s|m|l|xl",
  summary_bullets=["<what this step delivers>", "<why / dependency>", "<approach>"],
  status="backlog",                   # temporary until the ticket-level plan is written below
  command="/epic-split", agent="planner"
)
```

The `description` becomes the step's source artifact and must follow the step body structure
in `references/step-template.md` (Scope / Context / Requirements Rn / Reuse / Decisions /
Cross-repo contract / Out-of-scope / Related).

Then pin **order** and the **DAG**:

```
# Explicit execution-order position (k = the index in E000N-k). Idempotent.
add_epic_step(project, epic_id, ticket_id, repo, position=k, milestone_id="M3")

# The blocker→blocked DAG, by step UUID (get them from a fresh get_epic).
set_epic_member_deps(project, epic_id, edges=[{"blocker": <uuid>, "blocked": <uuid>}, ...])
```

Keep the two dependency representations in sync: ticket-level `depends_on` (display ids) and
epic-level `epic_member_deps` (uuids) must describe the **same** edges.

For every desired non-completed step ticket (new or reused), also create or update its own
ticket-level `plan` artifact. This is required; a step with only a `source` artifact is not fully
planned.

```
create_artifact(
  project, repo, ticket_id,
  artifact_type="plan",
  title="Plan: <step title>",
  content="<repo-local implementation plan>",
  command="/epic-split", agent="planner"
)

update_ticket(
  project, ticket_id, repo,
  status="planned",
  summary_bullets=["<what this step delivers>", "<why / dependency>", "<approach>"],
  reason="Ticket-level plan created for epic step",
  command="/epic-split", agent="planner"
)
```

If a live/current `plan` artifact already exists, update it with `update_artifact(...)` and a
change note instead of creating a duplicate, then still call `update_ticket(..., status="planned",
summary_bullets=[...])` so the status matches the now-current plan. The per-ticket plan must be
scoped to the one step and include:

- step goal and non-goals;
- implementation approach and ordered build phases;
- likely files/modules/config/migrations touched;
- cross-repo contracts consumed/exposed;
- test and verification plan;
- acceptance evidence expected at completion;
- rollback/kill-switch/deploy notes.

Do not copy the epic plan verbatim. Do not rewrite plans on merged/completed steps; create a
follow-up step if new work is needed after completion.

Milestone assignment is part of step creation, not a later nice-to-have. If the milestone does
not exist yet, **create it first** with `create_epic_milestone` (above). If the active MCP schema
for `create_ticket` does not expose `milestone_id`, still call `add_epic_step` with `milestone_id`
after the ticket is created. If `add_epic_step` cannot assign it, use
`assign_epic_step_milestone(project, epic_id, ticket_id, repo, milestone_id="M3")`. Do not
finish a named-milestone breakout with `milestone_id: null`; create the milestone or, only if it is
truly ambiguous, stop and report the blocker.

> Re-deriving an epic? Default to **reconcile**, not delete/recreate. Leave stale steps attached
> and report them as proposed removals unless the user explicitly asked for from-scratch cleanup.
> Only then detach stale steps with `remove_epic_step` (this leaves the ticket itself intact —
> `update_ticket(epic_id="")` fully detaches), clear/replace their edges, then recreate missing
> desired steps. Don't orphan edges pointing at removed steps.

## Phase 5 — Verify & report

Re-run `get_epic` and confirm:

- Steps appear in the intended order; `involved_repos` matches your repo assignment.
- Every desired non-completed step ticket has a current `plan` artifact, not only a `source`
  artifact, and its ticket status is `planned`.
- Every step created for a named milestone has `.steps[].milestone_id` matching that
  milestone's UUID from `.milestones[]`.
- `step_deps` form an acyclic graph; every cross-repo edge has a contract written in both tickets.
- Every gate milestone has concrete `acceptance_criteria`.
- Every gate milestone with runtime evidence criteria has at least one same-milestone step
  whose plan explicitly owns the producing runtime surface (Prefect YAML/flow, supervisor/worker
  registration, deploy-owned canary CLI, or disposable integration-DB evidence if the gate was
  deliberately scoped away from staging runtime rows).
- Every repo named by a desired step is either available as a workspace/linked directory or
  explicitly reported as a missing workspace blocker.
- No duplicate step tickets exist for the same step intent.
- `warnings` is empty.

Then report to the user as a table — execution order, milestone, the real ticket, its repo,
per-ticket plan artifact id and ticket status, blockers — plus the cross-repo contracts:

```
E0007-1  M1  F0112  ts-prefect   plan:abc123 planned  (no blockers)   exposes: companies.{market,sector}_etf_symbol
E0007-2  M1  F0111  ts-prefect   plan:def456 planned  ← F0112          reads:   companies.{market,sector}_etf_symbol
```

## Worked reference — E0007

E0007 ("Re-ground impact scoring on realized market outcomes") is the canonical example: 13
iterative design artifacts (design spec → sequencing → "added scope: merge dissemination" →
"freshness as two-stage signal" → …) consolidated into two ordered steps —
**`E0007-1` = F0112** (persist benchmark ETF symbols on `companies`) → **`E0007-2`** = F0111
(realized abnormal-return outcome, which **reads** those columns). The split exists *because*
F0111 was too big and its benchmark-resolver half was carved out into F0112 with a column-level
contract between them. Read F0111's source artifact for the gold-standard step body.

## Guardrails

- **Don't invent scope.** Consolidate what the artifacts decided; escalate genuine gaps.
- **One repo per step.** Cross-repo work = two steps + a contract.
- **Sources ≠ steps.** Never `add_epic_step` an existing motivating ticket — `absorb_ticket_into_epic`.
  Steps are *new* tickets.
- **Keep provenance.** Update the consolidated `plan` artifact in place; don't delete the
  iterative ones and don't create duplicates.
- **`E000N-k` is positional.** Reference steps by it, but always map to the real repo-scoped id.

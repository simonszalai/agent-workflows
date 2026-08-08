# Execution intensity

Shared policy for **ticketed** autonomous delivery (`/ticket-flow`, `/ticket-plan`,
`/ticket-build`, `/review`). Lifecycle ownership stays separate (epic / milestone / ticket /
phase). Intensity only chooses how much plan/build/review machinery runs.

Ticketless work is not this policy. Use `/go-fable` for ultra-light working-tree edits. There
is no `/lfg` path.

## Levels

| Level | Intent |
| --- | --- |
| `direct` | Fastest safe ticketed path for clear, low-blast-radius work |
| `standard` | Default auto path: light plan/review with trigger-based escalation |
| `heavy` | Risk-focused planner/build chain plus targeted specialist review |

Aliases for user flags: `--light` → `direct`, `--deep` → `heavy`. Prefer
`--intensity direct|standard|heavy` in new invocations.

## Packet fields (immutable once decided)

Every phase packet for a ticketed run must carry:

```text
intensity: direct | standard | heavy
intensity_reason: <one-line trigger or "user override" or "default auto">
intensity_floor: none | standard | heavy
```

- Decide **once** after source resolution and enough context to classify risk (epic membership,
  tags, source text, environment/capability route). Prefer deciding in `/ticket-flow` before
  `/ticket-plan`, or at the start of standalone `/ticket-plan` / `/ticket-build` when those run
  alone.
- **Escalate only, never silently downgrade** after plan or build starts. If the diff first
  crosses a hard floor (auth, secrets, destructive/irreversible migration, …), raise intensity
  for the remaining phases and record the new reason.
- User `--intensity` / `--deep` / `--light` wins unless a hard floor is higher.

## Decision gate (top-to-bottom, first match wins)

| Condition | Intensity |
| --- | --- |
| User passed `--intensity heavy` or `--deep` | `heavy` |
| User passed `--intensity standard` | `standard` (still raised by floors below) |
| User passed `--intensity direct` or `--light` | `direct` (still raised by floors below) |
| `intensity_floor` is `heavy` | `heavy` |
| Auth, secrets, billing, destructive/irreversible data migration, production incident, or a demonstrated high-blast-radius data-integrity risk | `heavy` |
| Novel cross-cutting architecture where a wrong choice is expensive to reverse AND material design questions are genuinely open | `heavy` |
| Multi-component or multi-subsystem work that follows established patterns | `standard` |
| Additive/reversible schema migration that follows an established repository pattern | `direct` when bounded to one subsystem, otherwise `standard`; add targeted data review, not the full heavy workflow |
| Bounded change following an existing pattern, or investigated bug fix with clear root cause, confined to one subsystem (roughly ≤5 files) | `direct` |
| Otherwise | `standard` |

Prompt length alone is never a signal. **Bias down, not up.** Size or file count alone never
selects `heavy` — only a named safety surface or genuinely open expensive-to-reverse design does.
"New code" is not "new system," and "has a migration" is not "destructive migration": adding a
feature that composes existing patterns is `standard`, and a pattern-following bounded change is
`direct` even when it is user-visible or includes an additive migration. Expected mix on a
mature repo: most tickets `direct`, a substantial minority `standard`, `heavy` rare. When the gate
is ambiguous between two levels, pick the lower one — escalation triggers mid-run raise it if
reality disagrees, and that one-way ratchet is cheaper than defaulting the machinery up front.

## Wall-clock design targets

Active-work targets per ticket (excluding genuine external waits: CI runs, deploy propagation,
soak windows):

| Intensity | Target | Interpretation |
| --- | --- | --- |
| `direct` | ~20 min | one delivery owner and one orchestrator health gate |
| `standard` | ~45 min | one delivery owner, one general reviewer, and one optional repair |
| `heavy` | ~60 min | one risk-focused plan, one build chain, targeted specialist review |

These are design targets, not mid-run stop gates: they exist so each phase's shape (fanout,
rounds, subagent depth) is chosen to finish inside them in **one generation per phase**. A run
that needs rotations or repair rounds may exceed the target; the bounded round/rotation caps in
the phase skills are the hard ceiling. A multi-hour single-ticket run means the shape was wrong,
not that the budget should grow.

## Role effort

Reserve the strongest model/effort for judgment-heavy roles: plan synthesis, architecture
critique, safety review, failure investigation. Mechanical roles — formatter/lint repair,
build-todo materialization from an approved plan, bounded verification execution, CI-wait
leaves, and bounded same-risk repairs — run on the cheaper tier at medium effort. Never spend
high/xhigh effort on a role whose output is deterministic or checklist-shaped.

### Floors

| Context | Floor |
| --- | --- |
| Standalone ticket | `none` (auto may pick `direct`) |
| Epic step (`--epic-context` or epic membership) | `none`; epic membership is sequencing, not risk |
| Explicit safety surface in source/plan/diff | `heavy` for remaining phases |

`/epic-flow` and `/milestone-flow` pass `intensity_floor: none` into ordinary child
`/ticket-flow` runs. They raise it only for a named safety surface. Milestone deploy/verify is
always full gate machinery and is not an intensity knob.

## No cumulative model-session stop gate

Do not count delegated sessions across phases or persist a run-budget ledger. Session count is an
observability signal, not a delivery stop condition: a completed build must never be prevented from
reaching review, landing, or verification merely because earlier work used several agents or
rotations. Control cost by selecting the smallest intensity, keeping fanout conditional, and using
the per-phase turn/elapsed/token/rotation contracts. Bounded repair-loop rules still prevent
no-progress retries, but there is no ticket- or epic-wide model-session allowance to exhaust.

## What each level runs

### Always (all levels)

- **Plan MCP artifact is mandatory.** The compact delivery owner persists it before editing;
  `heavy` and standalone planning use `/ticket-plan`. No ticketed path may build from
  conversation-only intent.
- Ticket status transitions owned by phase skills
- Orchestrator-owned health / validation (builders and reviewers never run health)
- Safety reviewers / heavy upgrade when a floor trigger appears mid-run
- Evidence-backed terminal reporting

### `direct`

| Phase | Behavior |
| --- | --- |
| Delivery | Exactly one compact delivery owner researches only what it needs, writes the short plan artifact before editing, creates minimal `build_todo` artifacts, implements, writes focused tests, and may run only focused tests. No separate planner, researcher, build-planner, builder chain, test writer, or reviewer. |
| Review | None. A discovered review/risk need escalates to `standard` or `heavy` before another role is dispatched. |
| Repair | At most one repair-owner reservation for one complete failure/finding batch; a fresh child is used only for non-mechanical work. No same-risk re-review. |
| Health | The parent runs one canonical full gate after delivery. If the repair changes the tree, it runs one final gate. |

### `standard` (default auto)

| Phase | Behavior |
| --- | --- |
| Delivery | The same single compact delivery owner as `direct`; minimal todos and focused tests stay in that session. `/create-build-todos` and `/write-tests` are not invoked. |
| Review | Exactly one independent native general reviewer after the first parent-owned health PASS. |
| Repair | At most one repair-owner reservation covers the complete health/review batch; a fresh child is used only for non-mechanical work. Same-risk repairs are not re-reviewed; a new risk boundary escalates to `heavy`. |
| Health | One gate after delivery; one final gate only when repair changed the tree. |

### `heavy`

| Phase | Behavior |
| --- | --- |
| Plan | One risk-focused native planner. Add one independent critic only when a named hard safety surface or unresolved expensive-to-reverse decision needs it; peers remain deadlock-only. |
| Build todos | Planner materializes concise risk/dependency-aware todos; no separate deep-research todo agent. |
| Build | One coherent builder chain by default; split once only when independent risk/subsystem ownership requires it. Tests stay in-chain. |
| Tests | Builder-owned focused tests plus the orchestrator health gate; no separate test-writer by default. |
| Review | One combined code/plan-conformance reviewer plus at most one merged specialist for the named safety surface. Peers remain deadlock-only. |
| Resolve | Up to 2 whole-batch repair cycles when actionable findings remain; no same-risk re-review. |
| Health | Pre-review + conditional final gate; no direct-style single-gate shortcut |

## Mapping to existing light/heavy gates

| Intensity | Plan path | Review path | Build-todo path |
| --- | --- | --- | --- |
| `direct` | compact delivery owner | none (upgrade on risk) | minimal todos in-chain |
| `standard` | compact delivery owner | one general reviewer | minimal todos in-chain |
| `heavy` | risk-focused planner (+ conditional critic) | combined reviewer (+ targeted specialist) | concise todos from the planner |

`--solo` still disables conditional peer providers only; it never removes native safety
personas or the plan-artifact requirement.

## Reporting

Every ticketed terminal report includes:

```text
Intensity: {direct|standard|heavy} ({reason}; floor={none|standard|heavy})
```

so retrospectives can audit under- and over-provisioning.

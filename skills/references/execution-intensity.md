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
| `heavy` | Full machinery: multi-framing plan, deep build-todos, specialist review |

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
  crosses a floor trigger (schema, auth, migration, …), raise intensity for the remaining
  phases and record the new reason.
- User `--intensity` / `--deep` / `--light` wins unless a hard floor is higher.

## Decision gate (top-to-bottom, first match wins)

| Condition | Intensity |
| --- | --- |
| User passed `--intensity heavy` or `--deep` | `heavy` |
| User passed `--intensity standard` | `standard` (still raised by floors below) |
| User passed `--intensity direct` or `--light` | `direct` (still raised by floors below) |
| Epic step ticket, or `intensity_floor` is `heavy` | at least `heavy` when floor is heavy; else at least `standard` |
| Schema/data migration, auth, secrets, billing, deploy-config, cross-repo contract, destructive data, production incident / data-integrity | `heavy` |
| Multi-component / new system / no established pattern / material open design questions | `heavy` |
| Bounded change following an existing pattern, or investigated bug fix with clear root cause | `standard` |
| Tiny single-area change, ≤~2 files expected, no risk surfaces above | `direct` |
| Otherwise | `standard` |

Prompt length alone is never a signal.

### Floors

| Context | Floor |
| --- | --- |
| Standalone ticket | `none` (auto may pick `direct`) |
| Epic step (`--epic-context` or epic membership) | `standard` |
| Explicit safety surface in source/plan/diff | `heavy` for remaining phases |

`/epic-flow` and `/milestone-flow` do not pick intensity for the epic. They pass
`intensity_floor: standard` (or higher when the step plan names a safety surface) into each
child `/ticket-flow`. Milestone deploy/verify is always full gate machinery and is not an
intensity knob.

## What each level runs

### Always (all levels)

- **Plan MCP artifact is mandatory.** Even `direct` must persist a `plan` artifact via
  `/ticket-plan` before build. No ticketed path may build from conversation-only intent.
- Ticket status transitions owned by phase skills
- Orchestrator-owned health / validation (builders and reviewers never run health)
- Safety reviewers / heavy upgrade when a floor trigger appears mid-run
- Evidence-backed terminal reporting

### `direct`

| Phase | Behavior |
| --- | --- |
| Plan | One native planner; no critic panel; peers only on explicit peer-escalation triggers. **Still writes the plan artifact.** Deployment-guide draft only when deploy shape is non-trivial. |
| Build todos | No separate deep build-planner agent. Orchestrator (or a single bounded pass) materializes **minimal** `build_todo` artifacts from the plan (objective + files + acceptance) so audit/resume still have per-step checkpoints. One coherent builder chain is the norm. |
| Build | One builder chain covering the todos; standard self-repair budget |
| Tests | Write tests only when behavior changed |
| Review | Light path: one native general reviewer. Safety/domain triggers upgrade to heavy. |
| Resolve | At most one fix-up + re-review round unless findings remain actionable |
| Health | One full orchestrator gate after implement+tests. Skip a second pre-review gate only when the tree is tiny, risk surfaces are absent, and a single post-build gate already covers the final tree. If review changes the tree, run the final gate. |

### `standard` (default auto)

| Phase | Behavior |
| --- | --- |
| Plan | Light plan path (one planner); peers only on peer-escalation triggers. Plan artifact required. |
| Build todos | `/create-build-todos` with normal depth when multi-step, multi-file, or dependencies are unclear; may keep a single deepened todo when the plan is already one clear step |
| Build | Coherent sequential chains as in `/build` |
| Tests | As in `/write-tests` orchestrator mode |
| Review | Light path by default; heavy when the review path gate fires; peers on peer-escalation triggers |
| Resolve | Up to 2 rounds when actionable findings remain |
| Health | Pre-review full gate after implement+tests; final gate only if review changed the tree |

### `heavy`

| Phase | Behavior |
| --- | --- |
| Plan | Heavy path: multi-framing + critic panel; peers when peer-escalation triggers fire. Plan artifact required. |
| Build todos | Always `/create-build-todos` with deep research |
| Build | Chains with stricter splits on risk/subsystem boundaries |
| Tests | As orchestrator mode |
| Review | Heavy native personas when path gate selects heavy; peers on peer-escalation triggers |
| Resolve | Up to 3 rounds when contested findings remain |
| Health | Pre-review + conditional final gate; no direct-style single-gate shortcut |

## Mapping to existing light/heavy gates

| Intensity | Plan path | Review path | Build-todo path |
| --- | --- | --- | --- |
| `direct` | light | light (upgrade on safety) | minimal todos, no deep planner |
| `standard` | light | light (upgrade on safety) | `/create-build-todos` (normal) |
| `heavy` | heavy | heavy when gate says so | `/create-build-todos` (deep) |

`--solo` still disables conditional peer providers only; it never removes native safety
personas or the plan-artifact requirement.

## Reporting

Every ticketed terminal report includes:

```text
Intensity: {direct|standard|heavy} ({reason}; floor={none|standard|heavy})
```

so retrospectives can audit under- and over-provisioning.

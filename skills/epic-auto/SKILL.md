---
name: epic-auto
description: High-level autonomous epic orchestrator. Plans, splits, executes milestones, and can call timer-friendly verify/promote gates when allowed. Defaults to stopping at gate boundaries unless explicitly configured.
max_turns: 800
---

# Epic Auto

End-to-end epic orchestrator. This is the long-term path toward fully autonomous epic
implementation.

## Default safety mode

By default, `/epic-auto` stops at verification/promotion gates. It does not deploy or verify
unless the user explicitly runs/authorizes the relevant gate skills or the configured timer job
picks them up.

## Usage

```text
/epic-auto E0007 --stop-at-gates       # default
/epic-auto E0007 --milestone M2
/epic-auto E0007 --allow-gate-skills   # may call ticket-verify/ticket-promote gates
```

## Process

1. Load the epic.
2. If no canonical plan exists, run `/epic-plan`.
3. If steps/milestones/contracts are missing or stale, run `/epic-split`.
4. For each milestone in order:
   - run `/epic-milestone-flow`;
   - stop at the milestone gate by default;
   - if `--allow-gate-skills`, run the configured verification/promotion skills.
5. Continue only when the milestone gate passes.
6. Mark the epic complete only after the final production verification gate passes.

## Parallelism

Parallelism is delegated to `/epic-milestone-flow`, which uses dependency waves and repo write
scope analysis. Never parallelize same-repo overlapping work just to save time.

## Output

Always report current epic state, completed milestone, next gate, and next command/timer action.

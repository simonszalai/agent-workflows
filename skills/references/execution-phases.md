# Shared autonomous execution phases

These phases are shared by ticket-flow and epic milestone execution. `lfg` intentionally keeps
its existing ticketless `.context` behavior and is not changed by this reference.

## Phase sequence

1. **Resolve scope** — ticket/issue/conversation input, project, repo, branch, target.
2. **Gather context** — feature research or bug investigation; similar tickets; relevant memory.
3. **Plan** — create/update a concise plan artifact.
4. **Critic loop** — adversarially review the plan; run heavy mode for complex/cross-cutting work
   and stop if open questions require user decisions.
5. **Build todos** — create detailed implementation steps with discovered patterns/gotchas.
6. **Build** — implement in dependency order; keep unrelated fixes in a separate commit.
7. **Write tests** — add focused tests for the changed behavior.
8. **Review + resolve (cross-review loop)** — run the Cross-Review Iteration Loop from the
   `review` skill: each round runs `/review mode:cross` (Claude self-review plus external Codex
   and Grok reviewers, merged and deduped with a cross-provider confidence boost), then Claude
   resolves the actionable findings. Repeat up to 3 rounds, or stop earlier when no actionable
   (`safe_auto`/`gated_auto`/`manual`) findings remain. Stop on unresolved design decisions and
   surface any remaining `gated_auto`/`manual` findings for a human.
9. **Local verification** — run targeted checks and project health commands.
10. **Land if policy allows** — merge to `main` or `staging`; no deploy; no environment verify.
11. **Status update** — set the ticket/epic-step state according to ticket-lifecycle.md.

## Plan critic loop

The loop is bounded and evidence-driven:

- use the existing light/heavy plan gate for single tickets;
- always use deep mode for epics;
- have critics check completeness, correctness, YAGNI/scope, contracts, data safety, and
  verification strategy;
- revise once or a few bounded times until there are no unresolved critical findings;
- if the critics disagree or expose unknown facts, gather the missing context before building.

## No hidden substitutions

Implementation must follow the approved plan. If build research discovers that the plan is
wrong, update the plan artifact and record the deviation before continuing.

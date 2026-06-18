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
8. **Review + resolve (cross-review loop)** — run the Cross-Review Iteration Loop by **invoking
   the `review` skill in `mode:cross`** each round. Do not hand-roll the review here and do not
   reason about what the providers "would" say — actually enter the skill. The `review` skill is
   the single orchestrator that owns the whole fan-out **and** the distillation: in one round it
   spawns Claude's native reviewers (Anthropic) **plus** an `external-reviewer` subagent for
   `provider=codex` (OpenAI) and one for `provider=grok` (xAI), then distills all three providers
   into one synthesized set (dedup by `(file, normalized title, |line diff| ≤ 3)`, cross-provider
   confidence boost, gate, partition). Claude then resolves the actionable findings.

   **Cross-coverage gate — the review round is NOT complete until all three providers contributed.**
   After each round, confirm `.context/review/codex.json` **and** `.context/review/grok.json` both
   exist and were folded into synthesis (a provider that failed still writes a valid envelope with
   empty `findings` and a `residual_risks` note — that counts as contributing; a *missing* file
   means the external-reviewer subagent was never spawned). If either file is absent, the
   cross-provider dispatch was silently skipped — go back and spawn the missing `external-reviewer`
   subagent(s) before treating the round as done. A round where only Claude-native reviewers ran is
   a **failed** review round, not a passing one.

   Repeat up to 3 rounds, or stop earlier when no actionable (`safe_auto`/`gated_auto`/`manual`)
   findings remain. Stop on unresolved design decisions and surface any remaining
   `gated_auto`/`manual` findings for a human.
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

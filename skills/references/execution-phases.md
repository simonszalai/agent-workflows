# Shared autonomous execution phases

These phases are shared by ticket-flow and epic milestone execution. `lfg` intentionally keeps
its existing ticketless `.context` behavior and is not changed by this reference.

## Phase sequence

1. **Resolve scope** — ticket/issue/conversation input, project, repo, branch, target.
2. **Gather context** — feature research or bug investigation; similar tickets; relevant memory.
3. **Plan** — run `/auto-plan` (the single planning skill; complexity-based light/heavy
   gate) to create/update the plan artifact.
4. **Critic loop (heavy path only)** — adversarially review the plan for complex/cross-cutting
   work and stop if open questions require user decisions. The light path skips the critic
   panel and relies on single-round cross-provider convergence.
5. **Build todos** — create detailed implementation steps with discovered patterns/gotchas.
6. **Build** — invoke the `build` skill: one builder per todo in dependency order, checkpoint
   each to MCP on success, bounded self-repair (≤2 retries) on a failed todo, and finish only
   when every todo is `complete` **and** the project health command (test + typecheck + lint)
   passes. A builder that finds the plan wrong returns `needs_replan` → stop and revise the plan.
   Keep unrelated fixes in a separate commit.
7. **Write tests** — add focused tests for the changed behavior.
8. **Review + resolve (cross-review loop)** — run the Cross-Review Iteration Loop by **invoking
   the `review` skill in `mode:cross`** each round. Do not hand-roll the review here and do not
   reason about what the providers "would" say — actually enter the skill. The `review` skill is
   the single orchestrator that owns the whole fan-out **and** the distillation: in one round the
   main runner performs native/self-review and runs the other two providers through
   `external-agent`, then distills all three providers into one synthesized set (exact dedup
   by `(file, normalized title, |line diff| ≤ 3)` plus a semantic same-issue merge for
   differently-worded duplicates, cross-provider confidence boost, gate, partition). The
   main runner then resolves the actionable findings.

   **Autonomous gated_auto rule.** In an autonomous run there is no user to answer
   `resolve-review`'s "Apply?" question for `gated_auto` findings. The runner may
   self-approve a `gated_auto` fix ONLY when the finding is corroborated — skeptic-upheld
   (`requires_verification: false` after verify) or multi-reviewer consensus; otherwise
   defer it to the follow-up report instead of applying or stalling. `manual` findings are
   never self-approved: defer them to the follow-up report. (Interactive runs keep
   `resolve-review`'s ask-first behavior.)

   **Cross-coverage gate — the review round is NOT complete until all three providers contributed.**
   After each round, confirm the two `.context/review/<provider>.json` files for the peer
   providers exist and were folded into synthesis (a provider that failed still writes a valid
   envelope with empty `findings` and a `residual_risks` note — that counts as contributing; a
   *missing* file means peer dispatch was never spawned). If either file is absent, the
   cross-provider dispatch was silently skipped — go back and spawn the missing peer provider(s)
   before treating the round as done. A round where only one provider ran is a **failed** review
   round, not a passing one.

   The canonical loop definition lives in the `review` skill. Rounds: heavy path ≤3, light
   path exactly 1. Stop earlier when no actionable (`safe_auto`/`gated_auto`/`manual`)
   findings remain, **or when a round's actionable findings were resolved and the adversarial
   verify produced no contested findings** (a second round is spent only to resolve genuine
   adversarial disagreement, not to re-confirm agreed fixes). Stop on unresolved design
   decisions and surface any remaining `gated_auto`/`manual` findings for a human.
9. **Local verification** — run targeted checks and project health commands.
10. **Deploy/land if policy allows** — for standalone ticket-flow, invoke `/auto-deploy` for
    the chosen target (`staging` for complex/risky/uncertain work, `production` only for tiny
    safe work). Epic-step landing remains parent-owned by the milestone/epic orchestrator.
11. **Status update** — trust `/auto-deploy` for standalone deploy status, or set the
    epic-step state according to ticket-lifecycle.md.

## Plan critic loop

The loop is bounded and evidence-driven:

- use `/auto-plan`'s complexity-based light/heavy gate for single tickets (critics are a
  heavy-path step);
- always use deep mode for epics;
- have critics check completeness, correctness, YAGNI/scope, contracts, data safety, and
  verification strategy;
- revise once or a few bounded times until there are no unresolved critical findings;
- if the critics disagree or expose unknown facts, gather the missing context before building.

## No hidden substitutions

Implementation must follow the approved plan. If build research discovers that the plan is
wrong, update the plan artifact and record the deviation before continuing.

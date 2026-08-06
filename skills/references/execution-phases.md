# Shared autonomous execution phases

These phases are shared by ticket-flow and epic milestone execution. Intensity
(`direct` / `standard` / `heavy`) is defined in `execution-intensity.md` and only changes how much
plan/build/review machinery runs — not lifecycle ownership. Ticketless ultra-light edits use
`/go-fable` and are outside this reference.

## Phase sequence

1. **Resolve scope** — ticket/issue/conversation input, project, repo, branch, target.
   Decide and record `intensity` / `intensity_reason` / `intensity_floor` per
   `execution-intensity.md` once before planning.
2. **Gather context once** — epic packet plus bug triage. Reuse a proven investigation. The compact
   delivery owner performs bounded diagnosis and code/memory lookup in-session; spawn a separate
   investigator only when an absent/unproven root cause forces the heavy path. Heavy knowledge
   retrieval otherwise belongs to `/ticket-plan`.
3. **Compact delivery (`direct` / `standard`)** — dispatch exactly one no-history delivery owner.
   Before editing it persists the short **plan MCP artifact (mandatory at every intensity,
   including `direct`)** and minimal `build_todo` artifacts. It then implements the whole bounded
   change, writes focused tests, may run focused tests, and checkpoints each todo. It does not run
   the canonical health gate. There is no separate planner, researcher, build-planner, `/build`
   chain, or `/write-tests` agent.
4. **Heavy delivery** — `/ticket-plan` owns research, planning, and the critic loop; then
   `/create-build-todos`, `/build`, and `/write-tests` run as separate bounded roles. Builders and
   test writers do not run validation, typecheck, lint, builds, schema pulls/migrations, browser
   verification, or health commands. A builder that finds the plan wrong returns `needs_replan`.
5. **Parent health gate** — after implementation and tests, the main orchestrator runs the canonical
   full health command once and records the PASS by `(tree SHA, exact command)`.
6. **Review** — `direct` has no independent review. `standard` dispatches exactly one native general
   reviewer over the diff and recorded PASS. `heavy` invokes `/review` with conditional specialist
   coverage. Reviewers never validate or edit. A review need discovered on `direct` raises it to
   `standard`; a new safety boundary raises any path to `heavy` before dispatch.
7. **One ordinary repair** — combine every health failure or accepted review finding into one
   complete batch. `direct`/`standard` consume one repair-owner reservation total. Run maintained
   deterministic autofixes first in the current orchestrator session; dispatch a fresh repair owner
   only for remaining non-mechanical work. The repair owner does not validate. Do not re-review a
   same-risk repair. A new risk boundary uses the heavy review path. `heavy` may use up to three
   repair cycles.

   **Autonomous decision-ownership rule.** Severity and decision ownership are independent:
   a p1 finding is not `manual` merely because the affected surface is sensitive or destructive.
   Use `manual` only when a genuine human choice remains (product intent, destructive scope
   expansion, materially different tradeoffs, new secrets/schema/infrastructure/cost, or unresolved
   reviewer conflict). A concrete deterministic fix that preserves the approved plan is
   `gated_auto`, even when it changes behavior or hardens a sensitive path.

   In an autonomous run, the runner may self-approve a `gated_auto` fix when it is both
   plan-conformant and corroborated — multi-reviewer consensus, or a settled finding
   (`requires_verification: false`). An explicit `/ticket-flow prod` (or
   `/ticket-deploy prod|full`) invocation is standing approval for those fixes and for bounded
   repair work within the selected intensity's cumulative budget; do not stop merely to ask the
   user to approve an agent-found
   deterministic correctness fix. Defer an uncorroborated or
   scope-expanding fix. A `manual` finding still requires the missing human decision, unless that
   decision is already recorded in the ticket or current conversation.

   **Conditional coverage gate.** A routine standard round is complete with its one native
   envelope. Direct has no review envelope. When the review skill records a peer-escalation trigger,
   the round is not complete until both
   peer envelopes were folded into synthesis or their failure is explicitly recorded as residual
   risk. Safety-critical native personas and adversarial checks remain mandatory even if peers fail
   or `mode:solo` was explicitly requested.

   The canonical heavy loop definition lives in the `review` skill. Stop on unresolved design
   decisions and surface any genuinely undecided `manual` findings for a human.
8. **Final local verification** — if a repair changed the tree since the first PASS, the main
   orchestrator runs the canonical full health command exactly once on the new tree. If unchanged,
   reuse the prior PASS. Exhaustion returns `BUDGET_EXHAUSTED`; it never rotates into a fresh repair
   allowance.
9. **Deploy/land if policy allows** — for standalone ticket-flow, invoke `/auto-deploy` for
    the chosen target (`staging` for complex/risky/uncertain work, `production` only for tiny
    safe work). Epic-step landing remains parent-owned by the milestone/epic orchestrator.
10. **Status update** — trust `/auto-deploy` for standalone deploy status, or set the
    epic-step state according to ticket-lifecycle.md.

## Plan critic loop

The loop is bounded and evidence-driven:

- use `execution-intensity.md` + `/ticket-plan`'s path gate for single tickets (critics are a
  `heavy` intensity step);
- epic planning stays deep via `/epic-plan`; epic **step** tickets are classified independently
  and become `heavy` only when their own safety surfaces apply;
- have critics check completeness, correctness, YAGNI/scope, contracts, data safety, and
  verification strategy;
- revise once or a few bounded times until there are no unresolved critical findings;
- if the critics disagree or expose unknown facts, gather the missing context before building.
- **never skip the plan artifact** — intensity never authorizes building without a persisted
  MCP `plan`.

## No hidden substitutions

Implementation must follow the approved plan. If build research discovers that the plan is
wrong, update the plan artifact and record the deviation before continuing.

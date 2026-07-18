# Shared autonomous execution phases

These phases are shared by ticket-flow and epic milestone execution. `lfg` intentionally keeps
its existing ticketless `.context` behavior and is not changed by this reference.

## Phase sequence

1. **Resolve scope** — ticket/issue/conversation input, project, repo, branch, target.
2. **Gather context** — bug investigation / triage and epic-context loading only. When Phase 3
   invokes `/ticket-plan`, do **not** run codebase research or memory/similar-ticket searches here:
   `/ticket-plan` Phases 3-4 are the single owner of knowledge retrieval. Only run that retrieval in
   this phase when the path does not invoke `/ticket-plan`.
3. **Plan** — run `/ticket-plan` (the single planning skill; complexity-based light/heavy
   gate) to create/update the plan artifact. Carry `/ticket-plan`'s returned prior-knowledge blob
   (the applicable rules/patterns it retrieved) forward into the build and review packets so
   downstream agents inherit the same knowledge without re-searching.
4. **Critic loop (heavy path only)** — adversarially review the plan for complex/cross-cutting
   work and stop if open questions require user decisions. The light path skips the critic
   panel and uses one bounded native planner unless a peer-escalation trigger fires.
5. **Build todos** — create detailed implementation steps with discovered patterns/gotchas.
6. **Build** — invoke the `build` skill: one builder per todo in dependency order, checkpoint
   each to MCP on success, bounded self-repair (≤2 retries) on a failed todo, and finish only
   when every todo is `complete` **and** the project health command (test + typecheck + lint)
   passes. A builder that finds the plan wrong returns `needs_replan` → stop and revise the plan.
   Keep unrelated fixes in a separate commit.
7. **Write tests** — add focused tests for the changed behavior.
8. **Review + resolve** — invoke the `review` skill rather than hand-rolling review. It chooses a
   genuinely light one-reviewer path or a heavy native specialist path and conditionally adds peer
   providers only for explicit risk, uncertainty, or disagreement. When peers are required, wait
   for their envelopes before the single synthesis; never simulate them. The main runner resolves
   actionable findings.

   **Autonomous decision-ownership rule.** Severity and decision ownership are independent:
   a p1 finding is not `manual` merely because the affected surface is sensitive or destructive.
   Use `manual` only when a genuine human choice remains (product intent, destructive scope
   expansion, materially different tradeoffs, new secrets/schema/infrastructure/cost, or unresolved
   reviewer conflict). A concrete deterministic fix that preserves the approved plan is
   `gated_auto`, even when it changes behavior or hardens a sensitive path.

   In an autonomous run, the runner may self-approve a `gated_auto` fix when it is both
   plan-conformant and corroborated — skeptic-upheld (`requires_verification: false` after verify)
   or supported by multi-reviewer consensus. An explicit `/ticket-flow prod` (or `/ticket-deploy prod|full`) invocation is standing
   approval for those fixes and for bounded resolve/re-review rounds; do not stop merely to ask the
   user to approve an agent-found deterministic correctness fix. Defer an uncorroborated or
   scope-expanding fix. A `manual` finding still requires the missing human decision, unless that
   decision is already recorded in the ticket or current conversation.

   **Conditional coverage gate.** A routine light round is complete with its one native envelope.
   When the review skill records a peer-escalation trigger, the round is not complete until both
   peer envelopes were folded into synthesis or their failure is explicitly recorded as residual
   risk. Safety-critical native personas and adversarial checks remain mandatory even if peers fail
   or `mode:solo` was explicitly requested.

   The canonical loop definition lives in the `review` skill. Rounds: heavy path ≤3, light
   path exactly 1. Stop earlier when no actionable (`safe_auto`/`gated_auto`/`manual`)
   findings remain, **or when a round's actionable findings were resolved and the adversarial
   verify produced no contested findings** (a second round is spent only to resolve genuine
   adversarial disagreement, not to re-confirm agreed fixes). Stop on unresolved design
   decisions and surface any remaining unapproved `gated_auto` findings or genuinely undecided
   `manual` findings for a human.
9. **Local verification** — run targeted checks and project health commands.
10. **Deploy/land if policy allows** — for standalone ticket-flow, invoke `/auto-deploy` for
    the chosen target (`staging` for complex/risky/uncertain work, `production` only for tiny
    safe work). Epic-step landing remains parent-owned by the milestone/epic orchestrator.
11. **Status update** — trust `/auto-deploy` for standalone deploy status, or set the
    epic-step state according to ticket-lifecycle.md.

## Plan critic loop

The loop is bounded and evidence-driven:

- use `/ticket-plan`'s complexity-based light/heavy gate for single tickets (critics are a
  heavy-path step);
- always use deep mode for epics;
- have critics check completeness, correctness, YAGNI/scope, contracts, data safety, and
  verification strategy;
- revise once or a few bounded times until there are no unresolved critical findings;
- if the critics disagree or expose unknown facts, gather the missing context before building.

## No hidden substitutions

Implementation must follow the approved plan. If build research discovers that the plan is
wrong, update the plan artifact and record the deviation before continuing.

# Fable variant — house prompting style

This reference governs every `-fable` suffixed skill and agent (`auto-plan-fable`,
`ticket-flow-fable`, `planner-fable`, …). It exists so future edits — including ones made by
`/compound`, `/deep-dream`, and `/heal-workflows` — keep the variant consistent instead of
drifting back toward the Opus-tuned style.

## What the Fable variant is

A parallel, fully detached set of the main workflow paths, optimized for Claude Fable 5
(per Anthropic's "Prompting Claude Fable 5" guide). The Opus-tuned originals stay untouched
and remain the default. Selection is explicit: the user invokes `/ticket-flow-fable`,
`/auto-plan-fable`, etc. Model split:

| Role | Model | Why |
| --- | --- | --- |
| Orchestrator session + planner/build-planner/reviewer agents | Fable 5 | highest-leverage reasoning (plan + review) |
| Builder | Codex GPT 5.5, reasoning `xhigh`, via `bin/external-build` | token-heaviest role moves off Anthropic billing; review is cross-provider by construction (GPT writes, Fable reviews) |
| Mechanical scaffolding (light-diff reviewers, react/pipeline reviewers) | sonnet | unchanged from the base system |

Deploy/verify/promote/compound skills and the fanout workflows are **shared** with the base
system, not forked — they are mechanical orchestration where prompt style barely matters and
duplicating deploy logic is a drift hazard.

## Style rules for -fable files

1. **Contract over procedure.** State the goal, why it matters, explicit boundaries, the
   verification method, and what outputs are required — then let the model work. Do not
   enumerate the steps of *how* to research or reason (no a-through-g checklists, no
   "Phase 1..N: do X" scaffolding for reasoning work). Fable's instruction following makes a
   short directive as effective as an exhaustive list, and Anthropic documents that
   over-prescriptive prior-model skills degrade its output.
2. **Hard invariants stay, verbatim and prominent.** MCP call shapes, artifact types and
   statuses, ticket lifecycle transitions, JSON output contracts, schema-artifact rules,
   commit/push/PR rules, safety gates (migration parity, elimination proof, polling volume,
   cache finality). These are correctness contracts, not scaffolding. Never soften them when
   simplifying.
3. **Never ask the model to echo or transcribe its reasoning.** "Show your step-by-step
   reasoning", "explain your thinking" and similar can trigger the `reasoning_extraction`
   refusal on Fable. Ask for conclusions with evidence instead.
4. **Effort:** `high` is the default for Fable agents; `medium` for mechanical/research-heavy
   agents (build-planner). Do not use `xhigh` — Fable at `high` matches or beats prior models
   at `xhigh`, and `xhigh` mainly adds latency and cost.
5. **Codex-side prompts are exempt from de-scaffolding.** The GPT 5.5 builder prompt inside
   `bin/external-build` deliberately keeps the prescriptive checklist style — GPT models
   respond well to it. Do not "Fable-ify" the Codex prompt.

## Standard guardrail snippets

Place these where they apply (they are the official Anthropic-recommended Fable snippets;
keep the wording stable so `/heal-workflows` can recognize them):

- **Anti-overplanning** (all skills): "When you have enough information to act, act. Do not
  re-derive facts already established, re-litigate a decision already made, or narrate options
  you will not pursue. If you are weighing a choice, give a recommendation, not an exhaustive
  survey."
- **Grounded progress** (autonomous orchestrators): "Before reporting progress, audit each
  claim against a tool result from this session. Only report work you can point to evidence
  for; if something is not yet verified, say so explicitly. If tests fail, say so with the
  output; if a step was skipped, say that."
- **Autonomy / no early stopping** (autonomous orchestrators): "You are operating
  autonomously. For reversible actions that follow from the original request, proceed without
  asking. Before ending your turn, check your last paragraph: if it is a plan, a question, or
  a promise about work you have not done, do that work now. End your turn only when the task
  is complete or you are blocked on input only the user can provide."
- **No unrequested tidying** (build/resolve paths): "Don't add features, refactor, or
  introduce abstractions beyond what the task requires. Do the simplest thing that works
  well. Only validate at system boundaries."
- **Delegation bounds** (orchestrators): "Delegate independent subtasks to subagents and keep
  working while they run. For simple, sequential, or single-file work, work directly — only
  delegate parallel or isolated workstreams."
- **Final-summary readability** (long autonomous runs): "Your final message is the user's
  first look at the run. Lead with the outcome, write complete sentences, drop working
  shorthand and labels invented mid-run, and give each file/commit/flag its own plain-language
  clause."

## Drift rules

- A correction captured while a `-fable` skill was running applies to the `-fable` file;
  a correction from an Opus-variant run applies to the Opus file. Cross-apply only
  deliberately, never automatically.
- `/heal-workflows`: the `-fable` files intentionally duplicate the intent of their base
  counterparts with different prompt style and different builder dispatch. Divergence in
  *style and dispatch* is by design and is not an inconsistency finding. Divergence in
  **contracts** (MCP shapes, statuses, JSON schemas, safety gates) between a base skill and
  its `-fable` fork IS a finding — contracts must stay in lockstep.
- Shared reference files (`skills/review/references/*`, `skills/auto-plan/references/*`,
  `skills/auto-plan/templates/*`, `skills/references/*`) are single-sourced: `-fable` skills
  point at the originals rather than carrying copies.

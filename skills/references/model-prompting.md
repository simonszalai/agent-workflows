# House prompting style and model profiles

One canonical workflow tree serves every model. There are no per-model skill forks: which
model plans, builds, or reviews is configuration (agent frontmatter `model:`/`effort:`,
`bin/external-build` flags), never a duplicated skill file. This reference keeps edits —
including ones made by `/compound`, `/deep-dream`, and `/heal-workflows` — consistent.

## Style rules (all skills and agents)

1. **Contract over procedure.** State the goal, why it matters, explicit boundaries, the
   verification method, and the required outputs — then let the model work. Do not
   enumerate the steps of *how* to research or reason (no a-through-g checklists, no
   "Phase 1..N: do X" scaffolding for reasoning work). All current-generation models
   (Claude Fable 5, GPT-5.6, Grok 4.5) are documented by their vendors to perform better
   with lean outcome-oriented prompts; OpenAI measured 41-66% fewer tokens *and* higher
   scores after de-scaffolding.
2. **Hard invariants stay, verbatim and prominent.** MCP call shapes, artifact types and
   statuses, ticket lifecycle transitions, JSON output contracts, schema-artifact rules,
   commit/push/PR rules, safety gates (migration parity, elimination proof, polling
   volume, cache finality). These are correctness contracts, not scaffolding. Never
   soften them when simplifying.
3. **Never ask a model to echo or transcribe its reasoning.** "Show your step-by-step
   reasoning" and similar can trigger the `reasoning_extraction` refusal on Fable. Ask
   for conclusions with evidence instead.
4. **Structured output rides an enforced schema** (Claude `--json-schema`, Codex
   `--output-schema`, workflow `agent({schema})`). Enumerate fields in prose only where
   enforcement is missing (the Grok adapter).

## Effort and model profiles

Effort is the primary cost dial. Escalate on evidence, never as a default.

| Model | Default effort | Escalate to | Never |
| --- | --- | --- | --- |
| Claude Fable 5 | `high` (orchestrators, planners, reviewers); `medium` for mechanical/research-heavy agents | — | `xhigh` — Fable at `high` matches prior models at `xhigh`; it mainly adds latency and cost |
| GPT-5.6 (Codex) | `medium` | `high` for cross-cutting logic, concurrency, migration design; `xhigh` only when retrying after a measured lower-effort failure | `xhigh` as a standing default |
| Grok 4.5 | `high` for planning legs, `medium` for execution | — | — |
| Opus 4.8 / GPT-5.5 (legacy) | per legacy prompt profile | — | — |

**Legacy profile:** older models (Opus 4.8, GPT-5.5) respond well to prescriptive
checklists and step enumeration. If a workflow must target them, add the scaffolding in
the dispatch prompt for that run — do not fork skill files, and do not let legacy
scaffolding become the shared default.

## Standard guardrail snippets

Place these where they apply (Anthropic-recommended wording; keep it stable so
`/heal-workflows` can recognize them):

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

- Shared reference files (`skills/review/references/*`, `skills/auto-plan/references/*`,
  `skills/auto-plan/templates/*`, `skills/references/*`) are single-sourced; skills point
  at the originals rather than carrying copies.
- `/heal-workflows`: a skill that re-grows per-model forks, unconditional multi-provider
  fan-out, or prescriptive reasoning scaffolding in the shared tree IS a finding.

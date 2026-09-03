# House prompting style and model profiles

One canonical workflow tree serves every model. There are no per-model skill forks: which
model plans, builds, or reviews is configuration (agent frontmatter `model:`/`effort:`,
`bin/external-build` flags), never a duplicated skill file. This reference keeps edits —
including ones made by `/compound` — consistent.

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
   enforcement is missing (the Grok adapter). A well-designed schema — clear names, enums,
   `minItems`, descriptions — teaches usage better than an example does; prefer tightening
   the schema over adding a worked example.
5. **No self-verification scaffolding.** Current models check and correct their own work.
   "Add a final verification step", "use a subagent to verify", "double-check before
   responding", and adversarial re-refutation of a model's own output compound with behavior
   the model already has: they cost calls and remove true positives without raising quality.
   This does **not** cover external evidence — staging/production behavior verification,
   absence searches, and deploy gates observe the world rather than the model, and stay.
6. **Never suppress at the producer.** Confidence floors, severity thresholds, "only report
   high-severity issues", and "be conservative" are followed literally and cause
   under-reporting. Have the producer report everything that clears an evidence bar, label it
   honestly, and filter in a separate pass that a human can inspect.
7. **Narrow delegation, don't encourage it.** Models delegate readily; the useful instruction
   is the bound, not the invitation. Delegate for work that needs its own context window;
   prefer one agent over several; cap fan-out; never spawn an agent to check your own work.
8. **Positive examples beat lists of don'ts.** Show the shape you want once, concretely, rather
   than enumerating failure modes. A "never do X" list is worth keeping only when X is a real
   safety or audit invariant.
9. **Say how long the answer should be.** Current models are verbose and expand scope by
   default; effort controls thinking, not output length. Skills that produce user-facing prose
   or written deliverables carry an explicit conciseness and scope-constraint line.

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

Place these where they apply (Anthropic-recommended wording; keep it stable):

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
- **Delegation bounds** (orchestrators): "Delegate to a subagent only for large tasks that are
  genuinely independent and parallelizable, such as a wide multi-file investigation. Do not
  delegate work you can finish yourself in a handful of tool calls, and do not use subagents to
  verify or double-check your own work. If one subagent can complete the task, use one rather
  than several, and keep spawn counts low."
- **Report-everything** (any producer whose output a later pass filters): "Report every finding
  that clears the evidence bar; breadth is wanted, and a separate pass filters. Score confidence
  honestly — it is a label for that pass, not a bar to clear."
- **Final-summary readability** (long autonomous runs): "Your final message is the user's
  first look at the run. Lead with the outcome, write complete sentences, drop working
  shorthand and labels invented mid-run, and give each file/commit/flag its own plain-language
  clause."
- **Context continuity** (any skill that can outlive a compaction): "Read CLAUDE.md, this
  skill, its references, and the tool catalog once. After a context compaction, continue from
  the compaction summary and your run-state note; do not re-read them or re-introspect tools.
  Reload one reference only when a concrete decision needs a rule you cannot recall."
- **Bounded waiting** (orchestrators that wait on subagents, sessions, CI, or flows): "Wait
  with one bounded blocking call per external event — `wait_agent` (≤5 min), `wait-ci`,
  `wait-prefect-flow`, or a 2–3 minute status poll — and compare each result with the previous
  one. Never `sleep` in a loop. A worker with no new activity for 10 minutes, or still reading
  docs or troubleshooting tool access 10 minutes in, gets one corrective message naming the
  first concrete action; the next stall replaces it."

## Drift rules

- Shared reference files (`skills/references/*`) are single-sourced; skills point at the
  originals rather than carrying copies.
- Audit rule: a skill that re-grows per-model forks, unconditional multi-provider
  fan-out, prescriptive reasoning scaffolding, a producer-side confidence/severity suppression
  gate, or an adversarial pass over the model's own output IS a finding.

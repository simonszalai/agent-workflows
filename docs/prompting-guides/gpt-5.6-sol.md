# Prompting Guidance for GPT-5.6 Sol

> Source: https://developers.openai.com/api/docs/guides/prompt-guidance-gpt-5p6
> Retrieved: 2026-08-12

## Overview

This guide helps you adapt prompts, tool descriptions, agent instructions, and prompt stacks for
GPT-5.6 Sol. Reference the current GPT-5.6 model guide for API details, limits, pricing, and
features.

GPT-5.6 performs best when prompts establish desired outcomes, key constraints, available
evidence, and success criteria while "leaving room for the model to choose an efficient path."

Research shows that leaner system prompts improved evaluation scores by roughly 10–15% while
reducing tokens by 41–66% and cost by 33–67%.

## Simplify Prompts First

Start with working prompts and tools. Remove one instruction group, set of examples, or tool at a
time, then re-run evaluations.

**Remove:**

- repeated rule statements
- repeated style instructions that don't change behavior
- examples that don't affect behavior
- process instructions for reliably-performed behavior
- unrelated tools and descriptions

**Keep:**

- user-visible outcomes
- success criteria and stopping conditions
- safety, business, evidence, and permission constraints
- tool-routing rules dependent on context
- required output shape and validation requirements

Review remaining instructions for contradictions, as "GPT-5-class models follow prompt contracts
closely."

## Outcome-First Prompts and Stopping Conditions

Describe destinations rather than prescribing steps. The model typically identifies efficient
paths when prompts define what success looks like.

**Preferred approach:**

```text
Resolve the customer's issue end to end.

Success means:
- make the eligibility decision from available policy and account evidence
- complete any allowed action before responding
- return completed_actions, customer_message, and blockers
- if required evidence is missing, ask for the smallest missing field
```

Avoid unnecessary absolute rules. Reserve ALWAYS, NEVER, must, and only for true invariants like
safety rules or required fields. For judgment calls, use decision rules instead.

Provide explicit user values. When values are implicit, offer decision criteria and let the model
reason from context or schema. Avoid universal defaults and broad semantic shortcuts.

**Add stopping conditions:**

```text
Resolve the request in the fewest useful tool loops, but do not let loop
minimization outrank correctness, required evidence, calculations, or
required citations.

After each result, ask whether the core request can now be answered with
useful evidence. If yes, answer. If required evidence is still missing,
name the missing fact and use the smallest useful fallback.
```

## Personality, Collaboration, and Response Length

GPT-5.6 tends toward greater conciseness than GPT-5.5. When migrating, reconsider broad brevity
instructions—they may be unnecessary or counterproductive.

For consistent control, use `text.verbosity` to establish default detail levels (low, medium, or
high), then use prompts for task-specific requirements.

For customer-facing assistants, define:

- **Personality:** tone, warmth, directness, formality, humor, empathy, and polish
- **Collaboration style:** when to ask questions, make assumptions, take initiative, explain
  tradeoffs, check work, and handle uncertainty

Keep both concise. Neither should replace clear goals, success criteria, tool rules, or stopping
conditions.

For shorter answers, identify required information and omittable detail:

```text
Lead with the conclusion. Include the evidence needed to support it, any material
caveat, and the next action. Omit secondary detail and repetition.

Keep all required facts, decisions, caveats, and next steps. Trim introductions,
repetition, generic reassurance, and optional background first.
```

Be specific about tone. Instead of labels like "friendly," describe writing choices:

```text
State the answer directly. If the user reports a problem, acknowledge the
specific issue before giving the next step. Use reassurance only when it is
relevant. Omit generic praise and unnecessary sign-offs.
```

For editing, rewriting, and drafts, specify what to preserve:

```text
Preserve the requested artifact, length, structure, genre, and factual claims
first. Improve clarity, flow, and correctness without adding new claims,
sections, or a more promotional tone unless requested.
```

## Define Autonomy and Approval Boundaries

GPT-5.6 can be proactive in multi-step tasks. Define authorization levels so the model continues
safe work without unnecessary pauses while stopping before external, destructive, costly, or
scope-expanding actions.

A compact policy works well:

```text
For requests to answer, explain, review, diagnose, or plan, inspect the
relevant materials and report the result. Do not implement changes unless
the request also asks for them.

For requests to change, build, or fix, make the requested in-scope local
changes and run relevant non-destructive validation without asking first.

Require confirmation for external writes, destructive actions, purchases,
or a material expansion of scope.
```

Name safe local actions explicitly (reading files, inspecting logs, editing code, running tests).
State each rule once to avoid unnecessary approval requests.

For long-running work, define current work layers. Distinguish research, design, implementation,
review, and external coordination to prevent silent transitions between stages.

## Tool Routing

Expose only task-relevant tools. Descriptions should state what the tool does, when to use it,
important return fields, and error behavior.

When correctness requires prerequisites:

```text
Before taking an action, resolve required discovery, retrieval, and
validation steps. Do not skip a prerequisite because the intended final
state seems obvious.
```

Parallelize independent reads; keep dependent work sequential. Synthesize parallel results before
acting.

If a tool returns empty or suspiciously narrow results, try one or two meaningful fallbacks before
concluding no result exists.

## Programmatic Tool Calling

Programmatic Tool Calling (PTC) works best for bounded workflows where code processes multiple
tool results or large outputs and returns smaller structured results.

**Use PTC for:**

- filtering, joining, sorting, ranking, deduplication, aggregation
- batching across many similar records
- repeated deterministic validation
- large structured results reducible to compact schemas

**Prefer direct tool calls when:**

- one call suffices
- intermediate outputs are already small
- each result may change the next decision
- an action requires approval
- final answers must preserve citations or native artifacts
- the workflow requires semantic judgment between calls

Avoid generic instructions. Instead, state the bounded stage, eligible tools, output schema, retry
limit, stop condition, and handoff:

```text
Use Programmatic Tool Calling only for the bounded record-reduction stage.
Call only the documented read-only tools. Filter and deduplicate the
intermediate results, then emit exactly the required compact schema with
evidence fields. Retry transient failures at most twice. Use direct tool
calls for approval, semantic judgment, citations, and final validation.
```

Test both `program_output` items and final assistant messages—programs may return correct records
while messages omit required fields or caveats.

Compare direct and programmatic calling on representative tasks. Check correctness, completeness,
and required evidence. Then compare tokens, latency, cost, calls, turns, and retries. Lower
resource use counts as improvement only when responses pass existing evaluations.

## Grounding, Citations, and Retrieval Budgets

Citation behavior should be part of prompts. Define what needs support, what counts as sufficient
evidence, and behavior when evidence is missing.

For ordinary Q&A:

```text
For ordinary Q&A, start with one broad search using short, discriminative
keywords. If the top results contain enough support for the core request,
answer from those results.

Make another retrieval call only when a required fact, owner, date, ID, or
source is missing; the user asked for exhaustive coverage or comparison; a
specific artifact must be read; or an important claim would otherwise be
unsupported.

Do not search again only to improve phrasing, add examples, or support
nonessential detail.
```

For research and synthesis:

- cite only retrieved sources
- attach citations to supported claims
- label inference separately from directly supported facts
- state conflicts between sources
- narrow answers or report missing evidence instead of guessing

For creative drafting, distinguish source-backed facts from creative wording. Don't invent names,
metrics, dates, roadmap status, customer outcomes, or product capabilities.

## Long-Running Workflows and State

For multi-step tasks, provide a short preamble before the first tool call, then sparse
outcome-based updates at major phase changes. Don't narrate routine tool calls.

```text
Before tool calls for a multi-step task, send a one- or two-sentence
user-visible update that states the first step. During the task, update only
when a major phase begins or a finding changes the plan. Each update should
state one concrete outcome and the next step.
```

Preserve assistant phase values when replaying history. Compact after major milestones rather than
every turn. Keep prompts functionally consistent after compaction.

Persisted reasoning works when objectives, assumptions, and priorities remain stable. Use
current-turn behavior when earlier reasoning is outdated. Stale reasoning can add tokens and
increase latency.

Prompt caching affects prompt construction. Keep reusable prefixes stable. Use explicit cache
breakpoints only when measured improvements justify them.

## Reasoning Effort

Establish baselines before changes:

- Preserve current GPT-5.5 or GPT-5.4 reasoning effort as baseline
- Test the same setting and one level lower on representative tasks
- Use low for latency-sensitive work when quality is preserved
- Use medium as balanced starting point
- Use high or xhigh only when evals show meaningful gains
- Reserve max for hardest quality-first workloads

Before increasing reasoning effort, check whether prompts are missing success criteria, dependency
rules, tool-routing rules, or verification loops.

## Frontend and Visual Tasks

GPT-5.6 demonstrates stronger layout, visual hierarchy, and design judgment. Still provide product
context, preserve existing design systems, and name relevant states and constraints.

For incremental frontend changes:

- inspect and preserve existing design tokens, components, and patterns
- don't add extra features or decorative UI unless requested
- preserve responsive behavior and expected states
- render and inspect results before finalizing

For vision, computer use, localization, or OCR tasks requiring spatial precision, choose image
detail intentionally. Use original detail for large, dense, or coordinate-sensitive images when
justified by cost and latency.

## Check Work Before Finishing

Give GPT-5.6 access to validation tools and state what matters.

For coding:

```text
After making changes, run the most relevant validation available:
- targeted tests for changed behavior
- type checks or lint checks when applicable
- build checks for affected packages
- a minimal smoke test when full validation is too expensive

If validation cannot be run, explain why and describe the next best check.
```

For visual artifacts:

```text
Render the artifact before finalizing. Inspect layout, clipping, spacing,
missing content, and visual consistency. Revise until the rendered output
matches the requirements.
```

For implementation plans, include requirements, named resources or files, state transitions or
data flow, validation checks, failure behavior, privacy or security considerations, and open
questions affecting implementation.

## Suggested Prompt Structure

Use this structure as a starting point for complex prompts. Keep each section short and add detail
only where it changes behavior.

```text
Role: [the model's function and context]

Personality: [tone and collaboration style]

Goal: [user-visible outcome]

Success criteria: [what must be true before the final answer]

Constraints: [policy, safety, business, evidence, and side-effect limits]

Tools: [which tools to use, when, and what not to use]

Output: [sections, length, format, and tone]

Stop rules: [when to retry, fallback, abstain, ask, or stop]
```

## Prompt Migration Workflow

When moving existing applications to GPT-5.6:

1. Switch the model and preserve current reasoning effort
2. Run representative evals before changing prompts
3. Remove obsolete scaffolding, repeated instructions, and irrelevant tools
4. Add only the smallest targeted instruction that fixes measured regressions
5. Re-run evals after each prompt or reasoning change

Don't rewrite working prompt stacks all at once. Otherwise you can't identify whether behavior
changes came from the model, reasoning setting, prompt, tool set, or runtime.

When prompts regress, debug with small sets of real traces. Identify failure modes, find
likely-causing instructions or contradictions, make surgical edits, and rerun the same cases.

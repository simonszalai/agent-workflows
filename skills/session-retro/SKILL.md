---
name: session-retro
description: Efficiency retrospective over a full session trace — every tool call, prompt bundle, subagent, and provider leg — judged against the workflow-efficiency rubric. Produces ranked, evidence-backed recommendations for improving the skills/agents/config. Use for "session retro", "audit this session's tokens", "why was this run so expensive", "token retrospective".
---

# Session Retro

Reconstruct what a session actually spent — spawns, prompt bundles, tool calls, repeated
work, external provider legs — and turn measured waste into specific system changes.
Propose-only: the output is recommendations naming exact files, never silent edits.

Not `/retrospect` (correctness post-mortem for a mess in the current thread) and not
`/deep-dream` (whole-corpus consolidation). This skill audits **one run's execution trace
for efficiency**. Quality regressions count as findings too: a retro that only cuts tokens
by cutting necessary verification has failed.

## Inputs

- A session reference: a Claude session `.jsonl` path, a project slug, "the last
  /ticket-flow run", or nothing (default: the most recent substantial session for the
  current workspace).
- Log locations: Claude `~/.claude/projects/<slug>/*.jsonl` (subagents are sibling files
  in the same directory); Codex rollouts `~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`.

## Procedure

1. **Measure with the scripts, not by reading transcripts.**
   - Claude tree: `bin/session-usage-report <main.jsonl>` (or
     `--project-dir ~/.claude/projects/<slug>`). It discovers child sessions in the time
     window and reports totals, per-spawn first-message context, tool histograms,
     repeated commands/MCP calls, and external legs.
   - Codex legs in the same window: `bin/workflow-efficiency-report` on the rollout
     files. Note compaction/truncation counts — context thrash is a finding.
   - Raw JSONL is off-limits except targeted `grep`/`jq` to answer a specific question a
     report raised. Never load whole transcripts into context.
2. **Judge the measurements against the rubric below.** For every violation, find the
   *system* cause — the skill section, agent frontmatter, bin default, or settings entry
   that made the behavior happen. A finding without a file to change is an observation,
   not a recommendation.
3. **Report.** Ranked list (worst first, max ~10): finding → measured evidence (numbers
   from step 1) → file:line to change → expected saving → quality risk and how it stays
   covered. Close with what the run did *well*, so good patterns don't get "optimized"
   away. Offer `/compound` or a ticket for accepted items; apply nothing yourself.

## Rubric

Fan-out and effort:

- Multi-provider or multi-agent fan-out must trace to a recorded trigger (security,
  destructive migration, cross-repo contract, material disagreement, explicit request) —
  not to a default. Unconditional peer legs are findings.
- Reasoning effort matches the work: medium for routine execution, high for cross-cutting
  logic or planning, xhigh only as escalation after a measured failure. A tree that ran
  everything at one high tier is a finding.
- Spawn overhead: a leaf agent whose first-message context exceeds ~25k tokens is
  carrying orchestrator skills it doesn't execute; it needs a leaf rubric, not the parent
  workflow. Micro-spawns (large bundle, tiny output) should have been inline steps.

Repeated work:

- Validation has one owner per layer: builders run targeted checks, reviewers judge the
  diff without rerunning suites, the orchestrator runs exactly one full health gate after
  the last change. Count full-suite executions; more than one on an unchanged tree is a
  finding.
- Identical MCP reads (same tool, same args) mean the run ignored its cache contract:
  ticket context is fetched once, bounded (`detail`, `artifact_types`,
  `include_events=false`), and passed to children as a packet.
- Long command output belongs in `bin/compact-exec`; CI waits belong in one foreground
  `bin/wait-ci` call (or a `fork_turns: "none"` waiter when the harness cannot block), not a
  background process followed by poll loops in model turns. The process may poll; the model should
  be sampled once at the terminal result.

Contracts and measurement:

- Structured output rides an enforced schema; prose field enumerations are justified only
  where enforcement is missing (Grok adapter).
- Every external leg must be measurable (usage sidecar or rollout). Unmeasured spend is
  itself a finding — recommend fixing capture before optimizing further.
- Validate attribution invariants before citing the report: descendant unique usage must never
  exceed its gross cumulative usage. A violation means replay/baseline detection is broken; fix the
  measurement before drawing efficiency conclusions.
- Prompts follow current-model guidance (Fable 5 / GPT-5.6 / Grok 4.5): outcome, success
  criteria, constraints, stop rules. Prescriptive step-by-step scaffolding is a legacy
  profile for older models, not the default.

## Stop rules

- Propose-only. Never edit skills, agents, or settings from this skill.
- Bounded output: top ~10 recommendations; drop the long tail rather than compressing it
  into shorthand.
- If a log source is missing (no Codex rollouts, no usage sidecars), state exactly what
  is unmeasurable and continue with what exists.
- Stop when each recommendation has evidence, a target file, and a quality-risk note —
  not when every conceivable inefficiency has been enumerated.

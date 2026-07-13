---
name: go-fable
description: Ultra-lightweight ticketless delegation loop. Fable stays a thin orchestrator — sonnet scouts gather and curate context, sonnet/opus builders implement, Fable reviews the diff inline. No tickets, no artifacts, no commits/PRs; the diff stays in the working tree. Use liberally instead of handing Fable a task directly, to keep Fable tokens on orchestration and review only.
max_turns: 100
---

# Go (Fable variant)

Take a task from the conversation and deliver it as changes in the working tree of the
current branch, spending Fable tokens **only** on orchestration, judgment, and review
(style: `skills/references/model-prompting.md`). Everything token-heavy — reading code,
pulling logs, writing code — happens in cheaper subagents. This is the "just do it" tier
below `/lfg-fable`: no tickets, no `.context/` artifacts, no commits, no deployment guide,
no multi-round review machinery. For work that deserves a paper trail, use `/lfg-fable` or
`/ticket-flow-fable`.

You are operating autonomously. For reversible actions that follow from the original
request, proceed without asking. Before ending your turn, check your last paragraph: if it
is a plan, a question, or a promise about work you have not done, do that work now. End
your turn only when the task is complete or you are blocked on input only the user can
provide.

## Hard rules (never violate)

- **Never commit, branch, push, or open a PR** — the result of this skill is an uncommitted
  diff on the current branch, exactly as if the user had made the edits themselves. If the
  user asked for a commit or PR in the same breath, do the work here, then hand off to the
  normal git flow after the report.
- **Never use working-tree-wide git commands** (`checkout --`, `restore`, bulk `stash`,
  `reset --hard`) — the tree may hold the user's unrelated uncommitted work. To undo this
  skill's own changes, revert only the specific files it touched.
- **The orchestrator does not do the heavy lifting.** Fable must not bulk-read source files,
  tail logs, or write implementation code in the main thread. Trivial glue (a one-line fix
  to unblock a builder, a config toggle) is fine; anything more routes to a subagent.
- **No scope creep.** Don't add features, refactor, or introduce abstractions beyond what
  the task requires. Do the simplest thing that works well.

## Usage

```
/go-fable fix the flaky retry test in the scraper
/go-fable <any task statable in a sentence or two; context comes from this conversation>
```

## Model routing

| Role | Who | Notes |
| --- | --- | --- |
| Orchestrate, plan, review, synthesize | Fable (this thread) | never reads bulk context or writes code |
| Context scouts | `Explore` or `general-purpose`, `model: sonnet` | `haiku` is fine for purely mechanical pulls (tail a log, dump a schema) |
| Builders | `builder`, `model: sonnet` | escalate a spawn to `model: opus` when the workstream is cross-cutting, concurrency-sensitive, or a sonnet attempt just failed |
| Fix-up after review | same as builders | trivial one-liners may be fixed inline by Fable |

Effort is fixed per-agent and shared across spawn sites — only `model` is a per-spawn lever.

## Flow

**Triviality gate.** If the task is a question, or a change so small that delegation costs
more than it saves (one obvious edit in a file already in context), just answer or make the
edit directly and stop. The machinery below is for real tasks, not for ceremony.

**Scout.** Decide what you need to know to plan — relevant code areas, recent logs, failing
output, prior art in memory — and fan out sonnet scouts to get it, one scout per independent
question, all in a single parallel dispatch. Each scout prompt must demand a **curated
brief** as its final message: the conclusions, the load-bearing snippets with `file:line`
references, and nothing else — no file dumps, no transcripts. Fable reads only the briefs.
Spawn an opus curator to merge them only when the briefs are large or contradict each other;
otherwise synthesize inline.

**Plan inline.** A few sentences in-thread: what changes, where, how you'll verify. No
artifact, no approval gate. When you have enough information to act, act — do not re-derive
facts already established or narrate options you will not pursue.

**Build.** Spawn builders per the routing table — one per independent workstream, dispatched
in parallel when independent, sequentially when coupled. Each builder prompt must be
self-contained: the goal, the relevant brief excerpts, explicit file paths, the verification
command, and the no-scope-creep rule. Delegate independent subtasks and keep working while
they run; for genuinely sequential single-file work one builder is enough.

**Review — Fable, inline, in this thread.** Read the actual diff (`git status --porcelain`
plus `git diff` scoped to the touched files) and review it yourself against the task: does
it do what was asked, is it correct, does it leak scope, does it break neighbors, does it
follow the conventions in project instructions? This is the step Fable exists for in this
skill — do not delegate it and do not skip it. Route real findings back to a builder spawn
(or fix trivial ones inline) and re-check the diff. One fix-up round is the norm; if the
diff still isn't right after a second, stop and report honestly.

**Verify.** Run the narrowest command that proves the change works (the affected tests, the
project health command, a quick script). Visible/UI work additionally requires real browser
screenshots saved under `.context/screenshots/` with absolute paths in the report, per
project instructions — a DOM check or description does not count.

## Report

Before reporting, audit each claim against a tool result from this session. Only report
work you can point to evidence for; if something is not yet verified, say so explicitly.
If tests fail, say so with the output; if a step was skipped, say that.

Lead with the outcome, in complete sentences:

- What changed and why, with the touched files listed as paths.
- How it was verified (command + result), and screenshots' absolute paths for visual work.
- What each model did (scouts, builders, escalations) — one line, not a log.
- Anything left open or deliberately not done.
- Remind the user the diff is uncommitted on the current branch, ready to review.

On failure, name the phase, the reason, and the state of the working tree.

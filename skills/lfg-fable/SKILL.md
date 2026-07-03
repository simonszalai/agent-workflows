---
name: lfg-fable
description: Fable-variant LFG. Autonomous ticketless end-to-end work on the current branch using the -fable chain's ticketless modes. Commits before and after; never branches, pushes, or opens PRs.
max_turns: 300
---

# LFG (Fable variant)

Take a GitHub issue, error report, or the conversation and deliver the work as commits on the
**current branch**, with no ticket system involved — all coordination through `.context/`
(style: `skills/references/fable-prompting.md`). This is the thin orchestrator over the
`-fable` skills' ticketless modes. For ticket-tracked work use `/ticket-flow-fable`.

You are operating autonomously: proceed without asking for reversible actions, and end your
turn only when the final commit exists or you are blocked on input only the user can provide.
Before reporting, audit every claim against a tool result from this session.

## Hard rules (never violate)

- **Never open a pull request** (`gh pr create` is forbidden).
- **Never create a branch** (`checkout -b`, `switch -c`, `branch <new>` are forbidden).
- **Never push** (with or without `-u`/`-f`).
- **Never use this as a multi-repo epic runner** — work needing cross-repo ordering,
  contracts, or deploy gates routes to `/epic-plan`/`/epic-split`/`/milestone-flow`. Only
  tiny ad-hoc multi-repo edits with no coupling may commit in each repo's current branch.

Reaching for any of these → stop and report back instead.

## Usage

```
/lfg-fable #123 | 123 | <issue URL>     # GitHub issue
/lfg-fable                              # requirements from this conversation
/lfg-fable --skip-verify
```

## Flow

**Checkpoint first.** Confirm a branch is checked out (detached HEAD → STOP and ask). If the
working tree has uncommitted changes, `git add -A` and commit
`chore: checkpoint before /lfg-fable` so the user's pending work is a discrete, separable
commit. Never branch, never push.

**Parse input.** Issue: `gh issue view … --json title,body,labels,author`; type from
labels/keywords (error/fix → bug; otherwise feature). Conversation: extract what to
build/fix, constraints, acceptance criteria from the thread. Bugs: capture service, error
type, timestamp, message when available. If context is genuinely insufficient to start, ask
for the missing specifics and STOP — that is the one legitimate early stop.

**Research & plan.** Write requirements to `.context/source.md`. Features: spawn
`researcher` → `.context/research.md`. Bugs: spawn `investigator` (or `hypothesis-evaluator`
for production incidents) → `.context/investigation.md`. Then spawn `planner-fable` with all
context and write the plan (what / how / why, verification strategy, risks, side effects) to
`.context/plan.md`. **The plan is auto-approved** — proceed straight to build.

**Build.** `/create-build-todos-fable` in ticketless mode (todos →
`.context/build_todos/NN-name.md`), then `/build-fable` in ticketless mode — one Codex GPT
5.5 builder per todo via `external-build`, checkpoints in the todo files' status headers,
bounded self-repair (≤2), health gate owns "done". Blocked → STOP and report the todo;
`needs_replan` → revise the plan before continuing.

**Test.** `/write-tests`; run the new tests and the full suite. Failures here log and
continue to review (non-blocking).

**Review loop.** The cross-review iteration loop from `/review-fable` (ticketless: findings
in `.context/review_todos/`), ≤3 rounds, cross-coverage gate enforced (both peer envelope
files must exist — a missing file means dispatch was skipped; spawn it). Resolve actionable
findings via `/resolve-review-fable`'s **routing and dispatch only** — no commit/push and no
deployment-guide step from that skill; lfg-fable owns its commits and the deploy guide comes
next. After round 3, remaining gated/manual findings go in the follow-up report.

**Wrap up.** `/compound` in autonomous mode (non-blocking). `/create-deployment-guide` in
ticketless mode → `.context/deployment-guide.md` (skip if genuinely no deploy steps;
non-blocking on error).

**Unrelated errors** surfaced anywhere along the way (pre-existing type/lint/review failures
in untouched files): fix the clear, low-risk ones and track them in
`.context/unrelated-fixes.md`; leave risky/ambiguous ones for the follow-up report. They get
their **own** commit — never fold them into the work commit.

**Final commits (per touched repo).** Still on the Phase-0 branch. First, if
`.context/unrelated-fixes.md` has entries, stage exactly those files and commit
`fix: resolve pre-existing lint/type errors surfaced during /lfg-fable` (files + errors in
the body). Then stage only the files this work changed — no `git add -A`; before **every**
commit run `git status --porcelain` and `git diff --staged --stat` and confirm nothing
unexpected is staged (no `.context/`, no other commit's files). Commit with a one-line
conventional subject and a brief body — a commit, not a PR description. Result: up to three
independently reviewable commits per repo (checkpoint / unrelated fixes / work).

## Report

```
LFG (fable) complete!

Branch: {current branch}
Commits:
  {sha} chore: checkpoint before /lfg-fable          # if made
  {sha} fix: resolve pre-existing lint/type errors…  # if made
  {sha} {work commit subject}

Summary:
- {what was built/fixed — outcome first, complete sentences}
- Tests: {passing}/{total}
- Review: {N} rounds, {remaining actionable or "no actionable findings remain"}
- Built by: Codex GPT 5.5 (external-build); planned/reviewed by Fable
- Screenshots: {absolute paths for UI/visual work; otherwise "not applicable"}
- Unrelated fixes: {list or "none"}

Next: review the diff, then push and open a PR when you're ready.
```

On failure, name the phase, the reason, and the commits that do exist. Every number above
must come from a tool result in this session.

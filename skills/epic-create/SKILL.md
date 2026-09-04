---
name: epic-create
description: Create a new autodev epic from a description, a GitHub issue, or existing tickets (absorbed as sources), then plan and split it into milestone step tickets under the shared splitting rules so /epic-flow can run it without a reconciliation pass. Use when asked to create an epic, turn tickets into an epic, or split a large feature into milestones.
max_turns: 150
---

# Epic Create

Create **one** epic and leave it ready to run: canonical plan artifact, gate milestones with
gradable acceptance criteria, and `planned` step tickets that follow
`../references/epic-lifecycle.md` §Splitting rules. This skill exists because epics created by
raw MCP calls (operator or Hermes sessions) kept arriving with steps that could not be tested
apart, foreign-repo work hidden inside a step, staging criteria that only production could
grade, and gate-critical backfills with no deploy row; `/epic-flow` then spent its first hour
reconciling them.

```text
resolve inputs -> create_epic (+ absorb source tickets)
  -> /epic-flow <E> --plan-only        # deep plan, milestones, steps, contracts, planned status
  -> readiness check against §Splitting rules -> report first milestone command
```

## Usage

```text
/epic-create "Replace the rule-based freshness pre-gate with an LLM judge"   # from a description
/epic-create F0331 F0332 B0426        # absorb existing tickets as sources
/epic-create #123                     # from a GitHub issue
/epic-create --dry-run "..."          # write nothing; print the intended epic, milestones, steps
```

## Hard boundaries

- One epic per run. Search first (`list_epics`, `search_tickets`) and stop if a non-terminal
  epic already covers the scope; report it instead of creating a duplicate.
- Absorbed tickets become sources (`absorb_ticket_into_epic`); they are parked, never landed.
  Never absorb a ticket that is `merged` or later.
- Planning and splitting are delegated to `/epic-flow <E> --plan-only`; do not re-implement
  the split here. This skill supplies the inputs and enforces the readiness check afterwards.
- Milestones are gates with acceptance criteria; steps carry `plan` artifacts and `planned`
  status before this skill ends. An epic left with `backlog` steps or criteria-free gates is a
  failed run, not a partial success.
- No product code is written or deployed. Reading code and memory is expected.

## Process

### 1. Resolve inputs

Project from `<!-- mem:project=X -->`; the runner repo from the git remote. Gather the
epic's intent from the argument (description, issue body, or the source tickets' artifacts)
and from the memory system (search the topic, the repos involved, prior incidents). Record the
user's explicit requirements verbatim in the epic description — they are the constraints the
plan critic grades against.

### 2. Create

`create_epic(project, title, description)` with a description that states **why**, **what**
(numbered, one item per observable capability), **constraints**, and **supersedes**. Then
`absorb_ticket_into_epic` for each source ticket. Set `epic_status=planning`.

### 3. Plan and split

Run `/epic-flow <E> --plan-only` in this session. It writes the canonical epic plan, critiques
it, creates milestones and steps, writes every step plan, and sets steps to `planned`.

### 4. Readiness check

Reload the epic (`get_epic`, light) and grade it against §Splitting rules; fix in place, do
not hand the defects to `/epic-flow`:

- Every step is one repo, and no step plan mentions edits in another repo.
- No two steps in one repo share a primitive that prevents testing them apart, unless they
  are on different sides of a gate.
- Each milestone's criteria are observable in staging at that gate; production-time metrics
  and cost baselines sit in the epic's production criteria; no human-labour criteria.
- Every backfill, prompt-row seed, enum, or config insert a criterion depends on is a
  deployment-guide row of that milestone, and a new slot's prompt row is seeded with the
  milestone that adds the enum.
- Model ids, config keys, column names, and cost caps are literal in the plan.
- Validation harness changes live in the step that changes the behaviour; validation steps
  are run-only.
- `depends_on` and `set_epic_member_deps` describe the same edges; steps are ordered by
  `add_epic_step` position.

Record each fix in the epic plan artifact under a "Split reconciliation" heading with the rule
it applied.

## Output

Keep it short: epic id and title; milestones with one-line criteria summaries; step tickets
with repo, milestone, size, and dependencies; source tickets absorbed; the first command
(`/epic-flow <E>` or `/epic-flow <E> --milestone M1`); and a `Not verified:` line naming any
open product or architecture question the plan critic surfaced.

```text
Epic created: E0034 — <title>
M1 (gate): <criteria summary>   steps F0340 (ts-prefect, size 5)
M2 (gate): <criteria summary>   steps F0341 (ts-prefect, size 8) <- F0340; F0342 (ts-dashboard, size 1)
sources: B0426
epic_status: in_progress
Next: /epic-flow E0034

Not verified: none
```

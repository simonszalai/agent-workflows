---
name: epic-milestone-flow
description: Execute one epic milestone's step-ticket DAG. Parallelizes independent cross-repo steps, serializes conflicting same-repo work, calls ticket-flow with epic context, and returns a gate package for epic-auto. No deploy or environment verification.
max_turns: 400
---

# Epic Milestone Flow

Execute one milestone of an epic. This is the milestone-level orchestrator over multiple
`/ticket-flow` runs. It is normally called by `/epic-auto`.

## Boundaries

- Works on one epic milestone at a time.
- May run independent step tickets in parallel when safe.
- Must pass epic context and contracts into each ticket-flow.
- Does not deploy, promote, or verify environments.
- Stops when the milestone's steps are landed/`merged` and a complete gate package exists.
- Full-auto deploy/verify/promotion is owned by `/epic-auto` immediately after this skill returns.

## Usage

```text
/epic-milestone-flow E0007 M2
/epic-milestone-flow E0007 --next
```

## Process

### 1. Load milestone graph

- `get_epic(project, epic_id)`.
- Resolve milestone by display id (`M2`) or choose the first incomplete milestone for `--next`.
- Load all step tickets in that milestone.
- Read parent epic plan, milestone acceptance criteria, blockers, and contracts.

### 2. Validate readiness

Stop if:

- epic has unresolved planning open questions;
- any required blocker from an earlier milestone is not complete/merged;
- cross-repo contracts are missing;
- two same-repo steps are marked parallel but touch overlapping/conflicting areas;
- the milestone has no staging evidence contract. Ask `/epic-auto`/planning to repair the
  milestone before build work continues.

### 3. Build execution waves

Create waves from the blocker -> blocked DAG:

- independent different-repo steps may run in parallel;
- same-repo steps default to serial unless their write scopes are demonstrably disjoint;
- if unsure, serialize.

### 4. Execute each wave

For each step ticket, run `/ticket-flow <ID> --epic-context --target staging` (or the
milestone's configured integration target). The ticket-flow must:

- load the parent epic plan and milestone contract;
- build/review/local-verify the step;
- land according to the milestone target;
- set the step ticket to `merged` after a successful epic-step landing;
- never run staging/production verification and never advance the milestone gate itself.

### 5. Milestone gate package

After all step tickets in the milestone are `merged`, write an epic artifact (use
`deployment_guide` when the artifact type must be chosen) summarizing:

- milestone id and acceptance criteria;
- steps landed, ticket ids, commits/PRs, and repos touched;
- contracts satisfied and any contract tests run;
- local checks and review results;
- staging and production evidence rows that `/ticket-verify --epic --milestone` must grade;
- risks for staging verification and likely failure-to-step mappings;
- the exact next command, normally
  `/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote` after deploy.

Do not run deploy commands or environment verification.

## Output

```text
Epic milestone flow complete: E0007 M2
Steps: 3/3 merged
Gate package: deployment_guide artifact updated
Deploy: not run
Environment verify: not run

Next: /epic-auto continues with staging deploy + milestone verification, or run the printed gate manually.
```

---
name: goal-flow
description: Hands-off execution of related tickets with shared context and integrated delivery gates.
max_turns: 300
---

# Goal Flow

Execute a bounded set of related tickets as one delivery goal without paying the context and
review cost of restarting a full single-ticket workflow for every item.

Use for `/goal`, "multi-ticket", "batch these related tickets", or a hands-off request naming
multiple related tickets. Use `/ticket-flow` for one standalone ticket and `/epic-flow` when an
existing epic/milestone contract already owns the work.

## References and boundaries

Read and follow:

- `../references/execution-economy.md`
- `../references/execution-phases.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`

This skill does not weaken per-ticket lifecycle truth. Plans, build todos, review findings,
deployment guides, and verification evidence stay on their owning tickets in MCP. `.context/` is
scratch only. Production operations still require the permission required by project rules.

Stop rather than silently widen scope when tickets are unrelated, their acceptance criteria
conflict, a dependency is missing, or landing/deployment isolation cannot be proven.

## Usage

```text
/goal F0123 B0042 F0128
/goal --query "related ready tickets for provider ingestion"
/goal F0123 B0042 --staging
```

## Process

### 1. Resolve and freeze the goal

Resolve project/repo and load every ticket once with the bounded `get_ticket_contexts` MCP batch
tool, selecting only the artifact/event types needed for planning. Exclude completed, abandoned,
or epic-owned step tickets unless the user explicitly selected them. Write a compact run-local
manifest containing ticket IDs, source artifact IDs/versions, current statuses, dependencies,
target environment, and branch heads. This is the cache freshness boundary; reuse returned
versions as `known_version` validators instead of refetching unchanged context.

Confirm the set has one shared outcome and that each ticket remains independently gradeable. Build
the dependency DAG. If the tickets actually form an unplanned epic with milestone-level staging
gates, stop and route to `/epic-plan` rather than inventing an implicit epic lifecycle.

### 2. Gather shared context once

Run one bounded codebase/memory search for the goal, then add ticket-specific deltas. Create one
goal context packet containing shared architecture, affected surfaces, known gotchas, dependency
edges, and acceptance criteria indexed by ticket. Reuse it throughout the run; do not make each
worker rediscover the repository.

### 3. Produce one integrated plan with per-ticket ownership

Plan the shared architecture, sequencing, compatibility strategy, landing route, deployment order,
and combined verification matrix once. Preserve per-ticket scope and acceptance mapping. Persist a
plan and DRAFT deployment guide on every ticket: shared sections may be identical, but each artifact
must identify that ticket's owned changes, dependencies, evidence rows, and goal ID. Persist
independent artifact/status writes with `mutate_ticket_workflows`; use atomic mode only when all
operations are one lifecycle unit, otherwise use explicit partial results and handle every item.
Capability-check the endpoint once. Until the server exposes `mutate_ticket_workflows`, group the
bounded sequential MCP mutations inside one orchestrator tool execution and return only a compact
per-operation ledger (operation, ticket/artifact ID, success/error); never spend one model turn per
mutation or echo full updated ticket bodies. Do not claim atomicity when using this fallback.

Use `/auto-plan`'s escalation gates. A routine goal can use one native planner; peer providers are
added only for explicit high risk, material uncertainty, or unresolved disagreement.

### 4. Cluster build work

Cluster build todos by non-overlapping write scope and shared context, not mechanically by ticket.
Each task packet must list:

- the ticket IDs and build-todo artifact IDs it satisfies;
- exact owned paths/surfaces and forbidden overlap;
- dependency inputs and required output contract;
- focused validation commands and the expected compact result.

Dispatch independent clusters in parallel with `fork_turns: "none"`; execute dependent waves in
topological order. One cluster may satisfy several tickets, but every completed change must map back
to its owning ticket artifacts. Stop on unexpected write overlap and re-plan the wave.

Before dispatch, merge proposed clusters that would read the same tickets, PRs, Git history, or
diff surface even when their output labels differ. For branch reconciliation, use one combined
tree-and-lifecycle audit cluster (semantic diff, PR ownership, ticket status) and, only when needed,
one independent merge-mechanics/protection cluster. Do not spawn separate ticket-audit and
diff-audit agents that must rediscover the same branch and ticket context.

### 5. Integrate, test, and review once per coherent diff

After each wave, integrate the clusters and run focused tests. After the final wave, run the goal's
combined regression suite. Review the coherent diff once with ticket/acceptance mappings, then
persist each actionable finding on every affected owning ticket. Use `/review` escalation rules:
light native review for routine diffs; peer/adversarial coverage for safety-critical scope or
evidence-backed uncertainty/disagreement. Resolve findings and rerun affected tests before landing.

### 6. Land and deploy in dependency-safe units

Choose staging-first versus direct-production from the combined highest-risk ticket. Use one PR only
when the tickets are intentionally atomic and their lifecycle/deploy units match; otherwise land
minimal ordered units. Schema and deploy state stay sequential even when code work was parallel.

Invoke `/auto-deploy` for each landing unit. Never mark a later unit deployed after an earlier unit
fails. Record shared deploy output once in the run manifest and backlink it from each affected
ticket's deployment artifact/status event.

### 7. Coalesced verification

Invoke `/ticket-verify` once for the selected ticket set and environment. It must coalesce identical
or compatible evidence checks by surface/query, execute each shared check once, then map the result
to every contract row and ticket it proves. A shared PASS cannot hide a ticket-specific missing row;
verdicts and evidence artifacts remain per ticket.

For staging-first delivery, let the normal promotion gate decide whether tickets can promote. When
promotion must be atomic, use `/ticket-promote` multi-ticket scope in dependency order; otherwise
promote independently eligible units. Production verification is still mandatory.

## Terminal report

Return the goal outcome plus one row per ticket: plan/build/review/test, landed branch/SHA, deploy
steps, verification verdict/artifact IDs, final status, and blocker/next action. Every success claim
must cite concrete evidence. Partial completion is reported explicitly; never flatten it into a
goal-level PASS.

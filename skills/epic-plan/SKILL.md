---
name: epic-plan
description: Deep planning for an autodev epic from absorbed source tickets and epic artifacts. Runs cross-provider Claude/Codex/Grok planning and adversarial review, consolidates context, writes/revises the canonical epic plan, synchronizes milestone pass conditions/gates, and idempotently reconciles epic step tickets/DAG by default.
max_turns: 200
---

# Epic Plan

Create or revise the canonical plan for an **entire epic**, then reconcile the epic's step
tickets against that plan. Use after tickets have been absorbed into an epic or after
substantial epic artifacts have accumulated.

The output is not complete unless it covers the whole epic end-to-end: every milestone (active
or deferred), every planned step needed to satisfy that milestone, and concrete acceptance
criteria for every milestone and step. If a future milestone is intentionally deferred, still
plan its expected steps and pass criteria; mark blockers/prerequisites explicitly instead of
omitting the work.

Important distinction: **planned steps are not automatically tickets**. The epic plan should be
complete and detailed, but ticket reconciliation should create deployable/testable work packages,
not one ticket per planning bullet. Prefer the smallest number of tickets that preserves clear
ownership, deployability, reviewability, and cross-repo contracts.

Default reruns are **incremental and idempotent**: treat the current plan, milestones, existing
steps, and the user's latest requested modifications as the baseline, then update/reconcile only
what changed. Do **not** discard the current plan and start from a blank slate unless the user
explicitly asks for a full replan/from-scratch run.

## Boundaries

- Always deep: no light planning path.
- A canonical epic plan is not valid from one model alone. Unless the user explicitly requests a
  degraded solo run, gather independent planning judgment from the two providers that are not the
  current runner (`claude`, `codex`, `grok`) and run a cross-review/convergence pass.
- By default, also performs the `/epic-split` behavior after the plan is settled: create or update
  missing/stale step tickets, each step ticket's own `plan` artifact, milestone assignments, and
  dependency edges. Use `--plan-only` only when the user explicitly wants a human approval pause
  before step reconciliation.
- Step reconciliation must be idempotent: rerunning `/epic-plan` updates the existing plan and
  matching step tickets instead of duplicating them.
- Ticket granularity must be intentionally coarse enough to avoid dashboard noise. Do not
  blindly convert every planned sub-step into a ticket.
- Does create/update epic milestone metadata, including concrete pass conditions, when the
  backend supports `create_epic_milestone` / `update_epic_milestone`.
- Plans the entire epic by default. `--focus M#` may add extra depth for one milestone, but it
  must not omit the other milestones' step breakdowns or acceptance criteria. `--plan-only`
  skips ticket reconciliation but still writes a full-epic plan.
- Does not build, land, deploy, or verify.

## References

- `../references/epic-lifecycle.md`
- `../references/conductor-multi-repo.md`
- `../references/execution-phases.md`

## Usage

```text
/epic-plan E0007
/epic-plan E0007 --focus M3
/epic-plan E0007 --plan-only
/epic-plan E0007 --from-scratch
```

## Process

1. Resolve project and load `get_epic(project, epic_id)`. `get_epic` is often large (tens of
   KB) and gets spilled to a file — read it with `jq` / offsets, don't try to swallow it whole.
2. Load context in **one parallel batch** — these streams are independent, never serialize them:
   - load all absorbed source tickets with `get_ticket` and read all epic artifacts in
     chronological order;
   - run broad codebase and memory research across involved repos.
3. Determine the planning mode:
   - **Default / incremental:** use the latest current `plan` artifact, milestone rows, existing
     step tickets, and dependency edges as the baseline. Incorporate the user's latest requested
     changes as amendments. Preserve still-valid prior decisions and step IDs.
   - **`--from-scratch` / explicit replan:** ignore prior plan conclusions except as historical
     evidence. Re-derive milestones and steps from source tickets/artifacts. This mode is only
     allowed when the user explicitly requested it.
   - **`--plan-only`:** revise the canonical plan and milestones but skip step-ticket/DAG
     reconciliation.
4. Build the peer-planning packet in `.context/epic-plan/`:
   - source tickets and their artifacts;
   - chronological epic artifacts;
   - latest current plan artifact, if any, clearly labeled as the baseline in incremental mode;
   - current milestone rows/pass conditions, if any;
   - current step tickets, milestone assignments, and dependency edges;
   - codebase and memory research;
   - known constraints, open questions, and explicit non-goals.
5. Run cross-provider planning:
   - Determine the current runner with `agent-workflow-provider`. The current runner is the native
     planner; the other two providers are peers.
   - Run the two peers with `external-agent --task plan --provider <claude|codex|grok>` using the
     peer-planning packet as the source artifact. Claude peers must use the subscription-backed
     `claude -p` path provided by `external-agent`, never a direct API call.
   - If Claude Code is the current runner, use the `external-planner` dispatcher for the non-Claude
     peers; if Codex or Grok is the current runner, call `external-agent` directly for the two
     peers.
   - Save peer envelopes under `.context/epic-plan/<provider>.json`. Do not summarize what a
     provider "would" say; actually run the providers and consume their JSON.
   - Stop instead of accepting a one-provider plan if fewer than two providers return usable
     plans.
6. Run cross-review and convergence:
   - Create `.context/epic-plan/plan-bundle.md` containing the native draft plus every usable peer
     draft, assumptions, evidence, disagreements, proposed milestones, and proposed pass criteria.
   - Run at least one adversarial review pass where each available provider reviews the combined
     bundle, calls out weak sequencing, missing milestone gates, unsafe assumptions, YAGNI issues,
     and contradictions with source tickets/artifacts.
   - Drive material disagreements to evidence-backed convergence. If uncertainty affects the
     plan, milestone split, pass criteria, data safety, or deployability, keep it as an explicit
     open-question blocker rather than hiding it in prose.
   - The final plan may choose one provider's proposal, synthesize several, or reject peer advice,
     but every material disagreement must be listed with how it was resolved or why it remains
     blocked.
7. Consolidate the design:
   - latest confirmed decisions override earlier drafts;
   - in incremental mode, the existing canonical plan remains authoritative for unchanged areas;
   - user-requested modifications are amendments to the current plan, not an excuse to replan
     unrelated areas;
   - duplicates collapse;
   - contradictions become open questions, not guesses.
8. Draft the epic plan for the **entire epic**. **Code-grounding rule:** before naming
   files/modules in step plans, READ them; every file/module claim needs a `path:line` citation
   or an explicit "unverified assumption" label. The plan covers:
   - goal and non-goals;
   - source-ticket synthesis: what each absorbed ticket contributes, supersedes, or makes obsolete;
   - milestone table: `M#`, title, description, pass/acceptance criteria, gate flag, and what
     evidence proves each criterion is met;
   - complete planned step-ticket breakdown for **every milestone**, including deferred/future
     milestones. This breakdown may include sub-steps inside a larger ticket. For each ticket or
     sub-step include:
     - stable step title and intended repo;
     - goal and non-goals;
     - milestone assignment;
     - dependencies/blockers;
     - implementation scope;
     - acceptance criteria / evidence;
     - migration/config/deploy notes where relevant;
     - cross-repo contracts consumed or exposed;
     - expected repo workspace requirement if the step is not in the current repo;
   - cross-repo contracts to create;
   - repo/workspace availability assumptions for every involved repo;
   - risks, rollback/promotion strategy, verification gates.
   Do not write vague placeholders such as "future work", "TBD", or "define later" for a
   milestone's steps unless the plan also explains the concrete blocker and the exact decision
   needed to unblock the step.
   - **Runtime evidence closure:** for every milestone gate whose acceptance criteria mention
     runtime behavior (for example: "canary run", "observer", "flow", "deployment", "stores
     rows", "polls", "scheduler", "worker", "Prefect", "supervisor", "webhook", or "live
     readback"), explicitly list `required evidence -> producing step(s) -> deploy surface`.
     A schema/parser/model-only step set cannot satisfy stored-row, flow-run, or deployment
     evidence unless the same milestone also includes one of:
       - a Prefect flow/deployment entry in the relevant environment YAML;
       - supervisor/worker registration when the runtime pattern requires one;
       - an explicit bounded canary/CLI owned by the deploy plan that writes durable evidence
         rows; or
       - a deliberately revised gate that verifies repository behavior in a disposable
         integration DB instead of claiming staging runtime evidence.
     Do not push the runtime surface to a later milestone while the current gate depends on it.
9. Run the bounded adversarial critic loop (≤3 rounds):
   - spawn **parallel** critics covering completeness, correctness, YAGNI, sequencing, data
     safety, deploy/verify gates, milestone independence, and cross-repo contracts;
   - each critic returns findings with the explicit schema
     `{title, severity: p1|p2|p3, area, issue, suggestion, lens}` (the same shape as
     plan-fanout's criticOutputSchema);
   - an empty findings list is acceptable — do NOT invent issues to appear thorough;
   - after each round, revise the plan against the findings, then re-run the critics;
   - stop early when a round leaves no unresolved p1 findings; hard cap at 3 rounds.
10. Unresolved p1 findings **block progression**. Stop for user decisions if critics expose
   unresolved product/architecture choices; do not continue to artifact writes or step
   reconciliation with an open p1.
11. Write the canonical `plan` epic artifact:
    - if no live `plan` artifact exists, create it via `create_epic_artifact`;
    - if a live/current `plan` artifact already exists, update it via `update_artifact` with a
      change note rather than creating a duplicate plan artifact;
    - mark metadata with whether the run was incremental, plan-only, or from-scratch.
12. Synchronize milestone rows and pass conditions:
    - compare the planned milestone table against `get_epic(...).milestones`;
    - for each missing planned milestone, call `create_epic_milestone(...)` with named arguments:
      `project`, `epic_id`, `title`, `description`, `acceptance_criteria`, `position`,
      `is_gate=True`, and `command="/epic-plan"`;
    - for each existing milestone whose title, description, position, gate flag, or
      `acceptance_criteria` no longer matches the canonical plan, call
      `update_epic_milestone(..., command="/epic-plan")` with the corrected fields;
    - pass conditions must be concrete and checkable from artifacts/logs/deploy evidence. Do not
      write generic criteria like "works", "implemented", or "tests pass" without the specific
      observable behavior/evidence;
    - every milestone row, including deferred milestones, must have non-empty acceptance criteria
      that describe either (a) what proves the milestone complete when executed, or (b) the exact
      prerequisite/decision that keeps it deferred;
    - preserve already-valid human-authored criteria, but tighten vague criteria rather than
      leaving a gate empty.
13. Reconcile step tickets, per-ticket plans, and the DAG unless `--plan-only` was explicitly
    requested:
    - derive the desired **ticket set** from the final plan; do not default to one ticket per
      planned sub-step;
    - first run a granularity pass:
      - target roughly 1-3 execution tickets per milestone by default, unless the milestone is
        unusually large;
      - combine tightly coupled design/build/verification sub-steps when they share the same repo,
        deploy together, and should be reviewed together;
      - split tickets only for real boundaries: different repos, independent deployability,
        distinct risky migrations/schema changes, separate owners, blocked vs unblocked work,
        or work that can land safely in parallel;
      - do not create standalone "decision", "monitoring", "runbook", or "validation" tickets
        when they are acceptance criteria of the implementation ticket and do not need independent
        build/deploy work;
      - keep one ticket per repo for cross-repo provider/consumer work, with the contract written
        into both sides;
      - if the proposed ticket set feels like project-management noise, merge before creating
        tickets;
    - include desired steps for every milestone in the final plan, not only the current active
      milestone. If creating far-future tickets would be harmful, still include them in the
      plan and explicitly mark the reconciliation exception in the final report;
    - one step = one repo; split cross-repo work into provider/consumer tickets;
    - never hide a required third repo inside an existing step; create/update a step for that repo
      and report it as needing a linked Conductor workspace if no path is available;
    - assign every step to the intended milestone;
    - build an acyclic blocker -> blocked DAG;
    - write cross-repo contracts into both sides of each cross-repo dependency;
    - match desired steps to existing epic steps by repo + title/intent + milestone + source
      artifact content before creating anything new;
    - update matching backlog/planned step tickets whose scope or contract changed;
    - preserve ticket IDs for still-valid steps and never create duplicate tickets for the same
      step intent;
    - create only missing steps with `create_ticket(..., epic_id=..., milestone_id=...)`;
    - when a rerun discovers over-split planned tickets that are not started:
      - choose one keeper ticket per merged work package;
      - update the keeper's title, source/plan artifacts, summary, status, milestone, and
        dependencies to cover the merged scope;
      - detach stale duplicate/absorbed tickets from the epic with `remove_epic_step` and set them
        to `abandoned` only when the user explicitly authorized cleanup/merge in the current turn;
      - record the merge mapping in the final report;
    - for every desired non-completed step ticket, create or update a ticket-level `plan`
      artifact via `create_artifact(..., artifact_type="plan")` or `update_artifact(...)`:
      - the source artifact explains **what** the step is; the ticket plan must explain **how**
        that exact step should be built and verified;
      - include the step goal, non-goals, implementation approach, ordered build phases,
        repo-local files/modules likely touched, migrations/config/deploy notes, test plan,
        acceptance evidence, rollback/kill-switch notes, and cross-repo contracts consumed or
        exposed;
      - keep it scoped to that one repo/step, not a copy of the epic plan;
      - update existing live/current `plan` artifacts when the step scope changes instead of
        creating duplicates;
      - immediately after each step's plan artifact is created or updated, call
        `update_ticket(..., status="planned", summary_bullets=[...], command="/epic-plan")` for
        that step ticket so generated plans do not leave tickets in `backlog`;
      - do not rewrite merged/completed step plans; create a follow-up ticket if new planning is
        needed after completion;
    - use `add_epic_step`, `assign_epic_step_milestone`, and `set_epic_member_deps(replace=True)`
      to make order, milestone assignment, and edges match the desired DAG;
    - do not detach/abandon/delete stale existing steps by default. If a step is obsolete, report
      the proposed removal and only remove it when the plan or user explicitly authorizes that
      cleanup. Never rewrite merged/completed steps; create follow-up steps if new work is needed.
14. Re-load the epic and verify every planned gate milestone exists, has non-empty acceptance
    criteria, has the intended `is_gate` value, and can be satisfied independently without later
    milestones. For each gate, re-run the runtime evidence closure check above against the final
    reconciled step set; if any required runtime evidence lacks a producing same-milestone
    step/deploy surface, revise the plan/split before returning. Also verify reconciled non-completed steps each have a current ticket-level
    `plan` artifact, have ticket status `planned`, are assigned to milestones, dependency edges
    are acyclic, cross-repo edges have contracts, warnings are empty, and no duplicate step tickets
    were created. If the backend
    lacks milestone, step, or artifact update support, explicitly report that limitation and
    include the exact criteria/step/plan edits to enter manually.

## Output

Report:

- canonical plan artifact title/id;
- provider participation and cross-review/convergence summary;
- milestones/gates and the milestone rows/criteria created or updated;
- step-ticket reconciliation table: reused/updated/created/unchanged/stale-proposed-removal,
  milestone assignment, blockers, per-ticket plan artifact id plus ticket status, and cross-repo contracts;
- open questions, if any;
- if `--plan-only` was used, recommended next command: `/epic-split E0007 --reconcile`;
- otherwise recommended next command is the appropriate execution command, not `/epic-split`.

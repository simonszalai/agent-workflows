---
name: epic-flow
description: >-
  Autonomous epic orchestrator: plan and split the epic into milestone step tickets, then for
  each milestone run the step tickets through /ticket-flow, deploy the milestone to staging, and
  pass the /ticket-verify --epic gate; with `prod`, promote and verify production via
  /ticket-promote --epic and /ticket-verify production --epic.
max_turns: 100
---

# Epic Flow

Execute an **entire epic** (or one milestone of it) with the correct MCP ceremony. The model does
the work; this skill defines the sequencing and the hand-offs:

```text
load epic -> plan + split (only if missing/stale)
  -> for each milestone in order:
       run step tickets (/ticket-flow <ID>, DAG order) -> all steps merged
       -> /ticket-deploy staging                         # milestone staging deploy
       -> /ticket-verify staging --epic E --milestone M --no-promote
       -> repair inside the milestone until PASS
  -> stop (default)  |  prod: /ticket-promote --epic E -> /ticket-verify production --epic E
```

## Usage

```text
/epic-flow E0007                  # all milestones through staging gates, then stop
/epic-flow E0007 prod             # continue through production promotion to completed
/epic-flow E0007 --milestone M2   # run one milestone and its staging gate
/epic-flow E0007 --plan-only      # plan/split/readiness only; build nothing
```

`prod` is the explicit human authorization for production promotion/deploy after every
milestone staging gate is an exact `PASS`. Never infer it.

## References

- `../references/epic-lifecycle.md` — milestones, contracts, evidence placement, `epic_status`
- `../references/ticket-lifecycle.md` — epic-step ticket statuses
- `../references/staging-autonomy.md` — what a milestone repair loop may do on its own

## Hard boundaries

- One epic per run. Milestones strictly in order; never start milestone N+1 before milestone N
  has a staging gate `PASS` with all three evidence artifacts (epic gate artifact, per-step
  `verification_evidence`, epic summary).
- This skill owns sequencing, gates, and deploy order — not design. Do not rewrite the
  mechanism/API/approach in an epic or step `plan` artifact from inside the milestone loop; if a
  readiness check says the design must change, re-enter the plan/split phase explicitly and
  record why.
- Step tickets land only on the milestone integration target (normally `staging`) and are set to
  `merged` by their `/ticket-flow`; this skill never sets per-step verification statuses
  itself — `/ticket-verify --epic` and `/ticket-promote --epic` do.
- Production is touched only with `prod`, only after the last milestone's staging `PASS`, and
  only through `/ticket-promote --epic` + `/ticket-verify production --epic`.
- Any remediation that changes product code/config/auth is a new fix step ticket attached to the
  failing milestone and goes through `/ticket-flow` — never an untracked branch or inline patch.

## Process

### 1. Load

Resolve project from `<!-- mem:project=X -->` and repo from the git remote. Load
`get_epic(project, epic_id, detail="light")` once; fetch `plan` / `deployment_guide` /
`verification_evidence` bodies with `detail="full"`, selected `artifact_types`, and a byte budget
only when needed. Cache the response for the run and reload only after this run mutates the epic
or a milestone completes. If the epic's repos don't include the current repo, stop and report.

Record `epic_status`, milestones (order, `is_gate`, acceptance criteria, recorded gate verdicts),
step tickets (status, repo, milestone, deps), and absorbed source tickets.

### 2. Plan and split (only when missing or stale)

Required when any of: no canonical epic `plan` artifact; a milestone with missing/vague
acceptance criteria; a milestone without steps; a step ticket without its own `plan` artifact;
a step still in `backlog` with a plan; cross-repo edges without contracts in both tickets.

Planning is always deep (`epic-lifecycle.md` §Epic planning): read all epic artifacts and
absorbed source tickets, research code and memory, consolidate contradictions by recency,
write/update **one** canonical epic `plan` artifact on the epic, critique it adversarially, and
stop on genuine product/architecture open questions.

Split idempotently — reconcile, never delete/recreate:

- milestones: `create_epic_milestone(project, epic_id, title, position, acceptance_criteria,
  is_gate=True)` for missing checkpoints; refresh stale criteria. No criteria-free gates.
- steps: one repo per step; `create_ticket(project, repo, ..., epic_id, milestone_id,
  depends_on, related=[E], status="backlog")` only for missing steps; then
  `add_epic_step(project, epic_id, ticket_id, repo, position, milestone_id)` and
  `set_epic_member_deps(project, epic_id, edges=[...])`. Keep `depends_on` and member deps
  describing the same edges.
- every non-completed step gets its own ticket-level `plan` artifact (goal/non-goals, approach,
  files, contracts consumed/exposed, tests, acceptance evidence, deploy/rollback notes), then
  `update_ticket(status="planned", summary_bullets=[...])` immediately.
- for every cross-repo edge, write the contract in both step tickets (provider exposes /
  consumer reads).

A milestone is valid only when it is an independently observable risk boundary: acceptance
criteria, staging + production deployment-guide evidence, and no dependency on unbuilt later
milestones. Fix the plan/split rather than faking a gate. Set `epic_status` to `in_progress`
when leaving planning. With `--plan-only`, stop here and report the first milestone command.

### 3. Milestone loop

For each milestone in order (or the single `--milestone`):

1. **Skip check** — a recorded staging `PASS` whose included steps still match their landed
   commits is done; move on.
2. **Build steps** — walk the step DAG in dependency waves. Each step runs as its own fresh
   `/ticket-flow <ID>` (delegate to a subagent with only: epic id, milestone id, the milestone's
   acceptance criteria, this step's contracts, and the integration target). Parallelize a wave
   only when repos/write scopes don't overlap. A step is done when `/ticket-flow` reports it
   `merged` on the integration target with plan artifact present. Already-`merged` steps are not
   rebuilt.
3. **Deploy** — after all steps are `merged`, deploy the integration target to staging with
   `/ticket-deploy staging` (no-ticket mode: local health + CI + project staging deploy steps)
   from the milestone's repo(s), in the order the deployment guide requires (schema first).
   Merged code is not deployed runtime evidence; never skip this.
4. **Gate** — set `epic_status=to_verify_staging`, then run
   `/ticket-verify staging --epic <E> --milestone <M> --no-promote`. Accept only an exact `PASS`
   plus the three evidence artifact ids. A `PASS` missing an evidence destination re-enters the
   verifier's evidence write, not the milestone.
5. **Repair** — on `FAIL`: classify with `staging-autonomy.md`. Infra/config repairs that are
   `staging_safe` run directly, then re-deploy and re-verify. Code/config/auth fixes become a new
   fix step ticket in this milestone run through `/ticket-flow`, then re-deploy and re-verify.
   Stop with `STOPPED` after two no-progress repair rounds; surface `BLOCKED` only for
   `human_required`/`agent_incapable`. Never advance past a failed gate.
6. For milestones after the first, confirm the verifier included a regression subset of earlier
   passed gates; a regression is a failure of *this* milestone.

After the last milestone's `PASS`, set `epic_status=staging_verified`. Without `prod`, stop.

### 4. Production (`prod` only)

```text
/ticket-promote --epic <E>            # verified step commits, milestone order; sets to_verify_prod
/ticket-verify production --epic <E>  # final gate; sets completed on PASS
```

Relay their terminal reports verbatim. On production `FAIL`, remediation is a new fix step
ticket through the milestone loop, then re-promote; never patch production inline.

## Output

Report: epic id and mode; each milestone's gate verdict with canonical gate artifact id, per-step
evidence artifact ids, and epic summary artifact id; step tickets and status changes; deploy /
promote commands run; final `epic_status`; and the next command or exact blocker. Keep staging
success distinct from production success — only a production `PASS` with `epic_status=completed`
is complete. End with a `Not verified:` line naming anything claimed but not exercised, e.g.:

```text
Epic flow: E0007 (staging)
M1: PASS  gate <id>; steps F0120 F0121 <ids>; summary <id>
M2: PASS  gate <id>; steps F0122 <id>; summary <id>
epic_status: staging_verified

Not verified: production (run /epic-flow E0007 prod)
```

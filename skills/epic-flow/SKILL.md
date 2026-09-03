---
name: epic-flow
description: >-
  Autonomous epic orchestrator: plan and split the epic into milestone step tickets, then for
  each milestone run the step tickets through /ticket-flow, deploy the milestone to staging, and
  pass the /ticket-verify --epic gate; with `prod`, promote and verify production via
  /ticket-promote --epic and /ticket-verify production --epic. One workspace orchestrates the
  whole epic: steps and deploys in other repos run in Conductor workspaces it creates and
  polls through the Conductor MCP.
max_turns: 100
---

# Epic Flow

Execute an **entire epic** (or one milestone of it) with the correct MCP ceremony. The model does
the work; this skill defines the sequencing and the hand-offs. The session that runs this skill
is the **orchestrator**; it lives in one repo's workspace (the *runner repo*) but owns every repo
in the epic — work in other repos is dispatched to sibling Conductor workspaces (§Remote repos).

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
- `../references/model-prompting.md` — effort defaults, context continuity, bounded waiting
- Conductor MCP (`mcp__conductor__*`: `create_workspace`, `create_session`, `send_message`,
  `list_messages`, `get_session_status`, `list_project_workspaces`, `run_sql`) — remote repos

## Hard boundaries

- One epic per run. Milestone **gates** strictly in order: never deploy or gate milestone N+1
  before milestone N has a staging gate `PASS` with all three evidence artifacts (epic gate
  artifact, per-step `verification_evidence`, epic summary). Building steps ahead of the gate is
  allowed under the build-ahead rule (§3.2); deploying or verifying them is not.
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
- Writes to another repo happen only inside a Conductor workspace for that repo. Never clone,
  worktree, commit, push, or deploy a foreign repo from the orchestrator's filesystem (a
  shallow read-only clone for reading contracts is fine). If no Conductor workspace can be
  obtained, stop and report the exact command to run there — do not improvise.
- Remote workspaces are workers, not orchestrators: they receive exactly one `/ticket-flow`,
  `/ticket-deploy`, or `/ticket-verify` command per session and never `/epic-flow`.

## Run budget

An epic run is long, so the orchestrator's own overhead is the cost that compounds. A 2026-09-03
E0031 run spent 4h19m: about half blocked on strictly serial subagents, a fifth on its own
re-reading and tool-catalog introspection after compactions, and 30 minutes polling a stalled
worker at 5-minute sleeps. These rules exist to stop that:

- **Read once.** CLAUDE.md, this skill, its references, the Conductor skill, and tool catalogs
  (`ALL_TOOLS` filters) are read exactly once per run, at load. After a context compaction, do
  not re-read them; continue from the compaction summary plus the run-state note below. Reload a
  reference only when a concrete decision needs a rule you cannot recall.
- **Run-state note.** Keep `.context/epic-<E>-run-state.md` (scratch, not a ticket artifact)
  with: epic/milestone ids, integration target, step tickets and their last confirmed status,
  workspace/session ids and deep links, deploy report shas, gate artifact ids, and the next
  action. Update it at every milestone transition and before any long wait so a compaction or
  a resumed run costs one file read, not a re-derivation.
- **Effort.** Follow `../references/model-prompting.md`: the orchestrator and every worker it
  spawns run at that model's default effort; escalate one step only after a measured failure at
  the lower effort. Never set `xhigh` as the standing effort for the orchestrator, forked
  subagents, or remote workspaces.
- **Waits are bounded and event-shaped.** Local forked subagents: `wait_agent` with a timeout of
  at most 5 minutes, then re-check status and wait again; no `sleep`. Remote sessions: poll
  `get_session_status` + `list_messages(after=...)` every 2–3 minutes; no fixed `sleep 300`
  loops longer than that. Every poll result is compared against the previous one for progress.
- **Stall detection.** A worker with no new tool activity for 10 minutes, or one still reading
  skills/docs, introspecting tools, or troubleshooting tool access 10 minutes after its command
  was sent, is stalled. Send one `send_message` that names the first concrete action (the file to
  open, the command to run) and restates the tool boundary; if the next poll shows no
  implementation activity, apply §Remote repos.4 (one fresh session, then `STOPPED`). Do not
  keep nudging.
- **Step count is a signal.** If the orchestrator's own tool calls since the last milestone
  transition exceed ~60 without a status change in any ticket or gate, stop deriving and write
  the run-state note, then take the next command in §3 directly.

Anti-overplanning applies throughout: when you have enough information to act, act. Do not
re-derive facts already established, re-litigate a decision already made, or narrate options you
will not pursue.

## Process

### 1. Load

Resolve project from `<!-- mem:project=X -->` and repo from the git remote. Load
`get_epic(project, epic_id, detail="light")` once; fetch `plan` / `deployment_guide` /
`verification_evidence` bodies with `detail="full"`, selected `artifact_types`, and a byte budget
only when needed. Cache the response for the run and reload only after this run mutates the epic
or a milestone completes.

Record `epic_status`, milestones (order, `is_gate`, acceptance criteria, recorded gate verdicts),
step tickets (status, repo, milestone, deps), and absorbed source tickets. Record the **runner
repo** (current git remote) and the set of **remote repos** = epic repos minus the runner repo.
The runner repo need not be one of the epic's repos; then every step is remote. If remote repos
exist and the Conductor MCP is unavailable in this session, say so up front and continue only
through the plan/split phase (§2) — building would stop at the first remote step.

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
   `/ticket-flow <ID>` with only: epic id, milestone id, the milestone's acceptance criteria,
   this step's contracts, and the integration target. Runner-repo steps are delegated to a
   subagent; remote-repo steps are dispatched as a session in that repo's workspace
   (§Remote repos). Parallelize a wave only when repos/write scopes don't overlap — different
   repos always qualify, since they are separate workspaces. A step is done when the ticket is
   `merged` on the integration target with plan artifact present (confirm with `get_ticket`,
   not only the session's text). Already-`merged` steps are not rebuilt.

   **Build ahead.** While milestone N is building, deploying, or gating, dispatch any step of
   a later milestone whose `depends_on` are all `merged`, whose repo is not touched by any step
   of milestone N, and whose contracts are fully written. Such steps land on their integration
   target and rest at `merged`; they are deployed and gated only when their own milestone's
   turn comes, in order. Build-ahead never applies to steps sharing a repo with an in-flight
   milestone (its gate must see a stable integration target) and never to deploy or verify.
   Record every build-ahead dispatch in the run-state note.
3. **Deploy** — after all steps are `merged`, deploy the integration target to staging with
   `/ticket-deploy staging` (no-ticket mode: local health + CI + project staging deploy steps)
   in every repo that has a step in this milestone, in the order the deployment guide requires
   (schema first). Runner repo: run it here. Remote repos: one session per repo in its workspace
   (§Remote repos), sequentially when the guide orders them, otherwise concurrently. Keep each
   repo's deploy report (repo, integration-target sha, result, session link); the gate needs all
   of them. Merged code is not deployed runtime evidence; never skip this.
4. **Gate** — set `epic_status=to_verify_staging`, then run
   `/ticket-verify staging --epic <E> --milestone <M> --no-promote` from the orchestrator (it
   reads staging externally; no foreign checkout needed), passing the per-repo deploy reports
   as context. Accept only an exact `PASS` plus the three evidence artifact ids. A `PASS`
   missing an evidence destination re-enters the verifier's evidence write, not the milestone.
   The gate grades the milestone's acceptance criteria and each step's deployment-guide
   evidence rows under ticket-verify's §5 evidence bound; it is not a second review of the
   code and does not invent extra producers, workflow runs, or oracles beyond that bound.
5. **Repair** — on `FAIL`: classify with `staging-autonomy.md`. Infra/config repairs that are
   `staging_safe` run directly (in the owning repo's workspace), then re-deploy and re-verify.
   Code/config/auth fixes become a new fix step ticket in this milestone run through
   `/ticket-flow` (local or remote per its repo), then re-deploy and re-verify.
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

Relay their terminal reports verbatim. `/ticket-promote --epic` runs from the orchestrator for
the runner repo and as one session per remote repo, in deployment-guide order; the final
`/ticket-verify production --epic` runs once, from the orchestrator. On production `FAIL`,
remediation is a new fix step ticket through the milestone loop, then re-promote; never patch
production inline.

## Remote repos

Any step, deploy, repair, or promotion whose repo is not the runner repo runs in a Conductor
workspace for that repo, driven through the Conductor MCP:

1. **Workspace** — one per (epic, repo), reused for the whole run. Find an existing one first
   (`list_project_workspaces` / `run_sql`, name `epic-<E>-<repo>`); otherwise
   `create_workspace(repo=<repo URL or Conductor project>, branch=<integration target>,
   name="epic-<E>-<repo>")` with the same agent as the orchestrator at that model's default
   effort from `../references/model-prompting.md`, unless the repo's settings override it.
   Never archive it mid-run; report its deep link.
2. **Session** — `create_session(workspace, prompt)` with exactly one command and its context:
   `/ticket-flow <ID>` + epic id, milestone id, acceptance criteria, this step's contracts, and
   the integration target; or `/ticket-deploy staging` (no ticket) for a milestone deploy; or
   `/ticket-promote --epic <E>` for production. Nothing else — the worker must not re-plan the
   epic or touch other milestones. The prompt also carries two lines verbatim: "Use only the
   MCP tools injected into this session; if one is missing or unauthenticated, report BLOCKED
   with the tool name — never build a custom client or inspect credentials." and "Read the
   skill and repo instructions once, then start implementing; your first edit should land
   within the first few tool calls after the plan artifact exists."
3. **Poll** — `get_session_status` plus `list_messages(session, after=<lastMessageId>)` every
   2–3 minutes (§Run budget); compare each result with the previous one for progress. Treat
   the session's terminal report as the worker's claim and confirm the fact in the source of
   truth: `get_ticket` status `merged` for steps, the deploy report's sha/result for deploys.
   A session that asks a question gets one `send_message` answer only when the answer is
   already in the orchestrator's context (contracts, acceptance criteria, integration target);
   anything else is a blocker to surface, not something to invent.
4. **Failure** — a session that errors, stalls (§Run budget stall detection, after its one
   corrective message), or ends without the expected status is retried once with a fresh
   session in the same workspace and the prior report attached; the second failure is a
   `STOPPED`/`BLOCKED` for this milestone, reported with the workspace link and last message.
   Never run two live sessions for the same step in the same workspace.
5. **Concurrency** — different repos in the same wave run as concurrent sessions; two sessions
   never write the same repo's integration target at once.

No Conductor MCP (local CLI, or the server is down): do not fall back to cloning the repo.
Finish everything the runner repo can do for the current milestone, then stop with `WAITING`
and the exact `/ticket-flow` / `/ticket-deploy` commands to run in a workspace for each remote
repo; re-running `/epic-flow` afterwards resumes from ticket state.

## Output

Report: epic id and mode; each milestone's gate verdict with canonical gate artifact id, per-step
evidence artifact ids, and epic summary artifact id; step tickets and status changes; deploy /
promote commands run per repo, with remote workspace/session deep links; final `epic_status`;
and the next command or exact blocker. Keep staging
success distinct from production success — only a production `PASS` with `epic_status=completed`
is complete. End with a `Not verified:` line naming anything claimed but not exercised, e.g.:

```text
Epic flow: E0007 (staging)
M1: PASS  gate <id>; steps F0120 F0121 <ids>; summary <id>
M2: PASS  gate <id>; steps F0122 <id>; summary <id>
remote: ts-dashboard -> <workspace link> (F0121 session <link>, deploy session <link>)
epic_status: staging_verified

Not verified: production (run /epic-flow E0007 prod)
```

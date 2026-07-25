---
name: epic-flow
description: Fully autonomous epic orchestrator. Plans/splits, runs milestone flows that deploy and verify each staging gate, then promotes/deploys/verifies production when explicitly authorized.
max_turns: 100
---

# Epic Flow

End-to-end epic execution coordinator. Use this when the user asks to run an epic, execute an
entire epic, continue across milestones, or do it without further human intervention.

## Operating modes

`/epic-flow` has two modes:

- **Full-auto** — enabled by `--full-auto` or by an explicit user request like "execute the whole
  epic" / "without me". This mode is authorized to invoke milestone-flow, which itself deploys and
  verifies each staging gate, plus production promotion and final verification after all milestone
  gates pass.
- **Gate-stop** — enabled by `--stop-at-gates` or by an ambiguous/manual request. This mode plans,
  splits, and stops before invoking a milestone gate if the user has not authorized deploy/verify.
  Do not call `/milestone-flow` in gate-stop as a "build-only" substitute; milestone-flow is a
  deploy+verify command.

Never silently choose gate-stop when the user explicitly asked for a hands-off/full-auto epic.
Never advance to a later milestone until the current milestone's staging gate has passed.

## Usage

```text
/epic-flow E0007 --full-auto       # run the whole epic, including gates
/epic-flow E0007                   # infer full-auto only if the user's request authorized it
/epic-flow E0007 --staging-only    # stop after every milestone is staged and verified
/epic-flow E0007 --milestone M2    # run one milestone and its gate
/epic-flow E0007 --stop-at-gates   # plan/split/readiness only; stop before milestone-flow deploy+verify
```

## References

Read before acting:

- `../references/execution-economy.md`
- `../references/epic-lifecycle.md`
- `../references/conductor-multi-repo.md`
- `../references/ticket-lifecycle.md`
- `../references/landing-policy.md`
- `../references/deployment-ownership.md`

## Full-auto process

### 1. Load and normalize the epic

- Load `get_epic(project, epic_id, detail="light")` for structure/manifests. Request only the
  needed `plan`, `deployment_guide`, or `verification_evidence` bodies with `detail="full"`,
  selected `artifact_types`, and an explicit `response_byte_budget`.
- Cache that response/version as the orchestration snapshot and pass bounded milestone extracts to
  milestone-flow. Reload only after `/epic-plan`, `/epic-split`, or a completed milestone mutates
  the epic; do not re-read the unchanged full epic between routing decisions.
- Create one active bounded, versioned shared packet per milestone under
  `.context/epic-flow/<EPIC_ID>/<MILESTONE>/`. Store immutable packet bodies as
  `packets/v<NNN>.md` and atomically replace `current.json`, which names the version, relative path,
  and SHA-256 of the exact packet bytes. Write a temporary packet, hash it, move it to its immutable
  versioned path, then write and atomically rename the manifest. Never edit a published version.
- The packet contains only the parent plan/acceptance contract, step/DAG summary, repo/path/branch
  map, relevant knowledge, activation/deploy constraints, and required return/checkpoint schemas.
  Cap the packet body at 16 KiB; summarize or reference immutable artifact IDs/paths rather than
  exceeding the cap. Delegated work receives the active packet path, version, and SHA-256, not
  duplicated epic history. Every consumer verifies the hash and records the version/hash it used in
  its terminal result.
- Advance the packet version only when a source artifact, epic structure, contract, relevant
  knowledge, or completed milestone checkpoint changes. Consumers reload MCP/source context only
  after the manifest advances or when a specifically named missing fact is required. Route a
  missing-fact request to the orchestrator for a bounded packet update; do not independently reload
  the whole epic.
- If the epic spans multiple repos, resolve every involved repo to an actual Conductor workspace
  path or linked directory using `conductor-multi-repo.md`. Declare a repo missing only on
  **positive evidence of absence**: check the Conductor workspace map, linked directories inside
  the current workspace, and the sibling workspace paths named by `conductor-multi-repo.md`, and
  record the exact paths checked. A failed first lookup is not "missing" — false positives here
  have wrongly blocked milestones. Only after that full sweep still finds nothing, stop before
  invoking milestone-flow and report the missing repo/path requirement plus the checked paths.
- If no canonical epic plan exists, or milestone pass conditions are missing/vague/stale, run
  `/epic-plan`; that skill owns synchronizing milestone gate criteria from source tickets and
  artifacts.
- If milestones, step tickets, dependency edges, cross-repo contracts, ticket-level plan
  artifacts, or step ticket `planned` statuses are missing or stale, run `/epic-split`.
- Re-check the plan after splitting. A milestone is valid only when it is an independently
  stageable/observable risk boundary: it has acceptance criteria, deployment-guide evidence for
  staging and production, and does not require unbuilt later milestones to pass its gate. If that
  is not true, improve the plan/split before building; do not paper over the gap with a fake gate.
- Before the first build, create and validate the non-mutating deployment/config ownership
  inventory. A fully autonomous straight-to-production run uses `mode="straight_to_prod"` and
  blocks on unresolved owners, missing owner workspaces, absent third-repo config steps, or an
  incomplete deployment guide. `--staging-only` uses `mode="staging_only"`: preserve the same gaps
  as `record_only` without falsely blocking unrelated staging work.

### 2. Walk milestones in order

For each milestone in dependency order:

1. If the milestone already has a recorded staging `PASS` and every included step still matches
   the verified commits, skip to the next milestone.
2. Run `/milestone-flow <EPIC_ID> <MILESTONE>` to execute the step-ticket DAG **and the staging
   gate**. That skill owns ticket parallelism, gate package creation, `/auto-deploy <EPIC_ID>
   staging`, `/ticket-verify staging --epic <EPIC_ID> --milestone <MILESTONE> --no-promote`, and
   any milestone-local fix/redeploy/reverify loop. Dispatch it with `fork_turns: "none"` and only
   the active milestone packet path/version/hash plus the exact command and expected result schema.
3. Accept milestone success only when `/milestone-flow` reports a staging `PASS` and artifact ids
   for all required evidence destinations:

   - canonical milestone-gate `verification_evidence` artifact on the epic;
   - full `verification_evidence` artifact on every included step ticket;
   - compact epic-level verification summary artifact.

   If any required artifact destination is missing, re-enter `/milestone-flow` or the verifier
   evidence-write path rather than marking the milestone complete.
4. For milestones after the first, ensure the milestone verifier included current-milestone
   evidence plus an impact-based regression subset from previously passed milestone gates. If a
   later milestone breaks earlier verified behavior, treat `/milestone-flow` as failed/incomplete
   and keep the fix loop inside that milestone before continuing.

### 3. Production promotion after all staging gates pass

After the final milestone has a staging `PASS`:

- If `--staging-only` is set, stop and report that production was intentionally not touched.
- Immediately before promotion, rebuild the ownership inventory from current tracked files and
  workspaces with `mode="promotion"`, `recheck_of`, and `rechecked_at_epoch`, then validate it.
  Promotion blocks on any newly unresolved owner/workspace/guide gap.
- Otherwise run the ordered epic production promotion/deploy path:

  ```text
  /ticket-promote --epic <EPIC_ID>
  /ticket-verify production --epic <EPIC_ID>
  ```

`/ticket-promote --epic` must promote only the verified epic step commits, in milestone
order, using isolated worktrees and the repo's production deployment instructions. It must not
silently include unrelated staging work. `/ticket-verify production --epic` is the final evidence
gate; mark the epic complete only after it passes.

## Gate-stop process

When running with `--stop-at-gates`, do planning/splitting/readiness checks only, then stop before
calling `/milestone-flow` and print the exact command that would run the full deploy+verify gate:

```text
/milestone-flow <EPIC_ID> <MILESTONE>
```

Do not claim the milestone is complete until `/milestone-flow` actually runs and the staging gate
passes.

## Parallelism

Parallelism is delegated to `/milestone-flow`, which uses dependency waves and repo write
scope analysis. Never parallelize same-repo overlapping work just to save time.

Every delegated epic/milestone call uses `fork_turns: "none"` and the shared packet above. A
history fork is allowed only when a self-contained packet is genuinely impossible: record the
reason before dispatch and use the smallest explicit numeric count of recent turns. Never use an
all-history fork.

## Phase checkpoints and rotation

Treat normalized plan/split, each milestone gate, and final production promotion/verification as
durable phase boundaries. Apply the validated dispatch/result/rotation contract in
`execution-economy.md`; prose-only or unspecified budgets are invalid. These are the default hard
per-generation budgets:

| Phase | Max turns | Max checkpoints | Max elapsed | Max tokens when exposed |
|---|---:|---:|---:|---:|
| normalize plan/split | 60 | 4 | 90 min | 100,000 |
| one milestone gate owner | 80 | 8 | 180 min | 160,000 |
| production promotion/verification | 60 | 6 | 180 min | 120,000 |

Use `max_packet_bytes: 16384`. If a milestone needs more than eight safe work-unit checkpoints,
slice it into bounded execution-wave generations rather than enlarging the session. Persist the
current epic artifact/checkpoint and packet manifest at every safe boundary. A valid
`rotate_required` result causes an immediate fresh `fork_turns: "none"` replacement from the first
incomplete unit; the old owner gets no follow-up work. Preserve passed milestones, landing state,
deploy state, and verification artifacts rather than rerunning them.

Every phase dispatch also carries the durable progress lease from `execution-economy.md`. The
parent blocks once per lease. At expiry it performs one inspection only: terminal results are
consumed, one renewal is allowed only after checkpoint/tool-receipt advancement, and stale or
hard-deadline work is interrupted and rotated. Sleep/paused/unknown time is reported, not mislabeled
as execution failure.

## Output

Load and apply `skills/references/terminal-outcomes.md` at each terminal stop of the requested
epic run. After the final milestone or production action, run the shared post-check, re-read the
epic and affected step tickets, and put exactly one large outcome banner plus details block before
the report below. A clean final production PASS with canonical completed state uses
`## ✅ COMPLETED — READY TO CLOSE`; staging-only success uses `## ✅ STAGING VERIFIED`; gate-stop,
blocked, and failed runs use their accurate non-complete banner.

Always report:

- epic id and current mode (`full-auto` or `gate-stop`);
- current milestone and gate verdict;
- step tickets and statuses changed;
- deploy/promote commands run and their evidence artifacts;
- for each verified milestone/final gate: canonical gate artifact id, per-step ticket evidence
  artifact ids, and compact epic summary artifact id;
- rotation count/reasons and productive, stall/sleep, and elapsed phase time when available;
- next automatic action or, if blocked, the exact blocker and safest resume command.

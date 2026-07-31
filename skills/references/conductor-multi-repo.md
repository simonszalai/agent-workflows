# Conductor multi-repo execution

Use this reference whenever an epic, milestone, ticket, or user request spans more than one repo,
or when the system context says directories are linked into the current Conductor workspace.

## Repo/workspace resolution

- Start from `get_epic(..., detail="light").involved_repos` and each step ticket's `repo`
  field; those are the
  authoritative repo names for epic work.
- Map each repo to an actual filesystem root before planning execution:
  - the current working directory's git remote basename usually maps to the primary workspace repo;
  - linked directories from the Conductor system context are valid repo roots when their git remote
    basename matches a required repo;
  - explicit user-provided paths are valid after checking they are git worktrees for the repo.
- Do **not** assume repos live at `~/dev/{repo}`. That may be true for source workflow repos, but
  Conductor work happens in `/Users/.../conductor/workspaces/...` plus linked directories.
- If a required repo is not accessible as the primary workspace, a linked directory, or an explicit
  path, the outcome depends on the executor mode (below). In `local` mode, stop before
  implementation and report the exact missing repo(s); ask the user to start/link the missing
  workspace or run the repo's step in a separate Conductor workspace. Do not fake the work inside
  another repo. In `hermes` mode, an unresolved repo is not a blocker — it is an instruction to
  create the workspace.

## Executor modes

Multi-repo orchestrators (`/epic-flow`, `/milestone-flow`) run under one of two executors. The
DAG, contracts, packets, gates, budgets, and evidence rules are identical in both; only how a
child run is placed and awaited differs.

- **`local`** (default): every step repo must resolve to the primary workspace, a linked
  directory, or an explicit user-provided path per the resolution rules above. Step dispatch is a
  same-workspace `fork_turns: "none"` subagent.
- **`hermes`**: the session has the Hermes Conductor MCP facade (workspace/session tools such as
  `create_workspace`, `create_session`, `send_session_message`, `get_session_status`). A step repo
  that does not resolve locally is placed by **creating a Conductor workspace on that repo** with
  the step's intended branch, creating one session in it, and sending exactly one prompt: the same
  `/ticket-flow` (or delegated) command line the local executor would run, plus the packet
  artifact id/version/hash and result schema. Await the session under the normal
  `execution-economy.md` progress lease: one bounded block per lease, one expiry inspection of
  `get_session_status`/terminal transcript, at most one renewal after real checkpoint advancement.
  Never busy-poll session status between lease boundaries.

Select `hermes` only when explicitly requested (`--executor hermes`) or when the run was started
by a Hermes scheduled agent; otherwise use `local`. Hermes-executed runs are unattended: they must
never ask interactive questions, must stay on the silent Keychain 1Password service-account path
(no `op://*-sensitive/...` access, no operations requiring Touch ID or commit-signing approval),
and must report results to their configured channel instead of assuming a watching user. Archive
or name created workspaces so a re-run reuses an existing open workspace for the same step ticket
instead of spawning duplicates; record every created workspace/session id in the run report.

## Step and branch boundaries

- One epic step lands in exactly one repo. Cross-repo work is multiple steps plus explicit
  provider/consumer contracts.
- Each repo uses its own current branch and target branch. Do not rename the current branch. Do not
  create a branch in a linked repo unless the active skill explicitly allows branch creation and the
  user/workspace context permits it.
- A multi-repo milestone normally creates one PR per repo/step, merged in blocker -> blocked DAG
  order. Provider contracts must land before consumer steps that depend on them.
- Never claim a cross-repo contract is satisfied until the provider repo's change is actually
  landed/merged in the target environment the consumer will build against.

## Execution and concurrency

- Before editing a repo, run `pwd`, `git status --short --branch`, and identify its remote basename
  so the final report can show repo/path/branch.
- Different-repo steps may run in parallel only when their DAG dependencies are independent and all
  repo roots are available. Same-repo overlapping work stays serial.
- Keep commits, tests, and PRs repo-local. Do not bundle unrelated repo changes into the primary
  workspace just because it is convenient.
- If a runtime gate spans repos, the milestone orchestrator owns the integrated deploy/verify step
  after the required repo-local changes have landed.

## Required reporting

For any multi-repo run, report a compact table with:

| Repo | Path or workspace/session id | Branch | Target/base | Step ticket | Executor | Status | PR/commit |

Also report cross-repo contracts in provider -> consumer order and identify any missing workspace
or manual deploy blocker explicitly.

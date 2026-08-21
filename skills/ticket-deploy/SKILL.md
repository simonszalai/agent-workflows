---
name: ticket-deploy
description: >-
  Get a branch CI-green, merge the PR, then deploy. Iterates the repo's deterministic local
  checks until they pass, waits for CI, iterates CI failures, compounds any local-vs-CI
  discrepancy, and lands the PR. With a ticket ID, continues through staging/prod verify and
  ticket status; without one, skips ticket state, /ticket-verify, and /ticket-promote.
max_turns: 150
---

# Ticket Deploy

Own the path from a finished tree to a green, merged PR, then (when a target is given) deploy.
The local-health → CI → discrepancy-compound loop is mandatory on every path, and a green PR
is always merged — CI-green is not landed. Ticket ceremony is optional: no ID means no ticket
load, no status writes, no `/ticket-verify`, no `/ticket-promote`.

With a ticket, this skill still delegates only the two dedicated owners:

- `/ticket-verify` — behavior/evidence verification, verdicts, evidence artifacts
- `/ticket-promote` — staging→main landing + production deploy steps

## Usage

```text
/ticket-deploy                 # current branch: local checks + CI until green, then merge
/ticket-deploy staging         # same, then deploy to staging (no ticket)
/ticket-deploy F0123 staging   # deploy to staging + verify staging; stop there
/ticket-deploy F0123 prod      # production leg only (status-aware, see below)
/ticket-deploy F0123 full      # staging leg, then on exact staging PASS the production leg
```

Parse the first token as a ticket ID only when it matches `F|B|R` plus digits. Otherwise it is
the target. `prod` accepts alias `production`.

- Ticket ID present: target is required (`staging`, `prod`, or `full`).
- No ticket: target is optional. Omit it to stop after the PR is merged. `staging` / `prod` /
  `full` still run project deploy steps after the merge.
- Standalone tickets only. Epic step/source tickets land on their milestone integration
  branch and are gated by `/ticket-verify --epic` (orchestrated by `/epic-flow`); refuse them
  here and say so. No ticket means this check does not apply.

## Authorization

Invoking with `prod` or `full` is the explicit human authorization for production
promotion/deploy (after an exact staging `PASS` where one exists). Never infer that
authorization from a `staging` invocation. `staging` and `full` also authorize
`/ticket-verify staging --produce-evidence` (one safe bounded producer run under ticket-verify's
contract; never a deploy, schedule enablement, backfill, or unbounded pipeline run) — only
when a ticket ID is in scope.

## Ticket optional

A missing ticket is a first-class mode, not an error. Do not create a ticket to continue.

| | Ticket in scope | No ticket |
|---|---|---|
| Load ticket / `deployment_guide` | yes | skip |
| Local health + CI loop (§Loop) | yes | yes |
| Merge the PR (§Merge) | yes | yes |
| Project deploy steps | yes, from guide + project config | yes, from project config only; skip when no target |
| `update_ticket` / lifecycle status | yes | skip |
| `/ticket-verify`, `/ticket-promote` | yes | skip |

Without a ticket, `full` is staging land+deploy then production land+deploy, with no verify
gate — the invocation is the authorization, and the report must say behavior was not verified.

## References

Read and follow:

- `../references/ticket-lifecycle.md` (ticket mode)
- `../references/staging-autonomy.md` (staging legs)
- `../references/environment-topology.md` (staging/prod/full target)
- the called skills' own boundaries

## Loop — local health, then CI

Run this loop before every push that should go to CI, and after every CI-driven fix. Ticket
or not. Start at the local gate — feature review is not a deploy gate. Goal: the tree CI sees
already passed the same deterministic checks locally; when it did not, diagnose the miss and
give `/compound` a chance to close it.

**Local gate.** First commands: `ci-local --run` (or the workflow's exact `run:` steps) and
`git status`. Do not review product source. Do not dump the full diff. The ci-local receipt's
`tree_sha` is the tree identity. Run the **full** gate on the current tree. On failure: fix
every finding, re-run the full gate, repeat. Permit rounds only while each round makes
concrete, stateable progress against the previous failure. Stop on no-progress or a human
decision (product intent, secrets, infrastructure). Do not push a tree whose local gate is
red.

**CI wait.** Push, open or reuse the PR against the target base (current-branch PR if no
target), then `wait-ci <pr_number> --timeout 540` as one blocking call. Never poll `gh`.

**CI iterate.** A red check is never terminal. Read the failing job logs, fix the repository
failure (lint, types, flaky-but-reproducible tests, lockfiles, generated files), re-run the
full local gate on the new tree, push, wait-ci again. Same stop conditions as the local gate.

**Discrepancy → `/compound`.** If CI failed on a tree whose local gate had passed, that is a
discrepancy. After the fix — or when stopping — classify why local missed it, then run
`/compound` once per distinct discrepancy. Causes include a missing or weaker local check,
different command or flags, env/version drift, generated files, lockfile, a flake local did
not reproduce, **or a skill/workflow gap** (this skill's inventory omitted a CI check, or
the agent did not follow it). Do not compound a CI failure the local gate already reported
on the same tree.

`/compound` APPLY and SKIP are both valid. APPLY closes a knowledge or workflow gap so the
next local gate would have caught it. SKIP (one-off, already documented, no systemic fix,
or a skill issue compound cannot close) is not a deploy failure — notify the user: the
discrepancy, the classification, that compound did not change anything, and what a human
would need to change if they want the gap closed. Do not pretend the miss is fixed.

Then merge the green PR (§Merge). If a ticket is in scope and this run just completed a
land+deploy gate, write the lifecycle status for that gate (`to_verify_staging` after staging
deploy, or whatever §2/§4 names). If no ticket, skip the write.

## Merge

A green PR is not landed. After the loop succeeds, merge it. If it is already `MERGED`, treat
land as done and continue. Do not stop after CI passes and hand the merge back to the user.

Detect the allowed method — do not assume a policy:

```bash
gh repo view --json squashMergeAllowed,rebaseMergeAllowed,mergeCommitAllowed
```

Prefer squash when allowed. Use `--merge` only when the head is a long-lived branch
(`staging` / `main`) that must keep ancestry. If the needed method is not allowed, STOP.

```bash
HEAD_BRANCH=$(gh pr view <pr_number> --json headRefName -q .headRefName)
gh pr merge <pr_number> --squash                    # or the chosen allowed method
test "$(gh pr view <pr_number> --json state -q .state)" = "MERGED"
case "$HEAD_BRANCH" in
  staging|main) echo "Head is long-lived ($HEAD_BRANCH) — leave it." ;;
  *)            if git ls-remote --exit-code --heads origin "refs/heads/$HEAD_BRANCH" >/dev/null
                then git push origin --delete "$HEAD_BRANCH"
                fi
                align-merged-pr-workspace <pr_number> ;;
esac
```

Never pass `--delete-branch` to `gh pr merge` from a Conductor worktree. `gh` may try to check
out the base locally even after the remote merge succeeded, then fail because that base is
already used by another worktree. Confirm remote `MERGED` first, delete only the remote
throwaway head, then use the guarded alignment command.

## Process

### 1. Resolve and resume safely

**No ticket:** skip this section. Do not review product source; do not dump the full diff.
First commands: `ci-local --run` (or the workflow's exact `run:` steps) and `git status`.
Then the loop, merge the PR, then the target section if one was given.

Load the ticket once with `detail="light", include_events=false`, then fetch only the artifact
bodies you need — at minimum the current `deployment_guide`. Refuse epic step/source tickets,
abandoned tickets, and ambiguous repository scope. If the guide is DRAFT, stale, or missing a
fact the accepted plan supplies, repair and re-finalize it **before** any remote mutation —
never after, retroactively calling it valid.

Enter from lifecycle truth rather than repeating completed legs:

| Current status | `staging` | `prod` | `full` |
|---|---|---|---|
| built, branch pushed (pre-deploy) | §2 | direct-production gate (§4a) | §2 |
| `to_verify_staging` | §3 | stop: staging verify pending | §3 |
| `staging_verified` | report already verified; stop | §4 | §4 |
| `to_verify_prod` | n/a | §5 verification only | same |
| `prod_verified_needs_cleanup` | n/a | `/ticket-verify production <ID>` | same |
| `completed` | report already complete; stop | same | same |
| `verify_staging_failed` | resume §3 repair loop from the persisted failure evidence | stop: staging repair pending | resume §3 |
| `verify_prod_failed` | n/a | stop at the production safety boundary with the persisted remediation route | same |

A staging `BLOCKED` artifact classified `staging_safe`/`owner_repair`/`external_wait` is a
resumable checkpoint, not a user-interaction gate. Evidence is *stale* only when scope code
landed after the artifact's activation boundary; age alone is not staleness.

### 2. Deploy to staging (`staging` and `full`)

1. Run the local-health → CI loop against a PR on `staging`, then merge it (§Merge).
2. Run the staging deploy steps from the ticket's `deployment_guide` (if any) and
   the project deploy config — execute each automatable step yourself and verify its success
   before the next. Include any repo-required schema-deploy artifact (Atlas reviewed plan,
   migrations).
3. Ticket in scope: set `to_verify_staging`. No ticket: skip status and stop unless the
   target is `full` (continue to production land+deploy, no verify).

Staging mutations follow `staging-autonomy.md`: documented bounded fixtures, seeds, and
registrations are standing-authorized — repair and continue instead of returning a command for
the user to run.

### 3. Verify staging (`staging` and `full`)

Ticket required. No ticket: skip.

Run:

```text
/ticket-verify staging <ID> --no-promote --produce-evidence
```

Handle the verdict:

- **exact `PASS`**: require the persisted evidence artifact. Target `staging`: report and stop
  (the ticket rests at `staging_verified` for an explicit `prod`/`full` continuation). Target
  `full`: continue to §4.
- **`PASS (contract-missing)`**: stop — a derived contract is not production-promotion
  evidence — unless the artifact records `risk_tier: tiny_safe`, which counts as exact `PASS`.
- **`FAIL`**: enter the repair loop below rather than returning the failure to the user.
- **`BLOCKED`**: consume the repairability classification. Execute `staging_safe` actions
  directly, fix `owner_repair` items yourself, run the deterministic waiter for
  `external_wait`. Stop only for proven `human_required` or `agent_incapable`.
- **`NEEDS_MORE_TIME`**: require a proven live `external_wait`, wait on it with a bounded
  deadline (`wait-ci`, `wait-prefect-flow`, or the operation's own terminal predicate), and
  continue from the terminal result.

**Staging repair loop.** For an agent-resolvable `FAIL`: diagnose from the verifier's evidence,
fix the assigned surface (code defect → fix + local-health → CI loop + redeploy;
verifier/contract defect → re-finalize the contract, no redeploy), then re-run the verify
command once. Permit repair rounds only while each round makes concrete, stateable progress
against the previous failure; when a round changes nothing, stop and report every attempted
delta. Never loop on hope.

### 4. Production leg — promote staging-verified work (`prod` and `full`)

**No ticket:** do not call `/ticket-promote`. PR against `main`, run the local-health → CI
loop, merge (§Merge), run production deploy steps from the project deploy config, stop. Report
behavior unverified.

**Ticket:** precondition is latest staging evidence is an exact `PASS` (or `tiny_safe`
contract-missing PASS). Run `/ticket-promote <ID>`. This invocation satisfies the
human-authorization requirement but waives none of ticket-promote's schema, isolation, parity,
CI, or deploy gates. It lands the work on `main`, runs production deploy steps, sets
`to_verify_prod`, and hands off to `/ticket-verify production <ID>` (§5). The promotion PR
uses the same local-health → CI loop.

### 4a. Production leg — direct-to-production (never staged)

Only for tiny safe standalone work. Classify the actual diff first: schema, auth, encryption,
deploy-config, new infrastructure/cost, wide blast radius, or material uncertainty means **not**
tiny/safe — stop and ask the user for confirmation before any production mutation, naming
exactly what makes it risky and recommending the staging path. With a tiny/safe classification
or explicit confirmation: PR against `main`, local-health → CI loop, merge (§Merge), production
deploy steps, then `/ticket-verify production <ID>` if a ticket is in scope.

Direct-to-main never leaves staging behind: merge the same change into `staging` and deploy it
there in the same run, and confirm that back-sync before reporting the leg complete.

Production mutation boundary: prefer audited MCP/server-side operations; never write the
production database from a local shell. Authenticated production CLI mutations with no remote
route run through `bin/redacted-exec -- <documented command>`.

### 5. Verify and complete production

Ticket required. No ticket: skip; the production land+deploy already happened in §4/§4a.

`/ticket-verify production <ID>` owns the production verdict, deferred cleanup, and
`completed`. Relay its terminal result. If it fails with a pure verifier/contract defect
(product-failure evidence empty), re-finalize the contract and re-verify against the already-live
revision — no product code, redeploy, or environment mutation in that loop. Any other failure
class stops at the production safety boundary with the persisted remediation route. If
production passes but deferred cleanup remains, report `prod_verified_needs_cleanup` rather
than claiming completion.

## Terminal report

One row per gate: command, result, PR/commit or run identifier, evidence artifact ID (ticket
mode), resulting ticket status (ticket mode). End with exactly one of:

- `LANDED` — no target: CI passed and the PR is merged; no deploy steps ran;
- `STAGING DEPLOYED` — no-ticket `staging` finished land+deploy (behavior not verified);
- `COMPLETE` — production verification passed and the ticket is `completed` (`prod`/`full`);
- `STAGING VERIFIED` — ticket + target `staging` finished with exact staging `PASS`; next
  command is `/ticket-deploy <ID> prod`;
- `STOPPED` — the failed/blocked/timing gate and the exact next command or human decision.

Never report `full` success from a staging PASS alone. Every PASS line must cite concrete
evidence; end with a "Not verified:" line for anything claimed but not exercised in this run.
If a local-vs-CI discrepancy was compounded and SKIPPED, name it in the report — do not bury
it inside a green banner.

---
name: auto-deploy
description: Autonomous deployment. Deploys PR to staging or production, runs migrations/blocks/deploys, updates ticket status.
max_turns: 100
---

# Auto-Deploy Command

Follow `../references/execution-economy.md`, `../references/ci-self-heal.md`, and
`skills/references/terminal-outcomes.md`. Efficiency never weakens correctness, fail-loud behavior,
lifecycle ownership, migration safety, deployment verification, or branch synchronization.

Auto-deploy creates or finds the deployment PR, proves CI and preflight readiness, lands it, runs
all automatable deployment work, verifies deployment mechanics, and advances the ticket or epic to
behavior verification. Standalone tickets and parent epics may use the staging segment. Production
is explicit: direct production arrives from `/ticket-flow`; verified staging promotion belongs to
`/ticket-promote`; milestone staging gates belong to `/milestone-flow`.

## Usage

```
/auto-deploy F007
/auto-deploy F007 staging
/auto-deploy F007 production
/auto-deploy B003
/auto-deploy
```

## Routing contract

Read only the reference required by the current phase. Load a conditional reference only after its
manifest predicate is true. A reference is normative, not optional background.

| ID | Phase | Load when | Required reference | Fail-loud gate |
| --- | --- | --- | --- | --- |
| P1 | Validate unit and target | Always | `references/lifecycle.md` | Unit exists; target/status is valid |
| P2 | Find or create PR | Always | `references/lifecycle.md` | Open/merged PR or usable pushed head exists |
| P2b | Local CI parity | Before PR creation, first CI wait, and every CI-triggering re-push | `references/lifecycle.md` | Exact PR-head tree has a passing `ci-local` receipt; all local failures were batch-repaired |
| P3 | Load project deploy contract | Project `.claude/commands/deploy.md` exists | `references/provider-project.md` | Project contract becomes authoritative for P6-P9 |
| P4 | Check CI | Open PR | `references/lifecycle.md` | Current PR tree is green or self-heal stops at human judgment |
| P5 | Update onto target | Open PR is behind target | `references/lifecycle.md` | Approved update strategy succeeds and rerun CI is green |
| P6 | Detect changes | Before merge | `references/change-and-execution.md` | Complete bounded inventory and evidence producer exist |
| P6b | Preflight deploy commands | Any deploy command will run | `references/change-and-execution.md` | Every ordered command has a passing safe preflight |
| P7 | Merge and align | P4-P6b passed | `references/lifecycle.md` | PR is `MERGED`; throwaway Conductor head is aligned |
| P8 | Execute deployment | Merge completed/already merged | `references/change-and-execution.md` | Every automatable and guide-specific step is accounted for |
| P8b | Back-sync main to staging | Direct production landing on `main` | `references/back-sync.md` | Content-preserving sync is complete and its CI is green |
| P9 | Verify mechanics | P8/P8b complete | `references/verification-and-status.md` | Code, migration, health, logs, and negative inventory pass |
| P10 | Set status and blockers | P9 passed | `references/verification-and-status.md` | Lifecycle and independent blocker truth are recorded |

Additional conditional routes:

- Load `references/migration-and-runtime-evidence.md` when the file inventory contains schema or
  migration paths, or the deployment guide expects rows/logs from a runtime producer.
- Load `references/provider-project.md` when the project deploy command exists or project
  instructions/memory name a provider-specific or manual deployment boundary.
- Load `references/back-sync.md` only for a direct production landing on `main`. It never applies to
  staging and is unnecessary for `/ticket-promote`, whose work already came through staging.

## Non-negotiable gates

- PR creation happens here, not in the build phase. CI must pass on the exact tree that will merge.
- Before staging creates a PR or waits on CI, `ci-local` must run every locally reproducible
  workflow step without short-circuiting, batch-repair the complete inventory, and prove an
  exact-tree passing receipt. CI is confirmation, not the first formatter/lint/type/test pass.
- `Preflight every deploy command before merge`; a missing or failed preflight stops the landing.
- Schema changes keep the repository's active migration contract. Runtime evidence must have a real
  deployed producer or deploy-owned canary before merge.
- Production DB writes use audited remote operations. Other authenticated production CLI mutations
  use `bin/redacted-exec`; raw secret-bearing logs are prohibited.
- Deployment-guide reconciliation and `negative inventory` closure are mandatory.
- Required manual work becomes explicit blocker metadata; it is never hidden or called complete.
- A direct `main` landing must complete the content-preserving staging back-sync before P10.
- Current Conductor throwaway heads use `align-merged-pr-workspace`; never substitute a normal
  post-squash rebase or delete a repository-defined long-lived branch.
- Auto-deploy proves deployment mechanics. `/ticket-verify` owns behavior/evidence verdicts and the
  `verify_staging_failed` / `verify_prod_failed` statuses.

## Literal Conductor CI wait

For each required CI generation, use this exact shape:

1. Dispatch exactly one fresh `fork_turns: "none"` leaf with the sole command
   `wait-ci {pr_number} --timeout 540`.
2. The leaf starts that deterministic command once and consumes it with one long blocking tool
   observation whose deadline covers the remaining 540 seconds. It returns only the compact JSON.
3. The parent blocks once with `wait_agent({target: <leaf>, timeout_ms: 600000})`. It must never poll
   the leaf, a resumable shell session, or GitHub directly, and must not issue a second wait.
4. Record the waiter's internal `github_status` observations plus the parent's single `wait_agent`
   observation in the run receipt. Validate it with
   `bin/progress-lease policy <receipt.json>` before claiming execution-economy compliance.

A failed result enters `../references/ci-self-heal.md`. A timeout is not green: stop and return the
waiter's exact `resume_command` unchanged. A new CI generation after a branch update gets one new
fresh waiter leaf and one new receipt condition.

## Terminal result

Direct invocation loads `skills/references/terminal-outcomes.md`, runs its post-check after the last
deploy/status action, and prints the environment-specific banner before deployment details. A
parent workflow receives the compact deploy result and owns the outer banner. Success ends at
`to_verify_staging` or `to_verify_prod`, followed by `/ticket-verify {environment} {ID}`.

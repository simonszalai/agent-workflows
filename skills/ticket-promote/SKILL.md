---
name: ticket-promote
description: Promote staging-verified work from staging to main AND run the project's production deploy steps. Modes: single ticket (default; auto-invoked by /ticket-verify staging on a PASS that clears the §9b auto-promotion gate), --all batch of every staging_verified ticket, --epic for verified epic steps, --all-staging for the whole staging range. Hands off to /ticket-verify production; never sets completed.
max_turns: 250
---

# Ticket Promote

Promote work that passed staging verification from `staging` to `main`, then execute the
project's **production deploy steps** for what landed. This skill owns the entire
post-staging production path except behavior verification: land + deploy, then hand off to
`/ticket-verify production`.

## Scopes

Infer the mode from the arguments; if ambiguous, stop and ask.

| Invocation | Mode | Scope |
|---|---|---|
| `/ticket-promote F0123` | Single ticket (default) | That ticket's isolated staging commits |
| `/ticket-promote F0123 B0042` | Multi-ticket | Each ticket, sequentially, single-ticket rules |
| `/ticket-promote --all` | Batch | Every `staging_verified` ticket, one at a time |
| `/ticket-promote --epic E0007 [--milestone M2]` | Epic | Verified epic step commits, in milestone order |
| `/ticket-promote --all-staging` | All staging | Entire `origin/main..origin/staging` range |
| `--dry-run` | Any mode | Discover + order + plan; no remote/prod changes |
| `--exclude F0130` | Batch | Promote the ready set except these IDs |

`/ticket-verify staging` calls this automatically (single-ticket mode) on each standalone
staging PASS **that passes its auto-promotion gate** (ticket-verify §9b: FINALIZED contract
fully graded on fresh evidence, and no schema/deploy-config/auth category in the diff).
Higher-risk scopes rest at `staging_verified` until a human invokes this skill explicitly.
Epic mode runs after all milestone staging gates pass.

## Unattended guard (scheduled contexts)

This skill merges to `main` and runs production deploy steps — for ts-prefect, merging to `main`
IS a production deploy (flows `git_clone` at runtime). Per `../references/scheduled-run.md` §1,
git merges/pushes to long-lived branches are never allowed unattended.

When invoked from a scheduled context — the session carries a scheduled-run marker
(Hermes `hermes/schedules/` prompt), the caller is `/ticket-verify --scheduled`, or there is no
human in the loop to approve a production mutation — **refuse to land or deploy anything**:

1. Perform no merge, push, PR creation, or production deploy step. Discovery/read-only preflight
   is fine.
2. Emit the promotion-ready report instead: for each ready scope, the ticket ID, staging PASS
   evidence artifact ID, ordered commit list, detected deploy categories, and the exact
   `/ticket-promote <ID>` command a human should run.
3. Post it per scheduled-run.md §2 (one line + thread) and end
   `promotion-ready — prod promotion awaiting Simon`.

There is no scheduled bypass flag. If scheduled provenance is uncertain, treat the context as
scheduled and refuse — a wrongly withheld merge costs one human command; a wrong unattended merge
is a production deploy.

## Non-Negotiables

- **Production-impacting. Prefer stopping over guessing.** Every stop must say exactly what
  landed, what deployed, what is stuck, and what was never touched. A stop requires a **named,
  concrete uncertainty** (which gate, which missing evidence, which unproven condition); with
  all gates green, general caution is not a stop reason.
- A ticket must be `staging_verified` with PASS evidence, or the caller must be
  `/ticket-verify staging` passing a fresh PASS verdict. No PASS evidence -> stop.
- **One unit fully landed AND deployed before the next begins** (batch/epic modes).
  Schema/deploy state is sequential even when code can move independently. Never land all the
  code first and batch the deploys at the end. Stop the whole batch on the first hard failure —
  later tickets may depend on it.
- All merge/cherry-pick/conflict work happens in a fresh `git worktree` under `.context/`,
  never in the current Conductor workspace. Never use `git reset --hard`,
  `git checkout -- <file>`, `git restore`, `git clean`, or unscoped `git stash` in the shared
  workspace. Do not rename the current branch.
- **Never `--delete-branch` (or otherwise delete) a long-lived branch — `staging` or `main`.**
  In all-staging mode the promotion PR's head is usually `staging` itself, and staging is often
  live infrastructure. Only ever delete throwaway `ticket-promote/<scope>-<stamp>` heads.
  *Example (ts-prefect, B0174 2026-06-17):* every staging Prefect deployment clones
  `--branch staging` at runtime; PR #390 merged with `--delete-branch` on head `staging` and
  crashed all 24 staging flows until the branch was re-pushed.
- `git fetch origin main staging --prune` before every branch comparison.
- Do not promote unrelated staging commits in ticket/batch/epic modes. Isolation is *proven*
  when the promoted commit set applies without pulling in other tickets' content and
  `git log origin/main..origin/staging` shows no other ticket's commits touching the promoted
  diff's files. Other tickets' commits on staging in unrelated files do not break isolation.
  If isolation cannot be proven by these checks, stop and report — do not silently widen scope.
- **A human may explicitly authorize the scoped parity bypass for an isolated, non-schema
  ticket.** This bypass means only that genuine branch or declarative-schema divergence proven
  unrelated to the promoted diff is reported and deferred instead of blocking the ticket. It does
  not waive PASS evidence, commit/file isolation, CI, deployment, production verification, or any
  schema dependency of the promoted code. Record the approving human instruction and the parity
  report in the manifest. Scheduled/unattended runs can never use this bypass.
- **Schema-bearing tickets are not the fast path.** Use the schema gate (§Schema gate) before
  treating them as normal cherry-picks.
- Deploy steps come from the ticket's `deployment_guide` artifact and the project deploy
  config (`.claude/commands/deploy.md` when it exists) — read them at runtime; never hardcode
  environment IDs, URLs, or commands from this skill.
- Never set a ticket to `completed`. `/ticket-verify production` owns that.

## Preflight — idempotency and repo policy

Run before creating any worktree, branch, or PR:

0. **Load once.** The orchestrator loads the scoped ticket(s) once with only
   `plan`, `deployment_guide`, and `verification_evidence` bodies plus light artifact manifests;
   epic mode loads `get_epic` once. Cache `context_version` and reuse these objects through landing,
   deploy, status update, and handoff. Re-read only after an external artifact mutation invalidates
   the recorded version; child steps receive bounded extracts, not independent MCP reads.

1. `git fetch origin main staging --prune`.
2. **Existing promotion PR check.** Look for an open promotion PR for the same scope:

   ```bash
   gh pr list --state open --base main --search "Promote <SCOPE>" \
     --json number,title,headRefName,url
   ```

   If one exists, resume it (re-check CI, merge, continue at the deploy phase) instead of
   creating a duplicate.
3. **Stale worktree check.** `git worktree list` — remove leftover
   `.context/ticket-promote/<SCOPE>-*` worktrees from crashed runs
   (`git worktree remove --force <path>`) before creating a new one, unless resuming.
4. **Already-landed check.** If every commit for the scope is already reachable from
   `origin/main`, skip landing: advance the ticket to `to_verify_prod` if still
   `staging_verified`, run any missing deploy steps, and hand off to verification.
5. **Merge-method detection.** Do not assume a merge policy:

   ```bash
   gh repo view --json squashMergeAllowed,rebaseMergeAllowed,mergeCommitAllowed
   ```

   - Ticket / batch / epic modes: use any allowed method; prefer squash when allowed.
     Cherry-picked promotions create new commits anyway, so linear methods are safe.
   - All-staging mode: a real merge commit (`--merge`) is REQUIRED to keep the
     `main`<->`staging` merge-base linked. Squash/rebase collapse staging's commits into new
     SHAs with no link back, so every staging-rooted branch afterwards shows phantom diffs
     against `main`. If merge commits are not allowed on the repo, STOP and report — do not
     substitute squash for a parity rollup.

## Establish scope

### Single ticket / multi-ticket

1. Normalize the ticket ID and confirm status `staging_verified` (or fresh PASS from caller).
2. Find candidate PRs and commits:

   ```bash
   gh pr list --state merged --base staging --search "F0123" \
     --json number,title,url,mergeCommit,headRefName,mergedAt
   git log --reverse --oneline origin/main..origin/staging --grep="F0123"
   ```

3. Build the minimal ordered commit list from commits that are reachable from
   `origin/staging` and NOT reachable from `origin/main`:

   ```bash
   git merge-base --is-ancestor <sha> origin/staging && echo on-staging
   git merge-base --is-ancestor <sha> origin/main && echo "already on main (skip)"
   ```

4. Stop if the list is empty (see Preflight #4), includes unrelated tickets, or requires
   unrelated staging dependencies that were not explicitly approved.

### Batch (`--all`)

1. Get the ready set: `list_tickets(project, repo, status="staging_verified")`.
   - If explicit IDs were passed, intersect; any requested ID not in `staging_verified` ->
     STOP and report it.
   - Apply `--exclude`. Skip `abandoned`/`completed`, source tickets, and epic-member step
     tickets whose parent milestone owns promotion.
2. Map each ticket to its isolated commit set (single-ticket rules above).
3. **Order the batch by staging merge order** — the sequence in
   `git log origin/main..origin/staging` (oldest first) — so cherry-picks apply cleanly.
4. Mark schema-lane tickets (see §Schema gate) — never silently mix them into a code batch.
5. Empty set -> report "no tickets are ready for prod" and stop.

### Epic (`--epic E0007 [--milestone M2]`)

1. Load `get_epic(project, epic_id, detail="light")` for structure, then selected gate artifact
   bodies with `detail="full"`, `artifact_types=["verification_evidence",
   "deployment_guide"]`, and an explicit `response_byte_budget`.
2. If `--milestone` is present, scope to that milestone; otherwise include every milestone
   whose staging gate has a recorded PASS, in milestone order.
3. Require each included step ticket to be `merged` or `staging_verified` with a passing
   epic/milestone staging gate. Source tickets in `absorbed_into_epic` are never promoted.
4. Build the ordered commit list from the step tickets' staging PRs/commits: milestone order,
   then dependency/topological order within each milestone, preserving schema ordering.
5. Prove every commit is on `origin/staging` and not on `origin/main`. Reject the promotion
   if the list contains unrelated tickets, misses a required milestone dependency, or would
   promote an unverified milestone.

This mode promotes verified epic work only,
deploys production, and leaves behavior verification to
`/ticket-verify production --epic <EPIC_ID>`.

### All staging (`--all-staging`)

- Scope is every commit in `origin/main..origin/staging`. Stop if the range is empty.
- List commit SHAs, subjects, likely PR numbers, and likely ticket IDs in the manifest.

## Isolated worktree and manifest

One worktree per unit (per ticket in batch mode; one for the whole range in all-staging mode):

```bash
SCOPE="F0123"                       # or E0007, all-staging, etc.
STAMP=$(date +%Y%m%d-%H%M%S)
BRANCH="ticket-promote/${SCOPE}-${STAMP}"
WT=".context/ticket-promote/${SCOPE}-${STAMP}"
git worktree add -b "$BRANCH" "$WT" origin/main
cd "$WT"
```

Write a promotion manifest at `.context/ticket-promote/<scope>-<stamp>/manifest.md`:

- mode and requested scope; source and target branch
- commits being promoted; detected tickets/PRs; changed-file summary
- schema/config/dependency impact and detected deploy categories
- conflicted files and resolution rationale
- local check commands and results
- landing and deploy outcomes (filled in as you go)

**If `--dry-run`: print the ordered plan + detected deploy steps per unit and STOP here.**

## Apply the changes

Ticket / batch / epic modes (ordered, isolated commit set):

```bash
git cherry-pick -x <sha1> <sha2> ...
```

All-staging mode:

```bash
git merge --no-ff origin/staging
```

Conflict handling:

1. Inspect each conflict and resolve intentionally; preserve production-only fixes already on
   `main` unless the staged change explicitly supersedes them.
2. If a conflict reveals an undeclared dependency on unrelated staging work, STOP and report.
   Ask for explicit approval to include it or to switch to `--all-staging` mode.
3. Record every conflicted file and rationale in the manifest.

*Example (ts-prefect):* cherry-pick conflicts in the models package `__init__.py` are common —
the diff drags in OTHER staging models as context. Keep only the promoted ticket's model
line(s).

## Schema gate (if the scope carries schema changes)

Detect schema changes before treating a unit as a normal cherry-pick:

```bash
git diff --name-only origin/main...HEAD -- \
  migrations/ alembic/ prisma/migrations/ schema.prisma \
  # plus the repo's declarative-schema paths from project config, e.g. Atlas model/plan dirs
```

Schema order is global state even when code moves independently. When schema files are
touched, use the repo's active schema lane — run `/migration-parity-check` first; it holds the
deep per-lane detail (content/patch equivalence, per-env schema truth, graph drift) and the
current per-repo rules. Summary of lanes:

- **Declarative/reviewed-plan repos** (*example: ts-prefect after E0017 uses Atlas*): changes
  must be additive-only and pass the repo's schema-plan validation; production applies through
  the reviewed committed plan gate. Do not create, re-point, or repair migrations from a
  decommissioned system — if the diff reintroduces retired migration tooling, STOP.
- **Legacy migration-graph repos (Alembic/Prisma):** a migration cherry-picked onto a diverged
  `main` re-points its parent at a revision that is not on `main`, forking the graph.
  **Default action: STOP** and use a safe lane instead: schema-first PR off current `main`
  (deploy, then immediately sync `main` back to `staging`), or a full `staging->main` parity
  merge via `--all-staging`. A selective cherry-pick with a `down_revision` re-point is an
  explicit emergency exception only: it requires user approval after the parity report, a
  manifest entry naming the file(s), old parent, new parent, and why the safe lanes were not
  used, and same-run reconciliation of `main`/`staging` before any other migration-bearing
  promotion.

DB-only object changes must be covered by the repo's schema-truth verification, not assumed.

For an isolated scope with **no schema files**, a global Atlas/declarative-model difference is not
automatically a schema-bearing promotion. Compare the promoted diff with every divergent schema
file and check whether the promoted code references objects that exist only on one branch. If
there is no overlap or runtime dependency, record the divergence as out-of-scope debt and proceed;
when a human explicitly requested the scoped parity bypass, cite that approval in the manifest.
Stop only when the promoted scope touches, imports, generates from, or otherwise depends on the
divergent schema state.

## Local checks

Run the repo's standard checks in the promotion worktree (install, typecheck, build, tests as
the project defines them). Do not start dev servers. Fix only promotion/conflict/schema-gate
issues — no unrelated refactors.

This is one final-tree health gate keyed by the promotion worktree tree SHA and command. Do not run
the same full gate again while that SHA is unchanged. A conflict fix, merge/rebase, generated-file
change, or other tree mutation invalidates the evidence and requires one new gate for the new SHA.
Targeted diagnostics are not duplicate full gates.

**Residual risk — verify against main, not staging.** The staging PASS evidence was collected
with OTHER staging commits present; the promoted commit set on top of `main` is a combination
that has never run anywhere. The worktree's local checks must therefore include at least the
ticket's own tests (and the affected module's tests), not just a global typecheck/build.

**Co-tenancy check.** Read the staging `verification_evidence` artifact's
`staging_head_sha` / `co_staged_tickets` metadata (written by `/ticket-verify` §6). If
co-staged tickets touched files that overlap this promotion's diff and are NOT part of the
promoted set, the staging PASS may not be attributable to this ticket alone — record that
in the manifest as residual risk, and weight it when deciding whether to proceed (a shared
helper fixed by a co-staged ticket is the classic false-PASS mechanism). Missing metadata
(older evidence artifacts) is not a blocker; note it and continue.

## Production command preflight (before landing)

Rebuild the deployment/config ownership inventory immediately before promotion — which repo,
workflow, or person owns each deploy/config step touched by this diff. Do not reuse a planning
snapshot. Unresolved owners, absent third-repo config steps, or an incomplete guide block
promotion.

While `origin/main` is still unchanged, read the cached production deployment guide and project
deploy config, detect deploy categories with `git diff origin/main..HEAD`, and build the exact
ordered production command table. Preflight every command: validate imports/CLI/config with a
non-mutating command and, when the guide defines a safe idempotent staging mirror, execute the same
command shape there with staging credentials. Record each expected production postcondition in the
manifest. Missing/failed preflight stops before merge; never invent a dry-run flag or use the
production mutation itself as its preflight. A preflight already recorded earlier in
the same workflow for the same command, guide version, and diff is valid — cite it instead of
re-executing; re-preflight only commands whose shape, target, or inputs changed.

## Land on main

```bash
git push -u origin "$BRANCH"
gh pr create --base main --head "$BRANCH" \
  --title "Promote ${SCOPE} to production" --body-file manifest.md
wait-ci <pr_number> --timeout 540
```

Run `wait-ci` as one blocking foreground call and consume its single JSON result — never poll
`gh`/GitHub status in a loop. If CI fails, fix in the promotion worktree, push, and wait again
for the new tree. If it cannot be made green, STOP (in batch mode: stop the whole batch).

Merge with the method chosen in Preflight #5:

```bash
# ticket / batch / epic modes — head is the throwaway promotion branch:
HEAD_BRANCH=$(gh pr view <pr_number> --json headRefName -q .headRefName)
gh pr merge <pr_number> --squash                    # or another allowed linear method
test "$(gh pr view <pr_number> --json state -q .state)" = "MERGED"
case "$HEAD_BRANCH" in
  staging|main) echo "Head is long-lived ($HEAD_BRANCH) — leave it." ;;
  *)            if git ls-remote --exit-code --heads origin "refs/heads/$HEAD_BRANCH" >/dev/null
                then git push origin --delete "$HEAD_BRANCH"
                fi
                align-merged-pr-workspace <pr_number> ;;
esac

# all-staging mode — real merge commit; head may be long-lived:
HEAD_BRANCH=$(gh pr view <pr_number> --json headRefName -q .headRefName)
gh pr merge <pr_number> --merge                     # do NOT pass --delete-branch
case "$HEAD_BRANCH" in
  staging|main) echo "Head is long-lived ($HEAD_BRANCH) — leave it." ;;
  *)            if git ls-remote --exit-code --heads origin "refs/heads/$HEAD_BRANCH" >/dev/null
                then git push origin --delete "$HEAD_BRANCH"
                fi
                align-merged-pr-workspace <pr_number> ;;
esac
git ls-remote --heads origin staging | grep -q refs/heads/staging \
  || git push origin origin/main:refs/heads/staging   # long-lived-branch safety net
```

Never pass `--delete-branch` to `gh pr merge` from a Conductor worktree. `gh` may try to check out
the base locally even after the remote merge succeeded, then fail because that base is already used
by another worktree. Confirm remote `MERGED` first, delete only the remote throwaway head, then use
the guarded alignment command. Never replay squash-merged commits with a normal post-merge rebase.

Confirm the landing:

```bash
git fetch origin main
git merge-base --is-ancestor <merge_sha> origin/main && echo landed
```

## Run the production deploy steps

Landing alone is not promotion — this skill also deploys what landed.

1. Use the deployment guide, detected categories, ordered command table, and preflight evidence
   already cached in the manifest before landing. Do not rediscover or reload them after merge.
2. Execute only the detected categories, in the deploy config's order, **running each
   automatable step yourself** — do not just print commands. Verify each step's success
   before the next.
3. Steps that are genuinely manual (no CLI path, or owned by a specific person) are recorded
   as blocker metadata (`blocked_by`, `blocked_reason`, `blocked_context`), not performed.

Production mutation boundary: prefer audited MCP/server-side operations; never write the production
database directly from a local agent shell. Authenticated production CLI mutations with no remote
route run through `bin/redacted-exec -- <documented command>`. Never inspect profiles/config/env and
never send possibly secret-bearing output to `compact-exec`'s raw log.

*Example (ts-prefect):* schema apply is the main-branch `Run Migrations` workflow's Atlas
reviewed-plan job (verify it is green — never run Alembic); block changes run prod
`save_blocks --yes`; a `prefect.prod.yaml` change requires sourcing the Conductor-mounted prod
env pipe in the same shell before `uv run prefect --no-prompt deploy --prefect-file
prefect.prod.yaml --all` (the pipe is single-read; a transient connection error is fine —
re-run, it is idempotent); DAG/contract changes run the documented `sync_dag` command;
dependency changes require a manual Render worker deploy (record as blocker until confirmed).

If any deploy step fails: STOP at that step (batch: stop the whole batch). The code is
already on `main`, so report that a re-run of the failed deploy step is what's needed, not a
re-promotion. Do not continue to later steps or later units.

For removal/decommission scopes, completion additionally requires the manifest's negative inventory:
every legacy code/config item is absent, every old live registration/route/job is absent from the
authoritative production inventory, and the sole surviving path is exercised. Do not call the cleanup
complete from positive tests alone or defer an unexplained old item as incidental debt.

## Status update and handoff

After the unit is landed AND its deploy steps completed:

```text
update_ticket(status="to_verify_prod",
  reason="Promoted staging->main and ran production deploy steps via /ticket-promote")
```

Epic mode: set promoted step tickets to `to_verify_prod` (or the closest parent-owned
production-verification state) and the parent epic to `to_verify_prod` after the deploy.

Then **invoke `/ticket-verify production <ID>`** (or
`/ticket-verify production --epic <EPIC_ID>`) rather than verifying behavior inline.
This skill NEVER sets `completed` — that belongs to `/ticket-verify production` after
evidence collection.

Clean up the worktree before the next unit:

```bash
cd -                          # back to the original workspace
git worktree remove "$WT"
```

## Terminal outcome

After status update and worktree cleanup, put one accurate banner plus details block before the
batch table or failure details. Promotion success uses `## ✅ PRODUCTION DEPLOYED` with
`Closeout check: NOT READY` because this skill never owns behavior verification or `completed`;
a partial/failed promotion uses an accurate red-X, blocked, or stopped banner. Never claim a
stage that did not verifiably complete.

## Batch loop (`--all`) specifics

- Sequential, stop-on-first-failure. Re-fetch `origin/main` at the top of each iteration so
  each worktree is based on the just-advanced main.
- Fill in the per-ticket result row in the manifest as you go.
- Report one table for the whole batch:

```text
Ticket-promote --all — 4 ready, 3 promoted, 1 stopped

Ticket  Order  Landed(main)  Deploy steps run          Status          Note
F0123   1      yes           schema, service deploy    to_verify_prod  -
B0042   2      yes           blocks                    to_verify_prod  -
F0130   3      yes           (none)                    to_verify_prod  -
F0131   4      NO            -                         staging_verified STOPPED: conflict pulled in unrelated F0129 work
```

## Re-converge check (measure divergence debt; never widen scope)

Per-ticket cherry-pick promotion only ADDS `main`/`staging` ancestry divergence — it never drains
it, and squash-merged promotions behave identically. The code lands, but the staging commits never
become ancestors of `main`, so they stay in `git log origin/main..origin/staging`. Some of those
commits are patch-equivalent phantom divergence; others may be genuine staging work intentionally
withheld from production. A raw commit count cannot distinguish them.

**Mandatory at the end of every run, in every mode** — not just after a schema exception:

1. Measure `git rev-list --count origin/main..origin/staging` and record the raw diagnostic count
   in the manifest.
2. When the count is non-zero, run `/migration-parity-check` and classify the range as:
   patch-equivalent/phantom commits, genuine approved commits in this promotion, and genuine
   out-of-scope commits. Record the content/schema truth, not just the count.
3. **Never widen a ticket/batch/epic promotion or block an otherwise isolated promotion solely
   because the raw count exceeds 25.** Above 25 is a maintenance-warning threshold: report the
   ancestry debt, but intentionally withheld or unverified staging work remains out of scope.
4. A full `staging->main` parity merge is allowed only in explicit `--all-staging` mode, or when
   the parity report proves that every out-of-scope staging commit is patch-equivalent to content
   already on `main` and the resulting tree introduces no unapproved content. If any genuine
   out-of-scope commit remains, do not merge; finish the isolated promotion and report the debt.
5. Residual schema divergence or schema-gate reconciliation debt remains a correctness blocker
   only when it affects the promoted scope. A parity check's repo-wide `DIVERGED` verdict does not
   by itself block a proven isolated non-schema ticket. If the divergence is unrelated, finish the
   isolated promotion and report the debt; if the human explicitly authorized the scoped parity
   bypass, record that authorization. STOP and name the exact schema debt and safe lane only when
   the promoted scope overlaps or depends on it. Do not silently include unrelated staging work to
   repair it.
6. When a parity merge is authorized, use a real `--merge` commit. Never substitute squash or
   rebase — both create new SHAs with no ancestry link. If merge commits are forbidden, report the
   repo-policy blocker, but only block a run that actually requires the authorized parity merge.
7. Record `parity: clean`, or the raw count, classified genuine/phantom debt, and whether cleanup
   is safe now or deferred because genuine staging work is intentionally withheld.

*Example (ts-prefect, 2026-07-28):* the last real merge commit on `main` was 2026-07-15, and every
promotion after it was a squash, so `main..staging` reached 165 commits while most of that code was
already running in production. Separating the ~22 genuinely undeployed files from the phantom ones
took a full content diff, and two real drifts — a prod-only artifact set and a file deleted on
staging — had been invisible inside the noise.

## Failure output

On any stop, report: mode and scope, which units landed on `main`, which deploy steps ran for
each, exactly which unit/phase/command stopped, whether `main` was modified, whether any prod
deploy step partially ran, and the single safest next action. Never claim production is
deployed without concrete evidence (merge SHA on `origin/main`, deploy command success
output, or service health).

## Relation to other skills

| Skill | Relationship |
|---|---|
| `/ticket-verify staging` | Upstream — sets `staging_verified` and auto-invokes single-ticket mode on PASS |
| `/migration-parity-check` | Schema gate + re-converge truth source; run before/after schema-bearing promotion |
| `/ticket-verify production` | Downstream — verifies behavior/evidence and sets `completed` |

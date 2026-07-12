---
name: ticket-promote
description: Promote staging-verified work from staging to main AND run the project's production deploy steps. Modes: single ticket (default; auto-invoked by /ticket-verify staging on a PASS that clears the §9b auto-promotion gate), --all batch of every staging_verified ticket, --epic for verified epic steps, --all-staging for the whole staging range. Hands off to /ticket-verify production; never sets completed.
max_turns: 250
---

# Ticket Promote

Follow `../references/execution-economy.md` for bounded output, run-local caching, batching, and
non-model-driven waits. Its economy rules never relax production, ordering, or fail-loud gates.

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
`/epic-flow` calls the epic mode after all milestone staging gates pass.

## Non-Negotiables

- **Production-impacting. Prefer stopping over guessing.** Every stop must say exactly what
  landed, what deployed, what is stuck, and what was never touched.
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
- Do not promote unrelated staging commits in ticket/batch/epic modes. If isolation cannot be
  proven, stop and report — do not silently widen scope.
- **Schema-bearing tickets are not the fast path.** Use the schema gate (§Schema gate) before
  treating them as normal cherry-picks.
- Deploy steps come from the ticket's `deployment_guide` artifact and the project deploy
  config (`.claude/commands/deploy.md` when it exists) — read them at runtime; never hardcode
  environment IDs, URLs, or commands from this skill.
- Never set a ticket to `completed`. `/ticket-verify production` owns that.

## Preflight — idempotency and repo policy

Run before creating any worktree, branch, or PR:

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

1. Load `get_epic(project, epic_id)` with milestones, step tickets, gate artifacts, events.
2. If `--milestone` is present, scope to that milestone; otherwise include every milestone
   whose staging gate has a recorded PASS, in milestone order.
3. Require each included step ticket to be `merged` or `staging_verified` with a passing
   epic/milestone staging gate. Source tickets in `absorbed_into_epic` are never promoted.
4. Build the ordered commit list from the step tickets' staging PRs/commits: milestone order,
   then dependency/topological order within each milestone, preserving schema ordering.
5. Prove every commit is on `origin/staging` and not on `origin/main`. Reject the promotion
   if the list contains unrelated tickets, misses a required milestone dependency, or would
   promote an unverified milestone.

This mode is the production half of `/epic-flow`: it promotes verified epic work only,
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

## Local checks

Run the repo's standard checks in the promotion worktree (install, typecheck, build, tests as
the project defines them). Do not start dev servers. Fix only promotion/conflict/schema-gate
issues — no unrelated refactors.

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

## Land on main

```bash
git push -u origin "$BRANCH"
gh pr create --base main --head "$BRANCH" \
  --title "Promote ${SCOPE} to production" --body-file manifest.md
gh pr checks <pr_number> --watch      # cap the wait at 10 minutes
```

If CI fails, fix in the promotion worktree, push, re-watch. If it cannot be made green, STOP
(in batch mode: stop the whole batch).

Merge with the method chosen in Preflight #5:

```bash
# ticket / batch / epic modes — head is the throwaway promotion branch:
gh pr merge <pr_number> --squash --delete-branch    # or another allowed linear method

# all-staging mode — real merge commit; head may be long-lived:
HEAD_BRANCH=$(gh pr view <pr_number> --json headRefName -q .headRefName)
gh pr merge <pr_number> --merge                     # do NOT pass --delete-branch
case "$HEAD_BRANCH" in
  staging|main) echo "Head is long-lived ($HEAD_BRANCH) — leave it." ;;
  *)            git push origin --delete "$HEAD_BRANCH" ;;
esac
git ls-remote --heads origin staging | grep -q refs/heads/staging \
  || git push origin origin/main:refs/heads/staging   # long-lived-branch safety net
```

Confirm the landing:

```bash
git fetch origin main
git merge-base --is-ancestor <merge_sha> origin/main && echo landed
```

## Run the production deploy steps

Landing alone is not promotion — this skill also deploys what landed.

1. Read the ticket's **`deployment_guide` artifact** (production section) and the project
   deploy config (`.claude/commands/deploy.md` when it exists). These are authoritative for
   step order, commands, env files, and verification; the guide's Verification Evidence
   section stays with `/ticket-verify`.
2. Detect which deploy categories the promoted diff actually touched — run the detection
   BEFORE the merge advances `main` (`git diff origin/main..HEAD --name-only -- <paths>` per
   category from the deploy config): schema apply, config/blocks, service deploy, data/DAG
   sync, dependencies, etc.
3. Execute only the detected categories, in the deploy config's order, **running each
   automatable step yourself** — do not just print commands. Verify each step's success
   before the next.
4. Steps that are genuinely manual (no CLI path, or owned by a specific person) are recorded
   as blocker metadata (`blocked_by`, `blocked_reason`, `blocked_context`), not performed.

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

## Re-converge check (drain divergence debt)

Per-ticket cherry-pick promotion only ADDS `main`/`staging` divergence — it never drains it.
Mandatory after any emergency schema exception, advisory otherwise:

1. Run `/migration-parity-check` — content/patch equivalence and per-env schema truth.
2. If it shows residual schema divergence or reconciliation debt from the schema gate,
   reconcile now (usually a full `staging->main` parity merge with a real `--merge` commit).
   Do not carry the debt into the next batch.
3. Record `parity: clean` or the exact outstanding debt in the manifest.

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
| `/create-deployment-guide` | Produces the `deployment_guide` artifact whose prod steps this skill executes |
| `/ticket-verify production` | Downstream — verifies behavior/evidence and sets `completed` |
| `/epic-flow` | Calls `--epic` mode after all milestone staging gates pass |

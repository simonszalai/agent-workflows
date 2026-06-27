---
name: promote-to-production
description: Promote code from staging to production/main. Use when the user asks to deploy a specific ticket from staging to production, merge one ticket from staging into main, promote all staged changes to main, merge staging into main, resolve production-promotion conflicts, or deploy main/production after staging verification.
---

# Promote to Production

Promote either one ticket or all currently staged changes from `staging` into `main`, resolve conflicts in an isolated worktree, verify, merge, and trigger/confirm production deployment.

## Operating Modes

Infer the mode from the request; if ambiguous, stop and ask for the mode.

| Request | Mode | Source |
|---|---|---|
| `/promote-to-production F012` | Ticket-only | Commits/PR(s) for that ticket already on `origin/staging` |
| `/promote-to-production --epic E0007` | Epic | Verified epic step commits, in milestone order |
| `/promote-to-production --epic E0007 --milestone M2` | Epic milestone | Verified step commits for one milestone |
| `/promote-to-production --all-staging` | All staging | Entire `origin/main..origin/staging` range |
| “deploy everything from staging to prod” | All staging | Entire `origin/main..origin/staging` range |
| “deploy F012 from staging” | Ticket-only | Only verified F012 commits |

## Non-Negotiables

- Treat this as production-impacting. Prefer stopping over guessing.
- Do all merge/cherry-pick/conflict work in a new temporary `git worktree`, never in the current Conductor workspace.
- **Never `--delete-branch` (or otherwise delete) a long-lived branch — `staging` or `main`.** In all-staging mode the promotion PR's head is usually `staging` itself, and `staging` is *live infrastructure*: every staging Prefect deployment clones `--branch staging` at runtime, so deleting it on origin instantly CRASHes all staging flows on their next pull (B0174, 2026-06-17). `--delete-branch` is only ever for a throwaway feature/promotion branch.
- Never use `git reset --hard`, `git checkout -- <file>`, `git restore`, `git clean`, or unscoped `git stash` in the shared workspace.
- Do not rename the current branch.
- Fetch before every branch comparison: `git fetch origin main staging --prune`.
- Use `bun` for repo checks. Never start the dev server.
- If a ticket-only promotion cannot be isolated to a proven commit set, stop and report why. Do not silently include unrelated staging changes.
- If an epic promotion cannot be isolated to the epic's verified step commits, stop and report why.
  Do not silently include unrelated staging work.
- **Schema-bearing selective promotions are not the fast path.** Keep parallel code velocity by
  serializing schema. For ts-prefect after E0017, schema changes use Atlas additive-only and
  reviewed-plan gates; do not create/re-point Alembic migrations. For legacy migration repos,
  prefer a schema-first migration lane off current `main` (then immediate `main→staging` sync)
  or an all-staging parity merge. Re-pointing `down_revision` during a cherry-pick is an
  explicit emergency exception that must be approved and immediately reconciled; never
  accumulate migration debt across promotions.
- Read `.claude/commands/deploy.md` if it exists; it overrides generic deployment steps.
- Read `.claude/environments/prod.md` if it exists for production URLs, service IDs, and verification instructions.

## Workflow

### 1. Establish Scope

Run from the repo root:

```bash
git fetch origin main staging --prune
git log --oneline origin/main..origin/staging
```

For all-staging mode:

- Scope is every commit in `origin/main..origin/staging`.
- Stop if the range is empty.
- Create a manifest listing commit SHAs, subjects, likely PR numbers, and likely ticket IDs.

For ticket-only mode:

1. Normalize the ticket ID (`F012`, `B003`, etc.).
2. Find candidate PRs and commits:

   ```bash
   gh pr list --state merged --base staging --search "F012" --json number,title,url,mergeCommit,headRefName,mergedAt
   git log --reverse --oneline origin/main..origin/staging --grep="F012"
   git log --reverse --oneline origin/main..origin/staging --grep="#<pr_number>"
   ```

3. If a PR is found, inspect it:

   ```bash
   gh pr view <pr_number> --json number,title,url,baseRefName,headRefName,mergeCommit,commits,files
   ```

4. Build the minimal ordered commit list from commits that are both:
   - reachable from `origin/staging`, and
   - not reachable from `origin/main`.

5. Prove isolation before continuing:

   ```bash
   git merge-base --is-ancestor <sha> origin/staging
   git merge-base --is-ancestor <sha> origin/main && echo "already on main"
   ```

Stop if the commit list is empty, includes unrelated tickets, or the ticket requires earlier staging commits that are not part of the ticket and were not explicitly approved.

For epic mode:

1. Load `get_epic(project, epic_id)` with milestones, step tickets, gate artifacts, and events.
2. If `--milestone` is present, scope to that milestone; otherwise include every milestone whose
   staging gate has a recorded `PASS`, in milestone order.
3. Require each included step ticket to be `merged` or `staging_verified` with a passing
   epic/milestone staging gate. Source tickets in `absorbed_into_epic` are never promoted.
4. Build the ordered commit list from the step tickets' staging PRs/commits. The order is:
   milestone order, then dependency/topological order within each milestone, preserving migration
   ordering.
5. Prove every commit is reachable from `origin/staging` and not from `origin/main`.
6. Reject the promotion if the commit list contains unrelated tickets, misses a required
   milestone dependency, or would promote an unverified milestone.

The epic mode is the production half of `/epic-flow --full-auto`: it promotes verified epic work
only, deploys production, and leaves final behavior verification to
`/ticket-verify production --epic <EPIC_ID>`.

### 2. Create an Isolated Promotion Worktree

Use a timestamped branch and worktree under `.context/`:

```bash
SCOPE="F012" # or all-staging
STAMP=$(date +%Y%m%d-%H%M%S)
BRANCH="promote-to-production/${SCOPE}-${STAMP}"
WT=".context/promote-to-production/${SCOPE}-${STAMP}"

git worktree add -b "$BRANCH" "$WT" origin/main
cd "$WT"
```

Write a promotion manifest at `.context/promote-to-production/<scope>-<stamp>/manifest.md` containing:

- mode and requested scope
- source branch and target branch
- commits being promoted
- detected tickets/PRs
- changed-file summary
- migration/config/dependency impact
- verification commands and results
- deployment outcome

### 3. Apply the Changes

All-staging mode:

```bash
git merge --no-ff origin/staging
```

Ticket-only mode:

```bash
git cherry-pick -x <sha1> <sha2> ...
```

Epic mode:

```bash
git cherry-pick -x <ordered-epic-step-sha1> <ordered-epic-step-sha2> ...
```

If a milestone is intentionally promoted as a single integration merge commit, document that in
the manifest and prove the merge contains only the verified epic step commits. Otherwise prefer
the explicit ordered cherry-pick list so unrelated staging changes cannot sneak into production.

If conflicts occur:

1. Inspect each conflict and resolve intentionally.
2. Preserve production-only fixes already on `main` unless the staged change explicitly supersedes them.
3. Run targeted checks after resolving.
4. Record every conflicted file and resolution rationale in the manifest.

If conflict resolution reveals that ticket-only promotion needs unrelated staging changes, stop and report the dependency. Ask for explicit approval to include them or switch to all-staging mode.

### 4. Detect Deployment Risk

Before merging to `main`, inspect changed files:

```bash
git diff --name-only origin/main...HEAD
```

Flag and handle:

| Change | Detection |
|---|---|
| Prisma schema/migrations | `prisma/schema.prisma`, `prisma/migrations/**` |
| ts-prefect Atlas schema changes | `ts_schemas/models/**`, `atlas.hcl`, `atlas/plans/**`, `cli_tools/atlas/**`, `migrations/db_object_manifest.py` |
| Legacy Alembic migrations | `migrations/versions/**`, `migrations/env.py`, `alembic/**` |
| Seed data | `prisma/data/**`, `prisma/seed.ts` |
| Dependencies | `package.json`, `bun.lock*` |
| Runtime/config/deploy | `Dockerfile`, Render/env/config files, `.github/workflows/**` |
| Auth/API/contracts | route modules, webhook handlers, API utilities |

If schema changes/migrations are present, check for repo-specific deployment gotchas in memory and ensure the deployment plan states whether the schema apply runs automatically on push to main or needs an explicit command/workflow verification.

**Schema-bearing promotions need the repo-specific schema lane.** When the change touches
schema files, do not assume the old migration workflow still applies.

**ts-prefect after E0017 (Atlas path):**
- Alembic is decommissioned. Do **not** create/re-point Alembic revisions or run
  `alembic upgrade head`.
- Promotion must keep `Validate Atlas Schema Plan` green and preserve the additive-only safety
  gate.
- Production verification is the main-branch `Run Migrations` workflow's
  `Run Atlas Reviewed Plan (Prod)` job: reviewed committed plan match (or no-op already applied),
  DB-only hook, `verify_schema_truth.py`, and post-apply no-op proof.
- If prod needs DDL, the committed reviewed plan file (`atlas/plans/e0017_m3_prod_reviewed_plan.sql`)
  must be intentionally updated/reviewed in the PR.

**Legacy Alembic repos/history only:** when the change touches `migrations/`, run
`/migration-parity-check` before merging. A migration-bearing ticket is **not** eligible for
ordinary selective cherry-pick off a diverged branch: the migration chain is ordered global
state, so cherry-picking forces a `down_revision` re-point that forks the graph and can strand
migrations on a live env (`alembic upgrade head` becomes a silent no-op while objects are
missing — the 2026-06-16 incident).

Choose one for legacy Alembic:

1. **All-staging rollup:** use a full `staging→main` parity merge (`--merge`, not squash/rebase)
   and reconcile the branches in that PR.
2. **Schema-first migration lane:** land the backward-compatible migration from current `main`,
   deploy it, then immediately sync/back-merge `main` to `staging` before dependent code
   continues.
3. **Emergency selective exception:** only with explicit user approval after the parity report.
   Re-point the migration onto the target head, document old parent/new parent and why the safe
   lanes were not used, merge/deploy, then immediately run `/migration-parity-check` and
   reconcile `main`/`staging` before any other migration-bearing promotion. Do not leave
   "reconciliation debt" for a future batch.

Never judge divergence by commit count — use content/patch equivalence, duplicate-revision drift
checks, and per-env schema truth.

### 5. Verify Before Merge

Run the repo’s standard checks in the promotion worktree:

```bash
bun install
bun run typecheck
bun run build
```

Run relevant tests when available and practical:

```bash
bun run test
bunx playwright test --list
# Run specific affected E2E specs only if needed; do not start the dev server.
```

If checks fail, fix only promotion/conflict issues. Do not perform unrelated refactors.

### 6. Create and Merge the Production PR

Push the promotion branch:

```bash
git push -u origin "$BRANCH"
```

Create a PR to `main` with the manifest summary:

```bash
gh pr create --base main --head "$BRANCH" --title "Promote ${SCOPE} to production" --body-file manifest.md
```

Wait for CI:

```bash
gh pr checks <pr_number> --watch
```

If CI fails, fix in the promotion worktree, push, and wait again. When green, merge using the method that matches the mode:

**All-staging mode — MUST use a real merge commit; delete the head ONLY if it is disposable:**

```bash
# The all-staging PR head may be `staging` itself (long-lived). Never blanket --delete-branch.
HEAD_BRANCH=$(gh pr view <pr_number> --json headRefName -q .headRefName)
gh pr merge <pr_number> --merge        # real merge commit; do NOT pass --delete-branch
case "$HEAD_BRANCH" in
  staging|main) echo "Head is long-lived ($HEAD_BRANCH) — leave it." ;;
  *)            git push origin --delete "$HEAD_BRANCH" ;;   # clean up throwaway promotion branch
esac
```

Why not a blanket `--delete-branch`: the all-staging PR's head is often `staging` itself
(you are promoting the whole `origin/main..origin/staging` range), and `staging` is
long-lived *live infrastructure* — every staging Prefect deployment clones `--branch staging`
at runtime, so deleting it on origin CRASHes all staging flows on their next pull. This is
B0174 (2026-06-17): PR #390 merged `--merge --delete-branch` with head `staging` and took down
all 24 staging flows until `staging` was re-pushed. The `case` above still deletes a throwaway
`promote-to-production/<scope>-<stamp>` head, so **promotion branches do not accumulate** — it
only ever spares `staging`/`main`.

Immediately after merging, assert `staging` still exists on origin and restore it from
`main` if it is gone (content-correct after a parity `--merge`):

```bash
git fetch origin --prune
git ls-remote --heads origin staging | grep -q refs/heads/staging \
  || git push origin origin/main:refs/heads/staging   # B0174 safety net
```

Never `--squash` or `--rebase` for an all-staging rollup. Both collapse staging's
commits into new SHAs on `main` with no link back to `staging`, breaking the
`main`↔`staging` merge-base. Once broken, every staging-rooted branch (including
fresh Conductor workspaces) shows hundreds of *phantom* changes when diffed against
`main`, even though the content is identical — because the three-dot diff falls
back to the last genuinely shared ancestor. A `--merge` commit keeps both branches'
histories linked so the merge-base stays current. (This is exactly what broke after
PR #310's squash; recovery required a manual `git merge --no-ff origin/staging` to
re-link the histories.)

**Ticket-only and epic modes — linear history is fine for the throwaway promotion branch:**

```bash
gh pr merge <pr_number> --rebase --delete-branch
```

Cherry-picked ticket/epic promotions already create new commits and do not aim to keep `main`
and `staging` at parity, so `--rebase` (or the repo's preferred linear method) is acceptable
here. `--delete-branch` is safe in these modes because the head is the throwaway
`promote-to-production/<scope>-<stamp>` branch, **not** `staging`.

After merge, fetch and verify `origin/main` contains the promoted commits:

```bash
git fetch origin main
git log --oneline -20 origin/main
```

### 7. Deploy Production

If `.claude/commands/deploy.md` exists, follow its production section exactly.

Generic fallback:

- Assume production deploy is triggered by pushing/merging to `main` only if project docs or CI configuration confirms it.
- If dependencies changed and the hosting platform does not auto-rebuild, flag the required manual Render/service deploy.
- If migrations are not automatic, run the documented production migration command; if no documented command exists, stop and ask.

### 8. Verify Production

Collect evidence, not vibes:

- Confirm `origin/main` contains the merge.
- Check CI/deploy workflow status for the merge commit.
- Check Render/service deploy status and logs if tools are available.
- Check production URL health from `.claude/environments/prod.md` if present.
- For data changes, run read-only post-deploy verification queries from the manifest/deployment guide.
- Recommend or run `/ticket-verify production <ticket>` for ticket-only promotions when the
  ticket workflow is in use.

### 9. Update Ticket Status

For ticket-only mode, if autodev-memory ticket tools are available:

- If deploy to production completed: set ticket status to `to_verify_prod`.
- If production verification completed and passed: set ticket status according to the project’s normal completion workflow.
- If deploy failed: leave/revert the ticket to its pre-promotion status and record the failure.

For all-staging mode, only update tickets whose IDs were confidently identified from promoted commits/PRs; otherwise report the list for manual triage.

For epic mode:

- Mark promoted step tickets `to_verify_prod` (or the closest parent-owned production-verification
  state supported by the current lifecycle).
- Mark/update the parent epic as `to_verify_prod` after production deploy completes.
- Do **not** mark the epic or steps `completed`; `/ticket-verify production --epic <EPIC_ID>`
  does that after evidence collection passes.

## Failure Output

On any stop/failure, report:

- mode and scope
- phase where it stopped
- exact failing command or uncertain condition
- what was changed remotely, if anything
- whether `main` was modified
- next safest action

Do not claim production is deployed until there is concrete evidence from git, CI/deploy status, or service health checks.

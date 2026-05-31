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
| `/promote-to-production --all-staging` | All staging | Entire `origin/main..origin/staging` range |
| “deploy everything from staging to prod” | All staging | Entire `origin/main..origin/staging` range |
| “deploy F012 from staging” | Ticket-only | Only verified F012 commits |

## Non-Negotiables

- Treat this as production-impacting. Prefer stopping over guessing.
- Do all merge/cherry-pick/conflict work in a new temporary `git worktree`, never in the current Conductor workspace.
- Never use `git reset --hard`, `git checkout -- <file>`, `git restore`, `git clean`, or unscoped `git stash` in the shared workspace.
- Do not rename the current branch.
- Fetch before every branch comparison: `git fetch origin main staging --prune`.
- Use `bun` for repo checks. Never start the dev server.
- If a ticket-only promotion cannot be isolated to a proven commit set, stop and report why. Do not silently include unrelated staging changes.
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
| Seed data | `prisma/data/**`, `prisma/seed.ts` |
| Dependencies | `package.json`, `bun.lock*` |
| Runtime/config/deploy | `Dockerfile`, Render/env/config files, `.github/workflows/**` |
| Auth/API/contracts | route modules, webhook handlers, API utilities |

If migrations are present, check for deployment gotchas in memory and ensure the deployment plan states whether migrations run automatically on push to main or need an explicit command.

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

**All-staging mode — MUST use a real merge commit:**

```bash
gh pr merge <pr_number> --merge --delete-branch
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

**Ticket-only mode — linear history is fine:**

```bash
gh pr merge <pr_number> --rebase --delete-branch
```

Cherry-picked ticket promotions already create new commits and do not aim to keep
`main` and `staging` at parity, so `--rebase` (or the repo's preferred linear method)
is acceptable here.

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
- Recommend or run `/auto-verify prod <ticket>` for ticket-only promotions when the ticket workflow is in use.

### 9. Update Ticket Status

For ticket-only mode, if autodev-memory ticket tools are available:

- If deploy to production completed: set ticket status to `to_verify_prod`.
- If production verification completed and passed: set ticket status according to the project’s normal completion workflow.
- If deploy failed: leave/revert the ticket to its pre-promotion status and record the failure.

For all-staging mode, only update tickets whose IDs were confidently identified from promoted commits/PRs; otherwise report the list for manual triage.

## Failure Output

On any stop/failure, report:

- mode and scope
- phase where it stopped
- exact failing command or uncertain condition
- what was changed remotely, if anything
- whether `main` was modified
- next safest action

Do not claim production is deployed until there is concrete evidence from git, CI/deploy status, or service health checks.

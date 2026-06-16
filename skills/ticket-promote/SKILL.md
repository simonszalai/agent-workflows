---
name: ticket-promote
description: Promote one or more staging-verified tickets from staging to main/production branch. Lands code only; does not deploy or verify. Usually called automatically by ticket-verify staging on PASS.
max_turns: 150
---

# Ticket Promote

Promote tickets that passed staging verification from `staging` to `main`. This is a landing
skill, not a deploy/verify skill.

## Usage

```text
/ticket-promote F0123
/ticket-promote F0123 B0042
/ticket-promote --all-passed-staging
```

`/ticket-verify staging` normally calls this automatically for each staging PASS.

## Boundaries

- Do not run deployment commands.
- Do not verify production behavior.
- Do not promote unrelated staging commits in ticket mode.
- Use an isolated worktree under `.context/`; never mutate the user's current workspace for
  promotion conflict resolution.

## Preconditions

A ticket should be in `to_verify_staging` with a PASS verification report, or the caller must be
`/ticket-verify staging` passing a fresh PASS verdict. If no PASS evidence exists, stop.

## Process

### 1. Establish scope

For each ticket:

1. Fetch `origin main staging --prune`.
2. Identify the ticket's staging PR/commits.
3. Prove each commit is reachable from `origin/staging` and not from `origin/main`.
4. Reject the promotion if the commit list includes unrelated tickets or requires unrelated
   staging dependencies without explicit approval.

### 2. Isolated worktree

```bash
SCOPE="F0123"
STAMP=$(date +%Y%m%d-%H%M%S)
BRANCH="ticket-promote/${SCOPE}-${STAMP}"
WT=".context/ticket-promote/${SCOPE}-${STAMP}"
git worktree add -b "$BRANCH" "$WT" origin/main
cd "$WT"
```

Write a manifest with commits, PRs, changed files, conflicts, checks, and final action.

### 3. Apply changes

Ticket mode uses the minimal isolated commit set:

```bash
git cherry-pick -x <sha1> <sha2> ...
```

If conflicts reveal an undeclared dependency on unrelated staging work, stop and report. Do not
silently widen scope.

### 3b. Migration pre-flight (if the ticket carries a migration)

If the cherry-picked diff touches `migrations/versions/`:

```bash
git diff --name-only origin/main...HEAD -- migrations/versions/
```

A migration cherry-picked onto a diverged `main` will point its `down_revision` at a
staging-only revision that is not on `main`, forking the Alembic graph. Before continuing:

1. **Run `/migration-parity-check`.** If it reports a stranded env or true divergence on the
   migration chain, STOP — a migration-bearing ticket is not eligible for selective cherry-pick
   off a diverged branch. Escalate to a full `staging→main` parity merge
   (`/promote-to-production --all-staging`) instead.
2. If parity is clean, **repair the graph**: set the promoted migration's `down_revision` (and
   its `Revises:` docstring) to `main`'s actual head — `uv run alembic heads` — then confirm a
   single head (`uv run alembic heads` → exactly one).
3. **Record the reconciliation debt** in the manifest: the same revision id now exists on both
   branches with a different `down_revision`; the next full `staging→main` sync must reconcile
   it. Do not try to "fix" staging here.

New migrations must already be order-independent (idempotent, additive, absolute-not-relative);
CI (`cli_tools/lint_migrations.py`) enforces this and rejects re-pointing an already-released
`down_revision`.

### 4. Local checks

Run project-appropriate local checks in the promotion worktree. Do not start dev servers unless
project docs explicitly require it for a check.

### 5. Land to main

Create and merge a promotion PR, or use the repo's approved merge path:

```bash
git push -u origin "$BRANCH"
gh pr create --base main --head "$BRANCH" --title "Promote F0123 to production" --body-file manifest.md
gh pr merge --rebase --delete-branch
```

Use the merge strategy required by project policy if it differs.

### 6. Status update

After the promotion commit lands on `main`:

```text
update_ticket(status="to_verify_prod", reason="Promoted from staging to main; production verification pending")
```

Do not set `completed`; `/ticket-verify production` does that after evidence collection.

## Output

```text
Ticket promote complete: F0123
Promoted: staging -> main
Status: to_verify_prod
Deploy: not run
Production verification: not run

Next: /ticket-verify production F0123
```

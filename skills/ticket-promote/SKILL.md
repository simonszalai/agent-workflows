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
- **Migration-bearing tickets are not normal ticket-promote work.** Code can move independently;
  schema order is global state. Prefer the serialized migration lane (schema-first PR off current
  `main`, then immediately sync/back-merge to `staging`) or a full `staging→main` parity merge.
  Selective migration cherry-picks are an explicit emergency exception only.
- Use an isolated worktree under `.context/`; never mutate the user's current workspace for
  promotion conflict resolution.

## Preconditions

A ticket should be in `staging_verified` with a PASS verification report, or the caller must be
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

### 3b. Migration gate (if the ticket carries a migration)

If the cherry-picked diff touches `migrations/versions/`:

```bash
git diff --name-only origin/main...HEAD -- migrations/versions/
```

A migration cherry-picked onto a diverged `main` will point its `down_revision` at a
staging-only revision that is not on `main`, forking the Alembic graph. This is how parallel
code velocity turns into migration debt. Before continuing:

1. **Run `/migration-parity-check`.**
2. **Default action: STOP.** A migration-bearing ticket should move through one of these safe
   lanes instead:
   - **Schema-first lane:** create/land the backward-compatible migration on current `main`,
     deploy it, then immediately merge/sync `main` back to `staging` before dependent code lands.
   - **Full parity lane:** if the migration is already on `staging`, use
     `/promote-to-production --all-staging` as a real merge commit and reconcile the branches in
     the same operation.
3. **Emergency exception only:** continue with selective cherry-pick only if the user explicitly
   approves the exact exception after seeing the parity report, and all are true:
   - no stranded env/schema-truth failure exists;
   - there is no outstanding duplicate-revision drift between `main` and `staging`;
   - the PR body/manifest names the migration file(s), old parent, new parent, and why the safe
     lanes were not used;
   - the operator commits to an immediate post-merge `main↔staging` reconciliation before any
     other migration-bearing promotion.
4. If the emergency exception is approved, re-point the promoted migration's `down_revision`
   (and its `Revises:` docstring) to `main`'s actual head — `uv run alembic heads` — then confirm
   a single head (`uv run alembic heads` → exactly one). This is **temporary debt**, not a normal
   success state.
5. After merge, immediately run `/migration-parity-check` and reconcile `main`/`staging`. Do not
   leave "the next full sync" as the owner of the debt.

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

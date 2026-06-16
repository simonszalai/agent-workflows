---
name: promote-ready-to-prod
description: Batch-promote every staging-verified ticket (the green "Ready for prod" flag on the autodev dashboard) from staging to production, one ticket at a time. The middle ground between /ticket-promote (one ticket) and /promote-to-production --all-staging (the whole staging branch). For each ready ticket it lands the code on main AND runs the project deploy steps (migrations, save blocks, prefect deploy, DAG sync), then advances the ticket. Use when the user asks to promote all ready tickets, deploy everything that passed staging, ship the ready-for-prod column, or batch-promote staging-verified tickets.
max_turns: 250
---

# Promote Ready-to-Prod (batch)

Promote **only the tickets that passed staging verification** — the ones resting in
`staging_verified` (the green "Ready for prod" flag in the autodev dashboard's verify-staging
lane) — from `staging` to `main`, one ticket at a time, and run each ticket's production deploy
steps before moving to the next.

This is the **middle ground**:

| Skill | Scope |
|---|---|
| `/ticket-promote F0123` | one named ticket, **land only** (no deploy) |
| `/promote-ready-to-prod` (this) | **every `staging_verified` ticket**, land **and** deploy, one by one |
| `/promote-to-production --all-staging` | the entire `origin/main..origin/staging` range as one rollup |

It composes the proven single-ticket primitives: it generalizes `promote-to-production`'s
**ticket-only** path (cherry-pick isolation) over the ready set, and runs the project's
`.claude/commands/deploy.md` **production** steps per ticket the way `/auto-deploy production`
does.

## Usage

```text
/promote-ready-to-prod                 # promote ALL staging_verified ts-prefect tickets, in order
/promote-ready-to-prod F0123 B0042     # restrict the batch to these (must already be staging_verified)
/promote-ready-to-prod --dry-run       # discover + order + plan, but make no remote/prod changes
/promote-ready-to-prod --exclude F0130 # promote the ready set except these IDs
```

## Non-Negotiables

- **Production-impacting. Prefer stopping over guessing.** Every stop must say exactly which
  tickets already landed, which is stuck, and which were never touched.
- **One ticket fully landed AND deployed before the next begins.** Migrations are sequential;
  a later ticket's migration parent is the previous ticket's migration once it is on `main`.
  Never land all the code first and batch the deploys at the end.
- **Stop the whole batch on the first hard failure.** Do not skip a failed ticket and continue —
  later tickets may depend on it and the Alembic chain must stay linear. Report and halt.
- All cherry-pick / conflict / migration-repair work happens in a **fresh `git worktree` under
  `.context/`**. Never mutate the current Conductor workspace. Never use `git reset --hard`,
  `git checkout -- <file>`, `git restore`, `git clean`, or unscoped `git stash` in the shared
  workspace (they sweep up parallel sessions' uncommitted work).
- Do not rename the current branch.
- `git fetch origin main staging --prune` before every branch comparison.
- **This repo allows squash merges only** — merge each per-ticket promotion PR with
  `gh pr merge --squash`. (Squash/rebase would break the merge-base only for an *all-staging
  rollup*; per-ticket cherry-pick promotions create new commits anyway, so squash is correct.)
- `.claude/commands/deploy.md` is the **authoritative** source of production deploy commands,
  env IDs, and ordering. Read it at runtime; do not hardcode environment IDs from this skill.

## Before You Start — load promotion memory

Search autodev-memory and load these before touching anything (they encode failures this skill
exists to prevent):

- `mcp__autodev-memory__search` for **"production promotion gotchas cherry-pick alembic fork
  prefect prod env"** (repo `ts-prefect`). The key entry documents:
  1. **Single-ticket cherry-pick forks the Alembic graph.** The promoted migration's
     `down_revision` points at a staging-only revision that is not on `main`, so
     `alembic upgrade` raises a missing-revision error and CI's migration-graph validation
     fails. **Fix during promotion:** re-point the migration's `down_revision` (and the
     `Revises:` docstring line) to `main`'s *actual* current head, then confirm exactly one
     head (`alembic heads`).
  2. **Prod Prefect deploy needs the mounted prod env pipe sourced.** Deploying flows to prod
     with only the prod profile active fails with a client connection error even when a plain
     health check passes. Source the Conductor-mounted prod env pipe
     (`/Users/simon/dev/ts-prefect/prod-deploy.env`, the prod analog of `staging.env`) in the
     **same shell** before the prefect deploy command. It is a named pipe — one read per open.
     A transient connection error on a later deployment in the batch is fine; re-running is
     idempotent and already-registered deployments are unaffected.
  3. **Cherry-pick conflicts in the models package `__init__.py` are common** — the diff drags
     in OTHER staging models as context. Keep **only** the promoted ticket's model.
- The merge-base rule: squash/rebase break `main`↔`staging` parity **for an all-staging
  rollup only**. Not a concern here (per-ticket cherry-pick), but never `--merge` these PRs
  either — squash per repo policy.

## Process

### Phase A — Discover the ready set

1. `git fetch origin main staging --prune`.
2. Get the ready tickets (the dashboard "Ready for prod" green flag === status
   `staging_verified`):

   ```text
   mcp__autodev-memory__list_tickets(project="ts", repo="ts-prefect", status="staging_verified")
   ```

   - If explicit IDs were passed, intersect with this set. Any requested ID **not** in
     `staging_verified` → STOP and report it (don't promote an unverified ticket).
   - Apply `--exclude`.
   - Skip `abandoned`/`completed`, source tickets, and epic-member step tickets whose parent
     milestone owns promotion.
3. If the resulting set is empty: report "no tickets are ready for prod" and stop.

### Phase B — Map each ticket to its staging commits and order the batch

For each ready ticket, find its commit set on staging that is **not yet on main**:

```bash
gh pr list --state merged --base staging --search "F0123" \
  --json number,title,mergeCommit,headRefName,mergedAt
git log --reverse --oneline origin/main..origin/staging --grep="F0123"
```

Prove isolation for every commit:

```bash
git merge-base --is-ancestor <sha> origin/staging && echo on-staging
git merge-base --is-ancestor <sha> origin/main && echo "already on main (skip)"
```

- Drop commits already on `main`. If a ticket has **no** un-promoted commits, it is already
  landed — mark it "already on main" and advance its status to `to_verify_prod` if it is still
  `staging_verified`, then exclude it from the deploy loop.
- **Order the batch by staging merge order** — the sequence in `git log origin/main..origin/staging`
  (oldest first). This keeps cherry-picks applying cleanly and the Alembic chain linear.
- Reject (STOP) any ticket whose commit set pulls in unrelated tickets, or that requires
  unrelated staging dependencies, without explicit approval. Do not silently widen scope.

Write a batch manifest at `.context/promote-ready-to-prod/<stamp>/manifest.md`: the ordered
ticket list, each ticket's commits/PR, detected deploy categories, and a per-ticket result row
to fill in as you go.

**If `--dry-run`: print the ordered plan + per-ticket detected deploy steps and STOP here.**

### Phase C — Per-ticket promote + deploy loop (sequential, stop-on-failure)

For each ticket, **in order**, do the full land-and-deploy before starting the next. Re-fetch
`origin/main` at the top of each iteration so the worktree is based on the *just-advanced* main.

#### C1. Isolated worktree off the current main

```bash
STAMP=$(date +%Y%m%d-%H%M%S)
SCOPE="F0123"
BRANCH="promote-ready/${SCOPE}-${STAMP}"
WT=".context/promote-ready-to-prod/${SCOPE}-${STAMP}"
git fetch origin main staging --prune
git worktree add -b "$BRANCH" "$WT" origin/main
cd "$WT"
```

#### C2. Cherry-pick the ticket's isolated commit set

```bash
git cherry-pick -x <sha1> <sha2> ...
```

Conflict handling:
- **`src/models/__init__.py` (or any package `__init__`)**: the diff drags in other staging
  models — keep only the promoted ticket's model line(s).
- If a conflict reveals an **undeclared dependency** on unrelated staging work, STOP the batch
  and report — do not widen scope.

#### C3. Repair the Alembic graph (if the ticket adds a migration)

If C2 brought in files under `migrations/versions/`:

1. Find `main`'s current head: `uv run alembic heads` (or read the head migration's revision).
2. In the promoted migration file, set `down_revision` to **main's actual head**, and update
   the `Revises:` docstring line to match.
3. Confirm a single head: `uv run alembic heads` → exactly one.

This prevents the missing-revision error and the CI migration-graph failure. (Note this leaves
the same revision id on both branches with different parents; the next staging→main sync must
reconcile it — flag it in the manifest, do not try to fix staging here.)

#### C4. Detect deploy categories — BEFORE merge

Detection must run before the merge advances `main`. Use the categories from
`.claude/commands/deploy.md` Phase 1:

```bash
git diff origin/main..HEAD --name-only -- migrations/versions/          # migrations
git diff origin/main..HEAD --name-only -- src/blocks/ cli_tools/save_blocks.py   # blocks
git diff origin/main..HEAD --name-only -- prefect.prod.yaml             # prefect config
git diff origin/main..HEAD --name-only -- pyproject.toml Dockerfile requirements.txt  # deps
git diff origin/main..HEAD --name-only -- src/dag/ src/prompts/contracts/   # DAG/contracts
```

Record which categories fired for this ticket in the manifest.

#### C5. Local checks in the worktree

Run the repo's standard checks (`uv run` lint/typecheck/tests as practical, and the
migration-graph validation if available). Do not start flows or the dev server. Fix only
promotion/conflict/migration-repair issues — no unrelated refactors.

#### C6. Land on main (squash merge)

```bash
git push -u origin "$BRANCH"
gh pr create --base main --head "$BRANCH" \
  --title "Promote ${SCOPE} to production" --body-file ../manifest.md
gh pr checks <pr> --watch
gh pr merge <pr> --squash --delete-branch     # repo allows squash only
git fetch origin main
git merge-base --is-ancestor <merge_sha> origin/main && echo "landed"
```

If CI fails, fix in the worktree, push, re-watch. If it cannot be made green, STOP the batch.

#### C7. Run production deploy steps — per `.claude/commands/deploy.md` Phase 3

Execute **only the detected categories** from C4, in this exact order, **executing each step
yourself** (do not just print commands). Use the production env file, Prefect API URL, and YAML
from `deploy.md` — read it for the current values; do not hardcode env IDs.

1. **Migrations** (if detected): `op run --environment <prod> -- uv run alembic upgrade head`.
   Verify it completes without error.
2. **Save blocks** (if detected): prod `save_blocks --yes` per deploy.md. Verify.
3. **Prefect deploy** (if `prefect.prod.yaml` changed): **source the prod env pipe first in the
   same shell**, then deploy:
   ```bash
   . /Users/simon/dev/ts-prefect/prod-deploy.env \
     && export PREFECT_API_URL=https://ts-prefect-server.onrender.com/api \
     && uv run prefect profile use prod \
     && uv run prefect --no-prompt deploy --prefect-file prefect.prod.yaml --all
   ```
   A transient connection error on a later deployment in the batch is fine — re-run; it is
   idempotent. Then run the **stale-deployment cleanup** (deploy.md Step 4b) if prefect config
   changed.
4. **DAG sync** (if `src/dag/` or contracts changed): `op run --environment <prod> -- uv run
   python -m cli_tools.sync_dag --db-url-var DATABASE_URL`. Verify node/contract counts.
5. **Dependencies** (if `pyproject.toml`/`Dockerfile`/`requirements.txt` changed): flows pull
   code from git at runtime, but dependencies are baked into the worker image. **Flag the
   manual Render worker deploy and do not mark the ticket done until confirmed** (record as a
   blocker if it can't be done now). This is the only genuinely manual step.

If any deploy step fails: **STOP the batch** at that step. Do not continue to later steps or
later tickets. Leave the ticket's status as-is and report (the code is already on `main`, so
note that a re-run of the failed deploy step is what's needed, not a re-promotion).

#### C8. Advance the ticket and clean up

```text
mcp__autodev-memory__update_ticket(
  project="ts", ticket_id="F0123", repo="ts-prefect",
  status="to_verify_prod",
  reason="Promoted staging->main and deployed to production via /promote-ready-to-prod",
  command="/promote-ready-to-prod"
)
```

If a manual blocker remains (e.g. Render worker redeploy for dep changes, or a
`ts-decrypt-proxy` prod deploy owned by Thomas), set the blocker metadata too (see
`/auto-deploy` Phase 10). Then remove the worktree and continue:

```bash
cd -            # back to the repo root / original workspace
git worktree remove "$WT"
```

Do **not** set `completed`; `/ticket-verify production` does that after prod evidence.

### Phase D — Report

Print one table for the whole batch and the manifest path:

```text
Promote-ready-to-prod — 4 ready, 3 promoted, 1 stopped

Ticket  Order  Landed(main)  Deploy steps run            Status         Note
F0123   1      yes (squash)  migrations, prefect, dag    to_verify_prod -
B0042   2      yes (squash)  blocks                      to_verify_prod -
F0130   3      yes (squash)  (none)                      to_verify_prod -
F0131   4      NO            -                           staging_verified  STOPPED: cherry-pick conflict pulled in unrelated F0129 work

Manifest: .context/promote-ready-to-prod/<stamp>/manifest.md
Next: /ticket-verify production   (verifies the promoted tickets in prod)
```

### Phase E — Re-converge check (drain divergence debt)

Per-ticket cherry-pick promotion only ADDS divergence — it never drains it. Every
migration-bearing ticket re-pointed its `down_revision` on `main` in C3, so `main` and `staging`
now hold the same revision ids under different parents (recorded as reconciliation debt). Letting
that accumulate across batches is exactly what produced the 2026-06-16 fork (R0031/R0032). After
the batch:

1. Run `/migration-parity-check` — it reports content/patch-equivalence (not commit counts) and
   per-environment schema truth, and surfaces any stranded migration.
2. If it shows residual migration divergence or any C3 reconciliation debt, schedule a full
   `staging→main` parity merge (`/promote-to-production --all-staging`, a real `--merge` commit)
   to re-linearize both branches onto one graph. Do **not** carry the debt into the next batch.
3. Record the outcome in the batch manifest — either `parity: clean` or the exact outstanding
   debt — so the next run starts from a known state.

## Failure Output

On any stop, report: the ordered batch, which tickets landed on `main`, which deploy steps ran
for each, which ticket stopped and at exactly which phase/command, whether `main` was modified,
whether any prod deploy step partially ran, and the single safest next action. Never claim a
ticket is deployed to production without concrete evidence (merge SHA on `origin/main`,
migration/deploy command success output, or service health).

## Relation to Other Skills

| Skill | Relationship |
|---|---|
| `/ticket-verify staging` | Upstream — sets tickets to `staging_verified` (the ready flag this skill consumes) |
| `/ticket-promote` | Single-ticket **land-only** primitive this skill generalizes |
| `/migration-parity-check` | Phase E gate — content/patch + per-env schema-truth before declaring parity or scheduling a re-converge merge |
| `/promote-to-production` | Single-ticket or whole-staging-rollup land+deploy; this is the per-ready-ticket batch form |
| `/deploy` (`.claude/commands/deploy.md`) | Authoritative production deploy steps run in C7 |
| `/ticket-verify production` | Downstream — verifies the promoted tickets and sets `completed` |

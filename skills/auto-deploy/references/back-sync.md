# Direct-production back-sync

Load this reference only for P8b: a direct production landing on `main`.

### Phase 8b: Back-sync main → staging (production target only)

Per `landing-policy.md`, a direct-to-`main` landing must also reach `staging` in the same run.
After the production deploy steps complete (Phase 8), and only when the target is `production`
and the merge landed on `main`:

```bash
git fetch origin main staging --prune
git merge-base --is-ancestor origin/main origin/staging && echo already-synced
```

If already synced, record that and continue. Otherwise merge `origin/main` into `staging` with a
real merge commit (`--merge` semantics — squash/rebase break the `main`<->`staging` merge-base,
see `/ticket-promote`'s merge-strategy rule) via a short-lived sync branch + PR, or a direct
merge push when the repository permits it. Never reset, force-push, or overwrite staging-only
work — this is a content-preserving sync. On merge conflict: STOP and report the exact
conflicting files; never resolve by discarding either side.

Pushing `staging` triggers the staging deploy pipeline; verify its mechanics (CI/migrate
workflows green) with one bounded `wait-ci`-style check. Include the back-sync result
(`already-synced` / `synced @ <sha>` / `blocked: <reason>`) in the Phase 9 checklist. Do not
advance the ticket to `to_verify_prod` while the back-sync is unexecuted or unaccounted for.

This phase never applies to the staging target, and `/ticket-promote` does not need it — its
promoted work is already on `staging` by definition.

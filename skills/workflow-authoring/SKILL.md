---
name: workflow-authoring
description: Implement changes to shared agent-workflows skills, agents, hooks, workflows, or binaries with bounded discovery, one canonical final health gate, worktree-safe PR handling, and truthful local propagation verification.
---

# Workflow Authoring

Use for direct changes to the `agent-workflows` repository. This workflow optimizes context shape;
it never weakens tests, review, merge policy, or propagation checks.

## 1. Establish the exact scope

- Work only in the linked/current Conductor workspace. Never modify `~/dev/agent-workflows`.
- Read `CLAUDE.md` once, then inventory the exact files named by the request and their nearest tests.
- Use bounded `rg` results and `sed`/`nl` ranges. Do not concatenate entire large skills, broad repo
  searches, and full diffs into one tool result. If a read truncates, narrow it before continuing.
- Record the intended files, behavior changes, regression tests, and final health command. Expand the
  inventory only when a concrete reference requires it.

## 2. Implement coherently

- Patch related code, documentation, and tests as one behavior unit.
- Follow existing neighboring conventions; do not create compatibility shims.
- Run focused tests while iterating. Focused checks are diagnostics, not the final health gate.
- Keep tool output bounded. Long test output goes through `bin/compact-exec`.

## 3. Final-tree health gate

After the last file change, run exactly once:

```bash
bin/check-agent-workflows
```

Any subsequent tree change invalidates that result and requires one new final gate. A zero-test run
is a failure, never a PASS.

## 4. Commit and publish

1. `git diff --check`, inspect the bounded diff/stat, then `git add -A` and commit everything.
2. Verify `git status --porcelain` is empty after the commit.
3. Push the workspace branch and create a regular PR against `main`.
4. Wait once with `bin/wait-ci <pr> --timeout 540`.
5. Merge without `--delete-branch`; Conductor often has `main` checked out in another worktree, and
   `gh` branch cleanup can report a local failure after the remote merge succeeded. Confirm the PR is
   `MERGED`, then delete only the remote throwaway head with `git push origin --delete <head>`.

## 5. Verify propagation truth

Remote `main` and the live local user-level checkout are different states. After merge:

```bash
git fetch origin main
bin/verify-agent-workflows-live <merge-sha>
```

- `status=live`: remote and local propagation are complete.
- `status=not_live` or `live_but_modified`: report remote merge success **and** local propagation
  pending. Never modify, reset, stash, or merge a dirty/diverged live checkout from the Conductor
  workspace.
- Cloud sessions receive merged files on their next SessionStart; an already-running agent retains
  instructions already loaded into its context, though explicit later file reads see filesystem
  changes.

## Output

Report PR/merge SHA, final health evidence, workspace cleanliness, and local propagation status as
separate facts. Never collapse “merged remotely” into “live everywhere.”

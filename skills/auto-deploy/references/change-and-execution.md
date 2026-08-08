# Change detection, preflight, and deployment execution

Load this reference when executing P6, P6b, or P8. Load the conditional migration, provider, and
back-sync references only when their manifest predicates become true.

### Phase 6: Detect Changes

Before merging, analyze what changed to determine which deployment steps
are needed. This MUST happen before merge (pushing advances the target branch).

```bash
# Keep the complete inventory on disk; inspect only a bounded excerpt.
git diff origin/{target_branch}..{branch} --name-only > .context/deploy-files.txt
sed -n '1,200p' .context/deploy-files.txt
```

**Generic detection categories:**

| Category     | Detect                                              |
| ------------ | --------------------------------------------------- |
| Schema       | ts-prefect Atlas paths (`ts_schemas/models/`, `atlas.hcl`, `atlas/plans/`, `cli_tools/atlas/`, `migrations/db_object_manifest.py`) or legacy migration dirs (`alembic/`, `migrations/versions/`, Prisma migrations) |
| Config       | Deployment config files (YAML, env, etc.)           |
| Dependencies | Package manifests, lockfiles, `Dockerfile`, and requirements files |

**Project-specific categories** (from `/deploy` command if loaded):

The project-specific deploy command may define additional categories like
blocks, Prefect config, DAG nodes, etc. Detect all categories it specifies.

Store detection results for use in Phase 8.


### Phase 6b: Preflight every deploy command before merge

Build the exact ordered command table for Phase 8 while the PR can still be stopped safely. Every
row must have a preflight result:

- validate script/module imports and CLI argument shape (`--help`, compile/import, config parse, or
  the project's non-mutating plan/dry-run command);
- when the project documents a safe idempotent staging mirror, execute the same command shape there
  with **staging credentials only** and verify its postcondition;
- when no staging mirror exists, use a non-mutating production plan/readiness check — never invent a
  fake dry-run flag and never perform the production mutation as the preflight.

Record `command`, `target`, `preflight`, and `expected postcondition`. A missing/failed preflight is
a STOP before merge. The preflight does not replace the real deploy or its verification; it catches
bad imports, stale flags, wrong YAML/entrypoints, and environment selection before production code
lands.


### Phase 8: Run Deployment Steps

If a project-specific `/deploy` command was loaded in Phase 3, follow its
deployment steps **in order**, using the change detection from Phase 6 to
determine which steps to run.

**CRITICAL: Use the correct environment-specific commands.** The `/deploy`
command documents commands for each environment (staging vs production) with
different env files, Prefect API URLs, and YAML files. Match the commands to
the target environment determined in Phase 1.

**Generic fallback** (when no project-specific deploy exists):

1. **Migrations**: If migration files detected, rely on CI auto-migration
   (most projects run `migrate.yml` on push to main/staging)
2. **Dependencies**: If dependency files changed, flag to user that a
   service redeploy may be needed

**Execution rules:**

- **EXECUTE every automatable step directly** — do NOT just print the
  commands or tell the user to run them. The whole point of auto-deploy
  is autonomous execution. If the project deploy command provides a bash
  command for a step (migrations, blocks, Prefect deploy, DAG sync, etc.),
  run it yourself.
- Skip the project deploy command's "Confirm with User" phase — the ticket
  being at `ready_to_deploy` status IS the confirmation (or the user
  explicitly passed a target override, which is also confirmation).
- Run steps in the order specified by the project deploy command
- Each step depends on the previous one succeeding
- If a production step fails: STOP, do not continue, revert ticket status. If a staging step fails
  on a documented bounded prerequisite, apply `../../references/staging-autonomy.md`, repair and
  retry that invalidated phase; stop only at its legitimate-stop boundary.
- Log output of each step for verification
- For production, prefer audited MCP/server-side mutations. Direct local production DB writes are
  prohibited. Any other authenticated production CLI step with no remote route must run as
  `bin/redacted-exec -- <documented command>`; never inspect the auth profile or write raw output to
  a compact-exec log.
- Only flag steps to the user that are **genuinely manual** and cannot be
  run from an available CLI/API/MCP route (e.g., clicking "Deploy" in a web dashboard with no
  callable provider tool). Steps that have callable commands are not manual: run them. For staging,
  documented bounded fixture/seed/registration prerequisites are standing-authorized.

**Deployment-guide reconciliation (MANDATORY, after the detected categories run).** The
project `/deploy` command is the per-repo source of truth for *how* standard categories
deploy — but the ticket's **`deployment_guide` artifact** (finalized by
`/create-build-todos`) is where *ticket-specific one-off steps* live: a new secret/
credential block, a new env var, a pre-enable backfill, a cross-repo ordering constraint.
Those exist in no generic category and are silently skipped unless reconciled here. After
executing the detected categories:

1. Read the guide's **Steps** section for the target environment (the artifact is already
   loaded from Phase 6's evidence-contract check).
2. For each guide step, classify and report it: `covered` (the project deploy command
   already ran it), `executed-now` (you ran it in this reconciliation), or `blocked`
   (genuinely manual — record blocker metadata per Phase 6).
3. A guide step that cannot be mapped to anything run, executed, or blocked is a **STOP
   condition**, not a skip — report it as a guide/deploy mismatch. Do not advance the
   ticket to a verification status with an unexecuted, unaccounted-for deploy step,
   because `/ticket-verify` will then fail (or worse, falsely pass) on an environment the
   guide says is incomplete.

Include the per-step reconciliation table in the Phase 9 verification checklist output.

If the diff removes or retires a route, writer, trigger, queue consumer, deployment, flag, or other
runtime surface, Phase 9 must also close the negative inventory recorded by the plan/deployment
guide: code/config search shows each old item absent, authoritative live inventory shows retired
registrations absent, and the surviving route is exercised. An unexplained legacy item is a failed
deploy verification.

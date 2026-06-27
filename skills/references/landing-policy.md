# Landing and deployment routing policy

This policy is shared by ticket-level and epic-level workflow skills.

## Default stance

- Small, obvious, low-risk standalone fixes may land/deploy directly to production (`main`).
- Anything complex, risky, or uncertain uses the staging-first path: land/deploy to `staging`,
  then run staging behavior verification before production promotion.
- Epic work lands through the epic/milestone path, normally to `staging` or a staging-bound
  integration branch. Single ticket flow must not silently treat an epic step as standalone.

## Preflight before building

Before planning/building, determine the intended delivery target:

1. Read the current branch and remote base:
   ```bash
   git fetch origin --prune
   git rev-parse --abbrev-ref HEAD
   git merge-base --fork-point origin/main HEAD 2>/dev/null || true
   git merge-base --fork-point origin/staging HEAD 2>/dev/null || true
   ```
2. Read Conductor/workspace target branch if available in the session context.
3. Load the ticket and check whether it is an epic step (`related`/`tags.related_epic` or an
   explicit epic membership returned by MCP).
4. Classify risk and choose either `staging` or `production`.

## Direct-to-main is allowed only for tiny safe work

Direct production (`main`) landing/deployment is acceptable when all of these are true:

- no schema migration or data backfill;
- no prompt/LLM behavior change;
- no auth/security/payment/deployment config change;
- no cross-repo contract;
- no user-visible multi-step workflow change;
- local tests/review pass cleanly;
- the diff is small and easily reversible.

If the workspace appears to target `main` but these checks do not pass, route standalone
ticket-flow to `staging` automatically unless the user explicitly requested direct production.

## Staging is required when in doubt

Use `staging` when any of these are true:

- migration/schema/data model changes;
- new jobs/flows/background processing;
- prompt/model/scoring logic changes;
- non-trivial UI/UX changes;
- risky bug fix where outcome needs observation;
- any epic step or cross-repo contract;
- any ambiguity about safety.

## Deployment and verification boundaries

This policy chooses the route; it does not define project-specific deploy commands.

- `/ticket-flow` deploys standalone tickets by invoking `/auto-deploy` for the chosen target.
- `/auto-deploy` owns PR creation, merge, deploy steps, deploy-mechanics checks, blockers, and
  transition to `to_verify_staging` or `to_verify_prod`.
- `/ticket-verify` owns post-deploy behavior/evidence testing. A staging-first ticket is not
  production-ready until `/ticket-verify staging` passes and promotion/deployment completes.
- Epic steps remain parent-owned: `/ticket-flow` never deploys or verifies a step's runtime
  surface in isolation — the milestone deploy + cross-step gate are milestone-level and owned by
  `/milestone-flow`. But a `/ticket-flow` run on an epic step must not dead-end at a
  silently-undeployed `merged`: a **direct** run (no `--epic-context`) that lands the milestone's
  final step hands off to `/milestone-flow <EPIC> <MILESTONE>`, which deploys the milestone target
  and runs the explicit epic/milestone verifier. A **delegated** run (`--epic-context`, invoked by
  `/milestone-flow`) or one that leaves sibling steps open lands only; `/milestone-flow` deploys +
  verifies once the milestone is complete. Either way `/milestone-flow` deploys the gate before
  reporting milestone success.

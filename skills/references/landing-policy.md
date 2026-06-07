# Landing policy

This policy is shared by ticket-level and epic-level workflow skills.

## Default stance

- Small, obvious, low-risk standalone fixes may land directly to `main`.
- Anything uncertain lands to `staging` first.
- Epic work lands through the epic/milestone path, normally to `staging` or a staging-bound
  integration branch. Single ticket flow must not silently treat an epic step as standalone.

## Preflight before building

Before planning/building, determine the intended landing target:

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
4. Classify risk.

## Direct-to-main is allowed only for tiny safe work

Direct `main` landing is acceptable when all of these are true:

- no schema migration or data backfill;
- no prompt/LLM behavior change;
- no auth/security/payment/deployment config change;
- no cross-repo contract;
- no user-visible multi-step workflow change;
- local tests/review pass cleanly;
- the diff is small and easily reversible.

If the workspace appears to target `main` but these checks do not pass, stop before doing work
and propose switching the workspace target to `staging`.

## Staging is required when in doubt

Use `staging` when any of these are true:

- migration/schema/data model changes;
- new jobs/flows/background processing;
- prompt/model/scoring logic changes;
- non-trivial UI/UX changes;
- risky bug fix where outcome needs observation;
- any epic step or cross-repo contract;
- any ambiguity about safety.

## No deployment or verification

Landing policy ends after the merge and ticket status update. Do not run deploy commands, wait
for deploy infrastructure, trigger flows, seed data, or perform environment verification here.

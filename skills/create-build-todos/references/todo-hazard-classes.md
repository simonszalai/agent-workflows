# Todo hazard classes

Four build shapes that have each shipped a production incident when the build todos did not
carry them explicitly. They are independent — load this file when the plan has the surface,
and give that hazard its own build todo.

## Elimination Build Todos (CRITICAL)

When the plan includes a "What We're Eliminating" section, create a **dedicated build todo**
for the elimination step. This is NOT optional — it is as mandatory as a migration step.

**The elimination todo must include:**

1. **Capture the before inventory** — list every old code call site, flag/config entry, route,
   writer/trigger/consumer, job/deployment registration, and operator script named by the plan
2. **Migrate all consumers** — list every call site from the plan's consumer search, with the
   new code each should use
3. **Delete old files/config/registrations** — list every scoped item being removed and assign
   runtime registration deletion to the deployment guide
4. **Negative-inventory verification commands (record for the main orchestrator; builders do not
   execute them):**
   ```bash
   # Verify zero imports of old system remain
   grep -r "OldSystem\|old_module" src/ --include="*.py" | grep -v __pycache__
   # Expected: no output

   # Verify old files are gone
   ls src/old/path/ 2>/dev/null
   # Expected: "No such file or directory"

   # Run type checker — catches any remaining broken references
   uv run pyright  # or project's type checker
   ```
   Also include the authoritative post-deploy inventory command/query that must show every retired
   runtime item absent, plus a smoke command for the sole surviving path.
5. **Position in build order:** Elimination comes AFTER all new code is wired up but BEFORE
   writing tests. Never leave elimination as the last implementation step. Its commands run in the
   main orchestrator's pre-review gate after test-writing, not in the builder chain.

**Rule:** If a plan replaces system X with system Y, and the build todos don't include an
elimination step plus before/after negative inventory for X, the build todos are incomplete.

## Polling / Storage Build Todos (CRITICAL)

When the plan includes a poller, observer, scheduler, queue consumer, webhook, scraper, or
other repeated writer, at least one build todo must own the storage-shape proof:

1. **List durable write paths** — tables/queues/logs written per run and whether each is a
   canonical upsert, changed-event insert, raw snapshot, append-only observation, or aggregate.
2. **Prove identical-input behavior** — include a unit/integration test or query showing that
   two identical polls do not create duplicate durable business data unless explicitly intended.
3. **Budget the multiplier** — include the formula for rows/day and bytes/day using poll
   interval, active source count, average/worst-case items per source, row width, and index/WAL
   impact.
4. **Bound append-only history** — if per-poll history is truly required, specify the consumer,
   retention/partitioning policy, and failure mode when the budget is exceeded.
5. **Prefer canonical/delta storage** — if the only consumer needs actual entries and timestamps,
   use canonical rows with `first_seen_at`, `last_seen_at`, and `seen_count`, plus optional
   first-seen/changed events. Do not save the same unchanged payload every poll because the
   plan says "lossless".

**Rule:** Build todos are incomplete if polling frequency can linearly multiply redundant
stored data and no step proves that this is required, bounded, and verified.

## Shared Deadline / Timeout Budget Todos (CRITICAL)

When the plan introduces or reuses a shared deadline, coordinator, timeout wrapper, semaphore,
or batch executor that heterogeneous work runs under, at least one build todo must own the
**budget-fit proof**:

1. **Enumerate every work type** that will execute inside the bounded construct — including ones
   the plan declares "outside this policy". If work physically executes inside the coordinator
   (even only on pass 1), it inherits the deadline regardless of what comments or plan
   assumptions say. A "remains outside this policy" claim must be enforced structurally
   (excluded from the `work` dict / run outside the wrapper), never by comment.
2. **Compute worst-case duration per work type** from its own internal budgets (e.g., browser
   strategy budgets, provider read timeouts, internal retries) and assert each fits under the
   shared deadline — or explicitly exempt/partition that work type.
3. **Require a test per slow work type**: a test that runs the slowest legitimate variant (e.g.,
   a `use_browser=True` config with a 150s strategy budget under a 55s coordinator) and asserts
   it is either exempted or fails with its **original diagnostic preserved**, not a generic
   deadline `TimeoutError` that masks the real error.

**Rule (B0312/B0306):** Build todos are incomplete if any work type's legitimate worst-case
duration exceeds a shared deadline it runs under and no todo proves exemption or diagnostic
preservation. B0306 put browser-based Truth Social (150s budget) inside a 55s coordinator,
replacing actionable bot-protection diagnostics with `TimeoutError` for 106 masked failures.

## External Data / Cache Finality Build Todos (CRITICAL)

When the plan touches provider-backed data, shared caches, market/reference data,
prompt-context enrichment, evaluation labels, or ground-truth outcomes, at least one build
todo must own the temporal-finality proof:

1. **Inventory writers/readers** — list every code path that writes or reads the table/cache.
   Include background jobs, prompt/live context fetchers, backfills, CLIs, and dashboards.
2. **Declare lifecycle per value** — `live`, `provisional`, or `final`, plus the timestamp,
   exchange/calendar/timezone, and provider rule that makes the value final.
3. **Prevent cross-writer poisoning** — if one writer fetches live/provisional data and another
   reader needs final labels, require separate storage or an explicit lifecycle/status column
   that readers enforce.
4. **Specify refresh/repair behavior** — mutable provider data must be upserted or refreshed
   safely. `ON CONFLICT DO NOTHING` is only acceptable for facts proven immutable.
5. **Add regression tests** — include a cache-hit test where a stale/provisional row already
   exists before the finalizing job runs, and prove the job ignores, refreshes, or repairs it.

**Rule:** Build todos are incomplete if time-varying provider data can be cached once and later
trusted as final ground truth without an explicit lifecycle contract and cache-hit test.

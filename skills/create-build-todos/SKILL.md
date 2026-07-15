---
name: create-build-todos
description: Create detailed implementation steps from an approved plan. Spawns build-planner agent to create build_todos/.
max_turns: 75
memory:
  tags:
    - migration
    - implementation-pattern
    - $tech_tags
  types:
    - gotcha
    - pattern
    - solution
---

# Create Build Todos

Create detailed implementation steps (`build_todos/`) from an approved `plan.md`. This command
performs **deep research** into the codebase, memory service, and git history to ensure all
existing patterns and rules are discovered and followed.

## Usage

```
/create-build-todos F0009                            # Feature ticket F0009
/create-build-todos B0009                            # Bug ticket B0009
/create-build-todos R0003                            # Refactor ticket R0003
```

**Ticketless mode (lfg):** when invoked from `/lfg` (no ticket exists), skip the MCP
prerequisites and write build todos as `.context/build_todos/NN-name.md` files instead of
build_todo artifacts. Everything else (research depth, template, quality bar) is unchanged.

## Prerequisites (MUST VALIDATE BEFORE STARTING)

Before doing any work, validate ALL prerequisites. Stop immediately if any fail.

```
# 1. Load ticket
ticket = mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  detail="full",
  artifact_types=["source", "plan", "investigation", "deployment_guide"],
  include_events=false
)
# If not found: STOP - ticket not found

# 2. Check plan artifact exists
# Look for artifact with type="plan" in ticket response
# If missing: STOP - run /auto-plan first
```

**If any prerequisite fails:**

| Missing             | Action                                 |
| ------------------- | -------------------------------------- |
| Ticket not found    | **STOP** - create ticket first         |
| No plan artifact    | **STOP** - run `/auto-plan [id]` first |
| Plan not reviewed   | **WARN** - suggest user review plan    |

**Additional requirements:**

- Review and iterate on plan.md before running this command

## What This Command Does

### Phase 1: Deep Research

1. **Knowledge base search** - Find all relevant:
   - References (architecture, patterns, standards)
   - Gotchas (pitfalls that apply to this change)
   - Solutions (past fixes for similar problems)

2. **Codebase pattern search** - Find all:
   - Similar implementations to follow
   - Conventions specific to affected areas
   - Error handling patterns in use
   - Test patterns for this type of code

3. **Git history analysis** - Understand:
   - Why affected code exists in its current form
   - Past issues with similar changes
   - Recent changes that might conflict
   - Contributors who know this area

### Phase 2: Break Down the Plan

4. **Split plan into independently completable steps:**
   - Each step maps to one logical change (one file group, one concept)
   - Order by dependencies
   - Identify which steps can be parallelized

### Phase 3: Deepen Each Step (CRITICAL)

5. **For each step, perform independent deep research:**
   - This is NOT just restating the plan in more detail
   - **Memory searches are batched:** run ONE consolidated memory search UP FRONT covering all
     steps' areas (see "Build Todo Creation Process" step 3). Do not re-run the same broad
     searches per step. Per-step searches are only for **step-specific unknowns** the
     consolidated search did not cover.
   - Each step gets its OWN research pass:
     a. **Check the consolidated memory results** for patches, solutions, and gotchas that
        apply to THIS step's area. Only if this step has a specific unknown not covered
        (e.g., an unusual library, a one-off migration mechanism), run a targeted search:
        ```
        mcp__autodev-memory__search(queries=[
          {"keywords": ["<step-specific-unknown>", "<technology>"],
           "text": "<the specific unknown> patch fix solution gotcha"}
        ])
        ```
        Read the full content of every relevant result — titles alone are
        not enough. Document findings in the "Known Patches & Solutions"
        subsection (see template).
     b. Read the actual files that will be modified — understand their
        current state, imports, patterns, and constraints
     c. Find the closest existing implementation to follow (grep for
        similar code, read it, document the pattern with file:line refs)
     d. Check git history for past changes to these specific files
     e. Trace data flow: what produces the input this step needs? What
        consumes this step's output? What breaks if the contract changes?
     f. Identify edge cases: what happens with empty input, null fields,
        concurrent execution, partial failure?
     g. For any repeated writer (poller/observer/scheduler/queue/webhook), trace write
        amplification: what rows are written per run, which writes are canonical upserts
        vs append-only history, what dedupes across runs, and what happens when the same
        source payload is observed twice.

   **The deepened step must contain enough detail that the builder can
   implement it without needing to do additional research.** If the builder
   would need to "figure out" how something works, the deepening was
   insufficient.

### Phase 4: Write Build Todos

6. **Create build_todo artifacts** with detailed steps:
   - Specific files to modify with current line numbers
   - Code examples following discovered patterns
   - Dependencies between steps
   - Test requirements per step
   - Verification commands
   - Edge cases to handle
   - **Complexity class tag (MANDATORY)** — see "Complexity Tagging" below

## Process

1. **Locate work item:**
   - Same ID resolution as `/auto-plan`
   - Error if the plan artifact doesn't exist

2. **Read context** from `get_ticket` response:
   - Plan artifact - The approved architecture plan
   - Source artifact - Original problem/feature description
   - Investigation artifact - Production findings (if exists)

3. **Spawn build-planner agent** for deep research:
   - Agent searches memory service exhaustively
   - Agent searches codebase for all relevant patterns
   - Agent analyzes git history for context
   - Agent may spawn additional researcher agents only with `fork_turns: "none"` and bounded,
     self-contained packets

4. **Write build_todo artifacts:**
   - One artifact per implementation step
   - Steps ordered by dependencies via `sequence` field
   - Each step includes discovered patterns to follow
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="build_todo",
     title="<step title>",
     sequence=N,
     status="pending",
     content="<step content, including the **Complexity:** simple|complex line>",
     command="/create-build-todos"
   )
   ```

5. **Finalize the deployment_guide artifact (MANDATORY):**

   `/auto-plan` left a DRAFT `deployment_guide` with the deploy *shape* and a first-cut
   verification evidence contract. The deep research you just did is exactly what turns that
   draft into actionable mechanics — do not leave it as a draft. Update it (`update_artifact`;
   create it if the ticket skipped `/auto-plan`) so the deploy steps name the **concrete**
   objects this build produced:

   - the actual **schema artifact**: for ts-prefect, Atlas/model/DB-only manifest changes and
     reviewed plan needs (or "no schema change"); for legacy repos, migration revision id /
     filename (or "no migration"), and whether it must run before the code deploy;
   - if there is a schema change, the **schema lane**: ts-prefect Atlas additive-only/reviewed-plan
     path, schema-first PR off current `main` followed by immediate `main→staging` sync, full
     `staging→main` parity merge, or no schema lane. Do not mark a schema-bearing ticket as
     suitable for routine per-ticket cherry-pick promotion unless the repo-specific gate supports it;
     legacy selective migration cherry-pick is an explicitly approved emergency exception only.
   - the **cross-repo order** confirmed against what was actually built — which repo's change must
     land first and why (the contract that forces it);
   - the **real deploy commands/objects** for this project (discover from the project
     `CLAUDE.md`/`AGENTS.md` + memory — e.g. how code reaches runtime, any scheduler/worker
     deploy, any secret/credential block to provision, DAG/pipeline sync, env vars);
   - if any verification row requires runtime evidence (canary run, observer, flow, deployment,
     stored rows, polling, scheduler, worker, Prefect, supervisor, webhook, or live readback), the
     concrete producing object in the same build scope: flow entrypoint, environment YAML entry,
     supervisor registration when applicable, deploy-owned canary CLI, or an explicit
     disposable integration-DB proof instead of staging runtime evidence;
   - the **Verification Evidence** rows refined to concrete queries/commands now that you know the
     real table/column/log names — each with expected good output and a bad-output interpretation,
     for both staging and production.
   - for polling/observer/storage changes, the **volume and redundancy evidence**: queries that
     compute rows/run, rows/day, bytes/day, duplicate/unchanged-payload write rate, retention/TTL,
     and whether repeated identical polls create new durable rows.

   Use the template in the `create-deployment-guide` skill. Mark `Status: FINALIZED` only when the
   deploy steps and both env evidence sections are concrete **and every runtime evidence row has a
   producing deployment/command**; otherwise leave the unknown rows as `TBD` and note them.

   Find the draft's `artifact_id` in the `get_ticket` response (the `deployment_guide` artifact)
   and update by id; if the ticket skipped `/auto-plan` and none exists, create one instead.

   ```
   mcp__autodev-memory__update_artifact(
     project=PROJECT,
     artifact_id="<deployment_guide artifact id from get_ticket>",
     content="<finalized guide>",
     command="/create-build-todos"
   )
   ```

## Complexity Tagging (MANDATORY — drives per-todo builder model routing)

The build-planner MUST tag **every** build_todo with a `complexity` class. `/build` reads this
tag to route each todo to the cheap (`sonnet`) or strong (`opus`) builder model:

- `complexity: simple` — the todo is scoped to **<=2 files**, touches **no**
  schema/migration/auth/deploy-config paths, and makes **no** cross-module contract change.
- `complexity: complex` — cross-cutting or schema-bearing todos, changes to auth or
  deploy-config, or any cross-module contract change.

Record the tag as a `**Complexity:** simple|complex` line in the todo content (first section),
and mirror it in the `create_artifact` call. When in doubt, tag `complex` — `/build` defaults
to opus (the fail-safe) whenever the tag is missing or ambiguous, so never guess `simple`.

## Deliverable Coverage Map (MANDATORY — no silent drops)

Before writing the todos, the build-planner MUST emit a **deliverable → build_todo coverage
map** derived from the plan's deliverables list (the plan's scope/deliverables/"what we're
building" section):

1. Enumerate every deliverable named in the plan.
2. Map each deliverable to the build_todo `sequence`(s) that implement it.
3. Any deliverable with **no** covering build_todo MUST appear as an explicit
   `DEFERRED — needs user approval: <deliverable>` line inside the **first** build_todo.
   A deliverable may never be silently dropped.

Include the full map (deliverable, covering sequences, or DEFERRED) in the first build_todo so
the reviewer's plan-conformance check can cross-check it against the raw plan/source list.

## Linked-Workspace Preflight (MANDATORY — fail fast before dispatch)

Before any build dispatch, verify that **every repo referenced in the plan/source artifacts**
(including cross-repo `related` contracts) has a linked, resolvable workspace on this machine.
If any referenced repo has no resolvable linked workspace, **STOP** with a clear message naming
the missing repo(s) — do not create todos that a later `/build` cannot execute.

## Research Depth

The build-planner agent performs thorough research. See
`references/research-requirements.md` for the full research methodology including:

- Memory service search requirements
- Codebase pattern research requirements
- Git history research requirements
- CLAUDE.md compliance checks

| Area            | What It Searches                               | Why                                        |
| --------------- | ---------------------------------------------- | ------------------------------------------ |
| Knowledge base  | All references, gotchas, solutions             | Avoid known pitfalls, follow standards     |
| Codebase        | Similar code, patterns, conventions            | Match existing style and approaches        |
| Git history     | Related commits, past issues, contributor info | Understand context and avoid past mistakes |
| Past work items | Similar build_todos, review findings           | Reuse patterns, avoid past review issues   |
| CLAUDE.md       | Project rules and critical requirements        | Ensure compliance with project rules       |

## Todo depth by builder engine

Todo depth follows who executes it, not a fixed rule:

- **Native builder (default):** the builder has MCP and memory access and can read the
  repository. Give it objective, acceptance criteria, likely files plus one relevant
  analogue, risk-specific gotchas, required validation, and hard boundaries. Pass paths
  to longer artifacts instead of copying their contents.
- **External builder (`/build --builder codex`):** the Codex side has NO MCP or memory
  access and sees only the todo text plus a short context blob. Everything it needs must
  be IN the todo — discovered patterns with `file:line` references, the closest analogous
  module, the exact verification commands, applicable CLAUDE.md rules. "None applicable"
  is a valid entry; silence is not.

## Output Template

Use the template at `templates/build-todo.md` for each build step.

**Formatting:** (keep lines ≤100 chars; tables exempt)

## Output

Build todo artifacts stored in MCP ticket system:

| Artifact | Type | Sequence |
|---|---|---|
| Step 1: [name] | build_todo | 1 |
| Step 2: [name] | build_todo | 2 |
| ... | build_todo | N |

Each build todo contains:

- **Objective** - What this step accomplishes
- **Files to Modify** - Specific files and line estimates
- **Discovered Patterns** - Patterns found that must be followed
- **Implementation Details** - Code snippets following patterns
- **Tests** - Test cases based on similar code
- **Verification** - Commands to verify step worked

## Agent Selection (if build-planner requests)

| Need                     | Agent          | Why                                |
| ------------------------ | -------------- | ---------------------------------- |
| Deeper pattern search    | `researcher`   | Find more examples in codebase     |
| Framework best practices | `web-searcher` | External docs for complex patterns |

## Build Todo Creation Process

1. **Read plan.md** - Understand the architecture
2. **Identify steps** - Break into independently completable units
3. **Pre-flight memory service audit (MANDATORY):**
   a. Search memory service for gotchas and references relevant to each build step's area
   b. For each build todo's affected area (database, migrations, encryption, API, etc.),
   search with relevant keywords
   c. Review the most relevant memory entries in full
   d. If a build todo involves database schema changes, search for migration-related gotchas
   e. Document findings in each build todo's "Discovered Patterns" section
4. **For each step:**
   a. Search memory service for gotchas/standards
   b. Research codebase for patterns to follow
   c. Research git history for context
   d. Check CLAUDE.md for applicable rules
   e. Write build todo with all findings

## Synthesis Guidelines

### Discovered Patterns Section

Every build todo MUST include a "Discovered Patterns" section:

```markdown
## Discovered Patterns

**From memory service:**

- [Entry title]: [How it applies]
- [Entry title]: [Standard to follow]

**From codebase:**

- `src/path/file.py:123`: [Pattern to follow]
- `src/path/other.py:45`: [Convention to match]

**From git history:**

- Commit `abc123`: [Why this matters]
- Past issue: [What to avoid]

**From CLAUDE.md:**

- [Specific rule and how to comply]

**Known patches & solutions (from memory + past tickets):**

- [Patch/solution title]: [What it fixes and how it applies to this step]
- [Past ticket ID]: [What was done and what to reuse or avoid]
```

### Implementation Details Section

After patterns, write implementation that:

- Explicitly follows each discovered pattern
- References pattern sources in comments
- Matches existing code style exactly

### Files to Modify Section

Be specific:

- List exact files to modify
- Estimate lines changed per file
- Note if creating new files

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
4. **Negative-inventory verification commands:**
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
   writing tests. Never leave elimination as the last step — it must be verified before the
   build is considered complete.

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

## Step Dependencies

Order steps by dependencies:

- Steps that create new files come first
- Steps that modify existing code come after
- Elimination steps come after all migrations are done
- Steps that add tests come last

Use `depends_on` field to make dependencies explicit.

## Quality Checklist

Before finalizing each build todo:

- [ ] Searched memory service for relevant gotchas, patterns, and solutions
- [ ] Checked memory service results (auto-injected + explicit search if needed)
- [ ] EVERY build todo has "From memory service" subsection (even if "none applicable")
- [ ] For database changes: repo-specific schema gotchas were read and referenced (ts-prefect Atlas after E0017; legacy migration rules only where applicable)
- [ ] For field modifications: all consumers of modified fields were audited
- [ ] For repeated writers: storage volume math, dedupe/change-gating, retention, and
      identical-input behavior are specified with tests/queries
- [ ] For provider-backed caches/outcomes: lifecycle (`live`/`provisional`/`final`),
      writer/reader inventory, refresh/repair policy, and cache-hit tests are specified
- [ ] Found and documented relevant codebase patterns
- [ ] Checked git history for context on affected files
- [ ] Verified CLAUDE.md compliance
- [ ] Patterns documented with file:line references
- [ ] Implementation details follow discovered patterns
- [ ] Test requirements match existing test patterns
- [ ] Verification commands included
- [ ] **Complexity tag set** (`simple`/`complex`) on every build_todo; `complex` when in doubt
- [ ] **Deliverable coverage map** emitted; any unmapped deliverable recorded as an explicit
      `DEFERRED — needs user approval` line in the first build_todo
- [ ] **Linked-workspace preflight** passed for every referenced repo
- [ ] **Elimination step included:** If plan has "What We're Eliminating" section, there is
      a dedicated build todo for deleting old code with grep verification of zero remaining
      imports

## Infrastructure Checklist

When feature involves infrastructure changes, include these steps:

### Database Migrations

If schema changes are needed:

1. Create a **dedicated build todo** for the migration file -- never bundle migration
   creation into a code change step
2. Include both upgrade AND downgrade functions
3. Document rollback procedure in the todo
4. Document the promotion path as **schema-lane**, not ordinary ticket cherry-pick:
   - ts-prefect after E0017: Atlas additive-only/reviewed-plan path; no Alembic revisions.
   - legacy migration repos: schema-first/backward-compatible off current `main` with immediate
     `main→staging` sync, or a full parity merge. If the plan proposes selective migration
     cherry-pick, send it back unless it explicitly records an approved emergency exception.
5. **CRITICAL:** After ANY schema file modification (schema.prisma, models.py, SQLModel, etc.),
   use the repo's active schema system. For Prisma/Alembic repos, create a migration (`bun run
   migrate`, `alembic revision --autogenerate`, etc.). For ts-prefect, do **not** create Alembic
   migrations; ensure Atlas plan/safety checks, the reviewed prod plan gate when needed, and
   `verify_schema_truth.py` cover the change. Never rely on `prisma db push` or equivalent local
   sync tools alone.
6. **CRITICAL for derived clients / multi-DB apps:** A migration file is not enough. Add a
   verification/deploy step proving the new column/table/enum is present in every runtime DB
   that the generated client will query (for example every configured `DATABASE_URL_*`). If any
   DB lags, default ORM selects such as Prisma `findMany()` can crash globally with column-not-
   found even though the migration exists in source.

### Environment Variables

If new API keys or env vars are needed:

1. Record them in the `deployment_guide` artifact (Steps + Env Var table), per environment
2. Add to .env.example with placeholder values

## Post-Creation Validation

After all build todos are written, verify memory service compliance by reading back
the ticket artifacts and checking each build_todo content contains memory service
references. If any are missing, go back and add the missing research.

## Output

After creating all build todos, output:

```
Build todos created for {ID}: {title}

Steps: {N} build_todo artifacts created
Ready for implementation.

Next: /build {ID} (implement each step)
```

## Next Steps

After build_todos are created and committed:

```
/build F001                   # Execute build in current session
```

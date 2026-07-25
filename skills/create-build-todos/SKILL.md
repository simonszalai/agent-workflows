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
# If missing: STOP - run /ticket-plan first
```

**If any prerequisite fails:**

| Missing             | Action                                 |
| ------------------- | -------------------------------------- |
| Ticket not found    | **STOP** - create ticket first         |
| No plan artifact    | **STOP** - run `/ticket-plan [id]` first |
| Plan not reviewed   | **WARN** - suggest user review plan    |

**Additional requirements:**

- Review and iterate on plan.md before running this command

## Process

1. **Locate work item:**
   - Same ID resolution as `/ticket-plan`
   - Error if the plan artifact doesn't exist

2. **Read context** from `get_ticket` response:
   - Plan artifact - The approved architecture plan
   - Source artifact - Original problem/feature description
   - Investigation artifact - Production findings (if exists)

3. **Spawn build-planner agent** for deep research:
   - Agent searches memory service exhaustively
   - Agent searches codebase for all relevant patterns
   - Agent analyzes git history for context
   - The agent researches directly. It may delegate at most one `researcher` subagent, and only
     for a named unknown its own tool calls could not resolve — with `fork_turns: "none"` and a
     bounded, self-contained packet

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

   `/ticket-plan` left a DRAFT `deployment_guide` with the deploy *shape* and a first-cut
   verification evidence contract. The deep research you just did is exactly what turns that
   draft into actionable mechanics — do not leave it as a draft. Update it (`update_artifact`;
   create it if the ticket skipped `/ticket-plan`) so the deploy steps name the **concrete**
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
   and update by id; if the ticket skipped `/ticket-plan` and none exists, create one instead.

   ```
   mcp__autodev-memory__update_artifact(
     project=PROJECT,
     artifact_id="<deployment_guide artifact id from get_ticket>",
     content="<finalized guide>",
     command="/create-build-todos"
   )
   ```

## Deepening Each Step

Splitting the plan into ordered steps is the easy half. The half that decides whether the
builder succeeds is the per-step research below — a deepened step is not the plan restated at
greater length. **A step is deep enough when the builder can implement it without doing its own
research.** If the builder would have to figure out how something works, deepen further.

**Batch the memory searches.** Run ONE consolidated memory search up front covering every step's
area. Per-step searches are only for a **step-specific unknown** the consolidated search did not
cover — an unusual library, a one-off migration mechanism:

```
mcp__autodev-memory__search(queries=[
  {"keywords": ["<step-specific-unknown>", "<technology>"],
   "text": "<the specific unknown> patch fix solution gotcha"}
])
```

Read the full content of every relevant result; titles alone are not enough. Document what you
find in the step's "Known Patches & Solutions" subsection (see template).

**Then, per step:**

a. Check the consolidated memory results for patches, solutions, and gotchas in this step's area.
b. Read the actual files that will be modified — current state, imports, patterns, constraints.
c. Find the closest existing implementation to follow: grep for similar code, read it, document
   the pattern with `file:line` refs.
d. Check git history for past changes to these specific files.
e. Trace data flow: what produces the input this step needs? What consumes its output? What
   breaks if the contract changes?
f. Identify edge cases: empty input, null fields, concurrent execution, partial failure.
g. For any repeated writer (poller/observer/scheduler/queue/webhook), trace write amplification:
   what rows are written per run, which writes are canonical upserts vs append-only history, what
   dedupes across runs, and what happens when the same source payload is observed twice.

## Complexity Tagging (MANDATORY — drives per-chain builder model routing)

The build-planner MUST tag **every** build_todo with a `complexity` class. `/build` takes the
maximum complexity/risk across each coherent chain to choose the cheap (`sonnet`) or strong
(`opus`) builder model:

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
  analogue, risk-specific gotchas, named orchestrator-owned validation, and hard boundaries. Pass
  paths to longer artifacts instead of copying their contents.
- **External builder (`/build --builder codex`):** the Codex side has NO MCP or memory
  access and sees only the todo text plus a short context blob. Everything it needs must
  be IN the todo — discovered patterns with `file:line` references, the closest analogous
  module, the exact orchestrator-owned verification commands that it must not execute,
  applicable CLAUDE.md rules. "None applicable"
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
- **Verification** - Commands for the orchestrator to verify the step; builders do not execute them

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

## Todo hazard classes

Four build shapes need a dedicated todo of their own, because each has shipped an incident
when it was folded into a general step. If the plan **removes an existing system**, introduces
or changes a **repeated writer** (poller/observer/scheduler/queue/webhook), puts work under a
**shared deadline or coordinator timeout**, or stores **provider-backed data that can be
provisional before it is final**, load `references/todo-hazard-classes.md` and follow the
matching section.

## Step Dependencies

Order steps by dependencies:

- Steps that create new files come first
- Steps that modify existing code come after
- Elimination steps come after all migrations are done
- Steps that add tests come last

Use `depends_on` field to make dependencies explicit.

## Quality Checklist

Everything above is the method; these are the four things that are silently wrong most often, so
check them explicitly before finalizing:

- [ ] **Complexity tag set** (`simple`/`complex`) on every build_todo — `/build` cannot route
      builder models without it
- [ ] **Deliverable coverage map** emitted; any unmapped deliverable recorded as an explicit
      `DEFERRED — needs user approval` line in the first build_todo
- [ ] **Linked-workspace preflight** passed for every referenced repo
- [ ] Every build_todo has a "From memory service" subsection, even when it reads "none applicable"
      — an absent subsection is indistinguishable from research that never happened

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

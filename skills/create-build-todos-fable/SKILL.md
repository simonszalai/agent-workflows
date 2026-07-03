---
name: create-build-todos-fable
description: Fable-variant build-todo creation. Spawns build-planner-fable to turn an approved plan into fully self-contained implementation steps for the Codex (GPT 5.5) builder.
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

# Create Build Todos (Fable variant)

Turn an approved plan artifact into `build_todo` artifacts (style:
`skills/references/fable-prompting.md`). Spawns `build-planner-fable` for the deep research.

**The defining constraint of this variant:** the todos are executed by a Codex GPT 5.5
builder via `bin/external-build` — it has **no MCP access and cannot search the memory
service**. A base-system todo could lean on the builder re-searching memory; here it cannot.
Every gotcha, pattern (`file:line`), analogous module, CLAUDE.md rule, and verification
command must be in the todo itself. A todo the builder would need to "research further" is a
defect.

## Usage

```
/create-build-todos-fable F0009 | B0009 | R0003
```

Ticketless mode (lfg): no MCP — read the plan from `.context/plan.md`, write todos as
`.context/build_todos/NN-name.md`. Research depth, template, and quality bar unchanged.

## Prerequisites (validate first, STOP on failure)

`get_ticket(project, ticket_id, repo)` — ticket must exist and carry a `plan` artifact
(otherwise: run `/auto-plan-fable` first). Warn if the plan was never reviewed.

## Process

Spawn `build-planner-fable` with the plan, source, and investigation artifacts. It owns the
research and writes one `build_todo` artifact per independently completable step
(`sequence` ordered, `depends_on` explicit; template:
`../create-build-todos/templates/build-todo.md`; content contract: `agents/build-planner-fable.md`).
Memory searches are batched — one consolidated pass up front covering all steps' areas,
per-step searches only for step-specific unknowns.

Dependency ordering: new files first, modifications after, elimination after all migrations
are wired but **before** tests, tests last.

## Mandatory todo contracts (safety gates — never drop when simplifying)

**Elimination.** If the plan has a "What We're Eliminating" section, there MUST be a
dedicated elimination todo: migrate every consumer (from the plan's consumer grep), delete
the old files, and verify with greps proving zero remaining imports plus a type-checker run.
Plan replaces X with Y but no elimination todo for X → the todos are incomplete.

**Schema/migration.** Schema changes get a dedicated todo — never bundled into a code step.
Use the repo's active schema system (check project CLAUDE.md): schema-truth repos (ts-prefect
after E0017) get Atlas plan/safety-check coverage, no Alembic; legacy repos get a real
migration with upgrade AND downgrade plus a rollback note. Name the promotion path as a
schema lane (schema-first + immediate `main→staging` sync, or full parity merge) — selective
migration cherry-pick only as a recorded emergency exception. For derived clients /
multi-DB apps, a migration file is not enough: add a verification step proving the new
column/table/enum exists in **every** runtime DB the generated client queries, or default ORM
selects crash globally.

**Polling/storage.** If the plan adds any repeated writer (poller, observer, scheduler,
queue consumer, webhook, scraper), one todo must own the storage-shape proof: durable write
paths per run and their kind (canonical upsert / changed-event / raw snapshot / append-only),
a test or query proving two identical polls create no duplicate durable business data unless
explicitly intended, the rows/day + bytes/day budget formula, and retention/partitioning for
any append-only history with its named consumer. Prefer canonical rows with
`first_seen_at`/`last_seen_at`/`seen_count` over per-poll payload copies — "lossless" is not
a consumer.

**External data / cache finality.** If the plan touches provider-backed data, shared caches,
market/reference data, prompt-context enrichment, or ground-truth labels, one todo must own
the temporal-finality proof: writer/reader inventory, per-value lifecycle
(`live`/`provisional`/`final` with the timestamp/calendar/provider rule that makes it final),
cross-writer poisoning prevention (separate storage or a lifecycle column readers enforce),
safe refresh/upsert policy (`ON CONFLICT DO NOTHING` only for proven-immutable facts), and a
cache-hit regression test where a stale/provisional row pre-exists the finalizing job.

**Env vars / secrets:** record new ones in the deployment guide (per environment) and
`.env.example`.

## Finalize the deployment guide (mandatory)

`/auto-plan-fable` left a DRAFT `deployment_guide`; the research just done is what turns it
into mechanics. Update it by artifact id (`update_artifact`, command
`"/create-build-todos-fable"`; create one only if the ticket skipped auto-plan):

- the concrete **schema artifact** (Atlas changes/reviewed plan, or migration revision id, or
  "no schema change") and whether it runs before the code deploy;
- the **schema lane** when there is one (see above);
- the **cross-repo order** confirmed against what will actually be built;
- the **real deploy commands/objects** for this project (from project CLAUDE.md/AGENTS.md +
  memory: runtime path, scheduler/worker deploys, blocks/secrets, DAG/pipeline sync);
- every runtime-evidence row's **producing object** in the same build scope (flow entrypoint,
  environment YAML entry, supervisor registration, canary CLI — or an explicit disposable
  integration-DB proof);
- **Verification Evidence** rows as concrete queries/commands with expected good output and
  bad-output interpretation, staging and production;
- for polling/observer/storage changes, the **volume and redundancy evidence** queries
  (rows/run, rows/day, bytes/day, duplicate-write rate, retention/TTL).

Mark `Status: FINALIZED` only when deploy steps and both environments' evidence are concrete
and every runtime evidence row has a producing deployment/command; otherwise leave `TBD` rows
and say so.

## Validate, then report

Read the artifacts back and confirm every todo carries its Discovered Patterns (memory
references included — "none applicable" allowed, silence not) and verification commands; fix
gaps before reporting.

```
Build todos created for {ID}: {title}

Steps: {N} build_todo artifacts created
Ready for implementation.

Next: /build-fable {ID}
```

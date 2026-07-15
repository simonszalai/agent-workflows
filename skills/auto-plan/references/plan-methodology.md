# Plan Methodology

Standards for creating high-level architecture plans. Loaded by the auto-plan orchestrator and
passed (in relevant part) to planner agents.

## Workflow by Work Type

| Work Type   | Input                                   | Research Needed                     |
| ----------- | --------------------------------------- | ----------------------------------- |
| **Feature** | source artifact + user prompt           | Codebase patterns, existing code    |
| **Bug**     | source artifact + investigation artifact | Usually none (investigation has it) |

**For features:** Plan includes codebase research to understand existing patterns before
designing.
**For bugs:** Plan uses investigation findings to design the fix.

## Output Template

Use the template at `templates/plan.md` for plan output. Plan artifacts are markdown stored via
MCP `create_artifact`/`update_artifact`, written by the auto-plan orchestrator.

(keep lines ≤100 chars; tables exempt)

## Code Snippets in Plans (No Invented Code)

Plans contain **no invented implementation code**. Code snippets are allowed only as citations
of existing canonical patterns with file:line references. When a plan does cite code:

1. **Cross-check against exploration findings** — cite only what research agents actually found
2. **Use canonical patterns from the codebase** — never invent new patterns; cite what exists
3. **Include file:line references** — show where the pattern comes from
4. **Never use simplified versions** — if the codebase uses a specific abstraction, cite it

## Plan Type Determination

Determine fix vs feature from input content:

**Fix indicators:**

- Keywords: fix, bug, error, broken, failing, issue, debug, crash, timeout
- Problem describes unexpected/incorrect behavior
- Investigation findings point to root cause

**Feature indicators:**

- Keywords: add, new, create, implement, build, feature, enhance, support
- Request describes new functionality
- No existing broken behavior to address

## Input Verification

Before planning, verify inputs are sufficient:

### For Features (FNNNN)

| Required           | Check                                              | Source                |
| ------------------ | -------------------------------------------------- | --------------------- |
| Requirements       | Clear description of what to build                 | source artifact       |
| Scope boundaries   | Know what's in/out of scope                        | source artifact       |
| Integration points | Identified where feature connects to existing code | **Codebase research** |
| Patterns           | Found similar implementations to follow            | **Codebase research** |

**Process:** Spawn `researcher` agent to explore codebase patterns before planning.

### For Bugs (BNNNN)

| Required        | Check                                              | Source                     |
| --------------- | -------------------------------------------------- | -------------------------- |
| Problem clarity | Can articulate what's broken and expected behavior | source artifact            |
| Root cause      | Investigation identified likely cause(s)           | **investigation artifact** |
| Affected scope  | Know which files/components are involved           | **investigation artifact** |
| Reproduction    | Understand when/how issue occurs                   | **investigation artifact** |

**Process:** Read the investigation artifact. If missing or incomplete, run `/investigate` first.

## Complexity Assessment

Assess implementation complexity to determine verification needs:

| Complexity | Criteria                                       | Verification Needed |
| ---------- | ---------------------------------------------- | ------------------- |
| Simple     | Single file change, obvious fix, <30 lines     | No (lint/types OK)  |
| Moderate   | 2-3 files, new logic, integrates with existing | Recommended         |
| Complex    | 4+ files, new model/flow, changes data flow    | Required            |

**Simple examples:** typo fixes, config tweaks, adding logging, small bug fixes

**Complex examples:** new processing pipeline, database schema changes,
new API integrations, changes to alert/notification logic

## Planning Process

### For Features

1. **Read the source artifact** - Understand requirements and scope
2. **Search memory service** - Find relevant gotchas, patterns, and past solutions:
   ```
   mcp__autodev-memory__search(queries=[
     {"keywords": ["<feature-area>"], "text": "<feature area> architecture patterns"},
     {"keywords": ["<technology>"], "text": "<technology> gotchas pitfalls"}
   ])
   ```
   Also review bounded injected context when present; it is representative, not exhaustive.
3. **First-principles analysis** - State fundamental goal, classify constraints, eliminate
   fake ones
4. **Research codebase** - Spawn `researcher` to find patterns, integration points
5. **Define what we're NOT building** - Explicitly list eliminated scope
6. **Assess complexity** - Determine verification strategy needed
7. **Design architecture** - Choose high-level implementation approach (simplest that works)
8. **Identify tradeoffs** - What we're optimizing for vs accepting
9. **Identify side effects** - What else this change affects
10. **Identify risks** - What could go wrong, how to mitigate
11. **Write the plan** - Synthesize research into architecture doc (per templates/plan.md)

### For Bugs

1. **Read source + investigation artifacts** - Understand problem and root causes
2. **Search memory service** - Find related past fixes and gotchas:
   ```
   mcp__autodev-memory__search(queries=[
     {"keywords": ["<bug-area>"], "text": "<bug area> root cause fix"},
     {"keywords": ["<technology>"], "text": "<technology> gotchas"}
   ])
   ```
3. **Verify investigation complete** - If missing root causes, run `/investigate` first
4. **First-principles analysis** - Is the root cause in code that should exist? Could we
   eliminate rather than fix?
5. **Assess complexity** - Determine verification strategy needed
6. **Design fix approach** - Choose solution based on root causes (prefer elimination over
   repair)
7. **Identify tradeoffs** - What we're optimizing for vs accepting
8. **Identify side effects** - What else this fix affects
9. **Identify risks** - What could go wrong, how to mitigate
10. **Write the plan** - Synthesize investigation into fix architecture (per templates/plan.md)

## Synthesis Guidelines

**Summary section:**

- 2-3 sentences max
- What we're building and why this approach

**What We're Building:**

- High-level description of the solution
- Answer: What will exist after this that doesn't exist now?
- NO invented code, NO file paths

**What We're Eliminating (if applicable):**

- Every file, class, and module being replaced or deleted
- All consumer call sites that must be migrated
- Answer: What will be GONE after this that exists now?
- If nothing is being eliminated, explicitly state "No code elimination required"
- **If this section is missing from a replacement plan, the plan is incomplete**

**How It Works:**

- Architectural flow description
- How pieces fit together
- NO implementation details

**Research Findings (features) / Investigation Summary (bugs):**

For features:

- Existing patterns found in codebase
- Integration points identified
- Conventions to follow

For bugs:

- Root causes from investigation
- Affected components
- Evidence summary

**Tradeoffs section:**

- What we're optimizing for
- What we're accepting/sacrificing
- Alternatives considered and why rejected

**Side Effects section:**

- Other components affected
- Data/state changes
- Downstream impacts

**Risks:**

- What could go wrong
- Likelihood and impact
- Mitigation strategies

## External Data Cache Semantics (CRITICAL)

When the plan touches provider-backed data, shared caches, market/reference data,
ground-truth labels, or evaluation outcomes, the plan must include a **cache semantics
contract** before implementation can proceed:

1. **Classify every stored value** as `live`, `provisional`, or `final`.
2. **Name every writer and reader** of the table/cache, including prompt-context and
   background/outcome jobs.
3. **State finality rules**: provider revision behavior, source timestamp, validity window,
   exchange/timezone/calendar if market data is involved, and when a row may be treated as
   immutable.
4. **Define refresh/repair policy** for provisional or time-varying rows. First-write-wins
   storage is not acceptable unless the source fact is proven immutable.
5. **Separate semantic lifecycles**: live/tweet-time/current-session data must not share
   final EOD / ground-truth storage unless the schema encodes lifecycle state and readers
   enforce it.
6. **Verification must cover cache hits**, not only provider misses: an existing stale or
   provisional row must not be reused as final ground truth after maturity.

**Rule:** Endpoint names such as "EOD", "latest", or "historical" are not semantic proof.
The plan must prove when the provider value is actually final.

## Feature Checklist

When planning features, verify these infrastructure needs:

### Field Transformation Audit (CRITICAL)

When a plan involves encrypting, changing format, or removing a database field:

- [ ] **Find all readers:** `grep -r "field_name" src/` to find every file that reads the field
- [ ] **Find all transformers:** Search for `.format(`, f-strings, regex, slicing, parsing
      operations on the field's value
- [ ] **Find all writers:** Identify every code path that writes to the field
- [ ] **Classify compatibility:** For each consumer, document whether the new format is
      compatible or requires changes
- [ ] **Document exceptions:** If some consumers are incompatible, document them explicitly
      in the plan as architectural constraints

### Data Dependencies (CRITICAL)

Before designing, verify data flow is complete:

- [ ] **What data does this feature need?** - List all input data required
- [ ] **Where does that data come from?** - Identify upstream sources/pipelines
- [ ] **Is that data available?** - Verify sources are configured and populated
- [ ] **Is the data sufficient?** - Check content quality matches use case needs

### Polling / Storage Amplification Audit (CRITICAL)

When a plan adds or changes a poller, observer, scheduler, queue consumer, webhook,
scraper, or other path that writes durable rows repeatedly:

- [ ] **Name the durable facts actually needed:** canonical entities, first/last seen
      timestamps, changed events, health/fetch metadata, or full per-poll history.
- [ ] **Reject redundant "lossless" writes:** "lossless" means preserving the facts or
      source events needed by consumers; it does NOT mean saving the same payload/item on
      every poll interval when nothing changed.
- [ ] **Classify every write:** canonical upsert, delta/change event, raw snapshot,
      append-only observation, aggregate, or log. State who reads it.
- [ ] **Do write-rate math:** `active sources × polls/day × items/response × rows/item`
      plus expected row width/bytes/day and WAL/index impact. Include worst-case and
      steady-state estimates.
- [ ] **Prove dedupe crosses polls:** the uniqueness key must not include only a fresh
      poll/fetch id if the intent is to dedupe unchanged source data across polls.
- [ ] **Gate append-only history:** per-poll observations require a named downstream
      consumer, a retention/partitioning plan, and a volume budget. Otherwise use
      canonical rows with `first_seen_at`, `last_seen_at`, and `seen_count`, or store only
      first-seen/changed events.
- [ ] **Make verification catch amplification:** evidence must show repeated identical
      polls do not create unbounded duplicate rows, and must extrapolate observed write
      rate to daily/weekly storage.

**Rule:** If increasing poll frequency linearly increases stored rows for unchanged data,
the plan is incomplete unless that history is explicitly required, bounded, and budgeted.

### Elimination Audit (CRITICAL)

When a feature replaces, supersedes, or eliminates an existing system:

- [ ] **List what gets deleted:** Enumerate every file, class, and module the new system
      replaces. This list goes into the plan under "What We're Eliminating"
- [ ] **Record a before inventory:** enumerate old imports/call sites, flags/env/config, routes,
      writers/triggers/consumers, scheduled jobs, deployment registrations, and operator scripts.
      Name the authoritative live-inventory query for runtime items.
- [ ] **Find all consumers:** bounded searches across code **and deployment/config paths** — every
      import, call site, and registration must be migrated or removed
- [ ] **Define the negative postcondition:** after deploy, code/config searches return zero
      unexplained matches, the live inventory contains none of the retired items, and the sole
      surviving path is exercised
      for the old system's imports
- [ ] **Deletion is part of the plan, not a follow-up:** The plan must include elimination
      as a required step, not a "nice to have" or separate PR. Adding a replacement without
      removing the old system is an incomplete plan.

**Rule:** If the plan says "replace X with Y", the deliverable is: Y is wired up at all
call sites AND X is deleted from code, config, and live registrations. If the plan only covers
adding Y, or has no before/after inventory commands, it is incomplete — send it back for revision.

### Database Changes

- [ ] New tables or columns needed? - Include migration step and migration-lane decision
- [ ] New enum values? - Add to migration and migration-lane decision
- [ ] Seed data needed? - Include in migration or seed script and state whether it is
      schema-lane critical
- [ ] If migration-bearing, is it backward-compatible enough to land schema-first before code?

### API Keys / Environment

- [ ] New API keys required? - Document in deployment notes
- [ ] Environment variables needed? - Add to .env.example

## Scope Completeness Rule (CRITICAL)

When creating a plan from a source document that lists multiple deliverables:

- Every item in the source MUST appear as a numbered implementation step in the plan
- If an item should be deferred, it MUST be explicitly flagged as
  **"DEFERRED — requires user approval"** (not "TBD" or "later")
- NEVER mark items as TBD and continue — present the deferral decision to the user
  before proceeding to build
- For combined tickets (superseding multiple sub-tickets), verify 1:1 coverage:
  every superseded ticket's scope must map to at least one plan step

**Why:** F0076 combined 5 tickets. The plan marked one item as "TBD" without user
approval. It was silently dropped, the ticket was marked complete, and $110/month
in unnecessary cost continued running for weeks.

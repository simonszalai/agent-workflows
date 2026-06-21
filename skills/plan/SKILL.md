---
name: plan
description: Create high-level implementation plan for work items. Spawns planner agent to create plan.md only.
memory:
  tags:
    - architecture
    - tradeoff
    - constraint
    - $tech_tags
  types:
    - architecture
    - pattern
    - preference
---

# Plan

Create a high-level architecture plan for a ticket. This command creates a `plan` artifact which
focuses on **what** we're building and **why** - not implementation details.

## When to Use

| Work Type   | Workflow                                      |
| ----------- | --------------------------------------------- |
| **Feature** | `/plan` directly (includes codebase research) |
| **Bug**     | `/investigate` first, then `/plan`            |

**For features:** This command does codebase research to understand existing patterns before
designing the solution. No separate investigation needed.

**For bugs:** Run `/investigate` first to find root causes, then `/plan` to design the fix.

## Usage

```
/plan                                     # Interactive: asks for details
/plan F0009                               # Plan existing ticket
/plan B0003                               # Bug ticket B0003
/plan F0009 additional context            # Ticket with extra context
/plan "Add new integration"               # Create new ticket and plan
/plan F0009 --deep                        # Force heavyweight workflow (panel + critics + revise)
/plan F0009 --light                       # Force inline path (still cross-provider)
/plan F0009 --solo                        # Emergency opt-out: current provider only
```

## What the Plan Contains

**Architecture-focused, not implementation-focused:**

- What we're building (high-level description)
- What we're eliminating (old code/systems being replaced — see Elimination Audit below)
- How it works (architectural approach)
- Why this approach (reasoning, alternatives considered)
- Tradeoffs made (what we're optimizing for vs sacrificing)
- Side effects (what else this affects)
- Risks and mitigations
- Verification strategy (how to know it works)

**For features, also includes:**

- Codebase research (existing patterns, integration points)
- Requirements analysis

**Does NOT contain:**

- Specific files to modify
- Code snippets or examples
- Line-by-line implementation details

Those details come later via `/create-build-todos`.

**Code snippets in plans:**

When a plan DOES include code snippets (e.g., for complex features), you MUST:

1. **Cross-check against exploration findings** - Before writing any code, review what the
   exploration agents found about existing patterns
2. **Use canonical patterns from codebase** - Never invent new patterns; use what exists
3. **Include file:line references** - Show where the pattern comes from
4. **Never use simplified versions** - If the codebase uses a specific abstraction, use it

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## Process

1. **Resolve ticket:**
   - **If ticket ID given** (e.g., `F0009`, `B0003`):
     ```
     mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
     ```
     - Read the source artifact for requirements/context
     - If ticket status is `backlog`, update to `in_progress`:
       ```
       mcp__autodev-memory__update_ticket(
         project=PROJECT, ticket_id=ID, repo=REPO,
         status="in_progress", command="/plan"
       )
       ```
   - **If description given** (no ID): Create a new ticket:
     ```
     mcp__autodev-memory__create_ticket(
       project=PROJECT, repo=REPO,
       title="<synthesized title>",
       type="bug",  # or "feature" based on context
       description="<user's description>",
       status="in_progress",
       command="/plan"
     )
     ```
     - The returned `ticket_id` is used for all subsequent operations

2. **Gather inputs based on work type:**

   **For features (F-prefix):**
   - Read source artifact from `get_ticket` response
   - Spawn `researcher` agent to analyze codebase patterns, integration points
   - No investigation expected (features don't need root cause analysis)

   **For bugs (B-prefix):**
   - Read source artifact from `get_ticket` response
   - Read investigation artifact (expected - if missing, suggest running `/investigate` first)
   - Use root causes from investigation to inform solution design

   **For all work types:**
   - The planner agent includes the `research` skill (references/past-work.md)
   - It searches for similar past tickets automatically via `get_similar_tickets`
   - Extracts architectural decisions, tradeoffs, and learnings

3. **Cross-provider planning and convergence (core, default for both paths):**

   A plan artifact is not valid until **all three providers** have contributed independent
   planning judgment and material disagreements have been driven to evidence-backed
   convergence. The main workflow runner is one provider (`claude`, `codex`, or `grok`);
   the other two providers are peers. Unless the caller explicitly passed `--solo`, run the
   two peer providers with `external-agent --task plan`, read their envelopes, and merge them
   into the same synthesis path as the native/current-runner plan. Do not summarize what a
   provider "would" say; actually run the providers and consume their JSON.

   Provider roles are symmetric:

   | Main workflow runner | Peer planners to run |
   | -------------------- | -------------------- |
   | `claude`             | `codex`, `grok`      |
   | `codex`              | `claude`, `grok`     |
   | `grok`               | `claude`, `codex`    |

   Determine the current runner with `agent-workflow-provider`. Claude peers use
   subscription-backed `claude -p`, never a direct Anthropic API call.

   **Dispatch shape must match `/review`:**

   - **Claude Code dispatch:** when Claude Code is the main runner, spawn two
     `external-planner` subagents in the same parallel `Agent` batch as the native/current
     planner. Each subagent calls `external-agent --task plan` for one peer provider
     (`codex` or `grok`) and returns the planner envelope JSON. This avoids foreground shell
     timeout caps and keeps provider dispatch as thin data collection, not hidden reasoning.
   - **Codex/Grok dispatch:** when Codex or Grok is the main runner, call `external-agent`
     directly for the two peer providers (including `--provider claude` when Claude is a peer).
   - **Synthesis/convergence:** always happens in the main `/plan` orchestrator, not inside the
     provider dispatcher. External providers contribute envelopes; the deterministic skill
     logic validates, synthesizes, audits disagreements, and revises.

   `external-planner` is the planning analogue of `/review`'s `external-reviewer` subagent.
   It must not draft or critique the plan itself; it only runs the adapter and returns JSON.

   ```bash
   mkdir -p .context/plan
   printf '%s' "$QUESTION" > .context/plan/question.txt
   printf '%s' "$SOURCE_ARTIFACT" > .context/plan/source.md
   printf '%s' "$CODEBASE_RESEARCH" > .context/plan/codebase-research.md
   printf '%s' "$PRIOR_KNOWLEDGE" > .context/plan/prior-knowledge.md
   for provider in $(agent-workflow-provider --peers); do
     external-agent --task plan --provider "$provider" \
       --question "$(cat .context/plan/question.txt)" \
       --source-artifact-file .context/plan/source.md \
       --codebase-research-file .context/plan/codebase-research.md \
       --prior-knowledge-file .context/plan/prior-knowledge.md \
       --out ".context/plan/${provider}.json" 2>".context/plan/${provider}.log" &
   done
   wait
   ```

   Each peer returns:

   ```
   {
     "planner_key": "claude|codex|grok",
     "plan": { title, what, why, how, tradeoffs, alternatives_considered,
               risks, verification_strategy, side_effects, elimination,
               open_questions },
     "assumptions": [...],
     "disagreements": [
       { area, claim, why_it_might_be_wrong, evidence_needed }
     ],
     "evidence": [...],
     "open_questions": [...],
     "notes": "..."
   }
   ```

   A provider failure contributes an empty envelope with a note; surface it but do not block
   if the other two providers plus the current runner can still converge. If fewer than two
   providers return usable plans, stop and report the provider failure instead of accepting a
   one-provider plan. `.context/plan/*.json` is scratch only; the converged artifact is the
   persisted plan.

   **Convergence rule:** Planning has subjective tradeoffs, but it also contains factual
   claims about code, data, infra, sequencing, migrations, verification, and elimination.
   Iterate on provider disagreements until every material factual/architectural disagreement
   is either:

   1. resolved by evidence from code, existing artifacts, memory, or production/staging facts;
   2. converted into an explicit `open_questions` item that blocks build planning; or
   3. deliberately rejected as preference/YAGNI with a recorded reason.

   Run at most **3 disagreement rounds**. In each round:

   ```
   synthesize current provider plans
   identify disagreements across provider assumptions, risks, alternatives, and open questions
   gather missing evidence with researcher/investigator only if evidence would settle the issue
   revise the plan toward the evidence-backed answer
   send the revised answer back through provider disagreement audit
   ```

   Stop early only when there are no material unresolved disagreements. Do not let
   "convergence" mean gold-plating: completeness claims must beat YAGNI only with concrete
   evidence. Do not bury unresolved factual uncertainty in prose; if it matters, it must be
   an `open_questions` blocker.

4. **Decide the execution path — complexity gate:**

   The heavy path runs 2 parallel plan drafts with different framings (MVP-first,
   risk-first), incorporates peer-provider drafts, synthesizes them, sends the result through
   3 parallel critics (completeness, correctness, YAGNI), and then performs the disagreement
   convergence loop above. The YAGNI critic exists specifically to counter the natural
   pressure of completeness critics.
   Heavy is appropriate when the plan needs diverse framings or independent critique;
   light is appropriate when the change is small or well-understood.

   Use this gate (top-to-bottom, first match wins):

   | Condition                                                          | Path  |
   | ------------------------------------------------------------------ | ----- |
   | User passed `--deep`                                                | Heavy |
   | User passed `--light`                                               | Light |
   | Bug ticket (B-prefix) with investigation artifact present           | Light |
   | Feature ticket source artifact ≥ 500 chars OR ≥ 80 words            | Heavy |
   | Request involves multi-component, migration, or cross-cutting work  | Heavy |
   | Otherwise                                                           | Light |

   Announce the chosen path:

   ```
   Plan path: heavy (feature with 1200-char source) — plan-fanout workflow
   ```

   or:

   ```
   Plan path: light (bug fix with investigation in place) — inline planner
   ```

4b. **Gather prior knowledge (heavy path only, and for all peer provider prompts):**

   The heavy-path workflow spawns generic subagents — they receive NO knowledge-menu
   injection and do NOT load the `autodev-search` skill, unlike the inline `planner` agent
   used on the light path, which searches the memory system and past tickets itself. So
   when going heavy, gather prior knowledge in the skill and pass it into the workflow. For
   both paths, pass the same prior-knowledge blob to every peer provider planner so all three
   providers reason from the same known gotchas and past decisions:

   ```
   # Related memories (gotchas, patterns, architecture)
   memories = mcp__autodev-memory__search(
     project=PROJECT,
     queries=[{ "keywords": [<feature/bug area>], "text": "<what is being planned>" },
              { "keywords": [<technology>],       "text": "<technology> gotchas pitfalls" }],
     limit=8
   )

   # Similar past work — proven approaches, tradeoffs, risks that materialized
   similar = mcp__autodev-memory__get_similar_tickets(
     project=PROJECT, ticket_id=ID, repo=REPO, status="completed"
   )
   ticket_hits = mcp__autodev-memory__search_tickets(
     project=PROJECT, query="<keywords>"
   )
   ```

   Render the hits into a compact markdown blob (omit a section if it is empty), pass it to
   every peer planner prompt, and pass it as `args.priorKnowledge` in step 5a, where it is
   injected into the drafter, synthesizer, critic, reviser, and disagreement-convergence
   prompts so the plan reuses proven approaches and avoids documented gotchas. Pass `null`
   if nothing relevant turns up — never fabricate entries.

   ```markdown
   ## Related memories
   - [<title>] (<type>): <one-line takeaway>

   ## Related past work
   - <TICKET_ID> "<title>" (<status>): <approach / key learning>
   ```

5. **Fan out — light path (inline):**

   When the gate selects "Light", spawn ONE native/current-runner planner agent with all
   inputs (source, codebase research findings if features, investigation findings if bugs)
   **and** run the two peer provider planners from step 3 unless `--solo` was passed. The
   native planner returns a plan object matching `planSchema` in `workflows/plan-fanout.js`;
   peer planners return the envelope shown in step 3. Validate all returned plans against
   the required fields (`title`, `what`, `why`, `how`, `tradeoffs`,
   `alternatives_considered`, `risks`, `verification_strategy`, `side_effects`,
   `elimination`, `open_questions`). If the native planner validation fails, re-prompt it
   with the schema rather than accepting a partial plan.

   Then synthesize the native plan + peer plans and run the disagreement-convergence loop
   from step 3 inline. Light path skips the completeness/correctness/YAGNI critic panel, but
   it does **not** skip cross-provider planning or convergence. Assemble the same return
   shape as the heavy path with empty `critic_findings` and zero-filled critic-only stats
   (`critics_succeeded: 0`, `total_findings: 0`, etc.). Populate provider/convergence stats.

   Skip steps 5a-5b below — those are for the heavy path only.

5a. **Fan out — heavy path (workflow):**

   When the gate selects "Heavy", invoke the workflow by name. The runtime resolves
   `name:` against `~/.claude/workflows/`, where agent-workflows is symlinked in every
   environment:

   If the current host tool does not expose Claude's `Workflow` tool (for example a
   Codex/Grok-orchestrated run), execute the equivalent heavy-path planning loop inline: generate
   multiple framings, run critics, revise until critical findings are resolved or a user decision
   is needed, then assemble the same result shape. Do **not** silently skip the critic loop or
   cross-provider convergence loop just because the Claude `Workflow` primitive is absent.

   ```
   result = Workflow({
     name: "plan-fanout",
     args: {
       question: "<the planning question/spec from source artifact + user input>",
       sourceArtifact: "<source artifact content>",
       codebaseResearch: "<research artifact content if /research ran first; null otherwise>",
       priorKnowledge: "<rendered blob from step 4b, or null>",
       providerDrafts: [
         // peer envelopes from .context/plan/*.json
       ],
       framings: [
         { key: "mvp-first", description: "..." },
         { key: "risk-first", description: "..." },
         // Optionally add { key: "integration-first", ... } for cross-system features.
         // Workflow defaults to mvp-first + risk-first if framings omitted.
       ],
       repoRoot: "<absolute path>",
       mode: "interactive" | "headless"
     }
   })
   ```

5b. **Result shape (both paths produce this object):**

   ```
   {
     question: "...",
     plan: {
       title, what, why, how, tradeoffs,
       alternatives_considered: [{name, why_rejected}],
       risks: [{risk, mitigation}],
       verification_strategy, side_effects, elimination,
       open_questions: [...]
     },
     provider_contributions: [
       { planner_key, assumptions, disagreements, evidence, open_questions, notes }
     ],
     revision_log: {
       incorporated: [{finding_title, critic_lens, how_addressed}],
       rejected:     [{finding_title, critic_lens, why_rejected}],
       tension_resolutions: [{tension, resolution}]   // completeness vs YAGNI conflicts
     },
     drafts_considered: [{framing, framing_notes}],
     critic_findings: [{title, severity, area, issue, suggestion, critic_lens}],
     disagreement_log: [
       { round, title, area, providers, status, resolution, evidence }
     ],
     stats: {
       framings_attempted, drafts_succeeded, critics_succeeded,
       total_findings, must_address_findings,
       incorporated, rejected, tensions_resolved,
       provider_contributors, disagreement_rounds,
       disagreements_found, disagreements_resolved, unresolved_disagreements
     }
   }
   ```

   The light path must zero-fill the heavy-only fields. Downstream write/persist steps must not
   branch on path.

5c. **Handle additional research needs (both paths):**

   - If the returned plan has `open_questions` that need codebase patterns: spawn
     `researcher` agent (or invoke `/research`) and re-run the path with the new
     findings as `codebaseResearch`.
   - If the plan has `open_questions` requiring production state for a bug: spawn
     investigator agents and re-run.
   - For the heavy path, prefer to satisfy open questions BEFORE re-running rather
     than running the workflow twice (it's not idempotent and not cheap).

6. **Write output** as a plan artifact:
   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="plan",
     content="<plan content>",
     command="/plan"
   )
   ```

7. **Write a DRAFT deployment guide** as a separate `deployment_guide` artifact. The plan knows
   the architecture, so it can already commit the *shape* of deploy and verification even though
   exact commands/revisions come later at build time. This draft is the seed that
   `/create-build-todos` finalizes and `/ticket-verify` grades against — do not skip it.

   Capture, from the architecture:
   - **Deploy shape:** which repos/components are touched and in what **order** (and why — which
     cross-repo contract or dependency forces it); whether there's a migration; whether a
     scheduler/worker/service deploy is needed; whether any secret/credential block or env var
     must be provisioned; whether code reaches runtime via git-pull or a service build. Name the
     project's *real* deploy primitives — discover them from the project `CLAUDE.md`/`AGENTS.md`
     and a memory search (`{"keywords": ["deploy", "migration"], "text": "deployment steps order"}`),
     never generic placeholders. Mark anything not yet known as `TBD — finalize at build`.
   - **Verification Evidence contract (per environment):** for **both staging and production**,
     what evidence proves this works — each item a reproducible read-only query/command, an
     expected good output, and a bad-output interpretation. This is the precise form of the plan's
     `verification_strategy`: "what exactly proves the fix works", split by env. Plus the
     **activation boundary** (how to know the new code is live).

   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="deployment_guide",
     content="<DRAFT filled from the template in the create-deployment-guide skill, Status: DRAFT>",
     command="/plan"
   )
   ```

   Use the template in the `create-deployment-guide` skill. Bugs and trivial single-file changes
   still get a draft — the Verification Evidence section is the whole point, and even a one-line
   fix needs a stated way to prove it in staging and prod.

## Agent Selection

**For features:** Always spawn `researcher` to analyze codebase before planning.

**For bugs:** Use investigation artifact findings; spawn additional agents only if needed.

**For all:** The planner agent includes the `research` skill (references/past-work.md) and searches past tickets
automatically as part of its research phase.

| Need                    | Agent                  | When Used                        |
| ----------------------- | ---------------------- | -------------------------------- |
| Codebase patterns       | `researcher`           | Always for features              |
| Past work learnings     | (built into planner)   | Automatic via research (references/past-work.md) |
| Production state (bugs) | Investigator agents    | If investigation incomplete      |
| Additional code context | `researcher`           | If planner requests              |
| Deep past work research | `researcher` | If planner needs more context    |

## Output

After plan is created, output:

```
Plan created for {ID}: {title}

Plan artifact stored. Review the plan and approve before proceeding.

Next: /create-build-todos {ID} (create detailed implementation steps)
```

## Next Steps

After plan is approved, create detailed implementation steps:

```
/create-build-todos F0009      # Create build_todos for ticket F0009
/create-build-todos B0003      # Create build_todos for bug B0003
```

---

# Plan Methodology

Standards for creating high-level architecture plans.

## Workflow by Work Type

| Work Type   | Input                        | Research Needed                     |
| ----------- | ---------------------------- | ----------------------------------- |
| **Feature** | source.md + user prompt      | Codebase patterns, existing code    |
| **Bug**     | source.md + investigation.md | Usually none (investigation has it) |

**For features:** Plan includes codebase research to understand existing patterns before
designing.
**For bugs:** Plan uses investigation findings to design the fix.

## Output Template

Use the template at `templates/plan.md` for plan output.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

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

### For Features (FNNN)

| Required           | Check                                              | Source                |
| ------------------ | -------------------------------------------------- | --------------------- |
| Requirements       | Clear description of what to build                 | source.md             |
| Scope boundaries   | Know what's in/out of scope                        | source.md             |
| Integration points | Identified where feature connects to existing code | **Codebase research** |
| Patterns           | Found similar implementations to follow            | **Codebase research** |

**Process:** Spawn `researcher` agent to explore codebase patterns before planning.

### For Bugs (NNN)

| Required        | Check                                              | Source               |
| --------------- | -------------------------------------------------- | -------------------- |
| Problem clarity | Can articulate what's broken and expected behavior | source.md            |
| Root cause      | Investigation identified likely cause(s)           | **investigation.md** |
| Affected scope  | Know which files/components are involved           | **investigation.md** |
| Reproduction    | Understand when/how issue occurs                   | **investigation.md** |

**Process:** Read investigation.md. If missing or incomplete, suggest running `/investigate`
first.

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

1. **Read source.md** - Understand requirements and scope
2. **Search memory service** - Find relevant gotchas, patterns, and past solutions:
   ```
   mcp__autodev-memory__search(queries=[
     {"keywords": ["<feature-area>"], "text": "<feature area> architecture patterns"},
     {"keywords": ["<technology>"], "text": "<technology> gotchas pitfalls"}
   ])
   ```
   Also review auto-injected context from the knowledge menu.
3. **First-principles analysis** - State fundamental goal, classify constraints, eliminate
   fake ones
4. **Research codebase** - Spawn `researcher` to find patterns, integration points
5. **Define what we're NOT building** - Explicitly list eliminated scope
6. **Assess complexity** - Determine verification strategy needed
7. **Design architecture** - Choose high-level implementation approach (simplest that works)
8. **Identify tradeoffs** - What we're optimizing for vs accepting
9. **Identify side effects** - What else this change affects
10. **Identify risks** - What could go wrong, how to mitigate
11. **Write plan.md** - Synthesize research into architecture doc

### For Bugs

1. **Read source.md + investigation.md** - Understand problem and root causes
2. **Search memory service** - Find related past fixes and gotchas:
   ```
   mcp__autodev-memory__search(queries=[
     {"keywords": ["<bug-area>"], "text": "<bug area> root cause fix"},
     {"keywords": ["<technology>"], "text": "<technology> gotchas"}
   ])
   ```
3. **Verify investigation complete** - If missing root causes, suggest `/investigate`
4. **First-principles analysis** - Is the root cause in code that should exist? Could we
   eliminate rather than fix?
5. **Assess complexity** - Determine verification strategy needed
6. **Design fix approach** - Choose solution based on root causes (prefer elimination over
   repair)
7. **Identify tradeoffs** - What we're optimizing for vs accepting
8. **Identify side effects** - What else this fix affects
9. **Identify risks** - What could go wrong, how to mitigate
10. **Write plan.md** - Synthesize investigation into fix architecture

## Synthesis Guidelines

**Summary section:**

- 2-3 sentences max
- What we're building and why this approach

**What We're Building:**

- High-level description of the solution
- Answer: What will exist after this that doesn't exist now?
- NO code, NO file paths

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

### Elimination Audit (CRITICAL)

When a feature replaces, supersedes, or eliminates an existing system:

- [ ] **List what gets deleted:** Enumerate every file, class, and module the new system
      replaces. This list goes into plan.md under "What We're Eliminating"
- [ ] **Find all consumers:** `grep -r "OldSystem\|old_module" src/` — every import and
      call site must be migrated or removed
- [ ] **Verify zero remaining references:** After migration, grep must return 0 results
      for the old system's imports
- [ ] **Deletion is part of the plan, not a follow-up:** The plan must include elimination
      as a required step, not a "nice to have" or separate PR. Adding a replacement without
      removing the old system is an incomplete plan.

**Rule:** If the plan says "replace X with Y", the deliverable is: Y is wired up at all
call sites AND X is deleted. If the plan only covers adding Y, it is incomplete — send it
back for revision.

### Database Changes

- [ ] New tables or columns needed? - Include migration step
- [ ] New enum values? - Add to migration
- [ ] Seed data needed? - Include in migration or seed script

### API Keys / Environment

- [ ] New API keys required? - Document in deployment notes
- [ ] Environment variables needed? - Add to .env.example

## Ticket System

Work items are tracked in the autodev-memory ticket system via MCP tools.
Use `mcp__autodev-memory__get_ticket` to read ticket details and artifacts.

Each ticket contains artifacts:

- `source` — INPUT: Problem/feature description (auto-created with ticket)
- `investigation` — INPUT (optional): From /investigate
- `plan` — OUTPUT: High-level architecture plan
- `deployment_guide` — OUTPUT: DRAFT deploy shape + per-env verification evidence contract
- `build_todo` — OUTPUT: From /create-build-todos (separate step)

### Scope Completeness Rule (CRITICAL)

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

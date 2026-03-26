---
description: Investigate bugs and incidents to find root causes. NOT for new features.
---

# Investigate Command

Spawn investigator agents to diagnose bugs and incidents. Focused on finding **root causes**
of problems, not designing solutions.

**For new features:** Skip this command and use `/plan` directly.

## Usage

```
/investigate "Service failing with timeout error"
/investigate work_items/active/009-fix-timeout
/investigate 009                              # Bug/incident #009 (NNN format)
```

## When to Use

| Situation                     | Use `/investigate`? | Instead Use             |
| ----------------------------- | ------------------- | ----------------------- |
| Bug: something is broken      | Yes                 | -                       |
| Incident: unexpected behavior | Yes                 | -                       |
| New feature                   | **No**              | `/plan` directly        |
| Understanding existing code   | **No**              | `/plan` (will research) |

## Naming Schemes

- **Bugs/Incidents**: `NNN-slug` (e.g., `009-timeout-failures`)

## Work Item Setup

**If work item path given:** Use that folder for `investigation.md`

**If starts with `F` followed by digits** (e.g., `F001`): **STOP**

Features should NOT use `/investigate`. Tell the user:

> "Features don't need investigation - use `/plan F001` directly to create an architecture plan."

**If starts with a number only** (e.g., `009`): Search for bug/incident

1. Extract the leading number (e.g., "009" from "009 check timeout settings")
2. Search: `find work_items -maxdepth 2 -type d -name "NNN-*"` (exclude `FNNN` patterns)
3. If found in **backlog/**: Move to **active/** first
4. If found in **active/** or **closed/**: Use that folder directly
5. If not found: create a new bug work item

**If no work item (prompt only):** Create new bug/incident folder:

1. Search active/closed for existing bugs: `find work_items/{active,closed} -maxdepth 1 -type d -name "[0-9][0-9][0-9]-*"`
2. Extract the numeric prefix from each folder name (e.g., `001`, `009`, `027`)
3. Find the highest number, add 1
4. **Pad to 3 digits** (e.g., 3 -> `003`, 42 -> `042`, 100 -> `100`)
5. Create folder: `work_items/active/NNN-slug/`

## Environment Detection

Parse the environment from the user's prompt. Look for keywords:

| Keyword                          | Environment | Default |
| -------------------------------- | ----------- | ------- |
| "in staging", "staging"          | staging     |         |
| "in prod", "production"          | prod        | Yes     |
| "in local", "locally", "dev"     | local       |         |

**If no environment keyword is found, default to `prod`.**

**Pass the environment explicitly to every sub-agent** in the Task prompt. Example:

```
**Environment: staging**
Use staging tools/endpoints:
- Prefect: PREFECT_API_URL=https://ts-prefect-server-staging.onrender.com/api
- Postgres: mcp__postgres_staging__ tools (NOT mcp__postgres_prod__)
- Render: filter services by staging names
```

**CRITICAL:** Never let agents default to production when the user asked for a different
environment. The environment must appear in every agent's Task prompt.

## Agent Selection

Choose agents based on problem symptoms. Refer to AGENTS.md for available investigator agents.

Common patterns:

| Symptoms                                  | Agent                    | Why                   |
| ----------------------------------------- | ------------------------ | --------------------- |
| crash, OOM, memory, timeout, deploy       | `investigator-render`    | Infrastructure issues |
| connection, query, data, records, missing | `investigator-postgres`  | Database state        |
| code, bug, why, pattern, history          | `researcher`             | Codebase & knowledge  |

**Spawn only what's needed.** Most bugs need 2-3 agents, not all available agents.

**Can spawn multiple of same type** with different focus areas.

## Process

1. **Parse problem** - Identify symptoms and likely sources
2. **Select agents** - Pick relevant agents (often 2-3)
3. **Spawn in parallel** - Single message, multiple Task calls
4. **Collect findings** - Wait for all agents
5. **Synthesize** - Write `investigation.md` with root causes and evidence
6. **Capture knowledge** - Store non-obvious findings in memory service (see below)

## Examples

**"Service crashing with OOM"**
-> `investigator-render` (memory metrics, crash details)

**"Missing data in database"**
-> `investigator-postgres` (data state) + `investigator-render` (processing status)

**"Why is this bug happening?"**
-> `researcher` (code analysis) + relevant investigator

**"Everything broke at 2pm"**
-> All investigator agents in parallel (unknown root cause)

## Knowledge Capture (Step 6)

After writing `investigation.md`, persist non-obvious findings to the memory service so future
investigations and builds benefit from them.

**Capture criteria** (store when ANY are true):
- Root cause was non-obvious (future sessions would struggle too)
- A diagnostic approach proved effective and reusable
- The bug reveals a recurring pattern or architectural gotcha
- The finding is project-specific (not general programming knowledge)

**Skip when ALL are true:**
- Root cause was obvious from error message/stack trace
- One-off issue unlikely to recur
- Already covered by an existing memory service entry

**How to capture:**

```
# 1. Search for duplicates first
mcp__autodev-memory__search(
  queries=["<root cause keywords>"],
  project="<from <!-- mem:project=X --> in CLAUDE.md>"
)

# 2. If no duplicate, store the finding
mcp__autodev-memory__add_entry(
  project="<from <!-- mem:project=X --> in CLAUDE.md>",
  title="<1-sentence root cause summary>",
  content="<Root cause explanation, evidence, and fix direction. 200-800 tokens.>",
  entry_type="gotcha",  # or "solution" if a fix pattern was identified
  summary="<1-sentence summary>",
  tags=["<area>", "<technology>"],
  source="captured",
  caller_context={
    "skill": "investigate",
    "reason": "<why this is worth persisting>",
    "action_rationale": "New entry — no existing entry covers this root cause",
    "trigger": "investigation finding"
  }
)
```

If the MCP tool is unavailable, skip this step silently.

## Output

Write `investigation.md` to work item folder with:

- Root causes identified
- Evidence from each source
- Severity assessment
- Recommended fixes (high-level)
- **Hypotheses for verification** (see below)

The **solution design** happens in `/plan`, not here.

## Hypothesis Generation

After collecting evidence from all agents, generate testable hypotheses:

### When to Generate Hypotheses

- **Always for BNNN work items** (autonomous bug fixes via `/lfg`)
- **Optional for NNN work items** (manual bug fixes) - generate when root cause is uncertain
- **Never for FNNN work items** (features don't use investigation)

### Hypothesis Quality Requirements

Each hypothesis must be:

| Criterion          | Description                                   |
| ------------------ | --------------------------------------------- |
| **Specific**       | Names exact component, condition, or behavior |
| **Testable**       | Has observable prediction                     |
| **Falsifiable**    | Can be proven wrong                           |
| **Evidence-based** | Grounded in observed data                     |

### Hypothesis Format

Add to `investigation.md` after Root Causes section:

```markdown
## Hypotheses for Verification

| ID  | Hypothesis             | Confidence | Status  |
| --- | ---------------------- | ---------- | ------- |
| H1  | [Name: specific claim] | High       | Pending |
| H2  | [Name: specific claim] | Medium     | Pending |
| H3  | [Name: specific claim] | Low        | Pending |

### H1: [Hypothesis Name]

**Statement:** [Specific claim about root cause]

**Evidence (from investigation):**

- [Observation 1 that supports this hypothesis]
- [Observation 2 that supports this hypothesis]

**Testable Prediction:**
[What we expect to find if this hypothesis is true]

**Evaluation Method:**
[Specific queries, commands, or checks to perform]

**Confidence Level:** High | Medium | Low

**Rationale:**
[Why this confidence level was assigned]
```

### Confidence Level Guidelines

| Level      | Criteria                                                         |
| ---------- | ---------------------------------------------------------------- |
| **High**   | Direct evidence (error message, stack trace, OOM log)            |
| **Medium** | Circumstantial evidence (timing correlation, similar past issue) |
| **Low**    | Speculative (process of elimination, theoretical possibility)    |

### Phase 6: Hypothesis Evaluation (Optional)

After generating hypotheses, optionally evaluate them to provide verified root causes.

**When to evaluate:**

| Context | Evaluate? | Why |
|---|---|---|
| Running inside `/lfg` | Yes (lfg handles it) | Full autonomous pipeline |
| Standalone with uncertain root cause | **Yes** | Verified root cause before planning |
| Standalone with obvious root cause | Skip | Single high-confidence hypothesis is enough |

**To evaluate standalone** (when not inside `/lfg`):

1. Spawn `hypothesis-evaluator` agent for each hypothesis (in parallel):

   ```
   Task(subagent_type="hypothesis-evaluator", prompt="
   Evaluate hypothesis from investigation.md:

   Hypothesis: [H1 statement]
   Evidence: [supporting evidence]
   Testable prediction: [what to verify]
   Evaluation method: [specific queries/checks]

   Work item: [path]

   Verify or refute this hypothesis using production data, metrics, and logs.
   Return verdict: CONFIRMED | REFUTED | INCONCLUSIVE with evidence.
   ")
   ```

2. Collect verdicts and update the hypotheses table in `investigation.md`:

   ```markdown
   | ID  | Hypothesis             | Confidence | Status     |
   | --- | ---------------------- | ---------- | ---------- |
   | H1  | [Name: specific claim] | High       | CONFIRMED  |
   | H2  | [Name: specific claim] | Medium     | REFUTED    |
   ```

3. Create `hypothesis-evaluation/` folder with evaluation documents for each hypothesis.

4. Suggest next step based on results:

   | Scenario | Suggestion |
   |---|---|
   | One CONFIRMED | "Root cause verified. Run `/plan` to design a fix." |
   | Multiple CONFIRMED | "Multiple root causes confirmed. Run `/plan` to address them." |
   | None CONFIRMED | "No hypothesis confirmed. Consider expanding investigation scope." |
   | All REFUTED | "All hypotheses refuted. Re-investigate with broader scope." |

**For BNNN work items inside `/lfg`:** The LFG workflow handles evaluation
automatically in its Phase 3 bug path. Do not duplicate it here.

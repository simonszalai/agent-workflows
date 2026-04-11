---
name: investigate
description: Investigate bugs and incidents to find root causes. NOT for new features.
---

# Investigate

Spawn investigator agents to diagnose bugs and incidents. Focused on finding **root causes**
of problems, not designing solutions.

**For new features:** Skip this command and use `/plan` directly.

## Usage

```
/investigate "Service failing with timeout error"
/investigate B0003                             # Existing bug ticket
/investigate 009                               # Legacy NNN format
```

## When to Use

| Situation                     | Use `/investigate`? | Instead Use             |
| ----------------------------- | ------------------- | ----------------------- |
| Bug: something is broken      | Yes                 | -                       |
| Incident: unexpected behavior | Yes                 | -                       |
| New feature                   | **No**              | `/plan` directly        |
| Understanding existing code   | **No**              | `/plan` (will research) |

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## Ticket Setup

**If ticket ID given** (e.g., `B0003`):

```
mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- Read the source artifact for context
- If status is `backlog`, update to `active`:
  ```
  mcp__autodev-memory__update_ticket(
    project=PROJECT, ticket_id=ID, repo=REPO,
    status="active", command="/investigate"
  )
  ```

**If starts with `F`:** **STOP** — features don't use `/investigate`. Tell the user:

> "Features don't need investigation - use `/plan F0009` directly."

**If description given** (no ID): Create a new bug ticket:

```
mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="<synthesized title>",
  type="bug",
  description="<user's description>",
  status="active",
  command="/investigate"
)
```

## Environment Detection

Parse the environment from the user's prompt. Look for keywords:

| Keyword                          | Environment | Default |
| -------------------------------- | ----------- | ------- |
| "in staging", "staging"          | staging     |         |
| "in prod", "production"          | prod        | Yes     |
| "in local", "locally", "dev"     | local       |         |

**If no environment keyword is found, default to `prod`.**

**Pass the environment explicitly to every sub-agent** in the Task prompt.

## Agent Selection

Choose agents based on problem symptoms. Refer to AGENTS.md for available investigator agents.

| Symptoms                                  | Agent                    | Why                   |
| ----------------------------------------- | ------------------------ | --------------------- |
| crash, OOM, memory, timeout, deploy       | `investigator`           | Infrastructure issues |
| connection, query, data, records, missing | `investigator`           | Database state        |
| code, bug, why, pattern, history          | `researcher`             | Codebase & knowledge  |

**Spawn only what's needed.** Most bugs need 2-3 agents, not all available agents.

## Process: Root-Cause-First Methodology

Follow this discipline strictly. The goal is to **confirm the root cause before
recommending a fix**. Premature fixes based on symptoms cause regressions.

1. **Reproduce** - Confirm the failure is real and current
   - Check Prefect flow runs, logs, or DB state to confirm the symptom
   - If the failure is intermittent, gather timing/frequency data
   - Document the exact error message, stack trace, or observable behavior

2. **Trace backward** - Follow the causal chain from symptom to origin
   - Start from the error and trace upstream: what called this? what data
     was passed? what state was expected vs actual?
   - Check deployment correlation: did failures start after a recent commit?
     If so, **suspect the new code first** before blaming external services
   - Search autodev-memory for similar past incidents:
     ```
     mcp__autodev-memory__search(
       queries=[{"keywords": ["<error area>"], "text": "<error message>"}],
       project=PROJECT
     )
     ```

3. **Select agents and spawn** - Pick relevant agents (often 2-3)
   - Single message, multiple Task calls for parallel investigation
   - Brief agents with the symptom AND the backward trace so far

4. **Collect and synthesize** - Wait for all agents, build the causal chain

5. **Form hypotheses with testable predictions**
   - For each hypothesis, define: "If this is the root cause, then we
     expect to see X when we check Y"
   - **Every hypothesis needs a prediction that can be confirmed or refuted**
   - Predictions must be specific and falsifiable, not vague

6. **Test predictions before concluding**
   - Execute the verification for each hypothesis
   - For high-confidence hypotheses: run the primary check
   - For medium-confidence: run primary + corroborating checks
   - For low-confidence: only pursue if higher-confidence hypotheses fail
   - **Do not conclude root cause without at least one confirmed prediction**

7. **Causal chain gate** — Do NOT proceed to writing the artifact until you can
   explain the full causal chain from trigger to symptom with **no gaps**:
   - Trigger → [each intermediate step] → Observed symptom
   - "Somehow X leads to Y" is a gap — fill it or flag it
   - For obvious chains (missing import, clear null deref): the chain itself is
     the gate — no prediction needed
   - For uncertain links: a prediction about something in a *different* code path
     that must also be true if this link is correct
   - **If a prediction was wrong but a fix appears to work, you found a symptom,
     not the root cause** — the real cause is still active

8. **Smart escalation** — If 2-3 hypotheses are exhausted without confirmation:

   | Pattern | Diagnosis | Next move |
   | ------- | --------- | --------- |
   | Hypotheses point to different subsystems | Architecture/design problem | Present findings, suggest `/plan` for redesign |
   | Evidence contradicts itself | Wrong mental model of the code | Re-read the code path without assumptions |
   | Works locally, fails in prod/staging | Environment problem | Focus on env differences, config, timing |
   | Fix works but prediction was wrong | Symptom fix, not root cause | Keep investigating — real cause still active |

   Present the diagnosis before proceeding. Do not keep trying blindly.

9. **Write investigation artifact** with confirmed root causes and evidence

10. **Capture knowledge** - Store non-obvious findings in memory service

## Writing the Investigation Artifact

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="investigation",
  content="<investigation content with root causes, evidence, hypotheses>",
  command="/investigate"
)
```

## Knowledge Capture (Step 6)

After writing the investigation artifact, persist non-obvious findings:

```
# 1. Search for duplicates first
mcp__autodev-memory__search(
  queries=["<root cause keywords>"],
  project=PROJECT
)

# 2. If no duplicate, store the finding
mcp__autodev-memory__create_entry(
  project=PROJECT,
  title="<1-sentence root cause summary>",
  content="<Root cause explanation, evidence, and fix direction. 200-800 tokens.>",
  entry_type="gotcha",
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

**Capture criteria** (store when ANY are true):
- Root cause was non-obvious (future sessions would struggle too)
- A diagnostic approach proved effective and reusable
- The bug reveals a recurring pattern or architectural gotcha

**Skip when ALL are true:**
- Root cause was obvious from error message/stack trace
- One-off issue with no broader lesson
- Already covered by an existing memory service entry

Individual investigator sub-agents do NOT call MCP tools — the orchestrator handles persistence
after synthesizing findings.

## Hypothesis Generation

After collecting evidence from all agents, generate testable hypotheses:

### When to Generate Hypotheses

- **Always for B-prefix tickets** (autonomous bug fixes via `/lfg` or `/auto-flow`)
- **Optional for other bugs** - generate when root cause is uncertain
- **Never for F-prefix tickets** (features don't use investigation)

### Hypothesis Format

Include in the investigation artifact after Root Causes section:

```markdown
## Hypotheses for Verification

| ID  | Hypothesis             | Confidence | Status  |
| --- | ---------------------- | ---------- | ------- |
| H1  | [Name: specific claim] | High       | Pending |
| H2  | [Name: specific claim] | Medium     | Pending |

### H1: [Hypothesis Name]

**Statement:** [Specific claim about root cause]
**Causal Chain:** [Trigger] → [Step 1] → [Step 2] → [Observed symptom]
**Uncertain Links:** [Which steps in the chain are unconfirmed, if any]
**Evidence:** [Observations supporting this]
**Testable Prediction:** [What we expect if true — something in a DIFFERENT code path]
**Evaluation Method:** [Specific queries/checks to test the prediction]
**Confidence Level:** High | Medium | Low
**Status:** Pending | Confirmed | Refuted
```

### Confidence Level Guidelines

| Level      | Criteria                                                         |
| ---------- | ---------------------------------------------------------------- |
| **High**   | Direct evidence (error message, stack trace, OOM log)            |
| **Medium** | Circumstantial evidence (timing correlation, similar past issue) |
| **Low**    | Speculative (process of elimination, theoretical possibility)    |

## Output

The investigation artifact contains:

- Root causes identified
- Evidence from each source
- Severity assessment
- Recommended fixes (high-level)
- Hypotheses for verification (when applicable)

The **solution design** happens in `/plan`, not here.

---

# Investigation Methodology

Standards for conducting **bug and incident investigations** and producing investigation
artifacts.

## Sub-Agent Behavior (CRITICAL)

**Sub-agents (investigator, investigator-prefect) must:**

- **RETURN findings directly** in your response - do NOT create files
- The parent agent will synthesize all findings into a single investigation artifact
- Never create local work_items folders or investigation files yourself

**Only the orchestrating agent** (invoked via `/investigate {number}`) writes the final
investigation artifact to the ticket via `mcp__autodev-memory__create_artifact`.

## Output Template

Use the template at `templates/investigation.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Synthesis Methodology

When combining findings from multiple sources:

1. **Correlate timestamps** - Match events across sources (logs, DB records, flow runs)
2. **Check cross-service correlation** - If multiple independent services fail
   simultaneously, investigate shared infrastructure (proxy, DB, network) before
   per-service causes. Error messages from individual services may assume a cause
   (e.g., "anti-bot challenge") that is actually a shared infrastructure failure.
3. **Follow causation** - Infrastructure issues -> flow failures -> data state
4. **Quantify impact** - Count affected records, flows, time windows
5. **Rank by severity** - Critical (data loss, outage) > High (degraded) > Medium (edge cases)
6. **Verify hypotheses** - Each root cause needs evidence from at least one source

## Evidence Quality

**Strong evidence:**

- Exact timestamps matching across sources
- Error messages with stack traces
- Metrics showing clear anomalies
- Database records showing state transitions

**Weak evidence (needs corroboration):**

- Absence of data (could be many causes)
- Timing correlation without causation
- Single source without cross-reference

## Severity Definitions

| Severity | Definition                                  |
| -------- | ------------------------------------------- |
| CRITICAL | Data loss, complete outage, security breach |
| HIGH     | Degraded service, significant data issues   |
| MEDIUM   | Edge cases, minor impact, workaround exists |
| LOW      | Cosmetic, minimal impact                    |

## Investigation Process

1. **Gather evidence** - Collect findings from all relevant sources
2. **Check deployment correlation** - Compare failure onset with recent deploys.
   If failures started right after a code change, **suspect the new code first** —
   don't blame external services until the new code is ruled out. New "guard" or
   "pre-flight" checks are especially suspect: they can silently block real work.
3. **Correlate timeline** - Build event sequence across sources
4. **Identify root causes** - Distinguish symptoms from causes
5. **Assess impact** - Quantify what was affected
6. **Recommend fixes** - High-level fix directions (not solution design)

**Note:** Investigation answers "what happened and why". Solution design happens in `/plan`.

## Closing Investigations

**Auto-close when all "Next Steps" are complete.** When all checkboxes in the investigation
are checked off:

1. Create a conclusion artifact on the ticket via `mcp__autodev-memory__create_artifact`
2. Update ticket status to `completed` via `mcp__autodev-memory__update_ticket`
3. Report: "Investigation complete. Ticket closed."

Do NOT wait for user to say "close" - if all action items are done, close it.

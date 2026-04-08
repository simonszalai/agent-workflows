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
| crash, OOM, memory, timeout, deploy       | `investigator-render`    | Infrastructure issues |
| connection, query, data, records, missing | `investigator-postgres`  | Database state        |
| code, bug, why, pattern, history          | `researcher`             | Codebase & knowledge  |

**Spawn only what's needed.** Most bugs need 2-3 agents, not all available agents.

## Process

1. **Parse problem** - Identify symptoms and likely sources
2. **Select agents** - Pick relevant agents (often 2-3)
3. **Spawn in parallel** - Single message, multiple Task calls
4. **Collect findings** - Wait for all agents
5. **Synthesize** - Write investigation artifact with root causes and evidence
6. **Capture knowledge** - Store non-obvious findings in memory service

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

## Hypothesis Generation

After collecting evidence from all agents, generate testable hypotheses:

### When to Generate Hypotheses

- **Always for B-prefix tickets** (autonomous bug fixes via `/lfg`)
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
**Evidence:** [Observations supporting this]
**Testable Prediction:** [What we expect if true]
**Evaluation Method:** [Specific queries/checks]
**Confidence Level:** High | Medium | Low
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

---
name: research
description: Research how something is implemented across the entire codebase. Finds patterns and inconsistencies.
---

# Research

Spawn a `researcher` agent to search the codebase for patterns, implementations, and
architectural decisions relevant to the research question.

## Usage

```
/research F0014 "how is historical pricing calculated"   # Add research to existing ticket
/research B0009 "where do timeout errors originate"      # Add research to bug ticket
/research "how is error handling done"                   # Creates new research ticket
```

## When to Use

| Situation                            | Use `/research`? | Instead Use    |
| ------------------------------------ | ---------------- | -------------- |
| Understanding current implementation | Yes              | -              |
| Finding patterns across codebase     | Yes              | -              |
| Finding inconsistencies              | Yes              | -              |
| Research to inform a feature/bug     | Yes              | -              |
| Bug/incident investigation           | **No**           | `/investigate` |
| Planning a new feature               | **No**           | `/plan`        |
| Checking specific file/function      | **No**           | Read directly  |

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## Ticket Setup

**If ticket ID given** (e.g., `/research F0014 "question"`):

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```
- If not found: error - "Ticket {ID} not found"
- Read source artifact for context

**If only a question given** (e.g., `/research "how does X work"`):

```
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="Research: <slug from question>",
  type="refactor",
  description="Research question: <user's question>",
  status="active",
  command="/research"
)
```

## Process

1. **Parse the research question** - What pattern/implementation are we looking for?

2. **Spawn researcher agent** with the research question:

   ```
   Task(subagent_type="researcher", prompt="
     Research question: [question]
     Ticket: [ticket_id]

     Search the codebase to answer this question. Focus on:
     - Finding ALL relevant implementations
     - Identifying architectural patterns used
     - Noting any inconsistencies between implementations
     - Understanding WHY patterns are used (read context, not just grep)

     Return findings using the research output template.
   ")
   ```

3. **Agent returns findings** — orchestrator stores as artifact

4. **Store research as artifact:**

   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="investigation",
     content="<research findings>",
     title="Research: <question>",
     command="/research"
   )
   ```

## Research Output Template (MANDATORY)

The researcher agent MUST use this template:

```markdown
# Research Findings

**Question:** [original question]
**Date:** YYYY-MM-DD

## Summary

[3-5 sentence overview of what was found]

## Key Architectural Patterns (MANDATORY)

### Pattern 1: [name]

**What:** [brief description]
**Where:** `file:line` - canonical example
**Why:** [why this pattern exists]
**Usage:** [code example showing correct usage]

## Findings

### [Topic 1]

**Locations:**
- `file:line` - description

**Implementation:**
[Description of how this works]

## Inconsistencies Found

### Inconsistency 1: [description]

**Locations:**
- `file:line` - uses approach A
- `file:line` - uses approach B

**Impact:** [why this matters]
**Recommendation:** [which approach to standardize on]
```

---

# Research Methodology

Standards for conducting **exhaustive codebase research** and storing findings as ticket
artifacts via `mcp__autodev-memory__create_artifact`. NEVER write research output to
`.context/` or any local file — all results go to ticket artifacts.

## Critical Requirement: Complete Coverage

Research MUST be exhaustive. Every relevant file must be examined. This is achieved through:

1. **Zone partitioning** - Codebase divided into non-overlapping zones
2. **Parallel agents** - One agent per zone, all running simultaneously
3. **Explicit file lists** - Agents must enumerate files they searched
4. **Coverage verification** - Synthesis checks all zones were covered

## Zone Definitions

Zones are project-specific. Check AGENTS.md for the project's zone definitions. A typical
partitioning divides the codebase into 3-6 non-overlapping zones based on architectural layers:

| Zone Example | Typical Contents                          |
| ------------ | ----------------------------------------- |
| Routes/API   | Request handlers, endpoints, page views   |
| Components   | UI components, shared widgets             |
| Models/Data  | Database access, schemas, repositories    |
| Core/Lib     | Utilities, hooks, type definitions        |
| Config       | Project configuration, infrastructure     |

## Sub-Agent Behavior (CRITICAL)

**Zone agents must:**

- **Search EVERY file** in their assigned zone - no sampling
- **Document file count** - "Searched X files in zone Y"
- **List every occurrence** of the pattern being researched
- **Note variations** between files
- **Return findings directly** - do NOT create files
- The orchestrator synthesizes all findings and stores them as a ticket artifact

## Agent Output Format

Each zone agent returns:

```markdown
## Zone: {zone_name}

**Files searched:** {count}
**Files with matches:** {count}

### Occurrences

#### {file_path}:{line_number}
```{language}
{code snippet}
```
**Pattern variant:** {description of how this implements the pattern}
**Notes:** {any issues or variations}

#### {file_path}:{line_number}
...

### Zone Summary

- **Dominant pattern:** {most common implementation}
- **Variations found:** {count}
- **Potential issues:** {list}

### Questions for Synthesis

- {questions about patterns that need cross-zone context}
```

## Synthesis Methodology

When combining findings from zone agents:

1. **Verify coverage** - Confirm all zones reported, check file counts
2. **Catalog patterns** - Group similar implementations
3. **Identify dominant pattern** - What's most common across zones
4. **Flag inconsistencies** - Where does implementation differ
5. **Rank by impact** - Which inconsistencies matter most
6. **Recommend standardization** - Suggest which pattern to adopt

## Inconsistency Severity

| Severity | Definition                                           |
| -------- | ---------------------------------------------------- |
| HIGH     | Could cause bugs, data loss, or security issues      |
| MEDIUM   | Makes code harder to maintain, confusing             |
| LOW      | Cosmetic, style preference, minor deviation          |

## Output Template

Use the template at `templates/research.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt).

## Research Process

1. **Understand topic** - What pattern/implementation to research
2. **Spawn zone agents** - All zones in parallel
3. **Collect findings** - Wait for ALL agents
4. **Verify coverage** - Check file counts, ensure completeness
5. **Synthesize patterns** - Catalog variations
6. **Store findings** - Create ticket artifact (artifact_type="investigation")

## Quality Standards

- **No sampling** - Every file must be checked
- **Code evidence** - Include snippets for each occurrence
- **Exact locations** - File paths and line numbers
- **Quantified results** - Counts of patterns, files, variations
- **Actionable output** - Clear recommendations for standardization

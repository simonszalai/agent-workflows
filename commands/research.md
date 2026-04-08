---
description: Research how something is implemented across the entire codebase. Finds patterns and inconsistencies.
---

# Research Command

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

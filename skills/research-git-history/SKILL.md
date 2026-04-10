---
name: research-git-history
description: Git history analysis methodology for understanding code evolution and patterns. Used by researcher agent.
---

# Git History Research Methodology

Standards for archaeological analysis of code repositories to uncover evolution patterns and historical context.

## Core Responsibilities

### 1. File Evolution Analysis

For each file of interest:

```bash
git log --follow --oneline -20 <file>
```

Trace recent history, identify major refactorings, renames, and significant changes.

### 2. Code Origin Tracing

```bash
git blame -w -C -C -C <file>
```

Trace origins of specific code sections, ignoring whitespace changes and following code movement across files.

### 3. Pattern Recognition

```bash
git log --grep="<keyword>" --oneline
```

Analyze commit messages for recurring themes, issue patterns, and development practices. Look for keywords like 'fix', 'bug', 'refactor', 'performance', etc.

### 4. Contributor Mapping

```bash
git shortlog -sn -- <path>
```

Identify key contributors and their relative involvement. Cross-reference with specific file changes to map expertise domains.

### 5. Historical Pattern Extraction

```bash
git log -S"pattern" --oneline
```

Find when specific code patterns were introduced or removed, understanding the context of their implementation.

### 6. Work Item History

Search the ticket system for context and decisions:

```
mcp__autodev-memory__search_tickets(project="ts", query="relevant search terms")
mcp__autodev-memory__get_ticket(project="ts", ticket_id="NNN", repo="ts-prefect")
```

For each relevant ticket, review its artifacts:

- `source` - Original problem statement
- `investigation` - Analysis and findings
- `plan` - Implementation approach taken
- `retrospective` - Final decisions and rationale

This provides context on why code changed, not just what changed.

## Analysis Methodology

- Start with a broad view of file history before diving into specifics
- Look for patterns in both code changes and commit messages
- Identify turning points or significant refactorings in the codebase
- Connect contributors to their areas of expertise based on commit patterns
- Extract lessons from past issues and their resolutions
- Cross-reference git history with closed work items for decision context

## Output Format

Structure findings as:

### Timeline of File Evolution

Chronological summary of major changes with dates and purposes

### Key Contributors and Domains

List of primary contributors with their apparent areas of expertise

### Historical Issues and Fixes

Patterns of problems encountered and how they were resolved

### Pattern of Changes

Recurring themes in development, refactoring cycles, and architectural evolution

## Analysis Considerations

- The context of changes (feature additions vs bug fixes vs refactoring)
- The frequency and clustering of changes (rapid iteration vs stable periods)
- The relationship between different files changed together
- The evolution of coding patterns and practices over time

## Key Insight

Understand not just what the code does, but why it evolved to its current state, informing better decisions for future changes.

---
name: review-simplicity
description: Code simplicity and YAGNI checklist. Used by code-simplicity-reviewer agent. Portable to Cursor.
---

# Simplicity Review Standards

Standards for code simplicity and YAGNI compliance. Apply these to identify unnecessary complexity.

## Core Rule

**Don't optimize what should not exist.** Before simplifying code, ask: should this exist at all?

## Core Principles

### 0. Question Existence First

Before analyzing HOW code works, ask WHETHER it should exist:

- What breaks if we delete this entirely?
- Is this solving a real problem or an imagined one?
- Who actually uses this flexibility/abstraction?

### 1. Analyze Every Line

Question the necessity of each line of code. If it doesn't directly contribute to current requirements, flag it for removal.

### 2. Simplify Complex Logic

- Break down complex conditionals into simpler forms
- Replace clever code with obvious code
- Eliminate nested structures where possible
- Use early returns to reduce indentation

### 3. Remove Redundancy

- Identify duplicate error checks
- Find repeated patterns that can be consolidated
- Eliminate defensive programming that adds no value
- Remove commented-out code

### 4. Challenge Abstractions

- Question every interface, base class, and abstraction layer
- Recommend inlining code that's only used once
- Suggest removing premature generalizations
- Identify over-engineered solutions

### 5. Apply YAGNI Rigorously

- Remove features not explicitly required now
- Eliminate extensibility points without clear use cases
- Question generic solutions for specific problems
- Remove "just in case" code

### 6. Optimize for Readability

- Prefer self-documenting code over comments
- Use descriptive names instead of explanatory comments
- Simplify data structures to match actual usage
- Make the common case obvious

## Review Process

1. First, identify the core purpose of the code
2. List everything that doesn't directly serve that purpose
3. For each complex section, propose a simpler alternative
4. Create a prioritized list of simplification opportunities
5. Estimate the lines of code that can be removed

## Output Format

```markdown
## Simplification Analysis

### Core Purpose

[Clearly state what this code actually needs to do]

### Unnecessary Complexity Found

- [Specific issue with line numbers/file]
- [Why it's unnecessary]
- [Suggested simplification]

### Code to Remove

- [File:lines] - [Reason]
- [Estimated LOC reduction: X]

### Simplification Recommendations

1. [Most impactful change]
   - Current: [brief description]
   - Proposed: [simpler alternative]
   - Impact: [LOC saved, clarity improved]

### YAGNI Violations

- [Feature/abstraction that isn't needed]
- [Why it violates YAGNI]
- [What to do instead]

### Final Assessment

Total potential LOC reduction: X%
Complexity score: [High/Medium/Low]
Recommended action: [Proceed with simplifications/Minor tweaks only/Already minimal]
```

## Key Philosophy

- **Don't optimize what shouldn't exist** - Elimination beats optimization
- **The best code is no code** - Question existence before quality
- **Perfect is the enemy of good** - Stop when it works
- **Every line is a liability** - Bugs, maintenance, cognitive load
- **Orders of magnitude first** - Can we eliminate (100%)? Then reduce 10x? Only then 2x

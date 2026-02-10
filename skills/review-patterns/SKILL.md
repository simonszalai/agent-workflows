---
name: review-patterns
description: Design patterns, anti-patterns, and code quality checklist. Used by pattern-recognition-specialist agent. Portable to Cursor.
---

# Pattern Review Standards

Standards for pattern analysis and code quality review.

## Primary Responsibilities

### 1. Design Pattern Detection

Identify common design patterns:

- Factory, Singleton, Observer, Strategy, etc.
- Document where each pattern is used
- Assess whether implementation follows best practices

### 2. Anti-Pattern Identification

Scan for code smells and anti-patterns:

- TODO/FIXME/HACK comments (technical debt indicators)
- God objects/classes with too many responsibilities
- Circular dependencies
- Inappropriate intimacy between classes
- Feature envy and other coupling issues
- **Append-before-confirm**: Mutating state (list append, dict update) before a fallible
  operation in a try block, causing inconsistent state on exception
- **Silent fallback**: Code that changes a boolean flag or classification when an operation
  fails instead of raising an error (e.g., flipping `is_existing = False` when lookup fails).
  This masks the real failure and creates invisible failure chains. Flag any pattern where
  failure silently alters control flow rather than surfacing an error.

### 3. Naming Convention Analysis

Evaluate consistency in naming across:

- Variables, methods, and functions
- Classes and modules
- Files and directories
- Constants and configuration values

Identify deviations from established conventions.

### 4. Code Duplication Detection

Identify duplicated code blocks that could be refactored:

- Use appropriate thresholds based on language
- Prioritize significant duplications
- Consider shared utilities or abstractions

### 5. Architectural Boundary Review

Check for layer violations:

- Proper separation of concerns
- Cross-layer dependencies that violate principles
- Modules respecting intended boundaries
- Bypassing of abstraction layers

## Analysis Workflow

1. Broad pattern search for structural matching
2. Compile list of identified patterns and locations
3. Search for anti-pattern indicators (TODO, FIXME, HACK, XXX)
4. Analyze naming conventions by sampling representative files
5. Run duplication detection
6. Review architectural structure for boundary violations

## Report Format

### Pattern Usage Report

- List of design patterns found
- Locations and implementation quality

### Anti-Pattern Locations

- Specific files and line numbers
- Severity assessment

### Naming Consistency Analysis

- Statistics on convention adherence
- Specific examples of inconsistencies

### Code Duplication Metrics

- Quantified duplication data
- Recommendations for refactoring

## Analysis Guidelines

- Consider specific language idioms and conventions
- Account for legitimate exceptions (with justification)
- Prioritize findings by impact and ease of resolution
- Provide actionable recommendations, not just criticism
- Consider project maturity and technical debt tolerance

## Project-Specific Patterns

If project has documented patterns (in CLAUDE.md or similar), incorporate these into the analysis baseline.

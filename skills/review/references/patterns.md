# Pattern Review Standards

Standards for pattern analysis and code quality review.

Output contract: structured findings JSON per `findings-schema.json` (severity p1/p2/p3) —
no other format.

## Primary Responsibilities

### 1. Anti-Pattern Identification

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
- **Success-only timestamp update**: A scheduling timestamp (e.g., `last_checked_at`) that
  gates "is this item due for processing?" but is only updated inside the success path of a
  try block. When processing fails, the timestamp is never advanced, causing the item to be
  reprocessed on every scheduler cycle (e.g., every minute) instead of its configured interval
  (e.g., every 7 hours). At scale this is catastrophic — expensive API calls (LLM searches,
  external providers) run on every cycle before hitting the same error, burning costs in a
  tight loop. **Fix:** Update the scheduling timestamp AFTER the try/except, unconditionally.
  Separate "last checked" (always update) from "last cursor position" (update on success).

- **Deadline over heterogeneous work**: A shared deadline/timeout/coordinator wrapping work
  units with different internal time budgets. For each work type actually executed inside the
  bounded construct, compare its legitimate worst-case duration (internal retry/strategy
  budgets, provider timeouts) against the shared deadline. Flag as p1 when a work type's budget
  exceeds the deadline, or when a comment/plan claims a work type is "outside this policy" /
  "terminal, non-retryable" but the code still runs it inside the wrapper — comment-level
  exemptions are not exemptions. Also flag when deadline cancellation replaces the underlying
  work's diagnostic exception with a generic `TimeoutError`/`CancelledError`, masking the
  actionable root cause (B0306/B0312: 55s coordinator cancelled 150s browser acquisition,
  hiding bot-protection diagnostics for 106 failures).

### 2. Naming Convention Analysis

Evaluate consistency in naming across:

- Variables, methods, and functions
- Classes and modules
- Files and directories
- Constants and configuration values

Identify deviations from established conventions.

### 3. Code Duplication Detection

Identify duplicated code blocks that could be refactored:

- Use appropriate thresholds based on language
- Prioritize significant duplications
- Consider shared utilities or abstractions

### 4. Architectural Boundary Review

Check for layer violations:

- Proper separation of concerns
- Cross-layer dependencies that violate principles
- Modules respecting intended boundaries
- Bypassing of abstraction layers

## Analysis Workflow

1. Search for anti-pattern indicators (TODO, FIXME, HACK, XXX)
2. Analyze naming conventions by sampling representative files
3. Run duplication detection
4. Review architectural structure for boundary violations

## Analysis Guidelines

- Consider specific language idioms and conventions
- Account for legitimate exceptions (with justification)
- Prioritize findings by impact and ease of resolution
- Provide actionable recommendations, not just criticism
- Consider project maturity and technical debt tolerance

## Project-Specific Patterns

If project has documented patterns (in CLAUDE.md or similar), incorporate these into the analysis baseline.

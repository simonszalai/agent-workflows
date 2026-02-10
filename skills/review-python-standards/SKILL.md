---
name: review-python-standards
description: Python coding standards and quality checklist. Used by kieran-python-reviewer agent. Portable to Cursor.
---

# Python Review Standards

Standards for high-quality Python code. Apply these when reviewing Python changes.

## 0. Project-Specific Standards First

**Before applying generic rules below, read project coding standards:**

```
.claude/knowledge/references/coding-standards-*.md
```

Project-specific conventions override generic best practices. For example, a project may allow
patterns (like assertions for data completeness) that generic rules would flag.

## 1. Existing Code Modifications - Be Very Strict

- Any added complexity to existing files needs strong justification
- Always prefer extracting to new modules/classes over complicating existing ones
- Question every change: "Does this make the existing code harder to understand?"

## 2. New Code - Be Pragmatic

- If it's isolated and works, it's acceptable
- Still flag obvious improvements but don't block progress
- Focus on whether the code is testable and maintainable

## 3. Type Hints Convention

- ALWAYS use type hints for function parameters and return values
- Use modern Python 3.10+ syntax: `list[str]` not `List[str]`
- Use union types with `|` operator: `str | None` not `Optional[str]`

**Examples:**

- FAIL: `def process_data(items):`
- PASS: `def process_data(items: list[User]) -> dict[str, Any]:`

## 4. Testing as Quality Indicator

For every complex function, ask:

- "How would I test this?"
- "If it's hard to test, what should be extracted?"
- Hard-to-test code = Poor structure that needs refactoring

## 5. Critical Deletions & Regressions

For each deletion, verify:

- Was this intentional for THIS specific feature?
- Does removing this break an existing workflow?
- Are there tests that will fail?
- Is this logic moved elsewhere or completely removed?

## 6. Naming & Clarity - The 5-Second Rule

If you can't understand what a function/class does in 5 seconds from its name:

- FAIL: `do_stuff`, `process`, `handler`
- PASS: `validate_user_email`, `fetch_user_profile`, `transform_api_response`

## 7. Module Extraction Signals

Consider extracting to a separate module when you see multiple of these:

- Complex business rules (not just "it's long")
- Multiple concerns being handled together
- External API interactions or complex I/O
- Logic you'd want to reuse across the application

## 8. Pythonic Patterns

- Use context managers (`with` statements) for resource management
- Prefer list/dict comprehensions over explicit loops (when readable)
- Use dataclasses or Pydantic models for structured data
- FAIL: Getter/setter methods (this isn't Java)
- PASS: Properties with `@property` decorator when needed

## 9. Import Organization

- Follow PEP 8: stdlib, third-party, local imports
- Use absolute imports over relative imports
- Avoid wildcard imports (`from module import *`)
- FAIL: Circular imports, mixed import styles
- PASS: Clean, organized imports with proper grouping

## 10. Modern Python Features

- Use f-strings for string formatting (not % or .format())
- Leverage pattern matching (Python 3.10+) when appropriate
- Use walrus operator `:=` for assignments in expressions when it improves readability
- Prefer `pathlib` over `os.path` for file operations

## 11. Documentation Staleness

Check for stale documentation that references old work items or outdated context:

- **Module docstrings** referencing completed/old work items (e.g., "Added in F003")
- **Function docstrings** describing removed parameters or old behavior
- **Comments** with TODO items for completed work
- **README/doc files** with outdated architecture descriptions

**What to flag:**

- Docstrings mentioning work item IDs from closed items (check `work_items/closed/`)
- Comments saying "temporary" or "TODO" for code that's been stable
- Docstrings that don't match current function signatures

## 12. pgvector/NumPy Truthiness

**Critical for database code with vector columns.**

pgvector columns (`Vector(N)`) return NumPy arrays, not Python lists. Using truthiness checks on
NumPy arrays raises `ValueError: The truth value of an array with more than one element is
ambiguous`.

**FAIL - Will crash at runtime:**

```python
if not record.core_event_embedding:  # NumPy array truthiness fails
    return []

if record.embedding:  # Same problem
    process(record.embedding)
```

**PASS - Use explicit None checks:**

```python
if record.core_event_embedding is None:  # Correct
    return []

if record.embedding is not None:  # Correct
    process(record.embedding)
```

**When to check:** Any code touching these column patterns:

- `core_event_embedding`, `title_embedding`, `*_embedding`
- Any `Field(sa_type=Vector(N))` column

See: `.claude/knowledge/gotchas/pgvector-numpy-truthiness-20260122.md`

## 13. Exception Handler Control Flow

When reviewing exception handlers around multi-step operations, check for the
**append-before-confirm anti-pattern**: mutable state (list appends, dict updates, flag sets)
modified BEFORE a fallible operation in the same try block.

**FAIL - Mutation before fallible call:**

```python
results = []
for item in items:
    try:
        results.append(item)           # Appended BEFORE the fallible call
        await external_api_call(item)  # If this throws, item is still in results
    except Exception:
        log_error(item)
        continue
```

**PASS - Fallible call before mutation:**

```python
results = []
for item in items:
    try:
        await external_api_call(item)  # Fallible call FIRST
        results.append(item)           # Only added on success
    except Exception:
        log_error(item)
        continue
```

**Checklist for exception handlers:**

- Are mutable collections modified BEFORE a fallible operation in the same try block?
- If the fallible operation throws, does the catch block clean up partial state, or does the
  mutation leak to downstream code?
- Is there a transactional invariant (e.g., "X must succeed before Y is considered done") that
  the ordering violates?

## 14. Core Philosophy

- **Explicit > Implicit**: "Readability counts" - follow the Zen of Python
- **Duplication > Complexity**: Simple, duplicated code is BETTER than complex DRY abstractions
- "Adding more modules is never a bad thing. Making modules very complex is a bad thing"
- **Duck typing with type hints**: Use protocols and ABCs when defining interfaces
- Follow PEP 8, but prioritize consistency within the project

## Review Checklist

When reviewing Python code:

1. Start with critical issues (regressions, deletions, breaking changes)
2. Check for missing type hints and non-Pythonic patterns
3. Verify modern type syntax (`tuple` not `Tuple`, `T | None` not `Optional[T]`)
4. Check for `logger.exception()` in except blocks (not `logger.error()`)
5. Look for unused parameters, variables, or fetched data
6. Check for stale docstrings referencing old work items
7. **Check for pgvector/NumPy truthiness bugs** (see section 12)
8. **Check exception handler control flow** for append-before-confirm anti-pattern (see section 13)
9. Evaluate testability and clarity
10. Suggest specific improvements with examples
11. Be strict on existing code modifications, pragmatic on new isolated code
12. Always explain WHY something doesn't meet the bar

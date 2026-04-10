---
name: write-tests
description: Write sensible tests for code changes. Analyzes what matters, skips what doesn't.
skills:
  - autodev-search
---

# Write Tests Command

Write tests that catch real bugs and protect important behavior. Not coverage theater.

## Usage

```
/write-tests                        # Analyze current diff, write tests for changes
/write-tests app/models/client.ts   # Write tests for specific file
/write-tests F003                   # Write tests for a work item's changes
```

## Process

### 1. Load Testing Strategy and Search Memory

Read `references/strategy.md` for:
- What to test vs what to skip (priority matrix)
- Test types and when to use each (unit, integration, e2e)
- Speed and parallelism requirements
- Anti-patterns to avoid

Also check the project's AGENTS.md for:
- Test runner commands
- Test database configuration
- Demo accounts for e2e
- Project-specific test conventions

**Search memory service** for testing gotchas relevant to the code being tested:

```
mcp__autodev-memory__search(queries=[
  {"keywords": ["test", "<technology>"], "text": "<area> testing gotchas pitfalls"},
  {"keywords": ["test", "<area>"], "text": "<area> test patterns assertions"}
])
```

Also review auto-injected context from the knowledge menu for relevant testing entries.

### 2. Analyze What Changed

Determine what code needs tests:

```bash
# If testing current diff
git diff --stat HEAD
git diff HEAD -- '*.ts' '*.tsx' '*.py'

# If testing a specific file
# Read the file and understand its exports

# If testing a work item
# Read the work item's plan.md and build_todos/ for changed files
```

**Classify each changed function/module:**

| Classification | Test Type | Location |
|---|---|---|
| Pure logic (transformers, validators, calculators) | Unit test (vitest) | Co-located `[name].test.ts` |
| Database operations (model functions with queries) | Integration test (vitest + DB) | `tests/vitest/[area]/` |
| API routes (loaders, actions) | Integration or E2E | Depends on complexity |
| Multi-step user flows (auth, checkout, forms) | E2E (playwright) | `tests/playwright/e2e/` |
| Configuration/wiring (no logic) | **Skip** | - |
| Getters, setters, trivial wrappers | **Skip** | - |
| Type-level guarantees | **Skip** | - |

### 3. Design Test Cases

For each function worth testing:

**Happy path (1-2 tests):**
- Most common successful scenario
- Second happy path only if meaningfully different branches

**Edge cases (only the ones that matter):**
- Empty/null inputs the function actually receives in production
- Boundary values where behavior changes
- Error cases users can actually trigger

**Apply the "Delete Test" litmus test:** If the test broke, would you investigate or just
update the assertion? If you'd just update it, skip it.

### 4. Write Tests

Follow the `references/strategy.md` for structure, naming, and patterns. Key rules:

**All test types:**
- Test names are sentences describing behavior
- One logical assertion per test
- Use `faker` for test data generation
- Every test must be independent and parallelizable

**Parallelism (critical):**
- Use unique identifiers: `test-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`
- No shared mutable state between tests
- `beforeEach` with fresh state, never `beforeAll` with mutable state
- Clean up in `afterEach` using the unique identifier
- Use `concurrent: true` in vitest where possible

**Speed:**
- Mock external services at the HTTP boundary, not business logic
- Prefer unit tests over integration when logic is testable without I/O
- Prefer API-level tests over browser tests for verifying behavior
- Keep test setup minimal - only create data each test actually needs
- Never use `waitForTimeout` in e2e - wait for conditions

### 5. Run and Verify

```bash
# Run the specific test files
bun run test [path/to/test.test.ts]

# For E2E
bun run test:e2e
```

All tests must pass. If a test is flaky on first run, fix it - don't retry and hope.

**Verify parallelism:** Run the full test suite to confirm new tests don't interfere with
existing tests.

### 6. Validate Test Quality

Before finishing, check each test:

- [ ] Tests behavior, not implementation (refactoring the code shouldn't break the test)
- [ ] A real bug would cause this test to fail
- [ ] Deterministic (no timing dependencies, random values in assertions)
- [ ] Independent (can run in any order, parallel with any other test)
- [ ] Test name is a sentence describing what broke
- [ ] Error/edge case assertions match actual implementation (read the code to check raises vs returns)

## Output

After writing tests, report:

```
Tests written:
- [file path]: [what it tests] (X tests)
- [file path]: [what it tests] (X tests)

Intentionally not tested:
- [thing]: [why - e.g., "trivial CRUD wrapper", "type-enforced", "no logic"]

Parallelism: All tests use unique identifiers and run independently.

Run: bun run test [paths]
```

### 7. Capture Test Failure Patterns (if failures were fixed)

If any tests failed during step 5 and you fixed them, store the failure pattern in memory so
future test-writing avoids the same pitfall:

```
# 1. Search for duplicates
mcp__autodev-memory__search(
  queries=["<failure pattern keywords>"],
  project="<from <!-- mem:project=X --> in CLAUDE.md>"
)

# 2. If no duplicate, store the pattern
mcp__autodev-memory__create_entry(
  project="<from <!-- mem:project=X --> in CLAUDE.md>",
  title="Test gotcha: <1-sentence failure summary>",
  content="<What failed, why, and the fix. 100-300 tokens.>",
  entry_type="gotcha",
  summary="<1-sentence summary>",
  tags=["test", "<technology>", "<area>"],
  source="captured",
  caller_context={
    "skill": "write-tests",
    "reason": "Test failure pattern that future test-writing should know about",
    "action_rationale": "New entry — no existing entry covers this test pitfall",
    "trigger": "test failure fix"
  }
)
```

**Capture when:** The failure was non-obvious (e.g., async timing, mock setup, DB state).
**Skip when:** The failure was a simple typo or wrong assertion value.

If the MCP tool is unavailable, skip this step silently.

## When Called from /build

If invoked as part of a build step, write tests for the specific build_todo's changes only.
Don't test unrelated code. Match test scope to change scope.

## When Called from /lfg or /auto-build

Write tests for all code changes from the build phase. Classify all changed code and write
tests at the appropriate level. Run the full test suite to verify no regressions.

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

Also review bounded injected context for relevant testing entries when present.

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

**Provider/cache temporal-finality cases (when applicable):**
- External provider data changes over time: before finalization vs after finalization.
- Cache hit differs from provider miss: an existing stale/provisional row must not be trusted
  as final ground truth.
- Multiple writers share a table/cache: live/prompt-context writers cannot poison
  outcome/label readers.
- First-write-wins behavior is explicit: `ON CONFLICT DO NOTHING` is tested or rejected for
  mutable provider values.
- Timezone/calendar boundaries are represented in fixtures when finality depends on exchange
  close, business day, or source timestamp.

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

Use the **project's test commands** — from its CLAUDE.md / AGENTS.md or package scripts — not
a hardcoded runner. Run the specific new test files first, then the relevant suite.

*Example (bun-based project):*

```bash
# Run the specific test files
bun run test [path/to/test.test.ts]

# For E2E
bun run test:e2e
```

All tests must pass. If a test is flaky on first run, fix it - don't retry and hope.

Run the new test files plus the suites covering the touched modules — NOT the whole
repository suite. The single full-suite run is owned by the orchestrator's final health
gate after the last code/test change; adding another one here duplicates it. Only run the
full suite yourself when no orchestrator gate will follow (standalone invocation) or the
new tests touch shared fixtures/config that could interfere beyond their modules.

### 6. Validate Test Quality

Before finishing, check each test:

- [ ] Tests behavior, not implementation (refactoring the code shouldn't break the test)
- [ ] A real bug would cause this test to fail
- [ ] Deterministic (no timing dependencies, random values in assertions)
- [ ] Independent (can run in any order, parallel with any other test)
- [ ] Test name is a sentence describing what broke
- [ ] Error/edge case assertions match actual implementation (read the code to check raises vs returns)
- [ ] For provider-backed caches/outcomes, cache-hit and provisional-vs-final behavior is tested

## Output

After writing tests, report:

```
Tests written:
- [file path]: [what it tests] (X tests)
- [file path]: [what it tests] (X tests)

Intentionally not tested:
- [thing]: [why - e.g., "trivial CRUD wrapper", "type-enforced", "no logic"]

Parallelism: All tests use unique identifiers and run independently.

Run: [project test command] [paths]
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

## When Called from an Orchestrator (/ticket-flow, /lfg)

This skill is invoked by orchestrators **after** the `/build` loop completes, scoped to the
**whole change set** from the build phase — not per-todo. Classify all changed code and write
tests at the appropriate level. Don't test unrelated code; match test scope to change scope.
Run the new tests plus affected suites; the orchestrator's single final health gate owns
the full-suite regression run.

**Ticketless note (lfg):** when running under `/lfg` there is no ticket — make no MCP writes
(no ticket or artifact updates). Report results back to the orchestrator only.

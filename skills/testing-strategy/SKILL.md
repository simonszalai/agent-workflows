---
name: testing-strategy
description: Universal testing methodology. What to test, what not to test, how to test, speed and parallelism rules. Referenced by /write-tests and /fix-tests.
memory:
  tags:
    - pytest
    - vitest
    - testing
    - mock
    - fixture
    - $tech_tags
  types:
    - gotcha
    - pattern
    - solution
---

# Testing Strategy

Universal testing methodology for all projects. This is the single source of truth for testing
decisions. Updated by `/compound` and `/retrospect` when test gaps are discovered.

## Philosophy

**Test the things that would wake you up at 3am if they broke. Skip the rest.**

Tests exist to catch real bugs and protect important behavior. Not for coverage metrics,
not for checking that the framework works, not for testing types the compiler already enforces.

## What to Test

| Priority | What | Why |
|---|---|---|
| **Always** | Data transformations with non-trivial logic | Wrong output = wrong data in prod |
| **Always** | Business rules and conditional logic | Regressions here lose money or trust |
| **Always** | Database model functions with query logic | Wrong queries = data loss or leaks |
| **Always** | Authorization / access control boundaries | Security failures are catastrophic |
| **Always** | Edge cases you already handled in code | If you handled it, it matters enough |
| **Often** | Validation and error paths users can trigger | User-facing errors should be correct |
| **Often** | Integration points between modules | Contract violations cause cascading bugs |
| **Rarely** | Simple CRUD pass-throughs | Framework handles this |
| **Never** | Type-level guarantees TypeScript enforces | Compiler already tests this |
| **Never** | UI layout / styling | Visual testing is a different tool |
| **Never** | Getters, setters, trivial wrappers | No logic = nothing to break |

### The "Delete Test" Litmus Test

Before writing a test, ask: **"If this test broke, would I investigate or just update the
assertion?"** If you'd just update it, the test is testing implementation, not behavior. Skip it.

## Test Types

### Unit Tests (vitest)

**When:** Pure logic - transformers, validators, calculators, utility functions.

**File location:** Co-locate with source as `[name].test.ts` in the same directory.

**Characteristics:**
- No I/O, no database, no network
- Runs in milliseconds
- Tests one function's behavior through its public API
- Uses `faker` for test data generation, not hardcoded values

### Database Integration Tests (vitest + DB)

**When:** Model functions that contain query logic, RLS policies, soft-delete cascades,
or any database-dependent behavior.

**File location:** `tests/vitest/[feature-area]/[name].test.ts`

**Characteristics:**
- Connects to a real test database
- Uses unique prefixes/timestamps for test isolation
- Always cleans up in `afterEach`
- Tests through model functions (what the app calls), not raw queries

### E2E Tests (playwright)

**When:** Multi-step user flows where the value is testing UI + API + database integration
together. Login flows, checkout, onboarding.

**File location:** `tests/playwright/e2e/[feature].spec.ts`

**Characteristics:**
- Tests complete user journeys, not individual components
- Uses semantic locators (`getByRole`, `getByLabel`, `getByText`)
- Uses `test.step()` for logical groupings
- One user journey per test

### Browser Verification (agent-browser) - NOT Automated Testing

**When:** AI needs to visually verify a feature works, explore UI behavior, or figure out
how to write proper e2e tests.

**This is NOT test automation.** It's an AI tool for:
- Initial smoke tests to confirm a feature works
- Discovering UI elements and behavior before writing playwright tests
- Visual verification that can't be done programmatically
- Debugging UI issues with screenshots

**Never use agent-browser for CI or automated test suites.**

## Speed and Parallelism (Critical)

Tests that run slowly don't get run. Speed is a first-class requirement.

### Parallelism Rules

1. **Tests run in parallel by default.** Every test must be isolated enough to run
   concurrently with any other test.
2. **No shared mutable state.** Each test creates its own data and cleans it up.
3. **Unique identifiers for test data.** Use timestamps + random suffixes to prevent
   collisions between parallel tests.
4. **Never use `beforeAll` with mutable state.** Use `beforeEach` so each test gets
   fresh state.
5. **Use `concurrent: true`** in vitest where possible. Only use `serial` mode when
   tests genuinely depend on each other (rare).

### Speed Rules

1. **Mock external services at the boundary.** Don't hit real APIs in tests.
   Mock the HTTP client, not the business logic.
2. **Use in-memory alternatives** where possible (SQLite for simple queries, etc.)
3. **Prefer unit tests over integration tests** when the logic can be tested without I/O.
4. **Prefer API-level tests over browser tests** for verifying behavior. Browser tests
   are slow - only use them for flows that genuinely need UI interaction.
5. **Keep test setup minimal.** Only create the data each test actually needs.
6. **Avoid `waitForTimeout` in e2e.** Use `waitForSelector`, `waitForURL`,
   `waitForLoadState` - wait for conditions, not arbitrary time.
7. **Tests follow the UI, never the reverse.** When intentional UI changes (text, labels,
   structure) break E2E selectors, update the tests to match — never revert the UI to
   make tests pass.

### Test Isolation Pattern

```typescript
// Good: each test is independent
const TEST_ID = `test-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

beforeEach(async () => {
  // Create ONLY what this test needs, with unique ID
  await createTestData({ prefix: TEST_ID })
})

afterEach(async () => {
  // Clean up ONLY this test's data
  await deleteByPrefix(TEST_ID)
})
```

```typescript
// Bad: shared state between tests
let sharedUser: User // DON'T DO THIS
beforeAll(async () => {
  sharedUser = await createUser() // Tests will fight over this
})
```

## Anti-Patterns

| Anti-Pattern | Instead |
|---|---|
| Testing every function has output | Test functions where wrong output = real bug |
| Snapshot tests for data structures | Assert specific fields that matter |
| Mocking everything the function calls | Only mock external services and I/O boundaries |
| Testing private/internal functions | Test through the public API |
| Copy-pasting tests with tiny diffs | Parameterize with `it.each` or skip them |
| Testing error messages are exact strings | Test error type/category, not wording |
| `beforeAll` with shared mutable state | `beforeEach` with fresh state per test |
| `expect(result).toBeTruthy()` | `expect(result).toEqual(expectedValue)` |
| Sequential tests that share state | Isolated parallel tests |
| `waitForTimeout(5000)` in e2e | `waitForSelector` or `waitForLoadState` |
| Browser tests for API behavior | API-level integration tests |
| Assuming error behavior without reading code | Read implementation to verify: raises vs returns None vs logs |

## Test Naming

Test names are sentences that describe behavior:

```typescript
// Good
'returns empty array when no bookings match date range'
'rejects unauthorized users with 403'
'soft-deletes cascade to child records'

// Bad
'test case 1'
'handles empty input'
'works correctly'
```

## When Tests Fail: Decision Framework

Used by `/fix-tests` to determine the correct action.

### Is the Test Wrong?

The test needs fixing when:
- Test relies on implementation details that changed (mock structure, internal state)
- Test has a timing dependency (flaky)
- Test asserts an incorrect expectation
- Test uses stale fixtures/seed data
- Test has wrong setup (missing beforeEach cleanup, shared state)

### Is the Code Wrong?

The code needs fixing when:
- Test correctly describes expected behavior and the code doesn't deliver it
- A regression was introduced by recent changes
- An edge case is genuinely not handled
- The test catches a real bug

### Both Need Changing?

Sometimes:
- Requirements changed: update the test to match new requirements, verify code matches
- Test is correct but testing the wrong layer: rewrite as correct test type

## Project-Level Configuration

Each project defines in its `AGENTS.md`:
- Test runner commands (`bun run test`, `pytest`, etc.)
- Test database configuration
- Demo accounts for e2e tests
- CI configuration specifics
- Project-specific test conventions

This skill provides the universal methodology. Project specifics live in the project.

## Verification Integrity (Critical - Added from Retrospective 2026-02-11)

### Never Claim Tests Exist Without Evidence

When reporting test coverage or claiming tests pass:

1. **Cite specific file paths**: "Tests in `tests/pdf.test.ts` cover..." not "comprehensive
   tests were written"
2. **Show test output**: Include actual test runner output, not just "all tests pass"
3. **Distinguish test types**: Unit tests of a client don't verify the integration works.
   Testing that `renderPdf()` makes a fetch call doesn't prove the PDF service accepts it.

### Cross-Service Integration Must Be Verified End-to-End

For any feature involving two services:

1. **Both services must be running** during verification
2. **The full flow must be executed** (not just each half independently)
3. **The result must be observed** (e.g., a PDF file is actually downloaded, not just "no
   errors in the log")
4. **Contract compatibility must be verified** by reading the receiving service's validation
   schema (Pydantic model, Zod schema) and confirming all required fields are sent

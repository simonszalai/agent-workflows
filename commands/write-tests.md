---
description: Write sensible tests for code changes. Analyzes what matters, skips what doesn't.
---

# Write Tests Command

Write tests that catch real bugs and protect important behavior. Not coverage theater.

## Usage

```
/write-tests                        # Analyze current diff, write tests for changes
/write-tests app/models/client.ts   # Write tests for specific file
/write-tests F003                   # Write tests for a work item's changes
```

## Philosophy: Sensible Testing

**Test the things that would wake you up at 3am if they broke.** Skip the rest.

### What to Test

| Priority   | What                                         | Why                                    |
| ---------- | -------------------------------------------- | -------------------------------------- |
| **Always** | Data transformations with non-trivial logic  | Wrong output = wrong data in prod      |
| **Always** | Business rules and conditional logic         | Regressions here lose money or trust   |
| **Always** | Database model functions with query logic    | Wrong queries = data loss or leaks     |
| **Always** | Authorization / access control boundaries    | Security failures are catastrophic     |
| **Always** | Edge cases you already thought about in code | If you handled it, it matters enough   |
| **Often**  | Validation and error paths users can trigger | User-facing errors should be correct   |
| **Often**  | Integration points between modules           | Contract violations cause cascading bugs|
| **Rarely** | Simple CRUD pass-throughs                    | Framework handles this                 |
| **Never**  | Type-level guarantees TypeScript enforces    | Compiler already tests this            |
| **Never**  | UI layout / styling                          | Visual testing is a different tool      |
| **Never**  | Getters, setters, trivial wrappers           | No logic = nothing to break            |

### The "Delete Test" Litmus Test

Before writing a test, ask: **"If this test broke, would I investigate or just update the
snapshot/assertion?"** If you'd just update it, the test is testing implementation, not behavior.
Skip it.

## Process

### 1. Analyze What Changed

Determine what code needs tests:

```bash
# If testing current diff
git diff --stat HEAD
git diff HEAD -- '*.ts' '*.tsx'

# If testing a specific file
# Read the file and understand its exports

# If testing a work item
# Read the work item's plan.md and changed files
```

**Classify each changed function/module:**

- **Pure logic** (transformers, validators, calculators) -> Unit test with vitest
- **Database operations** (model functions with queries) -> Integration test with vitest + DB
- **API routes** (loaders, actions) -> Integration test or E2E depending on complexity
- **Multi-step user flows** (auth, checkout, forms) -> E2E with playwright
- **Configuration/wiring** (no logic, just connecting pieces) -> Skip unless safety-critical

### 2. Design Test Cases

For each function worth testing, identify:

**Happy path (1-2 tests):**
- The most common successful scenario
- Only test a second happy path if the function has meaningfully different branches

**Edge cases (only the ones that matter):**
- Empty/null inputs the function actually receives in production
- Boundary values where behavior changes (not arbitrary numbers)
- Error cases users can actually trigger

**Skip these:**
- Exhaustive input permutations
- Testing the same branch with slightly different values
- Negative tests for impossible inputs (trust your types)
- Testing framework behavior (Prisma queries work, React renders, etc.)

### 3. Write Tests

#### Vitest Unit Tests

**File location:** Co-locate with source as `[name].test.ts` in the same directory.

**Structure:**
```typescript
import { describe, expect, it } from 'vitest'
// Import only what you're testing
import { myFunction } from './myModule'

describe('myFunction', () => {
  it('describes the behavior, not the implementation', () => {
    // Arrange - set up inputs
    // Act - call the function
    // Assert - check the result
  })
})
```

**Rules:**
- Test names describe behavior: `'returns empty array when no bookings match date range'`
  NOT: `'test case 1'` or `'handles empty input'`
- One logical assertion per test. Multiple `expect()` calls are fine if they assert
  one conceptual thing (e.g., checking multiple fields of a returned object).
- Use `faker` for generating test data, not hardcoded magic values
- Use `consoleError` from setup when testing error paths:
  `import { consoleError } from '#tests/vitest/setup/setup-test-env.ts'`
- Use helper functions for repeated setup (define in the same file, not a shared utils file,
  unless it's genuinely reused across 3+ test files)
- Prefer `toEqual` for objects/arrays, `toBe` for primitives, `toMatchObject` for partial checks

#### Vitest Database Integration Tests

**File location:** `tests/vitest/[feature-area]/[name].test.ts`

**When to use:** Testing model functions that contain query logic, RLS policies, soft-delete
cascades, or any database-dependent behavior.

**Structure:**
```typescript
import { describe, expect, it, beforeEach, afterEach } from 'vitest'
import { PrismaClient } from '@prisma/client'

// Use a unique identifier for test isolation
const TEST_PREFIX = `test-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`

describe('Feature under test', () => {
  const prisma = new PrismaClient()

  beforeEach(async () => {
    // Create test data with unique identifiers
  })

  afterEach(async () => {
    // Clean up test data - delete by TEST_PREFIX
  })

  it('describes the database behavior being tested', async () => {
    // Test the actual model function, not raw Prisma calls
  })
})
```

**Rules:**
- Always clean up test data in afterEach
- Use unique prefixes/timestamps to avoid conflicts with parallel tests
- Test through model functions (what the app actually calls), not raw Prisma
- For RLS tests: use `systemPrisma` for setup, `testPrisma` with session vars for assertions
- Check soft-delete behavior: verify `deletedAt IS NULL` in queries

#### Playwright E2E Tests

**File location:** `tests/playwright/e2e/[feature].spec.ts`

**When to use:** Multi-step user flows where the value is testing the integration of UI +
API + database together. Not for testing individual components.

**Structure:**
```typescript
import { expect, test } from '@playwright/test'

test.describe('Feature Name', () => {
  test('describes the user journey', async ({ page }) => {
    await test.step('Navigate to starting point', async () => {
      await page.goto('/route')
      await page.waitForLoadState('networkidle')
    })

    await test.step('Perform the key action', async () => {
      await page.getByRole('button', { name: 'Submit' }).click()
    })

    await test.step('Verify the outcome', async () => {
      await expect(page.getByText('Success')).toBeVisible()
    })
  })
})
```

**Rules:**
- Use `test.step()` for logical groupings of actions
- Use semantic locators: `getByRole`, `getByLabel`, `getByText` - never CSS selectors
- Wait for `networkidle` after navigation
- Use `test.describe.configure({ mode: 'serial' })` for tests that depend on each other
- Demo accounts are defined in AGENTS.md - use those for authentication
- Keep E2E tests focused: one user journey per test, not a grab bag of assertions

### 4. Validate Test Quality

Before finishing, check each test against these criteria:

- [ ] **Does it test behavior, not implementation?** Refactoring the code shouldn't break it.
- [ ] **Would a real bug cause this test to fail?** If not, it's testing the wrong thing.
- [ ] **Is it deterministic?** No timing dependencies, random values in assertions, or timezones.
- [ ] **Is it independent?** Can run in any order, doesn't depend on other tests' side effects.
- [ ] **Is the test name a sentence?** Someone reading test output should understand what broke.

### 5. Run and Verify

```bash
# Run the specific test file
bun run test [path/to/test.test.ts]

# Run with filtering
bun run test -t "test name pattern"

# For E2E
bun run test:e2e:dev  # UI mode for debugging
```

All tests must pass. If a test is flaky on first run, fix it - don't retry and hope.

## Anti-Patterns to Avoid

| Anti-Pattern                        | Instead                                        |
| ----------------------------------- | ---------------------------------------------- |
| Testing every function has output   | Test functions where wrong output = real bug    |
| Snapshot tests for data structures  | Assert specific fields that matter              |
| Mocking everything the function calls | Only mock external services and I/O boundaries |
| Testing private/internal functions  | Test through the public API                     |
| Copy-pasting tests with tiny diffs | Parameterize with `it.each` or just skip them   |
| Testing error messages are exact strings | Test error type/category, not wording       |
| beforeAll with shared mutable state | beforeEach with fresh state per test            |
| `expect(result).toBeTruthy()`      | `expect(result).toEqual(expectedValue)`         |

## Output

After writing tests, report:

```
Tests written:
- [file path]: [what it tests] (X tests)
- [file path]: [what it tests] (X tests)

Intentionally not tested:
- [thing]: [why - e.g., "trivial CRUD wrapper", "type-enforced", "no logic"]

Run: bun run test [paths]
```

## When Called from /build

If invoked as part of a build step, write tests for the specific build_todo's changes only.
Don't test unrelated code. Match test scope to change scope.

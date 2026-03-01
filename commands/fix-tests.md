---
description: Fix failing tests. Investigates root cause, determines if test or code is wrong, makes the right fix.
skills:
  - testing-strategy
---

# Fix Tests Command

Investigate test failures, determine root cause, and fix the right thing. Sometimes the test
is wrong. Sometimes the code is wrong. Sometimes both need changing.

## Usage

```
/fix-tests                              # Fix failures from last test run
/fix-tests tests/vitest/auth/login.test.ts  # Fix specific test file
/fix-tests --ci                         # Fix CI failures (reads CI output)
/fix-tests F003                         # Fix test failures for a work item
```

## Philosophy

**Be thorough and careful.** A failing test is a signal. The worst thing you can do is
silence the signal by making the test match broken code. Investigate before fixing.

## Process

### 1. Identify Failing Tests

**From last run or specific file:**

```bash
# Run the failing tests and capture output
bun run test [path] 2>&1
```

**From CI:**

```bash
# Get CI failure output
gh run view --log-failed
```

**From work item:**

Read work item for context on what changed, then run related tests.

### 2. Categorize Each Failure

For each failing test, gather:

1. **Test name and file**
2. **Error message and stack trace**
3. **What the test expects vs what it got**
4. **When was the test last passing?** (git log on the test file)
5. **What code changed recently?** (git log on the tested code)

### 3. Root Cause Analysis

This is the critical step. For each failure, determine:

**Is the test wrong?**

The test needs fixing when:
- Test relies on implementation details that changed (mock structure, internal state)
- Test has a timing dependency (flaky)
- Test asserts an incorrect expectation
- Test uses stale fixtures or seed data
- Test has wrong setup (missing cleanup, shared state, wrong beforeEach)
- Test was never correct (copy-paste error, wrong assertion)

**Is the code wrong?**

The code needs fixing when:
- Test correctly describes expected behavior and the code doesn't deliver it
- A regression was introduced by recent changes
- An edge case is genuinely not handled
- The test is catching a real bug

**Do both need changing?**

Sometimes:
- Requirements changed: update test to match new requirements, verify code matches
- Test is correct but testing at wrong layer: rewrite as correct test type
- Test and code both have bugs in different areas

### 4. Investigate Before Fixing

**Read the test thoroughly.** Understand what behavior it's protecting.

**Read the code under test.** Understand the current behavior and recent changes.

**Check git history:**

```bash
# When did this test last pass?
git log --oneline -10 [test-file]

# What changed in the tested code?
git log --oneline -10 [source-file]
git diff HEAD~5 -- [source-file]
```

**Check for pattern violations:**

```bash
# Shared mutable state?
grep -n "beforeAll" [test-file]
grep -n "let.*:" [test-file] | head -20

# Timing dependencies?
grep -n "waitForTimeout\|setTimeout\|sleep" [test-file]

# Missing cleanup?
grep -n "afterEach\|afterAll" [test-file]
```

### 5. Apply the Fix

**If the test is wrong:**

1. Fix the test to correctly describe expected behavior
2. Ensure the fix follows testing-strategy skill patterns:
   - Unique identifiers for test isolation
   - `beforeEach` not `beforeAll` for mutable state
   - Condition-based waits, not timeouts
   - Behavior assertions, not implementation assertions
3. Run the test to confirm it passes
4. Run the full suite to confirm no regressions

**If the code is wrong:**

1. Fix the code bug
2. Run the failing test to confirm it passes
3. Run the full suite to confirm no regressions
4. Consider: should there be additional tests for related edge cases?

**If both need changing:**

1. Fix the code first (to match correct behavior)
2. Update the test to match new requirements
3. Run everything

### 6. Fix Parallelism Issues

If tests fail intermittently or only when run together:

1. **Check for shared state:** Look for `beforeAll` with mutable variables, shared database
   records, global singletons
2. **Check for ordering dependencies:** Run the failing test in isolation - if it passes
   alone but fails with others, it has a dependency
3. **Check for resource conflicts:** Same database records, same ports, same file paths
4. **Fix:** Add unique identifiers, use `beforeEach`, ensure proper cleanup in `afterEach`

### 7. Verify the Fix

```bash
# Run the specific test
bun run test [path]

# Run 3 times to check for flakiness
bun run test [path] && bun run test [path] && bun run test [path]

# Run full suite for regression check
bun run test
```

### 8. Report Testing Strategy Gaps

If the failure revealed a gap in the testing approach (missing pattern, unclear guidance,
new anti-pattern discovered), note it for `/compound` to pick up:

```
Testing strategy gap found:
- [What the gap is]
- [What test scenario was missing]
- [What guidance should be added to testing-strategy skill]
```

This feeds into the `/compound` learning loop which updates the testing-strategy skill.

## Speed Considerations

When fixing tests, also look for speed improvements:

- Replace `waitForTimeout` with condition-based waits
- Replace unnecessary integration tests with unit tests
- Remove redundant setup (creating data the test doesn't need)
- Add `concurrent: true` where tests are properly isolated
- Mock external services that are being hit in tests

## Output

```
Test fixes applied:

Fixed (test was wrong):
- [test file]: [what was wrong, what was fixed]

Fixed (code was wrong):
- [source file]: [what bug was found, how it was fixed]

Fixed (both):
- [test + source]: [what changed and why]

Remaining failures: [N or "none"]

Testing strategy gaps: [gaps found, or "none"]

Run: bun run test [paths]
```

## When Called from /build or /auto-build

If tests fail during a build step:
1. Attempt automatic fix (up to 2 retries)
2. If the fix requires code changes beyond the test, flag it
3. Log details and continue to review phase if still failing

## When Called from CI

Parse the CI output to identify:
- Which tests failed
- On which platform/environment
- Whether the failure is environment-specific (works locally, fails in CI)

Environment-specific failures often point to:
- Missing environment variables
- Database state differences
- Timing issues (CI is slower)
- Missing dependencies or different versions

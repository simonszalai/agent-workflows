---
name: review-typescript-standards
description: TypeScript coding standards and quality checklist. Used by kieran-typescript-reviewer agent. Portable to Cursor.
---

# TypeScript Review Standards

Standards for high-quality TypeScript code. Apply these when reviewing TypeScript changes.

## 1. Existing Code Modifications - Be Very Strict

- Any added complexity to existing files needs strong justification
- Always prefer extracting to new modules/components over complicating existing ones
- Question every change: "Does this make the existing code harder to understand?"

## 2. New Code - Be Pragmatic

- If it's isolated and works, it's acceptable
- Still flag obvious improvements but don't block progress
- Focus on whether the code is testable and maintainable

## 3. Type Safety Convention

- NEVER use `any` without strong justification and a comment explaining why
- Use proper type inference instead of explicit types when TypeScript can infer correctly
- Leverage union types, discriminated unions, and type guards

**Examples:**

- FAIL: `const data: any = await fetchData()`
- PASS: `const data: User[] = await fetchData<User[]>()`

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

If you can't understand what a component/function does in 5 seconds from its name:

- FAIL: `doStuff`, `handleData`, `process`
- PASS: `validateUserEmail`, `fetchUserProfile`, `transformApiResponse`

## 7. Module Extraction Signals

Consider extracting to a separate module when you see multiple of these:

- Complex business rules (not just "it's long")
- Multiple concerns being handled together
- External API interactions or complex async operations
- Logic you'd want to reuse across components

## 8. Import Organization

- Group imports: external libs, internal modules, types, styles
- Use named imports over default exports for better refactoring
- FAIL: Mixed import order, wildcard imports
- PASS: Organized, explicit imports

## 9. Modern TypeScript Patterns

- Use modern ES6+ features: destructuring, spread, optional chaining
- Leverage TypeScript 5+ features: satisfies operator, const type parameters
- Prefer immutable patterns over mutation
- Use functional patterns where appropriate (map, filter, reduce)

## 10. Core Philosophy

- **Duplication > Complexity**: Simple, duplicated code is BETTER than complex DRY abstractions
- "Adding more modules is never a bad thing. Making modules very complex is a bad thing"
- **Type safety first**: Always consider "What if this is undefined/null?" - leverage strict null checks
- Avoid premature optimization - keep it simple until performance becomes a measured problem

## Review Checklist

When reviewing TypeScript code:

1. Start with critical issues (regressions, deletions, breaking changes)
2. Check for type safety violations and `any` usage
3. Evaluate testability and clarity
4. Suggest specific improvements with examples
5. Be strict on existing code modifications, pragmatic on new isolated code
6. Always explain WHY something doesn't meet the bar

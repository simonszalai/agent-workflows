---
description: Add a new test path to the browser testing library. Interactive wizard to create well-structured tests.
---

# Test Add Command

Add a new browser test path to the library with guided creation.

## Usage

```
/test-add                           # Interactive mode
/test-add "Login with SSO"          # Create with name
/test-add login-sso critical        # Create with name and importance
```

## Process

### 1. Gather Test Information

Ask user for (if not provided):

- **Test name:** Human-readable name (e.g., "Login Flow")
- **Importance:** critical / important / regular
- **Starting route:** The initial URL path
- **User role:** Who performs this test
- **Brief description:** What does this test verify?

### 2. Generate File Name

Convert test name to kebab-case:

- "Login with SSO" -> `login-with-sso.md`
- "Client Creation" -> `client-creation.md`

### 3. Create Test File

Use template from `test-paths/templates/test-path.md` (if exists) or use default:

```markdown
---
name: [Test Name]
importance: [level]
route: [starting route]
roles: [roles array]
preconditions:
  - Database seeded
postconditions:
  - [expected end state]
tags: [derived from name/description]
status: active
created: [today's date]
---

# [Test Name]

[Brief description]

## Preconditions

- [ ] Database seeded (run project's seed command)
- [ ] Dev server running
- [ ] Logged in as: [appropriate user]

## Steps

### Step 1: [First Action]

**Action:**
```

Navigate to [route]

```

**Expected:**
- Page loads without errors

[... additional steps to be filled in ...]

## Postconditions

- [ ] [Expected end state]
```

### 4. Save and Report

Save to: `test-paths/[importance]/[filename].md`

Report:

```
Created: test-paths/critical/login-with-sso.md

Next steps:
1. Edit the file to add detailed steps
2. Add SQL assertions for data verification
3. Test with: /test-run test-paths/critical/login-with-sso.md
```

### 5. Update Index (Optional)

Add entry to `test-paths/INDEX.md` test inventory table (if exists).

## Interactive Prompts

When running without arguments:

1. "What should this test be called?"
2. "What importance level?" (critical/important/regular)
3. "What route does this test start from?"
4. "What user role performs this test?"
5. "Brief description of what this verifies:"

## Template Sections

The generated test includes:

- **Frontmatter:** Metadata for filtering/organizing
- **Description:** What the test verifies
- **Preconditions:** Required state before test
- **Steps:** Numbered actions with expected outcomes
- **SQL Assertions:** Database verification queries
- **Postconditions:** Expected state after test
- **Cleanup:** SQL to reset test data

## Examples

**Quick creation:**

```
/test-add "Logout Flow" important
```

Creates: `test-paths/important/logout-flow.md`

**Full interactive:**

```
/test-add
> Test name: Password Reset
> Importance: critical
> Starting route: /forgot-password
> User role: guest
> Description: Verifies password reset email flow
```

Creates: `test-paths/critical/password-reset.md`

## Validation

Before creating, verify:

- [ ] Test name is unique (no existing file with same name)
- [ ] Importance level is valid
- [ ] Route format is valid (starts with /)

## Output

- Created test file path
- Instructions for completing the test
- Command to run the new test

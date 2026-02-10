---
name: retrospect-methodology
description: Post-incident analysis methodology for identifying workflow gaps. Used by retrospector agent.
---

# Retrospect Methodology

Standards for conducting post-incident retrospectives to identify gaps in the development workflow
that allowed bugs or issues to reach production.

## Purpose

When a bug reaches production, the goal is NOT just to fix it, but to understand:

1. **Where the workflow failed** - Which stage should have caught this?
2. **Why it failed** - What was missing from that stage?
3. **How to prevent recurrence** - What to add to the workflow?

## Workflow Stages to Analyze

Examine each stage in reverse order (closest to production first):

| Stage                   | Artifact               | Key Questions                               |
| ----------------------- | ---------------------- | ------------------------------------------- |
| Production Verification | verification-report.md | Did we verify the right scenarios?          |
| Local Verification      | (test output)          | Were integration tests sufficient?          |
| Review                  | review_todos/          | Did reviewers check the right dimensions?   |
| Implementation          | git diff, code         | Did code match plan? Quality issues?        |
| Build Todos             | build_todos/           | Were implementation steps complete?         |
| Plan                    | plan.md                | Did plan identify edge cases/constraints?   |
| Investigation (bugs)    | investigation.md       | Was root cause analysis thorough?           |
| Knowledge               | .claude/knowledge/     | Should there be a gotcha/reference/pattern? |

## Gap Categories

### 1. Plan Gap

**Symptoms:**

- Plan didn't identify the constraint that caused the bug
- Plan didn't research relevant existing patterns
- Plan missed important edge cases or scenarios

**Questions:**

- Was there a plan.md? If not, that's the gap
- Did the plan mention the area where the bug occurred?
- Did the plan research similar implementations?
- Were there edge cases the plan should have identified?

### 2. Build Todos Gap

**Symptoms:**

- Build todos didn't specify how to handle the failing case
- Missing verification steps in build todos
- No reference to relevant knowledge/gotchas

**Questions:**

- Were there build_todos? If not, that's the gap
- Did build todos include verification steps?
- Did build todos reference similar patterns in codebase?
- Should there have been a specific step for the bug area?

### 3. Implementation Gap

**Symptoms:**

- Code doesn't match what plan/build_todos specified
- Missing error handling, edge case handling
- Tests missing or inadequate

**Questions:**

- Did implementation follow the plan?
- Are there obvious code quality issues?
- Are tests present and covering the right scenarios?
- Did the implementer skip or misunderstand a build todo?

### 4. Review Gap

**Symptoms:**

- Reviewers didn't flag the issue
- Wrong review dimensions applied
- Review coverage incomplete

**Questions:**

- Was there a /review? If not, that's the gap
- Did review_todos exist for the affected area?
- Which review dimension should have caught this?
- Was reviewer context incomplete?

### 5. Local Verification Gap

**Symptoms:**

- Bug would have been caught with proper local testing
- Integration tests missing
- Test data didn't match production scenarios

**Questions:**

- Was local testing done before deployment?
- Were integration tests run?
- Did test data cover the failing scenario?
- Was verifier-local used?

### 6. Production Verification Gap

**Symptoms:**

- Bug occurred after /verify-prod passed
- Verification didn't check the failing scenario
- Verification criteria incomplete

**Questions:**

- Was /verify-prod run? If not, that's the gap
- Did verification-report.md cover the bug area?
- What verification step would have caught this?
- Was monitoring/alerting set up?

### 7. Knowledge Gap

**Symptoms:**

- A gotcha that should have been documented
- A pattern that wasn't in references
- A solution to a known issue that wasn't captured

**Questions:**

- Is this a recurring issue? - Add gotcha
- Is this a pattern others should know? - Add reference
- Is this a solution worth capturing? - Add solution

## Analysis Process

1. **Gather context**
   - Find the work item (if exists)
   - Read all artifacts: plan.md, build_todos/, review_todos/, etc.
   - Get git history for related commits
   - Read the bug report or incident description

2. **Trace the bug**
   - What is the bug? Be specific
   - When was it introduced? (git blame)
   - What feature/change introduced it?

3. **Analyze each stage**
   - For each stage, ask: "Should this stage have prevented the bug?"
   - If yes, identify specifically what was missing
   - Rate the gap severity: primary (main cause), contributing, or not applicable

4. **Identify root cause gap**
   - Usually ONE stage is the primary failure point
   - Other gaps may be contributing factors
   - Focus recommendations on the primary gap

5. **Recommend improvements**
   - Concrete additions to workflow artifacts
   - New knowledge docs if needed
   - Process changes if pattern is recurring

## Output Template

Use the template at `templates/retrospective.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Evidence Quality

**Strong evidence for workflow gap:**

- Artifact exists but doesn't mention the bug area at all
- Step that should have verification was skipped
- Known pattern not applied despite documentation existing
- Clear mismatch between plan and implementation

**Weak evidence (need more investigation):**

- Artifact partially covers the area
- Hard to say if verification would have caught it
- Edge case that's genuinely hard to predict

## Gap Severity Levels

| Severity  | Definition                                           |
| --------- | ---------------------------------------------------- |
| PRIMARY   | This gap directly caused the bug to escape detection |
| SECONDARY | This gap contributed but wasn't the main cause       |
| N/A       | This stage wouldn't have caught this type of bug     |

## Common Patterns

**"No plan" pattern:**

- Work was done ad-hoc without /plan
- Fix: Enforce planning for non-trivial changes

**"Untested edge case" pattern:**

- Happy path tested, edge case not
- Fix: Add edge case checklist to verification

**"Misunderstood requirement" pattern:**

- Plan captured wrong understanding
- Fix: Better requirement clarification in source.md

**"Rushed review" pattern:**

- Review done but not thorough
- Fix: Ensure right review dimensions applied

**"Missing gotcha" pattern:**

- Known pitfall not documented
- Fix: Add to .claude/knowledge/gotchas/

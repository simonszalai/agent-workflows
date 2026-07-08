# Plan: [Title]

## The Ask

[The user's request restated in one or two plain sentences, in their vocabulary. If this
plan's scope differs from the literal ask (broader, narrower, different deliverable), state
the difference explicitly here — never let the reader discover it in the build.]

**Scope split:** [If the request bundles separable concerns, name each piece and which one
this plan covers; recommend separate tickets for the rest. Otherwise "None — single concern."]

## Summary

[2-3 sentences describing what we're building and why this approach was chosen]

## Feasibility / Domain Fit

[The core mechanism assumption this plan rests on (e.g. "a script can transform these
one-shot", "this is batchable", "the data exists at that pipeline stage") and the evidence
it holds in this domain. If the mechanism is unverified, it belongs in Open Questions as a
build-blocking item, not silently assumed here.]

## First-Principles Analysis

### Fundamental Goal

[What user outcome matters? Strip away implementation details to the core need]

### Constraints Examined

| Constraint | Classification | Decision |
| ---------- | -------------- | -------- |
| [constraint] | Physical/Mathematical/Regulatory/Convention/Precedent/Assumption | Keep/Eliminate: [why] |

### What We're NOT Building

[Explicitly list features/scope that were considered but eliminated. Be specific about what you
chose NOT to include and why - this prevents scope creep and documents intentional simplicity]

- **[Feature/Scope]:** [Why it's excluded]

## What We're Building

[High-level description of the solution. Focus on the architecture and design, not implementation
details. Answer: What will exist after this is done that doesn't exist now?]

## How It Works

[Describe the approach at an architectural level. How do the pieces fit together? What's the
flow of data or control? No invented code — snippets only as citations of existing canonical
patterns with file:line references. Implementation detail comes in build_todo artifacts.]

<!-- Use ONE of the following sections based on work type -->

## Codebase Research (for features)

> Delete this section for bugs - use Investigation Summary instead.

### Existing Patterns

| Pattern   | Where Used | How It Applies               |
| --------- | ---------- | ---------------------------- |
| [pattern] | [location] | [relevance to this solution] |

### Integration Points

| Component       | How We'll Integrate              |
| --------------- | -------------------------------- |
| [existing code] | [how new feature connects to it] |

### Conventions to Follow

- [Convention 1 from codebase]
- [Convention 2 from codebase]

## Investigation Summary (for bugs)

> Delete this section for features - use Codebase Research instead.

### Root Causes (from the investigation artifact)

| #   | Root Cause | Severity | How We'll Address |
| --- | ---------- | -------- | ----------------- |
| 1   | [cause]    | [level]  | [approach]        |

### Affected Components

- [Component 1]: [how it's affected]
- [Component 2]: [how it's affected]

## Assumptions

[Every unverified claim about the codebase, data, or infrastructure is an assumption. List each
one explicitly so reviewers and build planning can check them.]

- [Assumption 1]
- [Assumption 2]

## Tradeoffs

[What are we optimizing for? What are we sacrificing?]

### Chosen Approach

- **Optimizing for:** [speed/simplicity/flexibility/reliability/etc.]
- **Accepting:** [complexity/performance cost/limited scope/etc.]

### Alternatives Considered

| Alternative | Pros       | Cons        | Why Not Chosen         |
| ----------- | ---------- | ----------- | ---------------------- |
| [approach]  | [benefits] | [drawbacks] | [reason for rejection] |

## Side Effects

[What else in the system will be affected by this change?]

- **[Component/Flow]:** [How it's affected]
- **[Data/State]:** [What changes]

## Risks

| Risk   | Likelihood   | Impact   | Mitigation      |
| ------ | ------------ | -------- | --------------- |
| [risk] | Low/Med/High | [impact] | [how to handle] |

## Open Questions

### Q: [Question that needs answering before implementation]

**A:** [Answer or "TBD - will resolve during build planning"]

## Verification Strategy

**Complexity:** [simple | moderate | complex]
**Verification Type:** [none | production | local | local+ui]

### How to Verify

[Describe how we'll know this works. What behavior should we observe? Name at least one
reproducible observation per environment (staging and production).]

### Test Scenarios

| Scenario              | Expected Behavior   |
| --------------------- | ------------------- |
| [happy path]          | [expected outcome]  |
| [edge case if needed] | [expected handling] |

## Success Criteria

[What does "done" look like? How do we measure success?]

- [ ] [Criterion 1]
- [ ] [Criterion 2]

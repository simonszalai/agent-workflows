---
name: first-principles
description: Constraint analysis and elimination. Questions existence before optimization. Core rule - don't optimize what should not exist.
---

# First-Principles Thinking

**Core Rule: Don't optimize what should not exist.**

Before improving, extending, or fixing anything, ask: should this exist at all?

## The Constraint Hierarchy

When analyzing any requirement, constraint, or existing code, classify it:

| Level | Type                      | Treatment                                   |
| ----- | ------------------------- | ------------------------------------------- |
| 1     | **Physical law**          | Accept - cannot be violated                 |
| 2     | **Mathematical necessity**| Accept - logically required                 |
| 3     | **Regulatory requirement**| Verify, then accept - may be misunderstood  |
| 4     | **Social convention**     | Challenge - often disguised as requirement  |
| 5     | **Historical precedent**  | Challenge - "we've always done it this way" |
| 6     | **Personal assumption**   | Eliminate - not a real constraint           |

**Rule:** Treat assumptions as guilty until proven real. Most constraints are levels 4-6.

## Application to Planning

Before designing a solution:

1. **State the fundamental goal** - What outcome matters? Strip away implementation details
2. **List all assumed constraints** - What limits the solution space?
3. **Classify each constraint** - Which level? Be ruthless
4. **Eliminate fake constraints** - Remove levels 4-6 unless justified
5. **Rebuild from fundamentals** - What's the simplest path to the goal?

### Questions to Ask

- Why does this feature exist? What user outcome does it serve?
- Why this approach? What if we did the opposite?
- Why these components? Could fewer pieces accomplish the same goal?
- Why this complexity? What's forcing it?
- What would a new engineer question here?

### Red Flags in Plans

- "We need this for future flexibility" - YAGNI violation
- "This follows the existing pattern" - Pattern may be wrong
- "We've always done it this way" - Historical precedent, not physics
- "The spec says to do X" - Spec may be wrong; question it
- "Users expect this" - May be assumption; verify

## Application to Review

When reviewing code, ask about every component:

1. **Should this exist?** - If deleted, what breaks?
2. **Should this be here?** - Is this the right location?
3. **Should this be this complex?** - What's forcing the complexity?
4. **Should this follow this pattern?** - Is the pattern itself correct?

### Review Questions

For each file/function/class:

- What happens if we delete this entirely?
- What's the simplest thing that could work?
- Why is this abstraction necessary?
- Who actually uses this flexibility?
- Is this solving a real problem or an imagined one?

### Severity Escalation

| Finding                                    | Severity |
| ------------------------------------------ | -------- |
| Code exists that serves no current purpose | p1       |
| Abstraction without multiple consumers     | p2       |
| Complexity without clear forcing function  | p2       |
| Pattern followed blindly without benefit   | p3       |

## The Elimination Checklist

Before adding anything, verify:

- [ ] **Necessity proven** - Can't achieve goal without it
- [ ] **Alternatives exhausted** - Simpler approaches won't work
- [ ] **Complexity justified** - Each element earns its existence
- [ ] **No speculation** - Solves today's problem, not tomorrow's maybe

Before keeping existing code:

- [ ] **Currently used** - Not "might be used someday"
- [ ] **Actively needed** - Removing breaks something real
- [ ] **Simplest form** - Can't be reduced further

## Orders of Magnitude Thinking

Don't optimize incrementally. Ask:

- Can we eliminate this entirely? (100% reduction)
- Can we reduce by 10x? (90% reduction)
- Only then: Can we reduce by 2x? (50% reduction)

**Never optimize at the margin until elimination is ruled out.**

## Output Integration

### For Planners

Add to plan.md:

```markdown
## First-Principles Analysis

### Fundamental Goal
[What outcome matters, stripped of implementation]

### Constraints Examined
- [Constraint]: [Classification] - [Keep/Eliminate and why]

### What We're NOT Building
[Explicitly list eliminated scope - features that could exist but shouldn't]
```

### For Reviewers

Add to findings:

```markdown
## Existence Findings

- [p1/p2] path:line - [Component] should not exist: [reason]
- [p2] path:line - [Abstraction] has no current justification: [evidence]
```

## Key Mantras

- The best code is no code
- The best feature is the one you don't build
- The best optimization is elimination
- Complexity is a cost, not a feature
- Every line is a liability until proven otherwise

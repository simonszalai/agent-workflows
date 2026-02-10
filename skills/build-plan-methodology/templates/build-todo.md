---
status: pending | in_progress | complete
step: NN
depends_on: []
---

# [Step Title]

## Objective

[1-2 sentences: What does this step accomplish?]

## Discovered Patterns

<!-- REQUIRED: Document all patterns found during research that apply to this step -->

**From knowledge base:**

- `.claude/knowledge/gotchas/xxx.md`: [How this gotcha applies to this step]
- `.claude/knowledge/references/xxx.md`: [Standard to follow]
- `.claude/knowledge/solutions/xxx.md`: [Past solution that informs this step]

**From codebase:**

- `src/path/file.py:123`: [Pattern to follow - describe what it does]
- `src/path/other.py:45`: [Convention to match]

**From git history:**

- Commit `abc123`: [Context on why code exists this way]
- Past issue: [What to avoid based on history]

**From CLAUDE.md:**

- [Specific rule]: [How to comply in this step]

## Files to Modify

| File                  | Change                  | Lines |
| --------------------- | ----------------------- | ----- |
| `src/path/to/file.py` | [description of change] | ~NN   |

## Implementation Details

[Detailed description of what to do. Code snippets MUST follow the discovered patterns above:]

```python
# Following pattern from src/path/file.py:123
# Example of what to add/change
```

## Tests

- [ ] [Test case 1 - following test patterns from tests/...]
- [ ] [Test case 2]

## Verification

```bash
# Commands to verify this step worked
uv run ruff check src/path/
uv run --active pyrefly check
```

## Completion Notes

<!-- Filled by /build when step is completed -->

**Completed:** YYYY-MM-DD
**Actual changes:**

- [what was actually done]

**Pattern deviations:**

- [any cases where discovered patterns couldn't be followed and why]

**Issues encountered:**

- [any problems and how they were resolved]

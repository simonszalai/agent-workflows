---
status: pending
source: [agent-name]
priority: p1 | p2 | p3
---

# Decision

**Action:** accept
**Notes:**

---

# [Finding Title]

## Finding

[What the review agent identified as an issue or improvement opportunity]

## Current Code

```python
# File: src/path/to/file.py:NN-MM
[current code snippet]
```

## Suggested Fix

```python
# Proposed change
[suggested code]
```

## Files

| File                  | Lines | Issue               |
| --------------------- | ----- | ------------------- |
| `src/path/to/file.py` | NN-MM | [brief description] |

## Impact

| Aspect          | Assessment                  |
| --------------- | --------------------------- |
| Complexity      | [reduces/increases/neutral] |
| Performance     | [improves/degrades/neutral] |
| Maintainability | [improves/degrades/neutral] |

## Process Improvement Recommendations

How to prevent similar issues in future work items:

### Plan Phase

**What the plan should have identified:**
[e.g., "Plan should have researched existing error handling patterns in similar flows"]

**Suggested addition to plan checklist:**
[e.g., "When planning database changes, verify existing constraint naming conventions"]

### Build Todos Phase

**What research should have been done:**
[e.g., "Should have searched .claude/knowledge/gotchas/ for async patterns before implementation"]

**Suggested pattern to include:**
[e.g., "Build todo should reference similar implementations like src/flows/example/task.py"]

### Build Phase

**What verification was missing:**
[e.g., "Should have run integration tests against staging data before marking complete"]

**Suggested check to add:**
[e.g., "Verify type hints match Pydantic model fields"]

---

## Resolution Notes

[Filled during /resolve-review]

**Resolved:** YYYY-MM-DD
**Action taken:**

- [what was actually done based on decision]

**Learnings:**

- [anything worth documenting via compound]

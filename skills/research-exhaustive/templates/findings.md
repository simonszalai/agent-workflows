# Research Findings

**Question:** {original_question}
**Date:** {YYYY-MM-DD}
**Files searched:** {total_file_count}

## Summary

{3-5 sentence overview of what was found across all partitions. Include:}
{- Main patterns discovered}
{- Key inconsistencies identified}
{- Overall assessment}

## Patterns Found

### Pattern 1: {pattern_name}

**Occurrences:** {count}
**Locations:**

| File           | Line | Description         |
| -------------- | ---- | ------------------- |
| `path/file.py` | 123  | {brief description} |
| `path/file.py` | 456  | {brief description} |

**Implementation:**

```python
# Representative code example showing this pattern
{code_snippet}
```

**Notes:** {when to use this pattern, any caveats}

### Pattern 2: {pattern_name}

**Occurrences:** {count}
**Locations:**

| File           | Line | Description         |
| -------------- | ---- | ------------------- |
| `path/file.py` | 789  | {brief description} |

**Implementation:**

```python
{code_snippet}
```

**Notes:** {when to use this pattern}

## Inconsistencies Found

### Inconsistency 1: {brief_title}

**Description:** {what the inconsistency is - different approaches to the same problem}

**Approach A:** (used in {N} files)

| File       | Line | Code                            |
| ---------- | ---- | ------------------------------- |
| `file1.py` | 100  | `example of approach A`         |
| `file2.py` | 150  | `another example of approach A` |

**Approach B:** (used in {N} files)

| File       | Line | Code                            |
| ---------- | ---- | ------------------------------- |
| `file3.py` | 200  | `example of approach B`         |
| `file4.py` | 250  | `another example of approach B` |

**Impact:** {why this inconsistency matters - maintenance burden, potential bugs, confusion}

**Recommendation:** {which approach should be standardized, or if both are valid}

### Inconsistency 2: {brief_title}

...

## Statistics

| Partition | Files | Matches | Patterns | Inconsistencies |
| --------- | ----- | ------- | -------- | --------------- |
| flows     | {N}   | {N}     | {N}      | {N}             |
| infra     | {N}   | {N}     | {N}      | {N}             |
| models    | {N}   | {N}     | {N}      | {N}             |
| database  | {N}   | {N}     | {N}      | {N}             |
| meta      | {N}   | {N}     | {N}      | {N}             |
| other     | {N}   | {N}     | {N}      | {N}             |
| **Total** | {N}   | {N}     | {N}      | {N}             |

## Recommendations

Based on the research findings:

1. **{recommendation_1}**: {description}
2. **{recommendation_2}**: {description}
3. **{recommendation_3}**: {description}

## Raw Partition Reports

See individual files for detailed partition findings:

- `partition-flows.md` - Flow and task patterns
- `partition-infra.md` - Infrastructure patterns
- `partition-models.md` - Model and prompt patterns
- `partition-database.md` - Migration patterns
- `partition-meta.md` - Documentation patterns
- `partition-other.md` - Test and script patterns

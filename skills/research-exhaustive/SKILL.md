---
name: research-exhaustive
description: Exhaustive codebase search methodology. Ensures complete coverage of every file in a partition. Used by pattern-researcher agent.
---

# Exhaustive Research Methodology

Standards for conducting **complete** searches across a codebase partition. The goal is to find
**every single occurrence** of a pattern, not just representative samples.

## Core Principle: No Sampling

Unlike investigative searches that sample relevant areas, exhaustive research must:

1. **List all files first** - Know exactly what needs to be searched
2. **Search every file** - No skipping based on "relevance"
3. **Report all matches** - Even duplicates or trivial ones
4. **Track coverage** - Prove that every file was checked

## Search Methodology

### Step 1: Enumerate Files

Before searching, list all files in your partition:

```bash
# Example for flows partition
find src/flows src/automations -type f -name "*.py" | wc -l
find src/flows src/automations -type f -name "*.py"
```

Record the count - you'll report this at the end.

### Step 2: Multi-term Search

For the research question, identify multiple search terms:

| Question                     | Search Terms                                                   |
| ---------------------------- | -------------------------------------------------------------- |
| "how is error handling done" | `try`, `except`, `raise`, `Error`, `Exception`                 |
| "database connections"       | `session`, `connection`, `engine`, `database`, `db`            |
| "raw SQL vs SQLAlchemy"      | `text(`, `execute`, `select(`, `raw`, `SQL`                    |
| "validation patterns"        | `validate`, `validator`, `@field_validator`, `ValidationError` |

Search for EACH term separately using Grep tool:

```python
# Search each term
Grep(pattern="try:", path="src/flows/")
Grep(pattern="except", path="src/flows/")
Grep(pattern="raise", path="src/flows/")
```

### Step 3: Context Reading

For each match, read surrounding context to understand:

- What pattern is being used
- Is it consistent with other occurrences
- Any variations or inconsistencies

Use the Read tool with specific line ranges for detailed analysis.

### Step 4: Pattern Classification

Group findings into patterns:

**Pattern types:**

- **Standard pattern**: The most common approach (document what it looks like)
- **Variant**: Slight variations that might be intentional
- **Inconsistency**: Different approaches to the same problem (flag for review)
- **Edge case**: Unusual usage that might need attention

### Step 5: Coverage Verification

At the end, verify complete coverage:

```bash
# Count files searched
find [partition_paths] -type f -name "*.py" | wc -l

# Compare to files with matches
# Should account for all files (match or explicitly no match)
```

## Output Format

```markdown
## Partition: [name]

### Coverage

- **Files in partition:** N
- **Files with matches:** N
- **Files without matches:** N (verified no relevant code)

### Search Terms Used

- `term1` - N matches
- `term2` - N matches
- `term3` - N matches

### All Matches

#### Pattern A: [name] (N occurrences)

| File           | Line | Code Snippet |
| -------------- | ---- | ------------ |
| `path/file.py` | 123  | `snippet...` |
| `path/file.py` | 456  | `snippet...` |

**Description:** [how this pattern works]

#### Pattern B: [name] (N occurrences)

...

### Inconsistencies Found

#### Inconsistency 1: [description]

| File       | Line | Approach           |
| ---------- | ---- | ------------------ |
| `file1.py` | 100  | Uses try/except    |
| `file2.py` | 200  | Uses if/else check |

**Impact:** [why this matters]

### Summary

[2-3 sentences summarizing what was found in this partition]
```

## Quality Checklist

Before submitting findings:

- [ ] All files in partition enumerated
- [ ] Each search term run separately
- [ ] Every match recorded with file:line
- [ ] Patterns classified and named
- [ ] Inconsistencies flagged with both examples
- [ ] Coverage numbers match (files searched = files in partition)

## Common Mistakes

**DON'T:**

- Skip files that "probably don't have it"
- Report only "interesting" findings
- Summarize without listing specific locations
- Forget to search for variant spellings/terms

**DO:**

- Search mechanically through every file
- Report even trivial or duplicate matches
- Include file:line for EVERY occurrence
- Note when a file was searched but had no matches

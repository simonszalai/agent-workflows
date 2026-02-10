---
name: research
description: Research output format, zone partitioning, and synthesis methodology. Used by research orchestrator.
---

# Research Methodology

Standards for conducting **exhaustive codebase research** and producing research.md files.

## Scope

**Use for:** Understanding implementations, finding patterns, auditing for consistency
**NOT for:** Bugs (use `/investigate`), new features (use `/plan`)

## Critical Requirement: Complete Coverage

Research MUST be exhaustive. Every relevant file must be examined. This is achieved through:

1. **Zone partitioning** - Codebase divided into non-overlapping zones
2. **Parallel agents** - One agent per zone, all running simultaneously
3. **Explicit file lists** - Agents must enumerate files they searched
4. **Coverage verification** - Synthesis checks all zones were covered

## Zone Definitions

| Zone       | Glob Pattern                                 | Contents                      |
| ---------- | -------------------------------------------- | ----------------------------- |
| Routes     | `app/routes/**/*.{ts,tsx}`                   | Loaders, actions, page views  |
| Components | `app/components/**/*.{ts,tsx}`               | UI components, local hooks    |
| Models     | `app/models/**/*.{ts,tsx}`                   | Database access, Prisma       |
| Core       | `app/lib/**`, `app/hooks/**`, `app/types/**` | Utils, hooks, type defs       |
| Config     | `*.config.*`, `prisma/**`, `.claude/**`      | Project configuration         |

## Sub-Agent Behavior (CRITICAL)

**Zone agents must:**

- **Search EVERY file** in their assigned zone - no sampling
- **Document file count** - "Searched X files in zone Y"
- **List every occurrence** of the pattern being researched
- **Note variations** between files
- **Return findings directly** - do NOT create files
- The orchestrator synthesizes all findings into a single research.md

## Agent Output Format

Each zone agent returns:

```markdown
## Zone: {zone_name}

**Files searched:** {count}
**Files with matches:** {count}

### Occurrences

#### {file_path}:{line_number}
```{language}
{code snippet}
```
**Pattern variant:** {description of how this implements the pattern}
**Notes:** {any issues or variations}

#### {file_path}:{line_number}
...

### Zone Summary

- **Dominant pattern:** {most common implementation}
- **Variations found:** {count}
- **Potential issues:** {list}

### Questions for Synthesis

- {questions about patterns that need cross-zone context}
```

## Synthesis Methodology

When combining findings from zone agents:

1. **Verify coverage** - Confirm all zones reported, check file counts
2. **Catalog patterns** - Group similar implementations
3. **Identify dominant pattern** - What's most common across zones
4. **Flag inconsistencies** - Where does implementation differ
5. **Rank by impact** - Which inconsistencies matter most
6. **Recommend standardization** - Suggest which pattern to adopt

## Inconsistency Severity

| Severity | Definition                                           |
| -------- | ---------------------------------------------------- |
| HIGH     | Could cause bugs, data loss, or security issues      |
| MEDIUM   | Makes code harder to maintain, confusing             |
| LOW      | Cosmetic, style preference, minor deviation          |

## Output Template

Use the template at `templates/research.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Research Process

1. **Understand topic** - What pattern/implementation to research
2. **Spawn zone agents** - All 5 zones in parallel
3. **Collect findings** - Wait for ALL agents
4. **Verify coverage** - Check file counts, ensure completeness
5. **Synthesize patterns** - Catalog variations
6. **Document findings** - Write research.md

## Quality Standards

- **No sampling** - Every file must be checked
- **Code evidence** - Include snippets for each occurrence
- **Exact locations** - File paths and line numbers
- **Quantified results** - Counts of patterns, files, variations
- **Actionable output** - Clear recommendations for standardization

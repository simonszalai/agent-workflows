---
description: Research how something is implemented across the entire codebase. Finds patterns and inconsistencies.
---

# Research Command

Spawn a `researcher` agent to search the codebase for patterns, implementations, and
architectural decisions relevant to the research question.

## Usage

```
/research F014 "how is historical pricing calculated"   # Add research to existing work item
/research 009 "where do timeout errors originate"       # Add research to bug work item
/research "how is error handling done"                  # Creates new research work item
```

## When to Use

| Situation                            | Use `/research`? | Instead Use    |
| ------------------------------------ | ---------------- | -------------- |
| Understanding current implementation | Yes              | -              |
| Finding patterns across codebase     | Yes              | -              |
| Finding inconsistencies              | Yes              | -              |
| Research to inform a feature/bug     | Yes              | -              |
| Bug/incident investigation           | **No**           | `/investigate` |
| Planning a new feature               | **No**           | `/plan`        |
| Checking specific file/function      | **No**           | Read directly  |

## Work Item Setup

**If work item ID is given first** (e.g., `/research F014 "question"` or `/research 009 "question"`):

1. **Extract the ID** from the start of the arguments (before the quoted question)
2. **Search for work item:**
   - For `FNNN` format: `find work_items -maxdepth 2 -type d -name "FNNN-*"`
   - For `NNN` format: `find work_items -maxdepth 2 -type d -name "NNN-*"`
3. **If found:** Use that folder for research output
4. **If not found:** Error - "Work item {ID} not found"

**If only a question is given** (e.g., `/research "how does X work"`):

1. Search active/closed for existing research items: `find work_items/{active,closed} -maxdepth 1 -type d -name "[0-9][0-9][0-9]-*"`
2. Extract numeric prefixes and find the highest number
3. Add 1 and **pad to 3 digits** (e.g., 42 -> `043`)
4. Create slug from question (first 3-4 keywords, kebab-case)
5. Create folder: `work_items/active/NNN-research-{slug}/`
6. Create `source.md` with frontmatter:
   ```yaml
   ---
   type: research
   ---
   ```

## Process

1. **Parse the research question** - What pattern/implementation are we looking for?

2. **Spawn researcher agent** with the research question:

   ```
   Task(subagent_type="researcher", prompt="
     Research question: [question]
     Work item path: [path to work item folder]

     Search the codebase to answer this question. Focus on:
     - Finding ALL relevant implementations
     - Identifying architectural patterns used
     - Noting any inconsistencies between implementations
     - Understanding WHY patterns are used (read context, not just grep)

     Write your findings directly to {work_item}/research.md using the template below.
   ")
   ```

3. **Agent writes research.md** directly to the work item folder

## Output Location

Single file output:

```
work_items/active/{id}-{slug}/
  source.md      # Work item description (created if new)
  research.md    # Research findings (main output)
```

**Note:** If the work item already has a `research.md`, append a timestamp suffix to avoid
overwriting: `research_YYYYMMDD_HHMMSS.md`

## Research Output Template (MANDATORY)

The researcher agent MUST use this template for `research.md`:

---

**Template start:**

```
# Research Findings

**Question:** [original question]
**Date:** YYYY-MM-DD

## Summary

[3-5 sentence overview of what was found]

## Key Architectural Patterns (MANDATORY)

This section documents the critical patterns that ANY implementation in this area MUST follow.
These are non-negotiable conventions established in the codebase.

### Pattern 1: [name]

**What:** [brief description]
**Where:** `file:line` - canonical example
**Why:** [why this pattern exists]
**Usage:** [code example showing correct usage]

### Pattern 2: [name]
...

## Findings

### [Topic 1]

**Locations:**
- `file:line` - description

**Implementation:**
[Description of how this works]

## Inconsistencies Found

### Inconsistency 1: [description]

**Locations:**
- `file:line` - uses approach A
- `file:line` - uses approach B

**Impact:** [why this matters]
**Recommendation:** [which approach to standardize on]
```

**Template end.**

---

## Key Architectural Patterns Section (CRITICAL)

The "Key Architectural Patterns" section is **MANDATORY** and must include:

1. **Patterns that affect implementation** - How code MUST be written in this area
2. **Canonical examples** - File:line references to the authoritative implementation
3. **Code snippets** - Showing correct usage (not simplified versions)

**Examples of patterns to capture:**

| Area                 | Pattern to Document                            |
| -------------------- | ---------------------------------------------- |
| LLM/AI calls         | Prompt construction, response handling         |
| Database operations  | Repository pattern, transaction scope          |
| External API clients | Client patterns, error handling                |
| Service structure    | Task decomposition, error propagation, logging |

**Bad example (too vague):**

> "Uses AI to extract information"

**Good example (actionable):**

> **Pattern: PromptBuilder for User Prompts**
> **Where:** `src/services/ai/extract.py:99-121`
> **Usage:**
>
> ```python
> builder = PromptBuilder(config, output_schema=ResultSchema)
> await builder.add_context(context)
> user_prompt = await builder.render()
> ```
>
> **Why:** Enables consistent prompt structure, auditability

## Examples

### Adding research to existing work item

**User:** `/research F014 "how is historical pricing calculated"`

**Agent:**

1. Finds `work_items/active/F014-historical-analogs/`
2. Spawns researcher agent with the question
3. Researcher explores codebase, identifies patterns
4. Writes `research.md` with:
   - Key Architectural Patterns section
   - Findings on historical pricing logic
   - Any inconsistencies found

### Creating new research work item

**User:** `/research "how do we handle database connections"`

**Agent:**

1. Finds highest work item number (e.g., `027`)
2. Creates `work_items/active/028-research-database-connections/`
3. Creates `source.md` with `type: research` frontmatter
4. Spawns researcher agent
5. Researcher writes `research.md` with:
   - Key Architectural Patterns: connection handling, repository pattern, session scope
   - Findings: connection pool config, session handling
   - Inconsistencies: some code doesn't use context managers properly

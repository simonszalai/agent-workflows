# Past Work Research Methodology

Standards for analyzing past work items to inform current implementation decisions.

## Purpose

Past work items contain valuable learnings that should inform new work:

- What architectural approaches worked/didn't work
- What patterns were discovered during implementation
- What review issues consistently appear
- What risks materialized and how they were handled
- What would have been done differently in hindsight

## Core Responsibilities

### 1. Find Similar Past Work

Search for tickets with similar characteristics using MCP:

```
# Find similar completed tickets (primary method)
similar = mcp__autodev-memory__get_similar_tickets(
  project=PROJECT, ticket_id=CURRENT_ID, repo=REPO, status="completed"
)

# Search across all ticket artifacts by keyword
results = mcp__autodev-memory__search_tickets(
  project=PROJECT, query="<relevant keywords>"
)

# List tickets by type/status for browsing
tickets = mcp__autodev-memory__list_tickets(
  project=PROJECT, type="feature", status="completed"
)
```

**Similarity criteria:**

- Same area of codebase (e.g., models, routes, components, pipelines)
- Same type of change (e.g., adding API integration, database schema change)
- Same external dependencies (e.g., shared libraries, external APIs)
- Same architectural pattern (e.g., new processing step, new endpoint)

### 2. Extract Architectural Decisions

From `plan.md` files, extract:

- **Approach chosen** and why
- **Alternatives considered** and why rejected
- **Tradeoffs made** (what was optimized vs sacrificed)
- **Risks identified** and mitigations
- **Open questions** and how they were resolved

Look for these sections:

```markdown
## Why This Approach

## Tradeoffs

## Risks

## Open Questions
```

### 3. Extract Implementation Patterns

From `build_todos/` files, extract:

- **Discovered patterns** - What existing code patterns were found
- **Files modified** - Common integration points
- **Test patterns** - How similar code was tested
- **Gotchas noted** - What pitfalls were flagged

Look for these sections in build todos:

```markdown
## Discovered Patterns

## Implementation Details

## Tests

## Verification
```

### 4. Extract Review Learnings

From `review_todos/` files, extract:

- **Common issues** - What problems were found during review
- **Priority patterns** - What tends to be p1 vs p2 vs p3
- **Process improvements** - What was recommended to prevent future issues

Group by category:

| Category       | Example Issues                      |
| -------------- | ----------------------------------- |
| Type safety    | Missing type hints, incorrect types |
| Data integrity | Missing constraints, null handling  |
| Performance    | N+1 queries, missing indexes        |
| Security       | Input validation, auth checks       |
| Simplicity     | Over-engineering, dead code         |

### 5. Extract Conclusions

From `conclusion.md` files, extract:

- **What was done** - Summary of changes
- **How we got here** - Key decision points
- **Outcome** - Results and resolution
- **Learnings** - What would be done differently

### 6. Cross-Reference Knowledge Base

After finding similar tickets, search the knowledge base for related entries:

```
mcp__autodev-memory__search(queries=[
  {"keywords": ["<ticket-area>"], "text": "<area> gotchas lessons learned"}
])
```

## Output Format

```markdown
## Similar Past Work Analysis

### Work Items Reviewed

| ID   | Title   | Relevance     | Key Learning    |
| ---- | ------- | ------------- | --------------- |
| [ID] | [Title] | [Why similar] | [Main takeaway] |

### Architectural Decisions

From similar past work:

#### [Work Item ID]: [Decision]

- **Approach:** [What was chosen]
- **Why:** [Reasoning]
- **Tradeoffs:** [What was sacrificed]
- **Outcome:** [How it worked out]

### Implementation Patterns Found

| Pattern               | Source                | Applies Because |
| --------------------- | --------------------- | --------------- |
| [Pattern description] | [Work item ID + file] | [Why relevant]  |

### Review Patterns

Issues commonly found in similar work:

| Issue Type | Frequency              | Example            | Prevention     |
| ---------- | ---------------------- | ------------------ | -------------- |
| [Category] | [Often/Sometimes/Once] | [From work item X] | [How to avoid] |

### Conclusions and Learnings

From completed similar work:

- **[Work Item]:** [Key learning or what would be done differently]

### Recommended Approach

Based on past work:

1. [Recommendation based on what worked]
2. [Warning based on what didn't work]
3. [Pattern to follow from successful implementation]

### Related Memory Entries

Related entries from memory service:

- [Entry title] - [Why relevant]
- [Entry title] - [Why relevant]
```

## Usage Guidelines

### When Planning (`/plan`)

Focus on:

- Architectural decisions from similar features/fixes
- Approaches that worked vs didn't work
- Risks that materialized

### When Creating Build Todos (`/create-build-todos`)

Focus on:

- Implementation patterns from similar build_todos
- Common integration points
- Test patterns

### When Reviewing (`/review`)

Focus on:

- Review findings from similar implementations
- Common issues in this area of codebase
- Process improvements suggested

## Key Insight

Past work items are a calibrated source of what actually happened, not what was
predicted. Use them to:

- Avoid reinventing approaches that failed
- Reuse patterns that succeeded
- Anticipate review findings before they're found
- Set realistic expectations based on actual outcomes

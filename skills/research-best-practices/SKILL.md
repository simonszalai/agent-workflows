---
name: research-best-practices
description: Research methodology for external best practices, community standards, and documentation. Used by investigator-research agent.
---

# Best Practices Research Methodology

Standards for researching and gathering external best practices, documentation, and examples.

## Research Approach

### 1. Leverage Multiple Sources

- Use Context7 MCP to access official documentation from GitHub, framework docs, and library references
- Search the web for recent articles, guides, and community discussions
- Identify and analyze well-regarded open source projects that demonstrate the practices
- Look for style guides, conventions, and standards from respected organizations

### 2. Evaluate Information Quality

- Prioritize official documentation and widely-adopted standards
- Consider the recency of information (prefer current practices over outdated ones)
- Cross-reference multiple sources to validate recommendations
- Note when practices are controversial or have multiple valid approaches

### 3. Synthesize Findings

- Organize discoveries into clear categories (e.g., "Must Have", "Recommended", "Optional")
- Provide specific examples from real projects when possible
- Explain the reasoning behind each best practice
- Highlight technology-specific or domain-specific considerations

### 4. Deliver Actionable Guidance

- Present findings in structured, easy-to-implement format
- Include code examples or templates when relevant
- Provide links to authoritative sources for deeper exploration
- Suggest tools or resources that can help implement the practices

## Research Methodology

1. Start with official documentation using Context7 for the specific technology
2. Search for "[technology] best practices [current year]" to find recent guides
3. Look for popular repositories on GitHub that exemplify good practices
4. Check for industry-standard style guides or conventions
5. Research common pitfalls and anti-patterns to avoid

## Focus Areas (for this codebase)

- Prefect flow and task organization patterns
- Pydantic model design and validation
- Async Python patterns for data pipelines
- Error handling and retry strategies
- Type annotation best practices
- Testing patterns for workflow orchestration

## Output Format

Structure findings as:

1. **Summary**: Brief overview of the topic
2. **Best Practices**: Organized by category
   - Must Have
   - Recommended
   - Optional
3. **Code Examples**: Practical examples adapted to project style
4. **Anti-Patterns**: What to avoid
5. **Sources**: Links to authoritative references

## Quality Standards

- Always cite sources and indicate authority level
- "Official Prefect documentation recommends..." vs "Many successful projects tend to..."
- If conflicting advice, present different viewpoints and trade-offs
- Be thorough but focused on practical application

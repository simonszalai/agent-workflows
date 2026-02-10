---
name: research-repo-patterns
description: Repository research methodology for structure, documentation, and patterns. Used by investigator-research agent.
---

# Repository Research Methodology

Standards for conducting thorough research on a repository's structure, documentation, and patterns.

## Core Responsibilities

### 1. Architecture and Structure Analysis

- Examine key documentation files (ARCHITECTURE.md, README.md, CONTRIBUTING.md, CLAUDE.md)
- Map out the repository's organizational structure
- Identify architectural patterns and design decisions
- Note any project-specific conventions or standards

### 2. GitHub Issue Pattern Analysis

- Review existing issues to identify formatting patterns
- Document label usage conventions and categorization schemes
- Note common issue structures and required information
- Identify any automation or bot interactions

### 3. Documentation and Guidelines Review

- Locate and analyze all contribution guidelines
- Check for issue/PR submission requirements
- Document any coding standards or style guides
- Note testing requirements and review processes

### 4. Template Discovery

- Search for issue templates in `.github/ISSUE_TEMPLATE/`
- Check for pull request templates
- Document any other template files (e.g., RFC templates)
- Analyze template structure and required fields

### 5. Codebase Pattern Search

- Use `grep` or `rg` for text-based pattern searches
- Identify common implementation patterns
- Document naming conventions and code organization

### 6. Work Item History

Check work_items folders for context and decisions:

```bash
# Search all folders (active/, backlog/, closed/)
find work_items -name "*.md" -path "*/closed/*" -o -name "investigation.md"
```

- Review closed work items (`work_items/closed/`) for architectural decisions and rationale
- Check backlog (`work_items/backlog/`) for planned features with context
- Examine `investigation.md` and `conclusion.md` files for past analysis
- Look for patterns in how problems were solved
- Understand why certain approaches were chosen over alternatives

## Research Methodology

1. Start with high-level documentation to understand project context
2. Progressively drill down into specific areas based on findings
3. Cross-reference discoveries across different sources
4. Prioritize official documentation over inferred patterns
5. Note any inconsistencies or areas lacking documentation

## Output Format

```markdown
## Repository Research Summary

### Architecture & Structure

- Key findings about project organization
- Important architectural decisions
- Technology stack and dependencies

### Conventions Discovered

- Formatting patterns observed
- Naming conventions
- Code organization patterns

### Documentation Insights

- Contribution guidelines summary
- Coding standards and practices
- Testing and review requirements

### Templates Found

- List of template files with purposes
- Required fields and formats
- Usage instructions

### Implementation Patterns

- Common code patterns identified
- Project-specific practices
- Patterns for flows, tasks, models

### Recommendations

- How to best align with project conventions
- Areas needing clarification
- Next steps for deeper investigation
```

## Quality Standards

- Verify findings by checking multiple sources
- Distinguish between official guidelines and observed patterns
- Note the recency of documentation (check last update dates)
- Flag any contradictions or outdated information
- Provide specific file paths and examples to support findings

## Important Considerations

- Respect any CLAUDE.md or project-specific instructions found
- Pay attention to both explicit rules and implicit conventions
- Consider the project's maturity and size when interpreting patterns
- Note any tools or automation mentioned in documentation
- Be thorough but focused - prioritize actionable insights

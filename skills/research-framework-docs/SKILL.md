---
name: research-framework-docs
description: Documentation gathering methodology for frameworks and libraries (Python and TypeScript/React). Used by investigator-research agent.
---

# Framework Documentation Research Methodology

Standards for gathering comprehensive documentation and implementation guidance for frameworks,
libraries, and dependencies across Python and TypeScript/React ecosystems.

## Core Responsibilities

### 1. Documentation Gathering

- Use Context7 to fetch official framework and library documentation
- Identify and retrieve version-specific documentation matching project dependencies
- Extract relevant API references, guides, and examples
- Focus on sections most relevant to current implementation needs

### 2. Best Practices Identification

- Analyze documentation for recommended patterns and anti-patterns
- Identify version-specific constraints, deprecations, and migration guides
- Extract performance considerations and optimization techniques
- Note security best practices and common pitfalls

### 3. GitHub Research

- Search GitHub for real-world usage examples of the framework/library
- Look for issues, discussions, and pull requests related to specific features
- Identify community solutions to common problems
- Find popular projects using the same dependencies for reference

### 4. Source Code Analysis

**Python projects:**

- Use `uv pip show <package>` to locate installed packages
- Explore package source code to understand internal implementations

**TypeScript/React projects:**

- Check `node_modules/<package>` for source code
- Use the project's package manager (bun/npm/pnpm) to view installed packages

**Both:**

- Read through README files, changelogs, and inline documentation
- Identify configuration options and extension points

## Workflow Process

### 1. Initial Assessment

- Identify the specific framework or library being researched
- Determine the installed version:
  - Python: from `pyproject.toml` or `uv.lock`
  - TypeScript: from `package.json`
- Understand the specific feature or problem being addressed

### 2. Documentation Collection

- Start with Context7 to fetch official documentation
- If Context7 is unavailable or incomplete, use web search as fallback
- Prioritize official sources over third-party tutorials
- Collect multiple perspectives when official docs are unclear

### 3. Source Exploration

- Read through key source files related to the feature
- Look for tests that demonstrate usage patterns
- Check for configuration examples in the codebase

### 4. Synthesis and Reporting

- Organize findings by relevance to current task
- Highlight version-specific considerations
- Provide code examples adapted to project's style
- Include links to sources for further reading

## Output Format

Structure findings as:

1. **Summary**: Brief overview of the framework/library and its purpose
2. **Version Information**: Current version and any relevant constraints
3. **Key Concepts**: Essential concepts needed to understand the feature
4. **Implementation Guide**: Step-by-step approach with code examples
5. **Best Practices**: Recommended patterns from official docs and community
6. **Common Issues**: Known problems and their solutions
7. **References**: Links to documentation, GitHub issues, and source files

## Quality Standards

- Always verify version compatibility with project's dependencies
- Prioritize official documentation but supplement with community resources
- Provide practical, actionable insights rather than generic information
- Include code examples that follow the project's conventions
- Flag any potential breaking changes or deprecations
- Note when documentation is outdated or conflicting

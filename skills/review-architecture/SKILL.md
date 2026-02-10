---
name: review-architecture
description: Architectural principles and compliance checklist. Used by reviewer-system agent. Portable to Cursor.
---

# Architecture Review Standards

Standards for architectural compliance. Apply these when reviewing code changes for architectural impact.

## Analysis Approach

1. **Understand System Architecture**: Examine overall system structure through architecture docs, README files, and existing code patterns
2. **Analyze Change Context**: Evaluate how proposed changes fit within existing architecture
3. **Identify Violations**: Detect architectural anti-patterns and violations
4. **Consider Long-term**: Assess impact on system evolution, scalability, maintainability

## Compliance Checklist

Verify changes against these principles:

### SOLID Principles

- [ ] **Single Responsibility**: Each class/module has one reason to change
- [ ] **Open/Closed**: Open for extension, closed for modification
- [ ] **Liskov Substitution**: Subtypes substitutable for base types
- [ ] **Interface Segregation**: Clients don't depend on unused interfaces
- [ ] **Dependency Inversion**: Depend on abstractions, not concretions

### Architectural Boundaries

- [ ] Changes align with documented architecture
- [ ] No new circular dependencies introduced
- [ ] Component boundaries properly respected
- [ ] Appropriate abstraction levels maintained
- [ ] API contracts and interfaces stable or properly versioned
- [ ] Design patterns consistently applied
- [ ] Significant architectural decisions documented

## Architectural Smells to Detect

- **Inappropriate intimacy** - Components knowing too much about each other
- **Leaky abstractions** - Implementation details escaping through interfaces
- **Dependency rule violations** - Wrong direction of dependencies
- **Inconsistent patterns** - Same problem solved differently in different places
- **Missing boundaries** - No clear separation between concerns

## Analysis Output Format

Structure analysis as:

1. **Architecture Overview**: Brief summary of relevant architectural context
2. **Change Assessment**: How changes fit within the architecture
3. **Compliance Check**: Specific principles upheld or violated
4. **Risk Analysis**: Potential architectural risks or technical debt
5. **Recommendations**: Specific suggestions for improvements or corrections

## Key Checks

### Component Dependencies

- Examine import statements and module relationships
- Check for import depth and circular dependencies
- Verify proper layering (no bypassing abstraction layers)

### Service Boundaries (if applicable)

- Inter-service communication patterns
- API contract stability
- Boundary violations

### Data Flow

- Where does data originate?
- How does it transform through the system?
- Are there proper validation points?

## When to Flag for Discussion

- New patterns introduced that differ from existing ones
- Cross-cutting changes that affect multiple components
- Changes that create new dependencies between layers
- API changes that affect external consumers

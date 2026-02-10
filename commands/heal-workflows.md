---
description: Audit skills, agents, commands for contradictions, broken refs, and inconsistencies.
---

# Heal Workflows Command

Audit the workflow system (skills, agents, commands) for internal consistency. Finds and fixes
contradictions, broken references, outdated patterns, and missing connections.

## Usage

```
/heal-workflows                    # Full audit of all workflow components
/heal-workflows skills             # Audit skills only
/heal-workflows agents             # Audit agents only
/heal-workflows commands           # Audit commands only
/heal-workflows --fix              # Auto-fix issues (with confirmation)
```

## What This Command Audits

### 1. Skill Validation

```
.claude/skills/*/SKILL.md files
```

Checks:

- [ ] All skills have valid YAML frontmatter (name, description)
- [ ] Referenced templates exist: `templates/*.md`
- [ ] Cross-references to other skills are valid
- [ ] No orphaned skills (skills not referenced by any agent or command)
- [ ] Consistent formatting and structure

### 2. Agent Validation

```
.claude/agents/*.md files
```

Checks:

- [ ] All agents have valid YAML frontmatter
- [ ] Referenced skills exist in `.claude/skills/`
- [ ] Role descriptions are clear and non-overlapping
- [ ] Agent routing logic is consistent (no conflicts)
- [ ] Subagent types match defined agents

### 3. Command Validation

```
.claude/commands/*.md files
```

Checks:

- [ ] All commands have valid YAML frontmatter (description required)
- [ ] Referenced skills exist
- [ ] Referenced agents exist
- [ ] max_turns values are reasonable (not too low for complex commands)
- [ ] Command descriptions are unique and clear
- [ ] Process sections align with referenced skills/agents

### 4. Cross-Reference Validation

Checks relationships between components:

- [ ] Every skill referenced by a command/agent exists
- [ ] Every agent referenced by a command exists
- [ ] No circular dependencies that cause issues
- [ ] Consistent naming conventions across components

## Process

### Phase 1: Collect Inventory

```bash
# Collect all workflow files
find .claude/skills -name "SKILL.md" -type f
find .claude/agents -name "*.md" -type f
find .claude/commands -name "*.md" -type f
```

### Phase 2: Parse and Validate

For each file:

1. Parse YAML frontmatter
2. Extract references to other components
3. Check internal consistency
4. Record issues found

### Phase 3: Cross-Reference Check

Build dependency graph:

```
command -> [skills, agents]
agent -> [skills]
skill -> [templates]
```

Validate all edges point to existing nodes.

### Phase 4: Report Issues

```markdown
## Workflow Health Report

**Date:** YYYY-MM-DD
**Scope:** [all | skills | agents | commands]

### Summary

| Component | Total | Valid | Issues |
| --------- | ----- | ----- | ------ |
| Skills    | 33    | 31    | 2      |
| Agents    | 17    | 16    | 1      |
| Commands  | 21    | 21    | 0      |

### Issues Found

#### Critical (breaks workflow)

1. **Missing skill reference**
   - File: `.claude/commands/review.md`
   - Issue: References skill `review-code` which doesn't exist
   - Fix: Create skill or update reference to `review-python-standards`

#### Warning (potential problem)

2. **Orphaned skill**
   - File: `.claude/skills/old-pattern/SKILL.md`
   - Issue: Not referenced by any agent or command
   - Fix: Delete or add to appropriate agent

#### Info (style/consistency)

3. **Missing description**
   - File: `.claude/agents/helper.md`
   - Issue: Frontmatter missing description field
   - Fix: Add description

### Dependency Graph
```

/build -> [build.md, researcher]
researcher -> [research]
research -> [templates/research-findings.md]

```

### Recommendations

1. [Priority action items]
2. [Suggested improvements]
```

### Phase 5: Auto-Fix (if --fix)

For each fixable issue:

1. Show proposed fix
2. Ask for confirmation
3. Apply fix
4. Log change

Fixable issues:

- Missing frontmatter fields (add with defaults)
- Broken skill references (suggest alternatives)
- Inconsistent naming (offer rename)

Non-fixable issues (require human decision):

- Conflicting agent responsibilities
- Missing functionality
- Architectural changes

## Common Issues

| Issue                  | Severity | Auto-Fix?   |
| ---------------------- | -------- | ----------- |
| Missing frontmatter    | Warning  | Yes         |
| Broken skill reference | Critical | Suggest     |
| Broken agent reference | Critical | Suggest     |
| Orphaned skill         | Info     | No (manual) |
| Duplicate command name | Critical | No (manual) |
| Missing template       | Warning  | No          |
| Inconsistent naming    | Info     | Yes         |

## Output

### Report File

Creates: `.claude/reports/workflow-health-YYYYMMDD.md`

### Console Summary

```
Workflow Health Check Complete

Critical: 0
Warning: 2
Info: 3

Run `/heal-workflows --fix` to address fixable issues.
Full report: .claude/reports/workflow-health-20260201.md
```

## When to Run

- After adding new skills, agents, or commands
- After major refactoring
- When workflows behave unexpectedly
- As part of regular maintenance (monthly)
- Before promoting workflow changes

## Related Commands

| Command                | Purpose                      |
| ---------------------- | ---------------------------- |
| `/heal-workflows`      | Audit workflow components    |
| `/heal-knowledge-base` | Audit knowledge organization |
| `/heal-work-items`     | Audit work item consistency  |

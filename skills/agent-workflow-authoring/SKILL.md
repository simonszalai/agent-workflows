---
name: agent-workflow-authoring
description: Reference guide for creating/modifying agent workflows. Rules for skill/agent/command system, user vs project level, file conventions, parallelism.
---

# Agent Workflow Authoring Guide

Authoritative reference for creating, modifying, and maintaining the agent workflow system.

## The 3-Layer System

Agent workflows consist of three layers, each with a distinct purpose:

### Skills (the HOW)

Portable methodology documents that agents load as reference material.

**Contains:** Review checklists, research methods, tool references, testing patterns
**Never contains:** Project-specific details (table names, service IDs, routes)
**Loaded by:** Agents via skill references in their definition

**File structure:**

```
skills/<name>/
├── SKILL.md          # Main skill document
└── templates/        # Optional output templates
    ├── template1.md
    └── template2.md
```

**SKILL.md frontmatter:**

```yaml
---
name: skill-name
description: Short description of what this skill provides. Used by [agent-name] agent.
---
```

### Agents (the WHO)

Role definitions that specify a specialized agent's purpose, methodology, and capabilities.

**Contains:** Agent purpose, methodology, skills to load, tool access requirements
**Gets project context from:** AGENTS.md (not hardcoded)
**Spawned by:** Commands via the Task tool

**File structure:**

```
agents/<name>.md     # Agent definition
```

**Agent frontmatter:**

```yaml
---
name: agent-name
description: What this agent does
skills:
  - skill-name-1
  - skill-name-2
tools:
  - Bash
  - Read
  - Grep
  # List specific tools the agent needs
---
```

### Commands (the WHAT)

User-invocable workflows that orchestrate agents and chain multi-step processes.

**Contains:** Workflow triggers, agent spawning logic, step coordination
**Invoked with:** `/<command-name>`
**Spawns:** One or more agents, potentially in parallel

**File structure:**

```
commands/<name>.md    # Command definition
```

**Command frontmatter:**

```yaml
---
description: What this command does. Shown in command help.
---
```

## User-Level vs Project-Level

| Level   | Location                                    | Contains                                 |
| ------- | ------------------------------------------- | ---------------------------------------- |
| User    | `~/.claude/skills/`, `agents/`, `commands/` | Universal methodology for ALL projects   |
| Project | `.claude/skills/`, `agents/`, `commands/`   | Project-specific overrides and additions |

### Placement Rules

1. **If used in 2+ projects** - belongs at user level
2. **Project-specific context** (table names, service IDs, routes) - goes in AGENTS.md
3. **Project-level overrides user-level** when both have the same filename
4. **Skills must never contain project-specific details** - even at project level

### What Goes Where

**User level (`~/.claude/`):**

- Generic review checklists (review-architecture, review-security, etc.)
- Generic research methodologies (research-git-history, research-best-practices)
- Tool references that work across projects (agent-browser, tool-postgres)
- Universal workflow commands (plan, build, review, investigate)
- Agent role definitions without project specifics

**Project level (`.claude/`):**

- Project-specific tool skills (tool-prefect for Prefect projects)
- Project-specific commands (deploy for specific deployment targets)
- Agent overrides that add project-specific behavior
- Skills unique to one project (app-designer for mobile)

**AGENTS.md (project root):**

- Database table names and schema context
- Service IDs and infrastructure details
- Project-specific conventions and framework rules
- Demo accounts and test credentials
- Page/route references for browser testing

## Creating a New Skill

1. Determine if it belongs at user or project level
2. Create `skills/<name>/SKILL.md` with frontmatter
3. Add templates/ if the skill produces structured output
4. Reference the skill in relevant agent definitions
5. Run `/heal-workflows` to validate references

**Skill content guidelines:**

- Write as reusable methodology, not project-specific instructions
- Include checklists where applicable
- Reference templates for structured output
- Keep format consistent with existing skills
- No project-specific paths, table names, or service IDs

## Creating a New Agent

1. Determine if it belongs at user or project level
2. Create `agents/<name>.md` with frontmatter listing skills and tools
3. Define the agent's methodology and output expectations
4. Reference the agent in relevant commands
5. Run `/heal-workflows` to validate

**Agent content guidelines:**

- Define clear role and responsibilities
- List all skills the agent should load
- Specify what tools the agent needs access to
- Describe expected output format
- Note where agent gets project context (AGENTS.md)

## Creating a New Command

1. Determine if it belongs at user or project level
2. Create `commands/<name>.md` with description frontmatter
3. Define the workflow steps and which agents to spawn
4. Specify any user interactions needed
5. Run `/heal-workflows` to validate

**Command content guidelines:**

- Define clear trigger conditions (when to use)
- Specify which agents to spawn and in what order
- Use parallel spawning for independent agents
- Define success criteria and output expectations
- Note any user approval gates

## Parallelism Rules

When a command spawns multiple independent agents:

- ALWAYS use parallel Task tool calls in a single message
- Never spawn sequentially when agents don't depend on each other's output
- Example: `/review` spawns reviewer-code, reviewer-data, reviewer-system in parallel

When agents DO depend on each other:

- Spawn sequentially, passing output from one to the next
- Example: `/auto-build` runs build -> review -> resolve sequentially

## Modifying Existing Workflows

1. Read the current file to understand existing content
2. Make targeted changes (don't rewrite unnecessarily)
3. Ensure consistency with other files in the same layer
4. Check that no references are broken
5. Run `/heal-workflows` to validate

## Common Patterns

### Skill loaded by multiple agents

Keep the skill generic. If different agents need different behavior, the agent definition
should specify how to use the skill, not the skill itself.

### Agent needs project context

The agent reads from AGENTS.md at runtime. Never hardcode project details in agent
definitions. Use phrases like "Read AGENTS.md for project-specific configuration."

### Command needs conditional logic

Commands can include decision trees (e.g., "if bug, spawn investigator; if feature,
spawn planner"). Keep the logic in the command, not the agents.

## Validation

After any modification to skills, agents, or commands:

1. Run `/heal-workflows` to check for broken references
2. Verify the affected command still works in at least one project
3. Check that no project-level file accidentally shadows a user-level file

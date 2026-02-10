---
description: Investigate production bugs to find workflow gaps. Spawns retrospector agent, produces retrospective.md with recommendations.
---

# Retrospect Command

Analyze why a bug reached production by examining agent workflows, prompts, skills, commands, and
tools at every stage. Identifies what's missing from the workflow.

## Usage

```
/retrospect "Bug description: items missing associations"
/retrospect work_items/active/009-missing-data
/retrospect 009                              # Bug/incident #009 (NNN format)
/retrospect F003                             # Feature F003 (FNNN format)
```

## When to Use

| Situation                    | Use `/retrospect`? | Instead Use      |
| ---------------------------- | ------------------ | ---------------- |
| Bug reached production       | Yes                | -                |
| Want to prevent similar bugs | Yes                | -                |
| Incident post-mortem         | Yes                | -                |
| Bug not yet in production    | **No**             | Fix directly     |
| New feature planning         | **No**             | `/plan` directly |

## Work Item Lookup

**If work item path given:** Use that folder as context.

**If number given (009 or F003):** Search for existing work item:

```bash
find work_items -maxdepth 2 -type d -name "*{id}*"
```

**If only description given:** Search for related work items by keyword, or create a new incident
work item:

1. Search: `find work_items -maxdepth 2 -type d -name "*keyword*"`
2. If found: Use that work item
3. If not found: Create `work_items/active/NNN-retrospect-slug/` with next available number

## Analysis Stages

The retrospective examines each workflow stage:

| Stage                   | Artifact               | Question                                    |
| ----------------------- | ---------------------- | ------------------------------------------- |
| Investigation (bugs)    | investigation.md       | Was root cause analysis thorough?           |
| Plan                    | plan.md                | Did plan identify the constraint/edge case? |
| Build Todos             | build_todos/           | Were implementation steps complete?         |
| Implementation          | git diff               | Did code match plan? Quality issues?        |
| Review                  | review_todos/          | Did reviewers check right dimensions?       |
| Local Verification      | test output            | Were integration tests sufficient?          |
| Production Verification | verification-report.md | Did we verify the right scenarios?          |
| Knowledge               | .claude/knowledge/     | Should there be a gotcha/reference?         |

## Agent Dispatch

Spawn the `retrospector` agent with full context:

```
Task(subagent_type="retrospector", prompt="
Bug description: [description]

Work item (if found): [path or 'none']

Context from conversation: [any additional context]

Analyze which workflow stage should have caught this bug.
Return analysis following the retrospect-methodology template.
")
```

**Optional:** For deeper code analysis, also spawn `researcher` agent:

```
Task(subagent_type="researcher", prompt="
Research the codebase for: [bug area]

Find:
1. When was the buggy code introduced? (git blame)
2. What commits relate to this area?
3. Are there similar patterns that handle this correctly?
4. Any knowledge docs that mention this area?
")
```

## Process

1. **Parse input** - Extract bug description and work item reference
2. **Find work item** - Locate existing work item or create incident folder
3. **Gather context** - Read all work item artifacts
4. **Spawn retrospector** - Analyze workflow gaps
5. **Spawn researcher** (optional) - Deep dive on code history
6. **Synthesize findings** - Write `retrospective.md` to work item folder
7. **Create action items** - Identify specific workflow improvements

## Output

Write `retrospective.md` to work item folder with:

- Primary gap identified (the main failure point)
- Secondary gaps (contributing factors)
- Evidence from artifacts and git history
- Specific recommendations for workflow improvement
- Action items checklist

## Examples

**Bug: "Items missing required associations"**

1. Find related work item (search for association keywords)
2. Read plan.md - Did it mention association logic?
3. Read build_todos/ - Were there steps for association handling?
4. Check review_todos/ - Did reviewers check data integrity?
5. Check verification - Was association verified?
6. Primary gap likely: Missing verification step for data associations

**Bug: "Migration failed on downgrade"**

1. Find related work item (search for migration)
2. Read plan.md - Did it mention constraint naming?
3. Check .claude/knowledge/gotchas/ - Is constraint naming documented?
4. Primary gap likely: Missing gotcha, or gotcha not referenced in plan

## Gap Remediation

After identifying gaps, take action:

| Gap Type           | Remediation                                                            |
| ------------------ | ---------------------------------------------------------------------- |
| Missing plan step  | Update plan checklist or skill                                         |
| Missing build todo | Update build-plan-methodology skill                                    |
| Missing review     | Update review skill checklists                                         |
| Missing verify     | Update verify-flow skill or add scenario                               |
| Missing knowledge  | Use `/compound gotcha`, `/compound reference`, or `/compound solution` |
| Process issue      | Update AGENTS.md or relevant command                                   |

## Workflow Improvement Loop

The retrospective is part of a continuous improvement loop:

```
Bug found -> /retrospect -> Identify gap -> Fix workflow -> Prevent similar bugs
```

Each retrospective should result in at least one concrete workflow change.

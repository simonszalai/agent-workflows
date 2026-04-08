---
description: Audit tickets for consistency and health across the ticket system.
---

# Heal Tickets Command

Audit tickets in the MCP ticket system for consistency, completeness, and lifecycle compliance.

## Usage

```
/heal-work-items                    # Full audit of all tickets
/heal-work-items active             # Audit active tickets only
/heal-work-items completed          # Audit completed tickets only
/heal-work-items backlog            # Audit backlog tickets only
```

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## What This Command Audits

### 1. Ticket Completeness

Check that tickets have appropriate artifacts for their status:

| Status | Expected Artifacts |
|---|---|
| backlog | source |
| active | source, (plan or investigation) |
| to_verify | source, plan, build_todo(s) |
| completed | source, plan, build_todo(s) |

### 2. Artifact Status Consistency

- build_todo artifacts should not be "pending" on completed tickets
- review_todo artifacts should not be "pending" on completed tickets
- Active tickets should have at least one artifact with recent updates

### 3. Stale Ticket Detection

- Active tickets with no artifact updates for 14+ days
- to_verify tickets older than 7 days

### 4. Cross-Reference Validation

- Tickets with `depends_on` references point to existing tickets
- Tickets with `related` references point to existing tickets/repos

## Process

### Phase 1: Collect Inventory

```
# List all tickets for the current repo
tickets = mcp__autodev-memory__list_tickets(
  project=PROJECT, repo=REPO, limit=100
)
```

### Phase 2: Validate Each Ticket

For each ticket, load full details:

```
ticket = mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO
)
```

Check:
1. Required artifacts exist for the ticket's status
2. Artifact statuses are consistent
3. No stale tickets (check `updated_at` timestamps)
4. Cross-references resolve

### Phase 3: Report Issues

```markdown
## Ticket Health Report

**Date:** YYYY-MM-DD
**Project:** {project}
**Repo:** {repo}

### Summary

| Status    | Total | Healthy | Issues |
| --------- | ----- | ------- | ------ |
| active    | 5     | 4       | 1      |
| backlog   | 12    | 12      | 0      |
| completed | 45    | 43      | 2      |

### Issues Found

#### Critical

1. **Missing plan artifact**
   - Ticket: F0015
   - Status: active (should have plan)
   - Fix: Run `/plan F0015`

#### Warning

2. **Stale active ticket**
   - Ticket: B0009
   - Last updated: 21 days ago
   - Fix: Move to backlog or continue work

### Recommendations

1. Run `/plan` on active tickets missing plans
2. Move stale tickets to backlog
3. Verify to_verify tickets or close them
```

## Common Issues

| Issue                      | Severity | Fix |
| -------------------------- | -------- | --- |
| Missing plan on active     | Warning  | Run `/plan` |
| Missing build_todos        | Warning  | Run `/create-build-todos` |
| Stale active (14+ days)    | Warning  | Move to backlog or work on it |
| Stale to_verify (7+ days)  | Warning  | Run `/verify-prod` |
| Broken cross-reference     | Info     | Update `related` or `depends_on` |

## When to Run

- Weekly maintenance
- Before sprint planning
- When tickets seem disorganized
- After bulk operations on tickets

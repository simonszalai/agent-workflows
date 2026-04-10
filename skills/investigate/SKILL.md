---
name: investigate
description: Investigation output format, YAML template, and synthesis methodology. Used by all investigator agents.
---

# Investigation Methodology

Standards for conducting **bug and incident investigations** and producing investigation.md files.

## Scope

**Use for:** Bugs, incidents, unexpected behavior, production issues
**NOT for:** New features (use `/plan` directly instead)

## Sub-Agent Behavior (CRITICAL)

**Sub-agents (investigator-postgres, investigator-render, investigator-prefect) must:**

- **RETURN findings directly** in your response - do NOT create files
- The parent agent will synthesize all findings into a single investigation.md
- Never create local work_items folders or investigation files yourself

**Only the orchestrating agent** (invoked via `/investigate {number}`) writes the final
investigation artifact to the ticket via `mcp__autodev-memory__create_artifact`.

## Output Template

Use the template at `templates/investigation.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Synthesis Methodology

When combining findings from multiple sources:

1. **Correlate timestamps** - Match events across sources (logs, DB records, flow runs)
2. **Check cross-service correlation** - If multiple independent services fail
   simultaneously, investigate shared infrastructure (proxy, DB, network) before
   per-service causes. Error messages from individual services may assume a cause
   (e.g., "anti-bot challenge") that is actually a shared infrastructure failure.
3. **Follow causation** - Infrastructure issues → flow failures → data state
4. **Quantify impact** - Count affected records, flows, time windows
5. **Rank by severity** - Critical (data loss, outage) > High (degraded) > Medium (edge cases)
6. **Verify hypotheses** - Each root cause needs evidence from at least one source


## Evidence Quality

**Strong evidence:**

- Exact timestamps matching across sources
- Error messages with stack traces
- Metrics showing clear anomalies
- Database records showing state transitions

**Weak evidence (needs corroboration):**

- Absence of data (could be many causes)
- Timing correlation without causation
- Single source without cross-reference

## Severity Definitions

| Severity | Definition                                  |
| -------- | ------------------------------------------- |
| CRITICAL | Data loss, complete outage, security breach |
| HIGH     | Degraded service, significant data issues   |
| MEDIUM   | Edge cases, minor impact, workaround exists |
| LOW      | Cosmetic, minimal impact                    |

## Investigation Process

1. **Gather evidence** - Collect findings from all relevant sources
2. **Check deployment correlation** - Compare failure onset with recent deploys.
   If failures started right after a code change, **suspect the new code first** —
   don't blame external services until the new code is ruled out. New "guard" or
   "pre-flight" checks are especially suspect: they can silently block real work.
3. **Correlate timeline** - Build event sequence across sources
4. **Identify root causes** - Distinguish symptoms from causes
5. **Assess impact** - Quantify what was affected
6. **Recommend fixes** - High-level fix directions (not solution design)

**Note:** Investigation answers "what happened and why". Solution design happens in `/plan`.

## Knowledge Capture

When an investigation reveals non-obvious root causes, diagnostic patterns, or gotchas, the
`/investigate` command orchestrator persists them via `mcp__autodev-memory__add_entry`. This
ensures debugging insights survive beyond the current session.

**Capture criteria** (store when ANY are true):
- Root cause was non-obvious (future sessions would struggle too)
- A diagnostic approach proved effective and reusable
- The bug reveals a recurring pattern or architectural gotcha

**Skip when ALL are true:**
- Root cause was obvious from error message/stack trace
- One-off issue with no broader lesson
- Already covered by an existing memory service entry

Individual investigator sub-agents do NOT call MCP tools — the orchestrator handles persistence
after synthesizing findings.

## Closing Investigations

**Auto-close when all "Next Steps" are complete.** When all checkboxes in the investigation.md are
checked off:

1. Create a conclusion artifact on the ticket via `mcp__autodev-memory__create_artifact`
2. Update ticket status to `completed` via `mcp__autodev-memory__update_ticket`
3. Report: "Investigation complete. Ticket closed."

Do NOT wait for user to say "close" - if all action items are done, close it.

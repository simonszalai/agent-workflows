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
- Never create work_items folders or investigation files yourself

**Only the orchestrating agent** (invoked via `/investigate {number}`) writes the final
`investigation.md` to the work item folder (searches active/, backlog/, closed/ for the number).

## Output Template

Use the template at `templates/investigation.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt). See AGENTS.md.

## Synthesis Methodology

When combining findings from multiple sources:

1. **Correlate timestamps** - Match events across sources (logs, DB records, flow runs)
2. **Follow causation** - Infrastructure issues → flow failures → data state
3. **Quantify impact** - Count affected records, flows, time windows
4. **Rank by severity** - Critical (data loss, outage) > High (degraded) > Medium (edge cases)
5. **Verify hypotheses** - Each root cause needs evidence from at least one source

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
2. **Correlate timeline** - Build event sequence across sources
3. **Identify root causes** - Distinguish symptoms from causes
4. **Assess impact** - Quantify what was affected
5. **Recommend fixes** - High-level fix directions (not solution design)

**Note:** Investigation answers "what happened and why". Solution design happens in `/plan`.

## Closing Investigations

**Auto-close when all "Next Steps" are complete.** When all checkboxes in the investigation.md are
checked off:

1. Create `conclusion.md` in the work item folder (see AGENTS.md for template)
2. Move work item to `work_items/closed/`
3. Report: "Investigation complete. Moved to closed/"

Do NOT wait for user to say "close" - if all action items are done, close it.

---
title: "Investigation: [Bug/Incident Title]"
status: in_progress
created: YYYY-MM-DD
severity: critical | high | medium | low
root_causes_found: 0
evidence_sources: []
---

# Investigation: [Bug/Incident Title]

> **Scope:** This document diagnoses the problem (root cause analysis). Solution design happens
> in `plan.md` after investigation is complete.

## Summary

[1-3 sentence overview of findings. What broke, when, and what was the impact?]

---

## Evidence

### Infrastructure (investigator-render)

[Findings from Render logs, metrics, deployments]

- Key finding 1
- Key finding 2

### Database (investigator-postgres)

[Findings from database queries, health checks]

- Key finding 1
- Key finding 2

### Prefect (investigator-prefect)

[Findings from flow runs, deployments, workers]

- Key finding 1
- Key finding 2

### Codebase (researcher)

[Findings from code analysis, git history, knowledge base]

- Key finding 1
- Key finding 2

---

## Root Causes

| #   | Root Cause | Severity | Evidence | Impact          |
| --- | ---------- | -------- | -------- | --------------- |
| 1   | [Name]     | CRITICAL | [Proof]  | [What it broke] |
| 2   | [Name]     | HIGH     | [Proof]  | [What it broke] |

---

## Detailed Analysis

### 1. [Root Cause Name]

**Location:** [File path, service, or component]
**Trigger:** [What causes this issue]
**Evidence:**

```
[Relevant logs, code, or metrics]
```

**Timeline:**

- [Timestamp]: [Event]
- [Timestamp]: [Event]

---

### 2. [Root Cause Name]

**Location:** [File path, service, or component]
**Trigger:** [What causes this issue]
**Evidence:**

```
[Relevant logs, code, or metrics]
```

---

## Recommended Fix Directions

> **Note:** These are high-level directions based on root cause analysis. Detailed solution
> design (architecture, tradeoffs, verification) happens in `/plan`.

### Priority 1: Critical

1. **[Fix direction]**
   - Root cause addressed: [Which root cause this fixes]
   - General approach: [High-level what needs to change]
   - Risk: [Low/Medium/High]

### Priority 2: High

1. **[Fix direction]**
   - Root cause addressed: [Which root cause this fixes]
   - General approach: [High-level what needs to change]
   - Risk: [Low/Medium/High]

### Priority 3: Medium

1. **[Fix direction]**
   - Root cause addressed: [Which root cause this fixes]
   - General approach: [High-level what needs to change]
   - Risk: [Low/Medium/High]

---

## Hypotheses for Verification

> **Note:** Hypotheses are generated when root cause is uncertain and needs experimental
> verification. Required for BNNN work items (autonomous bug fixes via `/auto-fix`).

| ID  | Hypothesis             | Confidence | Status  |
| --- | ---------------------- | ---------- | ------- |
| H1  | [Name: specific claim] | High       | Pending |
| H2  | [Name: specific claim] | Medium     | Pending |
| H3  | [Name: specific claim] | Low        | Pending |

### H1: [Hypothesis Name]

**Statement:** [Specific claim about root cause]

**Evidence (from investigation):**

- [Observation 1 that supports this hypothesis]
- [Observation 2 that supports this hypothesis]

**Testable Prediction:**
[What we expect to find if this hypothesis is true]

**Evaluation Method:**
[Specific queries, commands, or checks to perform]

**Confidence Level:** High | Medium | Low

**Rationale:**
[Why this confidence level was assigned]

### H2: [Hypothesis Name]

[Repeat structure for additional hypotheses]

---

## Metrics

| Metric                  | Value           |
| ----------------------- | --------------- |
| Total issues identified | X               |
| Critical                | X               |
| High                    | X               |
| Medium                  | X               |
| Time window             | [Start] - [End] |
| Records affected        | X               |

---

## Next Steps

After investigation is complete, run `/plan {id}` to design the solution.

- [ ] Review root causes with stakeholders
- [ ] Run `/plan` to create architecture plan
- [ ] [Additional action items if needed]

---
title: "Hypothesis Evaluation: [Hypothesis Name]"
hypothesis_id: H[N]
work_item: [BNNN or NNN]
date: YYYY-MM-DD
status: pending | evaluating | complete
verdict: pending | CONFIRMED | REFUTED | INCONCLUSIVE
confidence: High | Medium | Low
---

# Hypothesis Evaluation: [Hypothesis Name]

## Hypothesis

**Statement:** [Specific claim about root cause]

**Origin:** investigation.md, hypothesis H[N]

**Pre-evaluation Confidence:** High | Medium | Low

**Rationale for Confidence:**
[Why this confidence level was assigned based on initial evidence]

---

## Pre-Evaluation Evidence

Evidence gathered during investigation that led to this hypothesis:

| Source   | Finding                   | Support Level |
| -------- | ------------------------- | ------------- |
| Logs     | [What was observed]       | Strong/Weak   |
| Database | [What data showed]        | Strong/Weak   |
| Metrics  | [What metrics showed]     | Strong/Weak   |
| Codebase | [What code review showed] | Strong/Weak   |

---

## Testable Prediction

**If this hypothesis is true, we expect:**

1. [Specific observable outcome 1]
2. [Specific observable outcome 2]
3. [Specific observable outcome 3]

**If this hypothesis is false, we expect:**

1. [What would contradict it 1]
2. [What would contradict it 2]

---

## Evaluation Plan

### Primary Check

**Method:** [Data query / Metrics analysis / Log search / Flow inspection]

**Tool:** [Postgres MCP / Render MCP / CLI / Web Search]

**Specific Query/Command:**

```sql
-- or bash, or other format
[The exact query or command to run]
```

**Expected Result if CONFIRMED:**
[What the output should show]

**Expected Result if REFUTED:**
[What the output should show]

### Corroborating Check (Optional)

**Method:** [Secondary verification approach]

**Specific Query/Command:**

```sql
[The exact query or command to run]
```

---

## Evaluation Results

### Primary Check

**Executed:** YYYY-MM-DD HH:MM UTC

**Actual Result:**

```
[Raw output from the check]
```

**Interpretation:**
[What this result means for the hypothesis]

### Corroborating Check

**Executed:** YYYY-MM-DD HH:MM UTC

**Actual Result:**

```
[Raw output from the check]
```

**Interpretation:**
[What this result means for the hypothesis]

---

## Verdict: [CONFIRMED | REFUTED | INCONCLUSIVE]

### Summary

[1-2 sentence summary of the verdict and key evidence]

### Evidence Assessment

| Check         | Result    | Supports Hypothesis? |
| ------------- | --------- | -------------------- |
| Primary Check | [outcome] | Yes / No / Partial   |
| Corroborating | [outcome] | Yes / No / Partial   |

### Causal Chain (if CONFIRMED)

1. [Event/condition 1]
2. [Led to event/condition 2]
3. [Which caused the observed failure]

### Contradicting Evidence (if REFUTED)

- [Evidence that contradicts the hypothesis]
- [Why this rules out the hypothesis]

### Uncertainty (if INCONCLUSIVE)

- [What remains unknown]
- [What additional information would help]

---

## Impact on Fix

**If CONFIRMED:**
[How this should inform the fix in plan.md]

**Priority for addressing:** High | Medium | Low

**Related hypotheses:**
[Any other hypotheses that should be re-evaluated based on this result]

---

## Raw Evidence Appendix

### Log Excerpts

```
[Relevant log snippets]
```

### Query Results

```
[Full query output if too long for inline]
```

### Metrics Data

```
[Metrics snapshots or time-series data]
```

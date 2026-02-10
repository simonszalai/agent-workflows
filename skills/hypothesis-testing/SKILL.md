---
name: hypothesis-testing
description: Methodology for hypothesis quality, confidence levels, evaluation methods, and verdict criteria.
---

# Hypothesis Testing Methodology

Systematic approach to formulating and evaluating hypotheses during bug investigation. Used by
investigator agents and the hypothesis-evaluator agent.

## Purpose

Bug investigations often identify multiple possible causes. This methodology ensures:

1. **Hypotheses are testable** - Each has a concrete verification method
2. **Confidence is calibrated** - Based on evidence strength
3. **Verdicts are defensible** - Clear criteria for confirmation/refutation
4. **Evidence is preserved** - Full documentation of evaluation

## When to Use

- After `/investigate` generates initial hypotheses
- Before `/plan` to confirm the root cause
- In autonomous `/auto-fix` workflows

## Hypothesis Quality Criteria

### Good Hypotheses

A quality hypothesis must be:

| Criterion          | Description                                   | Example                                       |
| ------------------ | --------------------------------------------- | --------------------------------------------- |
| **Specific**       | Names exact component, condition, or behavior | "Memory exhaustion during batch >500 items"   |
| **Testable**       | Has observable prediction                     | "Memory spikes to >1GB when batch size >500"  |
| **Falsifiable**    | Can be proven wrong                           | "If memory stays flat, hypothesis is refuted" |
| **Evidence-based** | Grounded in observed data                     | "Based on OOM logs at 14:23 UTC"              |

### Poor Hypotheses (Avoid)

- **Vague:** "Something is wrong with the system"
- **Unfalsifiable:** "It might be a timing issue sometimes"
- **Speculative:** "Maybe the API changed" (with no evidence)

## Hypothesis Structure

Each hypothesis document must include:

```markdown
## Hypothesis: [Short Name]

**Statement:** [Specific claim about root cause]

**Evidence (Pre-evaluation):**

- [Observation 1 that supports this hypothesis]
- [Observation 2 that supports this hypothesis]

**Testable Prediction:**
[What we expect to find if this hypothesis is true]

**Evaluation Method:**
[Specific queries, commands, or checks to perform]

**Confidence Level:** High | Medium | Low

**Rationale for Confidence:**
[Why this confidence level was assigned]
```

## Confidence Levels

### High Confidence

**Definition:** Strong direct evidence, clear causal link

**Characteristics:**

- Error message explicitly states the cause
- Metrics show clear anomaly at incident time
- Code path directly leads to failure mode
- Multiple independent sources confirm

**Examples:**

- OOM killer log says "Killed process, memory exceeded limit"
- Stack trace shows exact line of failure
- Database constraint violation error

### Medium Confidence

**Definition:** Circumstantial evidence, plausible causal link

**Characteristics:**

- Timing correlation without direct proof
- Pattern matches known failure mode
- Single source of evidence
- Some alternative explanations possible

**Examples:**

- Memory increased significantly near failure time
- Similar errors occurred in past with this cause
- Code review suggests vulnerability

### Low Confidence

**Definition:** Weak evidence, speculative link

**Characteristics:**

- Based on absence of evidence elsewhere
- Theoretical possibility without data
- Conflicting evidence exists
- Requires assumptions

**Examples:**

- "It's not X, so it must be Y"
- "This could happen under race conditions"
- "The third-party API might have changed"

## Evaluation Methods

### Data Correlation (Database)

**When to use:** Hypothesis involves data state, record counts, or database behavior

**Techniques:**

```sql
-- Check state at incident time
SELECT * FROM table WHERE created_at BETWEEN $start AND $end;

-- Compare before/after
SELECT COUNT(*) FROM table WHERE status = 'failed' AND created_at > $incident_time;

-- Find anomalies
SELECT date_trunc('hour', created_at), COUNT(*)
FROM table
GROUP BY 1
ORDER BY 2 DESC;
```

### Metrics Analysis (Infrastructure)

**When to use:** Hypothesis involves resource exhaustion, performance, or infrastructure

**Techniques:**

- CPU/memory metrics at incident time
- Request latency spikes
- Connection pool exhaustion
- Deploy timing correlation

### Log Analysis

**When to use:** Hypothesis involves error patterns, stack traces, or runtime behavior

**Techniques:**

- Search for specific error messages
- Filter by time window around incident
- Pattern matching across instances
- Aggregate error counts by type

### Code Review

**When to use:** Hypothesis involves logic errors, race conditions, or configuration

**Techniques:**

- Trace code paths that lead to failure
- Check for missing error handling
- Review recent changes in affected area
- Analyze concurrency patterns

## Verdict Criteria

### CONFIRMED

**Definition:** Evidence strongly supports the hypothesis

**Requirements:**

- Direct evidence matches prediction
- No contradicting evidence found
- Causal mechanism is clear
- Reproduces reliably (if applicable)

**Documentation:**

```markdown
## Verdict: CONFIRMED

**Evidence Found:**

- [Specific finding 1 matching prediction]
- [Specific finding 2 matching prediction]

**Causal Chain:**
[Step-by-step explanation of how this caused the failure]

**Confidence:** High
```

### REFUTED

**Definition:** Evidence contradicts the hypothesis

**Requirements:**

- Prediction was not observed
- Alternative cause explains evidence better
- Direct contradiction found
- Hypothesis would require impossible conditions

**Documentation:**

```markdown
## Verdict: REFUTED

**Evidence Against:**

- [Finding that contradicts prediction]
- [Why hypothesis cannot be true]

**Alternative Explanation:**
[What the evidence actually suggests]
```

### INCONCLUSIVE

**Definition:** Insufficient evidence to confirm or refute

**Requirements:**

- Prediction partially observed
- Evidence is ambiguous
- Multiple interpretations possible
- Data unavailable for verification

**Documentation:**

```markdown
## Verdict: INCONCLUSIVE

**Partial Evidence:**

- [What was found]
- [What remains unclear]

**Blocking Factors:**
[Why a definitive verdict cannot be reached]

**Recommended Follow-up:**
[What additional investigation would help]
```

## Evaluation Process

### Step 1: Gather Existing Evidence

Before running new queries, compile what's already known:

- Error messages from logs
- Metrics already collected
- Database state observations
- User reports and context

### Step 2: Design Verification

For each hypothesis, define:

1. **Primary check** - The main test for the prediction
2. **Corroborating check** - Secondary evidence if available
3. **Ruling-out check** - What would refute this hypothesis

### Step 3: Execute Verification

Run checks in order of confidence level (high first):

1. High-confidence hypotheses - Quick win if confirmed
2. Medium-confidence hypotheses - May confirm or refute
3. Low-confidence hypotheses - Only if others fail

### Step 4: Document Results

For each hypothesis, create evaluation document:

- Store in `hypothesis-evaluation/hypothesis-NN-name.md`
- Use template from `templates/evaluation.md`
- Include all evidence (positive and negative)
- State clear verdict

### Step 5: Synthesize

After all evaluations:

1. **One confirmed:** Use as root cause for `/plan`
2. **Multiple confirmed:** Document all, prioritize for fix
3. **None confirmed:** Use highest-confidence INCONCLUSIVE
4. **All refuted:** Return to investigation phase

## Integration with Auto-Fix

In `/auto-fix` workflow:

```
/investigate -> generates hypotheses -> hypothesis-evaluator agent -> verdicts
                                                                      |
                    /plan uses confirmed hypothesis <- synthesis <-----+
```

## Templates

- `templates/evaluation.md` - Hypothesis evaluation document template

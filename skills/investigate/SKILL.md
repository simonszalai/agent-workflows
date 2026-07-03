---
name: investigate
description: Investigate bugs and incidents to find root causes. NOT for new features.
---

# Investigate

Spawn investigator agents to diagnose bugs and incidents. Focused on finding **root causes**
of problems, not designing solutions.

**For new features:** Skip this command and use `/auto-plan` directly.

## Usage

```
/investigate "Service failing with timeout error"
/investigate B0003                             # Existing bug ticket
/investigate 009                               # Legacy NNN format
/investigate B0003 --deep                      # Force heavyweight workflow (multi-angle hypothesis + skeptics)
/investigate B0003 --light                     # Force single-investigator path
/investigate B0003 --solo                      # Skip peer providers (current runner only)
```

## When to Use

| Situation                     | Use `/investigate`? | Instead Use             |
| ----------------------------- | ------------------- | ----------------------- |
| Bug: something is broken      | Yes                 | -                       |
| Incident: unexpected behavior | Yes                 | -                       |
| New feature                   | **No**              | `/auto-plan` directly        |
| Understanding existing code   | **No**              | `/auto-plan` (will research) |

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## Ticket Setup

**If ticket ID given** (e.g., `B0003`):

```
mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```

- Read the source artifact for context
- If status is `backlog`, update to `in_progress`:
  ```
  mcp__autodev-memory__update_ticket(
    project=PROJECT, ticket_id=ID, repo=REPO,
    status="in_progress", command="/investigate"
  )
  ```

**If starts with `F`:** **STOP** — features don't use `/investigate`. Tell the user:

> "Features don't need investigation - use `/auto-plan F0009` directly."

**If description given** (no ID): Create a new bug ticket:

```
mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="<synthesized title>",
  type="bug",
  description="<user's description>",
  status="in_progress",
  command="/investigate"
)
```

## Environment Detection

Parse the environment from the user's prompt. Look for keywords:

| Keyword                          | Environment | Default |
| -------------------------------- | ----------- | ------- |
| "in staging", "staging"          | staging     |         |
| "in prod", "production"          | prod        | Yes     |
| "in local", "locally", "dev"     | local       |         |

**If no environment keyword is found, default to `prod`.**

**Pass the environment explicitly to every sub-agent** in the Task prompt.

## Tool-Skill Bootstrap (Required Before MCP)

Before using any infrastructure, database, or external-service MCP tool, load the
matching `tool-*` skill if one exists. These skills contain required bootstrap
steps, safety rules, and known MCP gotchas. **Do not call the MCP directly first.**

Examples:

| MCP area | Required skill first | Why |
| --- | --- | --- |
| Render services/logs/metrics/Postgres | `tool-render` | Workspace bootstrap and log/metric patterns |
| Postgres MCP/database investigation | `tool-postgres` | Read-only/safety/query patterns |

For Render investigations, always load `tool-render` before `mcp__render__*`.
Run its workspace bootstrap first (currently `list_workspaces`; if there is a
single workspace it auto-selects it). If multiple workspaces are returned, stop
and ask the user which workspace to use; do not call `select_workspace`
autonomously.

## Agent Selection

Choose agents based on problem symptoms (the dispatch table lists the available investigator agents).

| Symptoms                                  | Agent                    | Why                   |
| ----------------------------------------- | ------------------------ | --------------------- |
| crash, OOM, memory, timeout, deploy       | `investigator`           | Infrastructure issues |
| connection, query, data, records, missing | `investigator`           | Database state        |
| code, bug, why, pattern, history          | `researcher`             | Codebase & knowledge  |

**Spawn only what's needed.** Most bugs need 2-3 agents, not all available agents.

## Process: Root-Cause-First Methodology

Follow this discipline strictly. The goal is to **confirm the root cause before
recommending a fix**. Premature fixes based on symptoms cause regressions.

1. **Reproduce** - Confirm the failure is real and current
   - Check Prefect flow runs, logs, or DB state to confirm the symptom
   - If the failure is intermittent, gather timing/frequency data
   - Document the exact error message, stack trace, or observable behavior

2. **Trace backward** - Follow the causal chain from symptom to origin
   - Start from the error and trace upstream: what called this? what data
     was passed? what state was expected vs actual?
   - Check deployment correlation: did failures start after a recent commit?
     If so, **suspect the new code first** before blaming external services
   - Search autodev-memory for similar past incidents:
     ```
     mcp__autodev-memory__search(
       queries=[{"keywords": ["<error area>"], "text": "<error message>"}],
       project=PROJECT
     )
     ```

3. **Decide the execution path — complexity gate:**

   The heavy path runs the `investigate-fanout` workflow: parallel hypothesis generators
   from different angles (stack-trace, recent-commits, code-pattern, data-state), dedup
   with cross-angle confidence boost, parallel evidence gathering, and adversarial
   skeptics on confirmed hypotheses. Premature convergence on the wrong root cause causes
   regressions, so for ambiguous or high-stakes bugs the skeptic pass is the load-bearing
   step.

   Use this gate (top-to-bottom, first match wins):

   | Condition                                                              | Path  |
   | ---------------------------------------------------------------------- | ----- |
   | User passed `--deep`                                                    | Heavy |
   | User passed `--light`                                                   | Light |
   | Bug description contains "intermittent", "flaky", "race", "only in"     | Heavy |
   | Bug already had a prior /investigate that didn't find the root cause    | Heavy |
   | Production incident (environment: prod)                                 | Heavy |
   | Clear stack trace pointing to a specific line + single-component scope  | Light |
   | Otherwise                                                               | Light |

   Announce the chosen path:

   ```
   Path: heavy (production incident — investigate-fanout workflow with skeptics)
   ```

4. **Fan out — light path (inline):**

   When the gate selects "Light", pick 2-3 relevant agents from the dispatch table below
   and spawn them in parallel (single message, multiple `Agent` tool-use blocks). Brief
   each with the symptom and the backward trace so far. Each agent returns hypotheses
   matching `hypothesisSchema` in `workflows/investigate-fanout.js` — validate against
   the required fields (`statement`, `evidence`, `testable_prediction`, `category`,
   `initial_confidence`).

   No dedup phase, no separate skeptic pass — but you should still apply the methodology
   in step 5+ below (test predictions, attempt to refute the strongest hypothesis, gate
   the causal chain). Assemble the same return shape as the heavy path with empty
   `skeptic_verdicts` arrays and zero-filled stats for the heavy-only fields.

   Skip steps 4a-4b below — those are for the heavy path only.

4a. **Fan out — heavy path (workflow):**

   When the gate selects "Heavy", invoke the workflow by name:

   If the current host tool does not expose Claude's `Workflow` tool (for example a
   Codex/Grok-orchestrated run), execute the equivalent heavy-path investigation inline: fan out
   the hypothesis angles the host supports, run the two peer providers in step 4c, dedup
   hypotheses, run skeptic/testing loops where available, and assemble the same result shape. Do
   **not** downgrade to a one-provider investigation just because the Claude `Workflow` primitive
   is absent.

   ```
   result = Workflow({
     name: "investigate-fanout",
     args: {
       bug: "<bug description from source artifact + user input>",
       environment: "prod" | "staging" | "local",
       errorEvidence: "<stack trace / log lines / observed behavior, if collected>",
       angles: [
         { key: "stack-trace", description: "..." },
         { key: "recent-commits", description: "..." },
         { key: "code-pattern", description: "..." },
         { key: "data-state", description: "..." },
         // Workflow defaults to these four if angles omitted.
       ],
       repoRoot: "<absolute path>",
       mode: "interactive" | "headless",
       testTopN: 6
     }
   })
   ```

4b. **Result shape (both paths produce this object):**

   ```
   {
     bug: "...",
     environment: "...",
     root_cause: {
       statement, confidence, evidence_summary, survived_skeptics
     } | null,                              // null is HONEST — do not invent
     causal_chain: ["trigger", ..., "symptom"],   // no gaps allowed
     recommended_remediation: "short paragraph; this is /investigate not /auto-plan",
     hypotheses: [
       { id, statement, category, source_angles, initial_confidence,
         verdict, final_confidence, evidence_gathered, skeptic_verdicts }
     ],
     refuted_hypotheses: [{ statement, why_refuted }],
     inconclusive_hypotheses: [{ statement, what_still_needs_checking }],
     residual_unknowns: [...],
     stats: { angles_attempted, raw_hypotheses, after_dedup, tested,
              confirmed, refuted_in_test, inconclusive_in_test,
              skeptic_attempts, root_cause_found }
   }
   ```

   The light path must zero-fill heavy-only stats fields. Downstream steps 5+ must not
   branch on path. Specifically: if `result.root_cause` is null, downstream MUST honor
   that — do not draft a fix in the artifact based on an unconfirmed hypothesis.

4c. **Cross-provider hypothesis generators (on by default — both paths):**

   After the chosen path produces its hypotheses (light: inline agents; heavy: the
   `investigate-fanout` workflow), add the two providers that are not the current main workflow
   runner as additional, independent hypothesis generators **unless** the user passed `--solo`.
   If Claude runs the workflow, run Codex + Grok; if Codex runs it, run Claude + Grok; if Grok
   runs it, run Claude + Codex. A root cause that a peer provider surfaces independently is a
   strong signal; one that only the main runner proposed deserves more skeptical testing. This
   is a required step, not optional — you MUST actually run the commands below and read the
   files they write. Do NOT simulate what another provider "would" say.

   Peer providers run through the `external-agent` adapter (`bin/external-agent` in
   agent-workflows, symlinked onto `PATH`). Claude peers use subscription-backed `claude -p`,
   never direct Anthropic API calls. Codex and Grok peers run read-only with repo access. Each
   returns a generator envelope
   `{generator_key, angle, hypotheses, notes}` whose hypothesis items match `hypothesisSchema`
   in `workflows/investigate-fanout.js` — the same shape your inline/workflow generators
   produce, so they merge with no special-casing.

   Dispatch both in parallel (1–3 min each — never serialize):

   ```bash
   mkdir -p .context/investigate
   # Write the bug symptom + collected error evidence to a file so it survives shell quoting.
   #   .context/investigate/bug.txt       = one-line symptom/description
   #   .context/investigate/evidence.txt  = stack trace / log lines / observed behavior
   BUG="$(cat .context/investigate/bug.txt)"
   for provider in $(agent-workflow-provider --peers); do
     external-agent --task investigate --provider "$provider" --bug "$BUG" \
       --evidence-file .context/investigate/evidence.txt --environment "$ENV" \
       --out ".context/investigate/${provider}.json" 2>".context/investigate/${provider}.log" &
   done
   wait
   ```

   Then fold both envelopes into the hypothesis set:

   1. Read the two `.context/investigate/<provider>.json` files for the peer providers. A
      provider that failed still returns a valid envelope with empty `hypotheses` and a note —
      surface the note but do not block.
   2. Merge each external hypothesis into the path's hypothesis list. Dedup against existing
      hypotheses by `(normalized statement, category)`; when an external hypothesis matches a
      main-runner one, record the agreement (add the provider to its `source_angles`) and bump
      confidence modestly — independent cross-provider agreement is corroborating evidence.
   3. Tag genuinely new external hypotheses with `source_angles: ["external:<provider>"]` so
      step 5+ tests them like any other. The honest-null rule still holds: an unconfirmed
      external hypothesis is NOT a root cause until its testable_prediction is verified.

   `.context/investigate/*.json` are ephemeral inter-agent scratch consumed immediately by the
   testing phase — correct use of `.context/` per the File Storage Rules.

**Reference: Agent Dispatch Table** (for the light path)

Choose agents based on problem symptoms (the dispatch table lists the available investigator agents).

Before any evidence-gathering MCP call in steps 1-3, apply **Tool-Skill
Bootstrap** above. If the first MCP call returns a known bootstrap/setup error
(for example Render says "no workspace set"), do not treat it as a blocker until
you have checked the matching `tool-*` skill.

4. **Collect and synthesize** - Wait for all agents, build the causal chain

5. **Form hypotheses with testable predictions**
   - For each hypothesis, define: "If this is the root cause, then we
     expect to see X when we check Y"
   - **Every hypothesis needs a prediction that can be confirmed or refuted**
   - Predictions must be specific and falsifiable, not vague

6. **Test predictions before concluding**
   - Execute the verification for each hypothesis
   - For high-confidence hypotheses: run the primary check
   - For medium-confidence: run primary + corroborating checks
   - For low-confidence: only pursue if higher-confidence hypotheses fail
   - **Do not conclude root cause without at least one confirmed prediction**

7. **Boundary-contract minimization** — For timeouts, provider/API failures,
   integration failures, or "only fails in env X" bugs, isolate the exact
   artifact crossing the failing boundary before blaming runtime infrastructure:
   - Capture what is actually sent after framework serialization/transforms
     (examples: generated SQL, JSON Schema, HTTP/gRPC payload, headers,
     prompt/tool declarations, queue/webhook body, env-expanded config).
   - Reproduce as directly as possible against the downstream component: remove
     proxies, orchestrators, caches, retries, and optional tools unless each is
     the variable under test.
   - Minimize to a tiny failing contract, then run an A/B test where exactly one
     feature changes while input, target, version, and timeout stay fixed.
   - If staging fails and prod works, diff the emitted artifacts and deployed
     code/data, not just the topology. Env correlation is not proof of infra
     causation.
   - Treat "direct minimized repro has the same symptom" as evidence against the
     removed infrastructure being causal.

8. **Causal chain gate** — Do NOT proceed to writing the artifact until you can
   explain the full causal chain from trigger to symptom with **no gaps**:
   - Trigger → [each intermediate step] → Observed symptom
   - "Somehow X leads to Y" is a gap — fill it or flag it
   - For obvious chains (missing import, clear null deref): the chain itself is
     the gate — no prediction needed
   - For uncertain links: a prediction about something in a *different* code path
     that must also be true if this link is correct
   - **If a prediction was wrong but a fix appears to work, you found a symptom,
     not the root cause** — the real cause is still active

9. **Smart escalation** — If 2-3 hypotheses are exhausted without confirmation:

   | Pattern | Diagnosis | Next move |
   | ------- | --------- | --------- |
   | Hypotheses point to different subsystems | Architecture/design problem | Present findings, suggest `/auto-plan` for redesign |
   | Evidence contradicts itself | Wrong mental model of the code | Re-read the code path without assumptions |
   | Works locally, fails in prod/staging | Environment problem | Focus on env differences, config, timing |
   | Fix works but prediction was wrong | Symptom fix, not root cause | Keep investigating — real cause still active |

   Present the diagnosis before proceeding. Do not keep trying blindly.

10. **Write investigation artifact** with confirmed root causes and evidence

11. **Capture knowledge** - Store non-obvious findings in memory service

12. **Report to the user** — end with a short summary: a 1-3 sentence statement of the
    problem (and confirmed root cause), followed by **one or more proposed fixes**. See
    the Output section for the required shape. Keep it concise — the detail lives in the
    artifact, not the final message.

## Writing the Investigation Artifact

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="investigation",
  content="<investigation content with root causes, evidence, hypotheses>",
  command="/investigate"
)
```

## Knowledge Capture (Step 6)

After writing the investigation artifact, persist non-obvious findings:

```
# 1. Search for duplicates first
mcp__autodev-memory__search(
  queries=["<root cause keywords>"],
  project=PROJECT
)

# 2. If no duplicate, store the finding
mcp__autodev-memory__create_entry(
  project=PROJECT,
  title="<1-sentence root cause summary>",
  content="<Root cause explanation, evidence, and fix direction. 200-800 tokens.>",
  entry_type="gotcha",
  summary="<1-sentence summary>",
  tags=["<area>", "<technology>"],
  source="captured",
  caller_context={
    "skill": "investigate",
    "reason": "<why this is worth persisting>",
    "action_rationale": "New entry — no existing entry covers this root cause",
    "trigger": "investigation finding"
  }
)
```

If the MCP tool is unavailable, skip this step silently.

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

## Hypothesis Generation

After collecting evidence from all agents, generate testable hypotheses:

### When to Generate Hypotheses

- **Always for B-prefix tickets** (autonomous bug fixes via `/lfg` or `/auto-flow`)
- **Optional for other bugs** - generate when root cause is uncertain
- **Never for F-prefix tickets** (features don't use investigation)

### Hypothesis Format

Include in the investigation artifact after Root Causes section:

```markdown
## Hypotheses for Verification

| ID  | Hypothesis             | Confidence | Status  |
| --- | ---------------------- | ---------- | ------- |
| H1  | [Name: specific claim] | High       | Pending |
| H2  | [Name: specific claim] | Medium     | Pending |

### H1: [Hypothesis Name]

**Statement:** [Specific claim about root cause]
**Causal Chain:** [Trigger] → [Step 1] → [Step 2] → [Observed symptom]
**Uncertain Links:** [Which steps in the chain are unconfirmed, if any]
**Evidence:** [Observations supporting this]
**Testable Prediction:** [What we expect if true — something in a DIFFERENT code path]
**Evaluation Method:** [Specific queries/checks to test the prediction]
**Confidence Level:** High | Medium | Low
**Status:** Pending | Confirmed | Refuted
```

### Confidence Level Guidelines

| Level      | Criteria                                                         |
| ---------- | ---------------------------------------------------------------- |
| **High**   | Direct evidence (error message, stack trace, OOM log)            |
| **Medium** | Circumstantial evidence (timing correlation, similar past issue) |
| **Low**    | Speculative (process of elimination, theoretical possibility)    |

## Output

The investigation artifact contains:

- Root causes identified
- Evidence from each source
- Severity assessment
- Recommended fixes (high-level)
- Hypotheses for verification (when applicable)

### Final message to the user (required)

After writing the artifact, your last message MUST be a short summary in this shape:

```markdown
**Problem:** <1-3 sentences: the symptom and the confirmed root cause.>

**Proposed fixes:**
1. <Option A — concise, one line of what + why.>
2. <Option B — if there is a meaningful alternative.>
```

- Always give **at least one** proposed fix; give more only when there are genuinely
  distinct options (e.g. "accept as noise" vs. "add targeted resilience").
- If `root_cause` is null (unconfirmed), say so plainly and frame the fixes as
  "next diagnostic steps" rather than fixes — do not invent a fix for an unconfirmed cause.
- Keep it tight: this is a pointer to the artifact, not a duplicate of it. The full
  **solution design** still happens in `/auto-plan`, not here.

---

# Investigation Methodology

Standards for conducting **bug and incident investigations** and producing investigation
artifacts.

## Sub-Agent Behavior (CRITICAL)

**Sub-agents (investigator, investigator-prefect) must:**

- **RETURN findings directly** in your response - do NOT create files
- The parent agent will synthesize all findings into a single investigation artifact
- Never create local work_items folders or investigation files yourself

**Only the orchestrating agent** (invoked via `/investigate {number}`) writes the final
investigation artifact to the ticket via `mcp__autodev-memory__create_artifact`.

## Output Template

Use the template at `templates/investigation.md` for output format.

**Formatting:** Limit lines to 100 chars (tables exempt).

## Synthesis Methodology

When combining findings from multiple sources:

1. **Correlate timestamps** - Match events across sources (logs, DB records, flow runs)
2. **Check cross-service correlation** - If multiple independent services fail
   simultaneously, investigate shared infrastructure (proxy, DB, network) before
   per-service causes. Error messages from individual services may assume a cause
   (e.g., "anti-bot challenge") that is actually a shared infrastructure failure.
3. **Follow causation** - Infrastructure issues -> flow failures -> data state
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

**Note:** Investigation answers "what happened and why". Solution design happens in `/auto-plan`.

## Closing Investigations

**Auto-close when all "Next Steps" are complete.** When all checkboxes in the investigation
are checked off:

1. Create a conclusion artifact on the ticket via `mcp__autodev-memory__create_artifact`
2. Update ticket status to `completed` via `mcp__autodev-memory__update_ticket`
3. Report: "Investigation complete. Ticket closed."

Do NOT wait for user to say "close" - if all action items are done, close it.

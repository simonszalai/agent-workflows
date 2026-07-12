---
name: investigate
description: Investigate bugs and incidents to find root causes. NOT for new features.
---

# Investigate

Spawn investigator agents to diagnose bugs and incidents. Focused on finding **root causes**
of problems, not designing solutions.

Follow `../references/execution-economy.md`; economy never permits an unconfirmed root cause.

Before any conditional external peer call, create its bounded memory packet (once per provider):

```bash
if ! cat .context/investigate/bug.txt .context/investigate/evidence.txt | \
  autodev-memory-task-packet --cwd "$PWD" --session-id "${SESSION_ID:-}" \
    --agent-type investigator --provider "$provider" --mechanism external_peer \
    --task-prompt-stdin --allow-unavailable > "$MEMORY_PACKET"; then
  printf '%s\n' '<autodev-memory-task-context>Memory context is unavailable.</autodev-memory-task-context>' \
    > "$MEMORY_PACKET"
fi
```

Pass `--memory-context-file "$MEMORY_PACKET"` to `external-agent --task investigate`.

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

**Spawn only what's needed.** Routine bounded bugs use the single light-path agent. Heavy-path
incidents use only the 2–3 distinct evidence roles justified by their symptoms, never every role.

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

3. **Decide the execution path and provider escalation:**

   Light means genuinely light: one native investigator, one bounded task packet, no workflow
   fanout, no peer provider, and no skeptic panel. Heavy means native multi-angle hypotheses and
   skeptic/testing loops. Peer providers are a separate escalation, not a default tax.

   Use this path gate (top-to-bottom, first match wins):

   | Condition | Path |
   | --- | --- |
   | User passed `--deep` | Heavy |
   | User passed `--light` | Light |
   | Intermittent/race/flaky behavior or a prior inconclusive investigation | Heavy |
   | Safety-critical incident: security, auth, billing, destructive data risk, or broad production outage | Heavy |
   | Clear stack trace + one component, or otherwise bounded routine defect | Light |
   | Material uncertainty remains after the native prediction tests | Heavy |
   | Otherwise | Light |

   Escalate to peer providers only when one of these is recorded in the run:

   - the user explicitly requested cross-provider analysis;
   - the safety-critical condition above applies;
   - native evidence leaves two plausible root causes or a material causal-chain gap; or
   - native agents/skeptics materially disagree about a prediction or verdict.

   `--solo` disables peer escalation but never removes native skeptic/testing coverage required
   for safety-critical incidents. Announce path and escalation separately, for example:

   ```text
   Path: light (bounded single-component defect); peers: no trigger
   Path: heavy (security-sensitive incident); peers: escalated for safety-critical risk
   ```

4. **Run the selected investigation:**

   **Light:** spawn exactly ONE relevant native agent from the dispatch table with
   `fork_turns: "none"` and a self-contained packet containing symptom, environment, collected
   evidence, exact paths/systems to inspect, prediction schema, output cap, and expected return
   shape. The agent may use multiple tools, but it must not recruit more roles. Test and attempt
   to refute its leading hypothesis inline. A null root cause is valid.

   **Heavy:** run `investigate-fanout` with bounded native angles, or its inline equivalent when
   the Workflow primitive is unavailable. Deduplicate hypotheses, test predictions, and run
   skeptics on the strongest confirmed candidates. Do not downgrade safety coverage because a
   host lacks the Workflow primitive.

   Both paths return the same object:

   ```text
   {
     bug, environment,
     root_cause: { statement, confidence, evidence_summary, survived_skeptics } | null,
     causal_chain: ["trigger", ..., "symptom"],
     recommended_remediation,
     hypotheses: [
       { id, statement, category, source_angles, initial_confidence,
         verdict, final_confidence, evidence_gathered, skeptic_verdicts }
     ],
     refuted_hypotheses, inconclusive_hypotheses, residual_unknowns,
     stats: { angles_attempted, raw_hypotheses, after_dedup, tested,
              confirmed, refuted_in_test, inconclusive_in_test,
              skeptic_attempts, root_cause_found }
   }
   ```

   Light zero-fills heavy-only stats and uses empty `skeptic_verdicts`. Downstream logic must
   honor `root_cause: null`; never draft a fix from an unconfirmed hypothesis.

4a. **Peer-provider escalation (conditional only):**

   When the escalation gate fires and `--solo` was not passed, run the other two providers in
   parallel as independent hypothesis generators through `external-agent --task investigate`.
   Use `fork_turns: "none"` for provider subagents, pass bounded self-contained packets, write
   full output/logs under `.context/investigate/<run-id>/`, and read only their compact envelopes.
   Merge by normalized statement/category, record agreement, and test new predictions exactly like
   native ones. A failed peer is surfaced; it is not silently simulated or replaced. If the gate
   does not fire, do not create provider packets or calls.

   Cross-provider agreement is corroboration, not confirmation. The honest-null and causal-chain
   gates still apply. For a safety-critical investigation, peer unavailability must appear as
   residual risk; native skeptic coverage remains mandatory and the workflow must not claim the
   missing independent review occurred.

   Before any evidence-gathering MCP call, apply **Tool-Skill Bootstrap** above. If the first MCP
   call returns a known bootstrap/setup error (for example Render says "no workspace set"), do not
   treat it as a blocker until you have checked the matching `tool-*` skill.

5. **Boundary-contract minimization** — For timeouts, provider/API failures,
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

6. **Causal chain gate** — Do NOT proceed to writing the artifact until you can
   explain the full causal chain from trigger to symptom with **no gaps**:
   - Trigger → [each intermediate step] → Observed symptom
   - "Somehow X leads to Y" is a gap — fill it or flag it
   - For obvious chains (missing import, clear null deref): the chain itself is
     the gate — no prediction needed
   - For uncertain links: a prediction about something in a *different* code path
     that must also be true if this link is correct
   - **If a prediction was wrong but a fix appears to work, you found a symptom,
     not the root cause** — the real cause is still active

7. **Smart escalation** — If 2–3 hypotheses are exhausted without confirmation:

   | Pattern | Diagnosis | Next move |
   | ------- | --------- | --------- |
   | Hypotheses point to different subsystems | Architecture/design problem | Present findings, suggest `/auto-plan` for redesign |
   | Evidence contradicts itself | Wrong mental model of the code | Re-read the code path without assumptions |
   | Works locally, fails in prod/staging | Environment problem | Focus on env differences, config, timing |
   | Fix works but prediction was wrong | Symptom fix, not root cause | Keep investigating — real cause still active |

   Present the diagnosis before proceeding. Do not keep trying blindly.

8. **Write investigation artifact** with confirmed root causes and evidence

9. **Capture knowledge** - Store non-obvious findings in memory service

10. **Report to the user** — end with a short summary: a 1–3 sentence statement of the
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

## Knowledge Capture

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

After collecting the selected path's evidence, generate testable hypotheses:

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

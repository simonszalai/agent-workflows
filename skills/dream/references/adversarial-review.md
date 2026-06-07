# Adversarial Review — Skeptic Loop Protocol

This is the detailed protocol for Step 8 of the dream skill. The goal: subject every
proposed memory mutation to hostile, evidence-based scrutiny from multiple independent
angles, and let only the proposals that survive reach execution. No human is in the loop,
so the skeptics *are* the safety mechanism — they must be genuinely adversarial.

## The principle

A single proposer (you, after the audit) is prone to motivated reasoning: once you've
decided an entry is stale or two entries are dupes, you look for reasons to act. The
skeptics' job is the opposite — to find any reason **not** to act, and to make you prove
your case with evidence. An action that cannot survive three hostile readings has no
business mutating a shared, production-influencing knowledge store.

Bias is asymmetric on purpose: the cost of wrongly keeping a mediocre entry is a few
tokens; the cost of wrongly deleting a load-bearing one is a reintroduced production bug.
So ties go to the status quo.

## Round structure

Run **up to 3 rounds**. Each round:

### 1. Assemble the candidate packet

For the current candidate list, gather:
- The action id (`A#`), type, target entry/entries, and stated reason.
- The **full current content** of every entry the action touches (don't make critics
  re-fetch — paste it in).
- For MERGE / ABSTRACT / SPLIT / RESCOPE: the proposed *new* content too.
- Any provenance you already traced (creating ticket/commit, `created_at`).

### 2. Spawn three skeptics in parallel

One message, three `Agent` tool-use blocks, `subagent_type: "general-purpose"`. Each gets
the **same** candidate packet but a **different lens** and is told to attack only through
that lens (overlap is fine; blind spots are not):

- **Critic 1 — Information-loss skeptic.** Hunts for anything a destructive or
  consolidating action would silently erase: a case-specific caveat, an exception, a worked
  example, provenance, a WHY. Default suspicion toward DELETE / MERGE / ABSTRACT / SIMPLIFY
  / SPLIT. Question: *"After this runs, what does a future task no longer know that it
  needed?"*
- **Critic 2 — Evidence skeptic.** Re-verifies the *justification* of each action against
  the actual code and the actual entry text. Greps for the symbols an entry references;
  confirms a "removed" function is really gone; confirms two "duplicate" entries truly say
  the same thing. Question: *"Is the stated reason factually true right now?"*
- **Critic 3 — Churn / utility skeptic.** Defends the status quo against low-value edits.
  Attacks cosmetic retags, speculative rescopes, splits that multiply entries, and rewrites
  whose benefit doesn't exceed the risk and review cost of touching the entry. Question:
  *"Is this change worth making at all, or is it motion without value?"*

Brief every critic that **autodev-memory facts flow into production code paths**, so a bad
consolidation has real downstream cost — they should err toward refusal and treat
"uncertain" as "kill". Give them codebase access and the `mcp__autodev-memory__*` tools so
they verify rather than speculate. Tell them: a `KILL` or `AMEND` must cite concrete
evidence (file:line, grep result, the entry's own text, provenance); a bare opinion is not
a valid verdict and you will ignore it.

### 3. Verdict schema

Each critic returns, for **every** action, one object:

```json
{
  "action_id": "A4",
  "verdict": "KILL",                      // PASS | AMEND | KILL
  "severity": "high",                     // low | medium | high  (KILL/AMEND only)
  "objection": "Entry B omits server_default on the audit table on purpose; the abstracted rule would erase that exception and cause a wrong migration.",
  "evidence": "src/models/audit.py:88 — column has no server_default; entry B content notes 'append-only, timestamp set in app'.",
  "safer_alternative": "Abstract A and C only; leave B as a standalone exception entry."  // AMEND only; optional on KILL
}
```

A critic that passes everything must still return a `PASS` object per action with a
one-line reason it survived — this forces them to actually read each one.

### 4. Adjudicate (you, the orchestrator)

For each action, combine the three verdicts:

| Situation | Ruling |
|---|---|
| All three `PASS` | Survives this round (provisionally accepted). |
| Any `KILL` you **cannot** rebut with cited evidence | **Drop the action.** |
| Any `KILL` you **can** rebut with cited evidence | Survives — **log the rebuttal + evidence.** |
| `AMEND` (and no surviving `KILL`) | Rewrite the action to the safer form; it re-enters next round as a new candidate. |
| Destructive action (DELETE/MERGE/ABSTRACT/SPLIT) with **any** unrebutted `KILL` | **Drop** — higher bar; do not try to salvage. |

Rebuttal discipline (principle 12): you may overrule a critic **only** by citing something
concrete. If your rebuttal would be "I still think it's fine," the critic wins. When two
critics disagree (one PASS, one KILL), the KILL controls unless rebutted — skepticism is
the tiebreaker.

### 5. Log

Maintain an **adjudication log** spanning all rounds. Per action: the three verdicts, your
ruling, and the evidence for any rebuttal. This is the audit trail that justifies each
autonomous mutation in Step 9 and populates the "Dropped by critics" section of the report.

### 6. Carry forward / converge

- Amended actions and any actions that drew a verdict this round go into the next round's
  candidate packet (re-scrutinized in their current form).
- Cleanly-passed actions are **also** re-submitted — a fresh round may surface something the
  last one missed.
- **Converge** when a full round returns all-`PASS` on every remaining candidate. Those are
  the final survivors.
- **Cap** at round 3. After round 3:
  - any action still carrying an unrebutted `KILL` → dropped;
  - an action stuck in `AMEND` limbo executes only in its safest proposed form, and only if
    it has no outstanding `KILL`; otherwise dropped.

## Anti-patterns (do not do these)

- **Rubber-stamp round.** If all critics pass everything on round 1, don't take it at face
  value — re-read the destructive actions yourself for missed information loss before
  declaring convergence.
- **Wearing critics down.** Don't re-run rounds hoping the panel eventually relents on an
  action it keeps killing. Three kills is a drop, not a negotiation.
- **Evidence-free rebuttal.** Overruling a KILL with reasoning instead of a citation. Not
  allowed.
- **Lowering the bar to ship.** An empty survivor set is a valid, successful outcome. Report
  "0 actions survived" plainly rather than forcing a marginal change through.
- **Scope creep.** Critics review the proposed actions; they do not propose brand-new
  mutations. New ideas that surface go in the report as observations, not auto-executed.

# Adversarial Review — Deep Dream Skeptic Loop

Phase 3 subjects **every** candidate from all five channels (M, G, P, K, W) to hostile,
evidence-based scrutiny before anything is applied. The skeptics are the safety mechanism: for
the memory channel there is no human in the loop, and for the skill channel they decide what is
even worth presenting at the gate.

This loop **extends** `references/adversarial-base.md` — read that first; it is the base
protocol (round structure, verdict schema, adjudication table, convergence/cap, anti-patterns).
This file adds only the skill-channel deltas.

## What is different from the base protocol

1. **Five channels, not one.** Memory candidates (M, G, memory-side P) get the three base lenses.
   Skill / workflow / CLAUDE.md candidates (K, W, skill-side P) get a **fourth lens** (below) in
   addition — they are the higher-stakes channel.
2. **Aggregate-evidence bar.** K and G candidates claim a *pattern*. A skeptic must check the
   claim: are there really ≥2 independent occurrences with valid locators? A K/G candidate
   resting on a single incident is `KILL` → reroute to `/retrospect`.
3. **Higher bar on the skill channel.** Every skill-file action is treated like a destructive
   memory action: a **single unrebutted `KILL` drops it**. Shared skills propagate everywhere; a
   wrong edit is expensive and not auto-reversible.

## The four lenses

Spawn skeptics in parallel (one message, multiple `Agent` blocks). Memory candidates → lenses
1–3. Skill / migration / CLAUDE.md candidates → lenses 1–3 **plus** lens 4.

1. **Information-loss skeptic** (base) — what would a destructive/consolidating action silently
   erase? Caveats, exceptions, provenance, the WHY.
2. **Evidence skeptic** (base) — is each action's stated reason factually true *right now*? Grep
   the symbols, confirm the "removed" function is gone, confirm two "duplicates" really match,
   confirm the cited session/ticket locator says what the candidate claims.
3. **Churn / utility skeptic** (base) — is the change worth its cost, or motion without value?
   Defends the status quo against cosmetic edits.
4. **Portability / altitude skeptic** (new — skill channel only). Attacks every skill, migration,
   and shared-CLAUDE.md candidate on these grounds:
   - **Project leakage:** does the edit put project-specific detail (table/service/route/repo
     path) into a *shared* skill? If so → `KILL`; the lesson belongs in memory/CLAUDE.md
     (`references/migration-rules.md`). This is the most common bad candidate — hunt for it.
   - **Wrong altitude:** is this a one-off instance dressed up as a reusable method? A method must
     generalize beyond the single case that produced it.
   - **Double-capture:** does the fact already live in another layer (CLAUDE.md, a starred entry,
     another skill, the code itself)? Adding it again is drift, not improvement.
   - **Skill bloat / contradiction:** does the new checklist line duplicate an existing one,
     contradict another step in the same skill, or contradict a *different* skill's guidance?
   - **Unsound cross-skill claim:** if the candidate asserts "skill X already covers Y" or "skill
     A and B overlap", verify by reading both — don't take the orchestrator's word.
   - **Aggregate-evidence check:** for K/G, confirm the ≥2-independent-occurrence claim against the
     cited locators.

Brief every critic: these memory facts **and** these skills drive production work across every
project and every machine, so a bad consolidation has real downstream cost. Default to `KILL` on
uncertainty. A `KILL`/`AMEND` must cite concrete evidence (`file:line`, grep, entry text, the
session/ticket locator, provenance); a bare opinion is ignored.

## Adjudication deltas

Use the base protocol's adjudication table, with these overrides:

| Situation | Ruling |
|---|---|
| Any skill-channel action (K, W, skill-side P, shared-CLAUDE.md) with **any** unrebutted `KILL` | **Drop** — single-kill bar, like destructive memory actions. |
| Lens-4 `KILL` for project leakage into a shared skill | **Drop** the skill edit; if the lesson is real, convert it into a memory/CLAUDE.md candidate for the next round (don't auto-apply — it's a new action). |
| K/G candidate whose aggregate-evidence claim fails (only 1 occurrence) | **Drop**; note in the report that it's a `/retrospect`-scale item, not a deep-dream pattern. |
| `AMEND` proposing "skill edit → memory edit instead" | Rewrite as the safer-layer action; it re-enters next round in the correct channel. |

## Cross-channel ordering at apply time (re-checked here)

A migration that spans both channels (e.g. "promote entry X's method into skill Y, then delete
X") must survive as a **pair**. If the skill-side edit is killed or gated-but-unapproved, the
memory-side deletion **does not run** — never retire the source before the destination is durable.
The skeptics flag any P pair whose two halves don't both survive.

## Anti-patterns (in addition to the base protocol's)

- **Treating a skill edit like a memory edit.** Skill edits are higher-stakes and gated; they
  never auto-apply just because they passed lenses 1–3. Lens 4 and the single-kill bar apply.
- **Letting the orchestrator's cross-skill claims stand unverified.** "Skill A already says this"
  is a factual claim the evidence skeptic must confirm by reading skill A.
- **Promoting an instance.** One session's mistake is not a method. If it happened once, it's a
  retrospect item, not a skill checklist line.

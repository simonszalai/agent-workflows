# Migration Rules — Which Layer Should Hold This Knowledge?

The **P channel** (promote / migrate) is what makes deep-dream more than five audits stapled
together. It moves a piece of knowledge to the layer where it actually belongs. This file is the
decision logic. Every P candidate must name the **from-layer**, the **to-layer**, and the rule
below that justifies the move.

## The layers

| Layer | Holds | Always in context? | Edited via |
|---|---|---|---|
| **L1 · CLAUDE.md** (project) | project conventions: stack, branch policy, repo layout, structural rules | Yes — auto-loaded | file edit + commit (project repo) |
| **L1g · agent-workflows/CLAUDE.md** | universal cross-project conventions (code style, agent rules) | Yes — auto-loaded | file edit + commit+push (shared) |
| **L2 · Starred memory** | critical self-contained rules/gotchas that must always apply | Yes — auto-injected with CLAUDE.md authority | `star_entry` / `unstar_entry` |
| **L3 · Memory (unstarred)** | detailed gotchas, solutions, references, patterns; **project/repo-specific** | No — surfaced by search | `create/update/supersede/delete_entry` |
| **Skill** | **portable methodology** — the reusable HOW: checklists, procedures, references | Loaded when the skill runs | file edit + commit+push (shared) |

The two anchoring facts that drive every rule:

- **A skill is a method, not a fact.** Per `agent-workflows/CLAUDE.md`, shared skills contain
  **zero** project-specific detail (no table names, service ids, routes, repo paths). If a lesson
  can't be stated without naming a specific project's internals, it does **not** belong in a
  shared skill.
- **CLAUDE.md is expensive.** Every byte is in every session's context. Reserve L1 for genuine
  conventions; prefer L2 (star) for self-contained rules so the doc stays short and the rule
  stays searchable.

## Decision procedure

For each durable lesson the evidence surfaced, ask in order:

1. **Is it a reusable method, or a fact?**
   - *Method* (a procedure, a check, a "how to do X correctly" that any project could follow) →
     candidate for a **Skill**.
   - *Fact* (a specific gotcha, a config value, an incident lesson, a decision) → a **memory /
     CLAUDE.md** layer. Continue to step 2.

2. **(facts) Is it project-specific or universal?**
   - Project-specific → **L3** (memory, scoped to the project/repo), or **L1** if it's a
     navigation-level convention of that project.
   - Universal across all projects → **L1g** (agent-workflows/CLAUDE.md) for conventions, or
     **global L3** for a cross-project gotcha.

3. **(facts) How load-bearing / how often violated?**
   - Violated repeatedly, must never be forgotten, self-contained → **L2 (star)**.
   - Important navigation convention of the repo → **L1**.
   - Useful-on-demand detail → **L3 (unstarred)**.

4. **(methods) Does a skill already own this area?**
   - Yes → **add a checklist item / step / reference line** to that skill (this is a **K** edit
     more than a P move; P applies when the *source* was a memory entry being retired).
   - No, and it's substantial and recurring → propose a **new skill** (rare; flag for human).

## The named migration moves

| Move | When | Mechanics |
|---|---|---|
| **memory → skill** | a memory entry is really a portable method (a HOW that any project could use), and a skill owns that area | graft the method into the skill's checklist/reference (gated K-style edit); **then** delete/supersede the entry — *skill edit committed first, entry removed after* |
| **skill → memory / CLAUDE.md** | a shared skill contains project-specific detail (leak) | move the specifics to L3 (memory, project-scoped) or the project L1 (CLAUDE.md); strip them from the skill, leaving the portable method |
| **L3 → L2 (star)** | an unstarred entry encodes a simple rule that the evidence shows was violated ≥2× | `star_entry`; tighten the summary so it reads as an imperative rule |
| **L2 → L3 (unstar)** | a starred entry no longer earns always-in-context cost (niche, superseded) | `unstar_entry`; keep it searchable in L3 |
| **L3 → L1** | a memory fact is actually a navigation convention a new contributor needs | add one line to the project CLAUDE.md; delete/supersede the entry |
| **L1 → L2/L3** | CLAUDE.md is bloated with a self-contained gotcha that doesn't need to be always-loaded | move it to a (starred or plain) memory entry; trim CLAUDE.md |

## Guardrails (the portability/altitude skeptic enforces these)

- **No project-specifics into a shared skill.** This is the single most common bad P/K candidate.
  If the proposed skill edit names a table, service, route, or repo path, it is invalid — reroute
  to L1/L3. The adversarial reviewer `KILL`s these on sight.
- **Don't double-store.** A fact lives in exactly one layer. If you promote a method into a skill,
  retire the memory entry (after the skill edit is committed). If you move a leak out of a skill,
  remove it from the skill. Leaving both is drift.
- **Method ≠ instance.** One project incident is an *instance*, not a method. Promote to a skill
  only when the lesson generalizes into a repeatable check that isn't tied to the one case
  (this is the abstraction discipline from `dream/references/audit-checklist.md` §M).
- **Order of operations for cross-layer moves:** create/commit the destination first, delete the
  source second. Never delete the only copy of a load-bearing fact before its replacement exists
  and is durable (committed for skills, written for memory).
- **CLAUDE.md edits to the shared file (L1g) are skill-channel** — they go through the gate and
  the mandatory commit+push, same as skill edits.

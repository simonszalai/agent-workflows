---
name: deep-dream
description: >-
  Whole-system offline consolidation. The big "dream" that goes beyond memory: scans recent
  Claude AND Codex session logs and autodev tickets for what keeps going wrong, audits and
  consolidates memory entries (merge / abstract / dedup / resolve contradictions), and decides
  what knowledge should move between memory, starred rules, CLAUDE.md, and the skills themselves
  — then improves the skills/workflows. Cheap models (haiku/sonnet) do the heavy log scouting;
  the orchestrator and skeptic critics adjudicate. Memory and skill/workflow mutations are
  proposed behind explicit gates by default; approved memory actions prefer repair,
  supersession, and reversible quarantine over deletion.
user_invocable: true
argument-hint: "[project] [--all] [--since 14d] [--apply-memory] [--auto-skills] [--dry-run]"
max_turns: 400
---

# Deep Dream

`/deep-dream` is the consolidation skill: it consolidates the **whole development system** the
way an offline "dreaming" pass would. It grounds itself in real evidence (recent Claude + Codex
session logs and autodev tickets), then runs five consolidation channels at once — memory
cleanup, knowledge gaps, knowledge *migration* between layers, skill-content improvement, and
workflow structural fixes. Every change must survive adversarial skeptic review before it is
applied.

It is an **orchestrator**, not a rewrite of the existing skills. It reuses their methodology:

| Channel | Reuses | What deep-dream adds |
|---|---|---|
| Memory audit/consolidation | `references/audit-checklist.md` + `references/adversarial-base.md` | evidence from logs/tickets feeds the candidates |
| Pipeline evidence (Claude logs) | `autodev-improve` | the same scan over **Codex** logs; ties findings to fixes |
| New knowledge capture | `compound`, `autodev-extract` | aggregate (cross-session) gaps, not one incident |
| Workflow structural lint | `heal-workflows` | substantive content improvement, not just broken refs |
| Ticket failure patterns | — (new) | recurring root causes across tickets become candidates |
| Memory ⇄ skill migration | — (new) | promote reusable methodology up; evict project leakage down |

## What it is NOT

- **Not a code change tool.** It never edits project application code. Its only side effects are
  (a) autodev-memory store mutations and (b) edits to the shared workflow files under
  `~/dev/agent-workflows` (`skills/`, `agents/`, `CLAUDE.md`). Nothing else.
- **Not `/retrospect`.** Retrospect is one live thread; deep-dream is a broad, periodic,
  evidence-grounded sweep.

## Usage

```
/deep-dream                     # Current project: full sweep, default 14-day evidence window
/deep-dream ts                  # Sweep a named project
/deep-dream --all               # Global + every registered project (heavier)
/deep-dream --since 30d         # Widen the evidence window
/deep-dream --apply-memory      # Auto-apply surviving memory actions (no memory gate)
/deep-dream --auto-skills       # Auto-apply surviving skill/workflow edits (no skill gate)
/deep-dream --dry-run           # Audit + adversarial review + report, apply NOTHING
```

A run that applies zero changes — because nothing survived scrutiny — is a normal, successful
outcome. Bias is toward **not acting**.

## Two autonomy tiers (read this first)

Deep-dream writes to two very different places, so it treats them differently:

| Channel | Target | Default behavior |
|---|---|---|
| **Memory** (M, G, memory side of P) | autodev-memory store | **Propose → human gate → apply.** Waive with `--apply-memory`. |
| **Skill / workflow** (K, W, skill side of P) | files in `~/dev/agent-workflows` | **Propose only → human gate → apply → commit+push.** Waive the gate with `--auto-skills`. |

Rationale: a wrong memory can be injected as authority, dominate unrelated retrievals, or hide
the evidence needed to repair it. Memory mutation is therefore not lower-risk merely because it
lives outside Git. Shared-skill edits have the additional propagation cost described in
`agent-workflows/CLAUDE.md`, so they retain their own gate and mandatory commit discipline.

`--dry-run` disables **both** apply steps.

## Critical safety rules

1. **No project code, ever.** The codebase is read-only ground truth, never an edit target.
2. **No mutation before scrutiny and approval.** A candidate is applied only after it survives
   the full adversarial loop (Phase 3) and the applicable human gate, unless that gate was
   explicitly waived with `--apply-memory` or `--auto-skills`.
3. **Bias toward NOT acting.** An unrebutted skeptic `KILL` drops the action. Doing nothing is
   always safe; a wrong destructive edit is not.
4. **Skills stay project-agnostic.** Per `agent-workflows/CLAUDE.md`, shared skills must contain
   **zero** project-specific detail (table names, service ids, routes). A candidate that would
   inject project specifics into a portable skill is invalid — route it to memory/CLAUDE.md
   instead (see `references/migration-rules.md`).
5. **Never auto-retire a hard-won rule.** Starred entries and CLAUDE.md rules are load-bearing.
   Quarantine, unstar, merge, rescope, or supersession of a starred entry always requires an
   explicit human decision even when `--apply-memory` is present.
6. **Commit+push is mandatory after any skill-file edit.** A shared-file change that isn't pushed
   never reaches other environments (see "Applying the skill channel").
7. **Cheap models scout, the orchestrator decides.** Scouts (haiku/sonnet) read and summarize;
   they do not mutate anything. All apply steps run in the orchestrator after adversarial review.

---

## Procedure

### Phase 0 — Scope & baseline

1. **Resolve project/repo.** Project from the `<!-- mem:project=X -->` stub in the repo
   `CLAUDE.md`; repo from `basename -s .git $(git config --get remote.origin.url)`. With `--all`,
   enumerate via `mcp__autodev-memory__list_projects()` / `list_repos()`.
2. **Set the evidence window.** Load the state file (below). Use a watermark per project, repo,
   provider, evidence source, and resolved model cohort. Re-scan a 48-hour late-arrival grace
   window and deduplicate by native session/event identity; do not use one project-wide timestamp
   that lets one provider or sibling repo advance past unseen evidence.
3. **Establish "already-fixed" baselines** (so you don't flag issues the latest code already
   resolved — `autodev-improve` Phase 0 discipline). Fetch the deployed-tip commit + timestamp
   for both maintenance repos, always via `origin/main` (local `main` may be stale):
   ```bash
   cd ~/dev/autodev-memory && git fetch origin -q && git log -1 --format="%ai %H %s" origin/main
   cd ~/dev/agent-workflows && git fetch origin -q && git log -1 --format="%ai %H %s" origin/main
   ```
   Evidence entirely older than the relevant baseline is likely stale — note it but don't act on
   it. (Project app-code fixes also count: a recurring failure that stopped after a recent commit
   is resolved, not open.)

**State file:** `~/.local/share/autodev-deepdream/state.json`
```json
{
  "version": 2,
  "runs": [{"at": "ISO-8601", "project": "ts", "window_start": "ISO-8601",
            "claude_sessions": 12, "codex_sessions": 9, "tickets": 30,
            "memory_applied": 5, "skills_applied": 2}],
  "high_water_marks": {
    "ts|ts-prefect|claude|session-log|claude-fable-5": {
      "observed_through": "2026-06-28T00:00:00Z",
      "late_arrival_grace_hours": 48
    }
  }
}
```
Create `~/.local/share/autodev-deepdream/` on first run. Re-runs ingest new evidence plus the
bounded grace window. Never advance a provider/source watermark from another source's scan.
When loading a version-1 state file, preserve its run history and seed each newly encountered
dimension from the old project watermark minus the 48-hour grace window; write version 2 only
after the sweep completes. Never discard or blindly advance an unknown legacy watermark.

### Phase 1 — Evidence gathering (CHEAP SCOUTS, parallel)

Fan out **independent scout agents in a single message** (multiple `Agent` blocks). Scouts read
large, noisy data and return **compact structured findings** — this is the heavy "data scouting"
and it runs on cheap models. Use `model: "sonnet"` for judgment-bearing scouts and
`model: "haiku"` for the most mechanical extraction. Full briefs + parsing recipes live in
`references/evidence-scouts.md`; spawn each scout with its brief from that file.

| Scout | Model | Reads | Returns |
|---|---|---|---|
| **claude-logs** | sonnet | recent Claude session + subagent JSONL (`~/.claude/projects/...`) | what went wrong: corrections, re-hit gotchas, ignored memories, failed tool loops, missed searches |
| **codex-logs** | sonnet | recent Codex rollouts (`~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl`) | same signal set, Codex-side (failed `exec_command` exits, patch failures, MCP `Err`, user retries) |
| **tickets** | sonnet | autodev tickets in window (`list_tickets`, `search_tickets`, `get_review_patterns`, `get_similar_tickets`) | recurring root causes, repeated bug themes, review findings that recur |
| **memory-inventory** | haiku | every applicable entry, global + project (`list_entries` + `get_entry`) | the per-entry audit table `dream` needs (id, type, summary, tokens, tags, scope, staleness flags) |
| **skill-inventory** | sonnet | skills relevant to the project + shared workflow skills (`SKILL.md` files) | structural map (broken refs, orphans, frontmatter) **and** content smells (project leakage, stale steps, overlap/contradiction between skills) |

Scouts must be **evidence-bound**: every finding cites a concrete locator (session+line, ticket
id, entry id, `file:line`, grep result). Speculation without a locator is dropped.

For Claude/Codex session logs, scouts MUST use the loaded deep-dream skill's
`scripts/parse_session_log.py` as the first-pass parser (resolve it under
`~/.agents/skills/deep-dream`, with `~/.claude/skills/deep-dream` as fallback). The parser
supports both legacy direct
function calls and current Codex `custom_tool_call(name="exec")` envelopes. A nested
`tools.<name>(...)` found in JavaScript is an **attempt**, not a confirmed success; only a direct
result/MCP event can confirm the inner call. Open raw JSONL only at the parser's cited line when
more context is required, and never copy secrets into the report.

For provider-aware memory compliance, run
`scripts/audit_memory_compliance.py --days <window>` before assigning delivery/retrieval labels.
It recursively correlates Claude Agent children, preserves direct-vs-nested Codex certainty, and
joins local hook telemetry. Its default output is coarse and hash-free; never persist or upload
`--restricted-diagnostics` output.

### Phase 2 — Synthesis & candidate generation (ORCHESTRATOR)

Merge the five scout reports into one grounded picture, then generate candidate actions across
the **five channels**. Every candidate gets a stable id (`M1`, `K3`, …), the exact change, and
its grounding evidence. This is round-0 input to the skeptics — nothing is applied yet.

| Code | Channel | Action vocabulary | Authority |
|---|---|---|---|
| **M** | Memory consolidation | QUARANTINE / UPDATE / SUPERSEDE / MERGE / ABSTRACT / SPLIT / RESCOPE / SIMPLIFY / RETAG / RETYPE / IMPROVE-SUMMARY / RESOLVE-contradiction | `references/audit-checklist.md` |
| **G** | Knowledge gap | CREATE new entry for a failure that recurs in the evidence and nothing currently captures | `compound`, `autodev-extract` |
| **P** | Promote / migrate | move knowledge between layers: memory→skill, skill→memory/CLAUDE.md, memory→starred, memory→CLAUDE.md, or the reverse | `references/migration-rules.md` |
| **K** | Skill content | add/repair a checklist item, step, or reference in a skill, driven by **aggregate** failure evidence (≥2 independent occurrences) | `compound` gap-analysis, extended |
| **W** | Workflow structural | fix broken cross-refs, orphaned skills, frontmatter, contradictions *between* skills | `heal-workflows` |

The discipline that ties them together:

- **Drive K and G from aggregate evidence.** One bad session is an incident (use `/retrospect`).
  A failure that shows up in two+ independent sessions/tickets is a *pattern* worth a skill edit
  or a new entry. State the count and cite each occurrence.
- **The migration question is the novel core.** For each durable lesson, ask *which layer should
  hold this?* using `references/migration-rules.md`. A reusable, project-agnostic methodology
  buried in a memory entry wants to be a skill checklist line. Project-specific detail that
  leaked into a portable skill wants to move down to memory/CLAUDE.md. A simple rule violated
  repeatedly wants to be **starred** (Tier 2) or a CLAUDE.md convention (Tier 1).
- **Tie findings to fixes, both directions.** If the evidence shows a failure that a *recent*
  commit already fixed, the lesson is "capture why it broke", not "re-flag it". If a memory
  entry describes a gotcha whose root cause was permanently fixed, that entry is now a candidate
  for SUPERSEDE, UPDATE, or reversible QUARANTINE.
- **Do not confuse delivery with use.** Search hit counters and operation-log results mean an
  entry was returned, not read or applied. Search currently mutates `last_searched_at` and the
  generic `updated_at`, so neither field proves content freshness. Claude SessionStart output is
  intentionally absent from transcripts; lack of a marker in Claude JSONL is not proof that no
  hook context was delivered. Use hook logs/backend `session_init` for delivery evidence.

### Phase 3 — Adversarial review (skeptic critics, several rounds)

Subject **every** candidate from all five channels to hostile, evidence-based scrutiny before
anything is applied. Follow `references/adversarial-review.md` (which layers a skill-channel
lens on the base protocol in `references/adversarial-base.md`). One round:

1. **Spawn skeptics in parallel** (one message, multiple `Agent` blocks). Memory candidates get
   the three base lenses (information-loss / evidence / churn-utility). Skill & migration
   candidates additionally get a **portability/altitude skeptic**: does this edit inject
   project-specifics into a shared skill? bloat it? rest on a cross-skill claim that isn't true?
   double-capture a fact that already lives in another layer? Brief critics that these facts and
   skills drive production work across every project, so a bad consolidation has real downstream
   cost — default to `KILL` on uncertainty.
2. **Collect verdicts** (`PASS` / `AMEND` / `KILL` + evidence + `safer_alternative`).
3. **Adjudicate.** An unrebutted `KILL` drops the action; you may overrule only by citing
   concrete evidence (grep, entry text, `file:line`, provenance). Destructive memory actions and
   **all** skill-file actions carry a higher bar: a single unrebutted `KILL` drops them.
4. **Carry forward / converge / cap** at round 3. Keep an adjudication log (the audit trail).

### Phase 4 — Apply (two channels)

**Memory channel** (surviving M, G, and memory-side P) — present the exact entry ids, before/after
state, evidence, reversibility, and blast radius, then stop for approval. With
`--apply-memory`, apply surviving non-starred actions without that stop. `--dry-run` applies
nothing. Use the MCP tools mapped in `references/audit-checklist.md` plus:
- **CREATE (G)** → `mcp__autodev-memory__create_entry(...)` (tags via the `autodev-tags` skill).
- **Star/unstar (P → Tier 2)** → `mcp__autodev-memory__star_entry` / `unstar_entry`.
- **Supersede** instead of hard-delete when a chain matters →
  `mcp__autodev-memory__supersede_entry`.

`QUARANTINE` is the only retirement action: unstar if separately approved, then use the MCP
soft-delete so the row and provenance remain recoverable and excluded from search. Never present
soft-delete as permanent deletion. Prefer `SUPERSEDE` when corrected guidance can replace the
stale entry. Any action touching a starred entry always stops for human approval.

**Skill / workflow channel** (surviving K, W, skill-side P) — see "Applying the skill channel"
below. Default: present for approval, then apply + commit + push. With `--auto-skills`: apply
without the gate (still commit + push). With `--dry-run`: nothing.

**Durable record.** Write a `learning_report` artifact summarizing the sweep to the most
relevant ticket (or project-level if none): `mcp__autodev-memory__create_artifact(...,
artifact_type="learning_report", command="/deep-dream")`. Update the state file's high-water
mark and append the run summary.

### Phase 5 — Report

Emit the final report (format below): evidence window + baselines, what each scout found,
candidates per channel, adversarial outcomes (survived / amended / killed with reasons), exact
memory mutations applied, and the skill-file edits (applied or awaiting approval).

---

## Applying the skill channel (gated)

Skill/workflow edits modify **shared, symlinked** files under `~/dev/agent-workflows`. After the
skeptics converge:

1. **Present** the surviving K/W/P-skill proposals as a concrete diff-level plan: file, exact
   edit, evidence, blast radius. **Stop for approval** (skip this stop only under `--auto-skills`).
2. **Apply** approved edits to the files (they're live immediately via the symlink).
3. **Commit + push** — mandatory, or the change never propagates:
   ```bash
   cd ~/dev/agent-workflows
   git add -A
   git commit -m "deep-dream: <what changed and why>"
   git push origin main
   ```
   Skip the push only if `$CLAUDE_CODE_REMOTE=true`. If the working tree has unrelated changes,
   stage only deep-dream's files (don't sweep up someone else's work-in-progress).

Migration actions that span both channels (e.g. "move entry X's methodology into skill Y, then
quarantine entry X") execute the **skill side first** (gated) and the **memory side only after**
the skill edit is committed — never retire the source before its replacement is durable.

---

## Report format

```markdown
# Deep Dream Sweep

**Date:** YYYY-MM-DD  **Project:** <project>  **Mode:** <gated | dry-run | --apply-memory | --auto-skills>
**Evidence window:** <start> → now
**Baselines:** autodev-memory <hash> (<date>) · agent-workflows <hash> (<date>)
**Scanned:** <N> Claude sessions · <M> Codex sessions · <T> tickets · <E> memory entries · <S> skills

## Executive summary
<3-5 sentences: system health, the most impactful patterns, headline changes.>

## What the evidence showed (cross-source patterns)
- **P1.** <recurring failure> — seen in <session/ticket locators> ×N. Already fixed by <commit>? Y/N.
- ...

## Adversarial review
<rounds run, converged/capped>. <C> candidates → <S> survivors (<D> dropped).

## Applied / proposed — memory channel  [APPLIED | AWAITING APPROVAL]
- Merged "<A>" + "<B>" → "<merged>" (id …)  | evidence: …
- Created entry "<title>" (G) for recurring <pattern>
- Starred "<title>" (violated ×N)
- ...

## Applied / proposed — skill channel  [APPLIED & PUSHED | AWAITING APPROVAL]
- skills/<name>/SKILL.md — add checklist item "<…>"  | evidence: ×N occurrences …
- MIGRATE entry "<title>" → skills/<name> (reusable methodology); entry quarantined after commit
- heal: skills/<x> referenced missing `templates/y.md` → fixed
- ...

## Dropped by critics (not applied)
- [K2] add step to plan skill → KILL: would inject ts-prefect specifics into a portable skill;
  rerouted to CLAUDE.md candidate P5. Evidence: …
- [M4] ABSTRACT 3 entries → KILL: entry B carries a real exception the rule would erase. Evidence: …

## Pending human decisions
- <unresolved contradiction the code couldn't arbitrate>
- <skill edits awaiting approval, if gated>
```

## Key principles

1. **Evidence first.** Every candidate cites a concrete locator. Current code/config arbitrates
   claims about current behavior; it cannot arbitrate human preferences or architecture intent.
   No locator → no candidate.
2. **Cheap to scout, careful to decide.** The bulk reading is delegated to haiku/sonnet scouts;
   judgment, adversarial review, and all mutations stay with the orchestrator.
3. **Right knowledge, right layer.** The migration question (`references/migration-rules.md`) is
   what makes this more than five audits stapled together: reusable lessons rise into skills,
   project specifics fall into memory/CLAUDE.md, repeated rules get starred.
4. **Patterns, not incidents.** Skill/knowledge edits need ≥2 independent occurrences. A one-off
   belongs to `/retrospect`, not here.
5. **Two independently waivable gates.** Memory and shared-skill mutations are both gated by
   default. `--apply-memory` and `--auto-skills` waive only their named channel. Never infer one
   from the other.
6. **Survival, not selection, is the gate** (memory channel). The default for any action is
   *not applied*. An empty survivor set is success, reported plainly.
7. **Preserve hard-won rules.** Starred/CLAUDE.md rules are load-bearing; suspicion is the
   default before touching them.
8. **Idempotent & incremental.** The dimensioned high-water marks plus event dedup mean the
   late-arrival grace re-scan creates no duplicate actions. Re-runs converge, they don't churn.
```

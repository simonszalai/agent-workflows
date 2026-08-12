---
name: night-dream
description: >-
  Scheduled, cloud-safe nightly unattended consolidation over autodev
  tickets + the memory store ONLY (session logs are local-only and excluded by design). Auto-applies
  only adversarially-surviving repair/supersession/quarantine memory actions; everything else —
  including the ts-graph-dream production graph cleanup plan — is posted to Slack as a proposal.
max_turns: 200
---

# Night Dream

`/night-dream` is unattended nightly consolidation over tickets and the memory store,
restricted to evidence and mutations that are safe without a human present. It runs under the full unattended contract in
`../references/scheduled-run.md` — mutation boundary, Slack one-line + thread format,
`SCHEDULED_RUN_RESULT` ending, `rc_fingerprint` dedup. Invoked by Hermes
`hermes/schedules/nightly-dream.md`; report channel `#autodev-nightly` (ID from
`hermes/schedules/schedules.yaml`).

## Evidence base — tickets + memory store ONLY

- **In scope:** autodev tickets (statuses, artifacts, event history, review findings) and the
  autodev-memory store (entries, tags, usage/funnel stats), via the autodev-memory MCP.
- **Excluded by design, not by fallback:** Claude/Codex session logs. They are local-only and a
  cloud workspace cannot see them; do not attempt to mount, fetch, or approximate them. Channels
  that need session-log evidence (pipeline-evidence scans, token audits) belong to the manual
  skills, not here.
- **No skill/workflow edits.** A scheduled run never edits `skills/`, `agents/`, hooks, or any
  repo file. Skill-improvement observations become Slack proposals (see mutation policy).

## Channels

Three consolidation channels:

| Channel | Method | Output |
|---|---|---|
| Memory audit/consolidation | audit a bounded slice of entries for the defect classes below | repair/supersession/quarantine actions (auto-apply if surviving), everything else proposed |
| Ticket-failure patterns | recurring root causes across recent tickets (verify FAILs, investigation artifacts, review findings) | proposals; recurring findings use `rc_fingerprint` extend-not-duplicate |
| Knowledge gaps | incidents/tickets that a missing memory entry would have prevented | proposed new-entry drafts in the thread (creation is not auto-applied) |

Memory-audit defect classes: factually wrong or stale content; duplicates/near-duplicates of a
canonical entry; entries contradicted by newer confirmed knowledge; harmful or misleading
guidance; orphaned project-specific entries for retired systems. An entry is a candidate only
with concrete evidence (the contradicting ticket/entry/commit), never on style grounds.

**Adversarial gate:** before applying any candidate action, genuinely try to refute it — is the
"stale" fact actually still true, is the "duplicate" carrying distinct nuance, would quarantine
lose knowledge that still fires usefully? An action is applied only when the refutation attempt
fails on evidence. **A run that applies zero mutations because nothing survived scrutiny is a
normal, successful PASS** — bias is toward not acting.

## Mutation policy (the entire unattended surface)

Auto-apply is limited to adversarially-surviving **memory-store** actions of exactly three kinds:

1. **repair** — fix a factually wrong/stale entry in place (`update_entry`), preserving intent;
2. **supersession** — `supersede_entry` linking a superseded entry to its replacement/canonical;
3. **quarantine** — deactivate a harmful/misleading entry pending human review (no hard delete).

Everything else is a **Slack proposal in the report**, never applied: new entry creation, entry
deletion, merges beyond a supersession link, tag-taxonomy changes, skill/workflow suggestions,
ticket mutations other than `rc_fingerprint` extend/create per scheduled-run.md §4. Record every
applied mutation with `record_memory_event`/audit trail so the morning review can see exactly
what changed and revert it.

## Lane 2 — ts-graph-dream, propose-only

Run `../ts-graph-dream/SKILL.md` in **propose-only mode**: audit passes and dry-run SQL counts
are fine (prod reads via the read-only credential only), but the run performs **zero `graph_*`
mutations** — no supersede/tag/collapse/merge writes, no `graph_maintenance_*` rows. Include the
resulting evidence-bound production graph cleanup plan (action classes, row counts, sample IDs,
risk notes) in `dream_report`. Applying the plan is a separate,
human-approved `/ts-graph-dream` follow-up session — never this run.

## Bounds

Cap the pass explicitly per run and state the caps in the thread: a bounded ticket window (e.g.
last 14 days or N tickets), a bounded memory slice (e.g. N entries by staleness/last-use), and a
bounded graph audit (ts-graph-dream's own sampling). Never run an unbounded sweep; carry
unexamined scope over to the next night.

## Report

The Hermes runner owns Slack delivery. End with the `SCHEDULED_RUN_RESULT` block from
scheduled-run.md §3 and include its required single-line `dream_report` JSON object. Populate it
as follows:

- `what`: one sentence saying what was reviewed, what changed, and whether proposals were made;
- `why`: one sentence explaining why actions were applied or why nothing survived the safety gate;
- `how`: one sentence naming the bounded evidence and adversarial/dedup method used;
- `memory_actions`: one `entry ID — action — reason` item per applied repair, supersession, or
  quarantine;
- `ticket_consolidations`: one `ticket ID — consolidation — reason` item per created or extended
  recurring-root-cause ticket;
- `proposals`: one `proposal — reason it needs human review` item per proposed action;
- `graph_plan`: one sentence summarizing the propose-only graph outcome; and
- `scope`: the explicit ticket window, memory slice, and graph audit bounds.

Use empty arrays when no actions or proposals exist. Do not put the human report above the block
or attempt to post Slack messages directly: the runner renders one count-rich parent message and
one structured thread reply, while the raw machine block remains in Conductor only. A zero-action
PASS must say why no action was safe or necessary; never use a generic `ended PASS` summary.

## Relation to manual sessions

Whole-system consolidation involving session logs or skill/workflow edits remains manual-local
only. Night-dream never substitutes for it; it surfaces what it cannot safely do as proposals
for a manual session.

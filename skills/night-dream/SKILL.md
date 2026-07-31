---
name: night-dream
description: >-
  Scheduled, cloud-safe subset of deep-dream. Nightly unattended consolidation over autodev
  tickets + the memory store ONLY (session logs are local-only and excluded by design). Auto-applies
  only adversarially-surviving repair/supersession/quarantine memory actions; everything else —
  including the ts-graph-dream production graph cleanup plan — is posted to Slack as a proposal.
max_turns: 200
---

# Night Dream

`/night-dream` is the scheduled arm of the dreaming family: what `/deep-dream` does in a manual
local session, this does unattended from a cloud workspace, restricted to evidence and mutations
that are safe without a human present. It runs under the full unattended contract in
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

Three consolidation channels, reusing deep-dream's methodology files for candidate quality and
gating — read both before proposing anything:

| Channel | Method | Output |
|---|---|---|
| Memory audit/consolidation | `../deep-dream/references/audit-checklist.md` over a bounded slice of entries | repair/supersession/quarantine actions (auto-apply if surviving), everything else proposed |
| Ticket-failure patterns | recurring root causes across recent tickets (verify FAILs, investigation artifacts, review findings) | proposals; recurring findings use `rc_fingerprint` extend-not-duplicate |
| Knowledge gaps | incidents/tickets that a missing memory entry would have prevented | proposed new-entry drafts in the thread (creation is not auto-applied) |

Every candidate action must survive the adversarial gate in
`../deep-dream/references/adversarial-base.md`. **A run that applies zero mutations because
nothing survived scrutiny is a normal, successful PASS** — bias is toward not acting.

## Mutation policy (the entire unattended surface)

Auto-apply is limited to adversarially-surviving **memory-store** actions of exactly three kinds:

1. **repair** — fix a factually wrong/stale entry in place (`update_entry`), preserving intent;
2. **supersession** — `supersede_entry` linking a superseded entry to its replacement/canonical;
3. **quarantine** — deactivate a harmful/misleading entry pending human review (no hard delete).

Everything else is a **Slack proposal in the thread**, never applied: new entry creation, entry
deletion, merges beyond a supersession link, tag-taxonomy changes, skill/workflow suggestions,
ticket mutations other than `rc_fingerprint` extend/create per scheduled-run.md §4. Record every
applied mutation with `record_memory_event`/audit trail so the morning review can see exactly
what changed and revert it.

## Lane 2 — ts-graph-dream, propose-only

Run `../ts-graph-dream/SKILL.md` in **propose-only mode**: audit passes and dry-run SQL counts
are fine (prod reads via the read-only credential only), but the run performs **zero `graph_*`
mutations** — no supersede/tag/collapse/merge writes, no `graph_maintenance_*` rows. Post the
resulting evidence-bound production graph cleanup plan (action classes, row counts, sample IDs,
risk notes) as a reply in the nightly Slack thread. Applying the plan is a separate,
human-approved `/ts-graph-dream` follow-up session — never this run.

## Bounds

Cap the pass explicitly per run and state the caps in the thread: a bounded ticket window (e.g.
last 14 days or N tickets), a bounded memory slice (e.g. N entries by staleness/last-use), and a
bounded graph audit (ts-graph-dream's own sampling). Never run an unbounded sweep; carry
unexamined scope over to the next night.

## Report

One summary line to `#autodev-nightly`, detail (per-channel findings, applied mutations with
entry IDs, proposals, graph plan) as thread replies, FAIL/BLOCKED routing per scheduled-run.md
§2, and the `SCHEDULED_RUN_RESULT` block ending the session's final message.

## Relation to the manual skills

`/deep-dream` (whole-system, session logs, skill edits), `/heal-workflows`, and
`/autodev-improve` remain **manual-local only**. Night-dream never substitutes for them; it
surfaces what it cannot safely do as proposals for those sessions.

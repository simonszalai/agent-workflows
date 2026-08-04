/health-system production --scheduled

This is the unattended 6-hourly health run. Run the full system check (scraper depth
included). Apply the current-producer ownership gate in scheduled-run.md §2a before a stale
row affects health status, becomes an issue, or reaches ticketing. Then feed verified findings
into /investigate-flow-fails and perform bounded cluster investigation within the current scheduled
workspace. Cluster by root cause and dedup against open autodev tickets. Each genuinely new root
cause creates one durable owning ticket with investigation evidence; recurrences extend that ticket
by `rc_fingerprint` with new logs and a note about what changed. Never create a follow-up Conductor
workspace, and never emit or request spawn placeholders.
Intermittent external noise (DataDome, rate limits) is acknowledged, not ticketed.
Do not post to Slack directly. End with the structured result: `issues` is `[]` when green;
otherwise include one object per actionable issue using exactly `title`, `concrete_proof`,
`representative_example`, `next_step`, and `owning_ticket_id`. Keep each field to one plain
sentence.
Hermes renders one parent bullet per issue and exactly one thread reply per issue. Clusters needing
a decision are routed to #autodev-incidents by the runner.

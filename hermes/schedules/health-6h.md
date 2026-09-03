/health-system production --scheduled

This is the unattended 6-hourly health run. Run the full system check (scraper depth
included). Apply the current-producer ownership gate in scheduled-run.md §2a before a stale
row affects health status, becomes an issue, or reaches ticketing. Then feed verified findings
into /investigate-flow-fails and complete every actionable cluster in the bounded result. Cluster
by root cause and dedup against open autodev tickets. Each genuinely new root cause creates one
durable owning ticket with triage evidence; recurrences extend that ticket by `rc_fingerprint` with
new logs and a note about what changed. After ticket assignment, append `ticket:<ID>` to every
verified failed/crashed flow run and persist the deferred-cleanup contract. Do not create Conductor
workspaces yourself: the Hermes runner creates one cloud `/ticket-flow <ID>` workspace per emitted
issue, supervises it through staging verification, and posts the final issue/fix/evidence reply.
Intermittent external noise (DataDome, rate limits) is acknowledged, not ticketed.
Do not post to Slack directly. End with the structured result: `issues` is `[]` when green;
otherwise include one object per actionable issue using exactly `title`, `concrete_proof`,
`representative_example`, `next_step`, `owning_ticket_id`, and `remediation_ready`. Set readiness
to true only after the owning ticket/artifacts exist and every applicable tag write returned zero
errors. Keep each prose field to one plain sentence.
Hermes renders one parent bullet per issue and exactly one final thread reply per issue after its
cloud ticket flow ends. Clusters needing a decision are routed to #autodev-incidents by the runner.

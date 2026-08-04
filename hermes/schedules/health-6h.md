/health-system production --scheduled

This is the unattended 6-hourly health run. Run the full system check (scraper depth
included). Apply the current-producer ownership gate in scheduled-run.md §2a before a stale
row affects health status, becomes an issue, or reaches ticketing. Then feed verified findings
into /investigate-flow-fails: cluster by root cause,
dedup against open autodev tickets (extend existing tickets with new logs and note what
changed), create tickets and spawn one investigation workspace per genuinely new cluster.
Intermittent external noise (DataDome, rate limits) is acknowledged, not ticketed.
Do not post to Slack directly. End with the structured result: `issues` is `[]` when green;
otherwise include one object per actionable issue with its short title, concrete proof, one
representative example, next step, and owning ticket ID. Keep each field to one plain sentence.
Hermes renders one parent bullet per issue and exactly one thread reply per issue. Clusters needing
a decision are routed to #autodev-incidents by the runner.

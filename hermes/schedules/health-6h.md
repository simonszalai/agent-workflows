/health-system production --scheduled

This is the unattended 6-hourly health run. Run the full system check (scraper depth
included), then feed findings into /investigate-flow-fails: cluster by root cause,
dedup against open autodev tickets (extend existing tickets with new logs and note what
changed), create tickets and spawn one investigation workspace per genuinely new cluster.
Intermittent external noise (DataDome, rate limits) is acknowledged, not ticketed.
Do not post to Slack directly. End with the structured result: `issues` is `[]` when green;
otherwise include one object per actionable issue with its short title, problem explanation,
and owning ticket ID. Hermes renders one parent bullet per issue and exactly one thread reply
per issue. Clusters needing a decision are routed to #autodev-incidents by the runner.

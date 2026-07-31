/health-system production --scheduled

This is the unattended 6-hourly health run. Run the full system check (scraper depth
included), then feed findings into /investigate-flow-fails: cluster by root cause,
dedup against open autodev tickets (extend existing tickets with new logs and note what
changed), create tickets and spawn one investigation workspace per genuinely new cluster.
Intermittent external noise (DataDome, rate limits) is acknowledged, not ticketed.
If green, post a single ✅ line to #autodev-health; otherwise one line per cluster there,
and clusters needing a decision go to #autodev-incidents with evidence in the thread.

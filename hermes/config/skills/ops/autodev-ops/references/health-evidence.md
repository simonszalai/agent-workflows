# Scheduled health evidence

## health-6h
- Conductor workspaces on **ts-prefect**: `sched-health-6h-YYYYMMDD-HHMM`
- Session names like `health-6h YYYYMMDD-HHMM`
- Prompt skill: `/health-system production --scheduled` → chains `/investigate-flow-fails --scheduled`
- Slack: summary → `#autodev-health`; FAIL detail routing → `#autodev-incidents`

## SCHEDULED_RUN_RESULT (parse from final agent message)
```text
SCHEDULED_RUN_RESULT
status: PASS | FAIL | BLOCKED
schedule: health-6h
summary: <one line>
checks_total: <int>
checks_failed: <int>
tickets_touched: [B0xxx, ...]
rc_fingerprints: [subsystem:signature, ...]
issues: [{title, concrete_proof, representative_example, next_step, owning_ticket_id}]
```
(Block may omit `issues` when empty / green.)

## SQL shortcut (Conductor)
```sql
SELECT workspace_name, session_title, transcript_updated_at,
  substring(transcript from greatest(1, position('SCHEDULED_RUN_RESULT' in transcript)-100) for 4000) AS snip
FROM session_transcripts_view
WHERE workspace_name LIKE 'sched-health-6h-%'
ORDER BY transcript_updated_at DESC
LIMIT 3;
```

## Example fingerprints (illustrative, not exhaustive)
| rc_fingerprint | Meaning |
|----------------|---------|
| `prefect-scheduler:default-queue-polled-late-runs-not-submitting` | Pool/queue READY + polled; runs stay Late; spare concurrency (e.g. B0395) |
| worker / local-pool not ready | Pool NOT_READY — worker not heartbeating (e.g. B0390-class) |
| `poller-api:nodemaven-...` | External proxy noise — often ack, not ticket |

## Prefect prod API (when running *inside* ts-prefect / health workspace)
```bash
export PREFECT_API_URL=https://ts-prefect-server.onrender.com/api
uv run prefect work-pool inspect local-pool --output json
# production pool name is local-pool (not "default")
```
Hermes VM: usually **no** this env — use health session + tickets instead.

## Public smoke URLs
- `https://autodev-memory.onrender.com/health` → `{"status":"ok"}`
- `https://autodev-dashboard.onrender.com/healthz` → status + per-project DB role safety

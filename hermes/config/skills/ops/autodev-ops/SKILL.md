---
name: autodev-ops
description: >-
  Operational status and triage for TS/autodev via Hermes — restricted
  autodev-memory MCP, Conductor workspaces/sessions, Slack ops channels, and
  scheduled health-6h evidence. Use when the user asks about tickets/epics,
  prod health, Prefect status, open incidents, Conductor workspaces, or Slack
  ops channels after deploys or credential rotations.
---

# Autodev / TS ops triage (Hermes)

## Communication (user preference)
- **Final answer only** on WhatsApp/status checks — no progress narration, no tool play-by-play, no “checking X now”.
- Lead with status (OK / degraded / blocked), then compact evidence bullets.
- Do not dump raw JSON; summarize IDs, times (UTC), and next step.

## Surfaces available from Hermes

| Surface | How | Notes |
|---------|-----|--------|
| autodev-memory | MCP `autodev-memory` + loopback `http://127.0.0.1:8792/` | Restricted principal; project often **clamped to `ts`** |
| Conductor | MCP `conductor` @ `http://127.0.0.1:8794/` | Full workspace/session API (not launch-only) |
| Slack | `SLACK_BOT_TOKEN` in `~/.hermes/.env` | Membership-limited; ops channels listed in references |
| Local services | `systemctl` `hermes-gateway`, `hermes-autodev-mcp`, `hermes-conductor` | |

Hermes config may **allowlist** only a subset of memory tools (`get_ticket`, `search_tickets`, …). For epics/`list_tickets`/stats, call the loopback MCP proxy directly with JSON-RPC `tools/call`.

## autodev-memory MCP

### Project scope
- Probe with `get_stats` / `list_tickets`: if every project name returns the same `project` field (e.g. always `ts`), the token is **force-scoped** — do not claim access to `autodev` repos.
- `list_projects` is often **not permitted**.
- `get_ticket` for autodev repo IDs fails with “not found in project ts” when scoped to `ts`.

### Tickets vs epics
- Ticket IDs: `F####`, `B####`, `R####` → `get_ticket`.
- Epic IDs: `E####` → **`get_epic` / `list_epics`** (not `get_ticket`; invalid format error).
- Epic tools may be denied for restricted tokens; fall back to `search_tickets` + titles/tags mentioning `E00xx`, or member tickets if `epic_id` is populated (often null).

### Auth failures
- Upstream `403 Invalid bearer token` on `:8792` = proxy credential stale (`hermes-autodev-mcp.service` / `LoadCredential` token). Report blocked; do not invent ticket data.
- When healthy: `get_security_config_summary` shows `enforcement_active` + principal count.

### Useful reads
- Open work: `list_tickets` + status filters; `search_tickets` for semantic.
- Latest health ownership: tickets tagged `rc_fingerprint`, origin `hermes-ts`, titles from health-6h.
- `debug_logs` = memory *operation* logs, **not** Prefect/Render logs.

## Conductor

Current tools include: `get_current_user`, `list_projects`, `list_project_workspaces`, `get_workspace` / `get_workspace_status`, `list_workspace_sessions`, `get_session` / `get_session_status`, `list_session_messages`, `query_conductor_sql`, create/archive/send, etc.

- **Active workspaces:** `list_project_workspaces` per `project_id` from `list_projects` (e.g. `ts-prefect`). Names like `sched-health-6h-YYYYMMDD-HHMM` are unattended health runs.
- **Do not** rely on old `list_launches` / `launch_workspace` names — tool surface evolved; `tools/list` on `:8794` if unsure.
- Large transcripts: `query_conductor_sql` on `session_transcripts_view` with `ILIKE` / `substring` for `SCHEDULED_RUN_RESULT`, `local-pool`, `Late`, ticket ids — faster than paging all `list_session_messages`.
- Session status `idle` + workspace `ready` after a scheduled run means the run finished; read the final `SCHEDULED_RUN_RESULT` block.

## Slack ops channels

See `references/slack-ops-channels.md`.

- Bot must be **in** the channel (`conversations.history` → `not_in_channel` if not).
- Bot-token **search.messages** often fails (`not_allowed_token_type`); use history on known channel IDs.
- `#autodev-health` = 6h summaries; `#autodev-incidents` = FAIL routing; `#ops-alerts` = provider recoveries.

## Prod health / “Prefect logs” workflow

Hermes host usually has **no** `PREFECT_API_URL` / Render CLI. Do **not** claim live Prefect CLI access unless credentials exist.

**Default evidence chain (in order):**
1. Local proxies + public `/health` / dashboard `/healthz` (cred-rotation smoke).
2. Slack `#autodev-health` + `#autodev-incidents` latest messages.
3. Newest Conductor `sched-health-6h-*` on `ts-prefect` → session → `SCHEDULED_RUN_RESULT` + issue fields.
4. Owning ticket (`B0xxx`) via memory: source + investigation artifacts (`rc_fingerprint`, observed_at).

Interpret common Prefect patterns from health evidence:
- Pool **NOT_READY** → worker not polling (historical B0390-class).
- Pool/queue **READY** + many **Late** + 0 Pending/AwaitingConcurrency + RUNNING ≪ concurrency → submit path stuck (`prefect-scheduler:default-queue-polled-late-runs-not-submitting` / B0395-class).
- Health sandbox may skip Render logs if `render-cli` missing — note that gap; don’t invent worker log lines.

## Credential rotation smoke checklist
- `systemctl is-active` gateway + both MCP proxies
- MCP `initialize` 200 on `:8792` and `:8794`
- memory `get_stats` / `list_tickets` for `ts`
- Conductor `get_current_user` + `list_projects`
- Slack `auth.test` + history on home + ops channels
- `https://autodev-memory.onrender.com/health` and dashboard `/healthz` (DB roles safe)

## Pitfalls
- Narrating every tool step on WhatsApp (user rejected this).
- Treating `project=ts` search hits that mention “autodev” as access to the autodev project DB.
- Using `get_ticket("E0023")` for epics.
- Saying “no active Conductor workspaces” from empty Hermes-launch lists while `list_project_workspaces` is full of `sched-*` runs.
- Calling memory `debug_logs` “Prefect logs”.
- Asserting live Prefect state without a fresh health run or API creds — label evidence time (UTC) and source.

## References
- `references/slack-ops-channels.md` — channel IDs and roles
- `references/health-evidence.md` — SCHEDULED_RUN_RESULT shape and fingerprint examples

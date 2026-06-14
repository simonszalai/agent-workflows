# mcp-gateway

One local daemon that fronts every remote MCP server for all workspaces/sessions,
so clients connect over `type: http` to `127.0.0.1` instead of each spawning its
own `mcp-remote` child.

## Why
Before: each repo `.mcp.json` ran `project-mcp <project> <server>`, which `exec`s a
**per-session** stdio bridge. With many Conductor workspaces × servers × clients
that was ~60 `mcp-remote` node processes, and N bridges hammering the single small
`autodev-memory` instance starved it (writes hung). After: **one** process, secrets
loaded **once**, upstream TCP **pooled** (shared keep-alive agent), and **project
identity carried in the URL path** so project-scoped servers (render, postgres)
still route to the right credentials.

Postgres was the worst offender (Phase 2): every workspace eagerly starts 5 stdio
`postgres-mcp` servers via `project-mcp`, and **each spawn re-reads 1Password** (the FIFO
env mount + an `op read` for the prod URL base). With ~25 workspaces that was **114
`postgres-mcp` processes** and a burst of 1Password biometric prompts on every
multi-workspace launch. Phase 2 folds them into this daemon: secrets resolved **once** at
daemon start, one **shared** `postgres-mcp` per DB (its connection pool shared across all
workspaces' sessions), and the children are **daemon-owned** so they die with the daemon
instead of orphaning (we used to see ~300 orphaned `postgres-mcp` accumulate).

## Pieces
- `gateway.mjs` — zero-dependency Node transparent reverse proxy. Relays MCP-over-HTTP
  bytes unchanged except for swapping the client's auth for the route's upstream
  credential. Handles stateless and stateful/SSE upstreams uniformly. **Also supervises
  the Phase-2 `spawn` routes**: launches/restarts one `postgres-mcp` child per DB, reaps
  them on shutdown, and rewrites the SSE `endpoint` event for prefixed routing (below).
- `routes.json` — `<project>/<server>` prefix -> one of two kinds:
  - **remote**: `{ target, authEnv, authHeader?, authScheme? }` — proxied to a real remote.
  - **spawn**: `{ spawn: { kind, urlEnv, accessMode, port, bin? } }` — a local child the
    daemon runs and proxies to (`target` derived as `http://127.0.0.1:<port>`).
  Tokens/secrets are NEVER stored here; only env-var names. `SIGHUP` reloads it live
  (additively for spawn routes — new children start, running ones are left alone).
- `start-gateway.sh` — launchd entrypoint; loads the 1Password mount + per-project render
  tokens **and the 5 ts postgres `DATABASE_URI`s** once, generates a local listener token
  (`.gateway-token`, 0600), exports `POSTGRES_MCP_BIN`, execs node.
- `com.simon.mcp-gateway.plist` — launchd job (KeepAlive, RunAtLoad).

## Install
```
cp com.simon.mcp-gateway.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.simon.mcp-gateway.plist
# first start = ONE 1Password prompt; then:
curl -s http://127.0.0.1:8765/healthz   # {"ok":true,"routes":[...]}
```

## Client config migration (the cutover)
Each server entry changes from a stdio `project-mcp` command to a `type: http` URL
at the gateway. Clients read the local token from `MCP_GATEWAY_TOKEN` in the shell env
(export it from `~/dev/agent-workflows/mcp-gateway/.gateway-token` in your shell rc).

**Userland — `~/.claude.json` top-level `mcpServers`** (project-agnostic, every workspace):
```json
"autodev-memory": { "type": "http", "url": "http://127.0.0.1:8765/shared/autodev-memory",
                    "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } },
"context7":       { "type": "http", "url": "http://127.0.0.1:8765/shared/context7",
                    "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } }
```

**Per-repo `.mcp.json`** (project-scoped — project baked into the URL; travels into
every Conductor workspace of that repo). Example for a ts repo:
```json
"render": { "type": "http", "url": "http://127.0.0.1:8765/ts/render",
            "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } }
```
(amaru -> `/amaru/render`, workflow -> `/workflow/render`.)

**Postgres (Phase 2)** — `type: sse`, one entry per DB. Note the trailing `/sse`
(the SSE stream endpoint); the daemon rewrites the server's `endpoint` event so the
client's message POSTs come back through the same prefix. The `restricted`/`unrestricted`
access mode lives on the daemon (routes.json), not the client.
```json
"postgres_dev":          { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_dev/sse" },
"postgres_staging":      { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_staging/sse" },
"postgres_prod":         { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_prod/sse" },
"postgres_prod_prefect": { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_prod_prefect/sse" },
"postgres_autodev_ts":   { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_autodev_ts/sse" }
```
(Add `"headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" }` to each only if you
turn on `MCP_GATEWAY_REQUIRE_TOKEN=1`; default is off / localhost-only, matching `render`.)

Old before (for reference / rollback):
```json
"render":       { "command": "/Users/simon/.local/bin/project-mcp", "args": ["ts", "render"] },
"postgres_dev": { "command": "/Users/simon/.local/bin/project-mcp", "args": ["ts", "postgres_dev"] }
```

## Cutover plan (deliberate — high blast radius)
1. Install + verify the daemon (`/healthz`, and an `initialize` curl per route). For
   postgres, `/healthz` should show all 5 children `alive`.
2. Migrate ONE repo's `.mcp.json` (e.g. this repo) — render to `type: http` and the 5
   postgres entries to `type: sse` (above) — restart the client, confirm tools work
   (`list_schemas` etc. resolve). Keep all other repos on `project-mcp` meanwhile.
3. Once proven, propagate: userland servers to `~/.claude.json`; per-repo render + postgres
   to each repo's `.mcp.json` (commit so Conductor copies pick it up). For ts-prefect this
   is one `.mcp.json` shared by all ~25 workspaces.
4. Once postgres is fully cut over, the `project-mcp` postgres paths + their per-session
   `postgres-mcp` orphan reaping are no longer exercised; the `mcp-remote-reaper` launchd
   job can be dropped (no more orphan stdio proxies to reap).

## Rollback
Revert the `.mcp.json` / `~/.claude.json` entries to the `project-mcp` command form
(above) and `launchctl unload` the gateway. `project-mcp` still works unchanged.

## Phase 2 — postgres (done)
`postgres_*` are stdio (`postgres-mcp`) against per-project DBs and hold DB connections.
They're folded in as **`spawn` routes**: the daemon launches one long-lived
`postgres-mcp --transport sse` per DB and proxies to it under `/<project>/postgres_<env>`,
replacing the per-session `project-mcp` spawns (and the ~300-orphan problem).

**How it works**
1. `start-gateway.sh` resolves the 5 `DATABASE_URI`s **once** (mount values for
   dev/staging/autodev; an `op read` of `TS_PROD_POSTGRES_URL_BASE` joined with the DB
   name for prod/prod_prefect — identical to `project-mcp`) and exports them, plus
   `POSTGRES_MCP_BIN` (the postgres-mcp binary the daemon spawns).
2. On startup the daemon reaps any stray `postgres-mcp` on its managed ports, then spawns
   one child per `spawn` route with `DATABASE_URI` in the **env** (never argv → stays out
   of `ps`). It supervises them (capped-backoff respawn on crash) and kills them on
   shutdown (`SIGTERM`/`SIGINT`) so they don't orphan.
3. Clients connect `type: sse` to `…/ts/postgres_<env>/sse`. postgres-mcp's legacy SSE
   transport advertises an **absolute** POST path (`event: endpoint` / `data:
   /messages/?session_id=…`); behind a path prefix that would 404. The daemon rewrites
   that one event to `data: /ts/postgres_<env>/messages/?session_id=…` so the POST lands
   back on the right route. All other SSE bytes pass through untouched.

**DB → port → access mode** (mirrors `project-mcp` exactly):

| Route                       | Port | Access mode    | DATABASE_URI env (set by start-gateway.sh) |
| --------------------------- | ---- | -------------- | ------------------------------------------ |
| `ts/postgres_dev`           | 8811 | `unrestricted` | `TS_POSTGRES_DEV_URL`                       |
| `ts/postgres_staging`       | 8812 | `unrestricted` | `TS_POSTGRES_STAGING_URL`                  |
| `ts/postgres_prod`          | 8813 | `restricted`   | `TS_POSTGRES_PROD_URL`                     |
| `ts/postgres_prod_prefect`  | 8814 | `unrestricted` | `TS_POSTGRES_PROD_PREFECT_URL`            |
| `ts/postgres_autodev_ts`    | 8815 | `unrestricted` | `TS_POSTGRES_AUTODEV_TS_URL`               |

`/healthz` lists each child's `{ prefix, port, pid, alive }`. A `spawn` route whose
`urlEnv` is unset is skipped (logged) and returns 502 — it never crashes the daemon.

## Restart after changing gateway code/config
```
launchctl kickstart -k gui/$(id -u)/com.simon.mcp-gateway   # restart (one 1Password prompt)
curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool # verify routes + children alive
```
(A plain `routes.json`-only change can instead be hot-reloaded: `kill -HUP <daemon pid>`.)

## Troubleshooting (postgres)
- **502 + `connect ECONNREFUSED 127.0.0.1:88xx`** — the child isn't up. Check
  `/tmp/mcp-gateway.log` for its startup line / DB connection error, and `/healthz` for
  `alive`. Common causes: `DATABASE_URI` env unset (see the warning line), or
  `POSTGRES_MCP_BIN` wrong/not executable (`spawn postgres-mcp ENOENT`).
- **Client connects but POSTs 404** — the SSE `endpoint` rewrite didn't apply. Confirm
  the client URL ends in `/sse` and the route has a `spawn` block.
- **`postgres-mcp` not found under launchd** — its PATH is minimal; `POSTGRES_MCP_BIN`
  must be an absolute path (start-gateway.sh defaults it to the ts-prefect venv binary).
- **Port already in use on restart** — a crashed prior daemon left an orphan; the startup
  reaper clears `--sse-port <ourports>` matches, but a foreign listener on 88xx will
  surface as a child that won't bind (see the log).

## Rollback
Revert the `.mcp.json` / `~/.claude.json` entries to the `project-mcp` command form
(above) and `launchctl unload` the gateway. `project-mcp` still works unchanged for both
render and postgres.

## Status
Phase 1 (remote HTTP servers) and **Phase 2 (postgres)** built and proven end-to-end:
a full MCP `initialize` + `tools/list` handshake succeeds through the gateway over the
rewritten SSE path, and the live daemon runs all 5 `postgres-mcp` children (each connected
to its DB; `postgres_prod` in `restricted` mode). Daemon side is live; per-repo `.mcp.json`
client cutover is deliberate (high blast radius) — migrate one repo, prove it, then
propagate.

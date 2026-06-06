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

## Pieces
- `gateway.mjs` — zero-dependency Node transparent reverse proxy. Relays MCP-over-HTTP
  bytes unchanged except for swapping the client's auth for the route's upstream
  credential. Handles stateless and stateful/SSE upstreams uniformly.
- `routes.json` — `<project>/<server>` prefix -> `{ target, authEnv, authHeader?, authScheme? }`.
  Tokens are NEVER stored here; only env-var names. `SIGHUP` reloads it live.
- `start-gateway.sh` — launchd entrypoint; loads the 1Password mount + per-project
  render tokens once, generates a local listener token (`.gateway-token`, 0600), execs node.
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

Old before (for reference / rollback):
```json
"render": { "command": "/Users/simon/.local/bin/project-mcp", "args": ["ts", "render"] }
```

## Cutover plan (deliberate — high blast radius)
1. Install + verify the daemon (`/healthz`, and an `initialize` curl per route).
2. Migrate ONE workspace's `.mcp.json` (e.g. this repo) to `type: http`, restart the
   client, confirm tools work. Keep all other repos on `project-mcp` meanwhile.
3. Once proven, propagate: userland servers to `~/.claude.json`; per-repo render to
   each repo's `.mcp.json` (commit so Conductor copies pick it up).
4. Drop the `mcp-remote-reaper` launchd job (no more orphan proxies to reap).

## Rollback
Revert the `.mcp.json` / `~/.claude.json` entries to the `project-mcp` command form
(above) and `launchctl unload` the gateway. `project-mcp` still works unchanged.

## Phase 2 — postgres
`postgres_*` are stdio (`postgres-mcp`) against per-project DBs and hold DB
connections. Fold them in by having the daemon supervise one long-lived `postgres-mcp`
per DB (wrapped stdio->http) under `/<project>/postgres_<env>`, replacing the
per-session spawns (the ~300-orphan problem). Not in phase 1.

## Status
Phase-1 core built and proven: transparent relay + auth injection + local-token
gating + pooling verified end-to-end against `autodev-memory` (`initialize` 200 in
~0.4s through the gateway). Not yet cut over; configs still use `project-mcp`.

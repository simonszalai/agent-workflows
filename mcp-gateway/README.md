# mcp-gateway

One local daemon that fronts every remote MCP server for all workspaces/sessions,
so clients (Claude Code / Codex / Cursor) connect over native `type: http` to
`127.0.0.1:8765` instead of each spawning its own `mcp-remote` child.

## Why

Before: each repo `.mcp.json` ran a **per-session** stdio bridge. With many Conductor
workspaces × servers × clients that was ~150 `mcp-remote` node processes (~12 GiB RSS),
and N bridges hammering the single small `autodev-memory` instance starved it (writes
hung). Postgres was worse: every workspace eagerly started 5 stdio `postgres-mcp`
servers, each re-reading 1Password on spawn.

After: **one** daemon, secrets loaded **once** (a single `op run` = one Touch ID for the
daemon's lifetime), upstream TCP **pooled**, project identity carried in the **URL path**
so project-scoped servers (render, postgres) route to the right credentials, and postgres
served by **daemon-owned dbhub children** whose DB pools are shared across every
workspace's sessions.

## Layout

| File | Role |
|---|---|
| `gateway.mjs` | entrypoint: wiring, `--validate`, SIGHUP reload, shutdown |
| `lib/config.mjs` | routes.json loading + config preflight |
| `lib/proxy.mjs` | transparent streaming reverse proxy (auth swap, TTFB-guarded retry) |
| `lib/supervisor.mjs` | dbhub child supervision (spawn, backoff respawn, pid-probing, reap) |
| `lib/render-preflight.mjs` | auto-select the Render workspace per MCP session |
| `waf-encode.mjs` | encode autodev-memory writes past Render's edge WAF |
| `routes.json` | the routing table (no secrets — env-var names only) |
| `dbhub/*.toml` | per-project dbhub configs: DB tiers as sources, prod readonly |
| `start-gateway.sh` | launchd entrypoint: one `op run` resolves `gateway.env`, execs node |
| `gateway.env` | `ENV_VAR=op://vault/item/field` refs resolved by that `op run` |
| `com.simon.mcp-gateway.plist` | launchd job |

Zero runtime dependencies; plain Node ≥ 20.

## Routes

`routes.json` maps `<project>/<server>` prefixes to one of two kinds:

- **remote**: `{ target, authEnv, authHeader?, authScheme? }` — proxied to a real remote
  URL with the client's credential swapped for the route's.
- **spawn**: `{ spawn: { kind: "dbhub", config, port, bin? } }` — a local dbhub child the
  daemon runs on `127.0.0.1:<port>` (Streamable HTTP at `/mcp`) and proxies to. One child
  per **project**; the project's DB tiers are sources in `dbhub/<project>.toml`, so tools
  are `execute_sql_<tier>` / `search_objects_<tier>` and prod tiers carry
  `readonly = true`. DSNs reach the child via `${ENV_VAR}` interpolation in the TOML —
  never argv, never this repo.

`SIGHUP` reloads routes.json live (additively for spawn routes: new children start,
running ones and their sessions are untouched).

## Client config

Everything is native `type: http`; no client spawns any bridge process.

```json
// per-repo .mcp.json (project baked into the URL)
"postgres":  { "type": "http", "url": "http://127.0.0.1:8765/ts/postgres/mcp",
               "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } },
"render":    { "type": "http", "url": "http://127.0.0.1:8765/ts/render",
               "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } }
// userland ~/.claude.json: shared/autodev-memory, shared/context7, shared/postgres_global
```

```toml
# .codex/config.toml — same URLs, headers from env
[mcp_servers.postgres]
url = "http://127.0.0.1:8765/ts/postgres/mcp"
env_http_headers = { "x-mcp-gateway-token" = "MCP_GATEWAY_TOKEN" }
```

Clients read the local token from `MCP_GATEWAY_TOKEN` (exported from `.gateway-token`,
0600, by shell rc / `launchctl setenv`). The token gate exists because the 127.0.0.1 bind
alone doesn't stop browser-borne requests (DNS rebinding).

## Operate

```bash
node gateway.mjs --validate     # preflight config WITHOUT a restart (see below)
curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool   # routes + children alive
kill -HUP <daemon pid>          # hot-reload routes.json (additive)
launchctl kickstart -k gui/$(id -u)/com.simon.mcp-gateway      # full restart — ONE Touch ID
```

**Always `--validate` before a restart.** Restarts cost a biometric prompt and re-resolve
`gateway.env`'s `op://` refs, so a 1Password vault/item rename that happened months ago
surfaces only then. Validate checks routes.json shape, port collisions, spawn bins and
TOML files on disk, and that every `${ENV_VAR}` used by TOMLs/auth is set. To also verify
the `op://` refs themselves:

```bash
grep -oE 'op://[^ ]+' gateway.env | sort -u | while read r; do
  op read "$r" >/dev/null 2>&1 && echo "OK  $r" || echo "FAIL $r"; done
```

A failed daemon start exits **cleanly by design** (no KeepAlive retry — each retry would
be another Touch ID prompt); it posts one macOS notification and stays down until
manually kickstarted.

## Troubleshooting

- **502 `spawn route unavailable` / `ECONNREFUSED 127.0.0.1:88xx`** — the dbhub child
  isn't up. Check `/tmp/mcp-gateway.log` for its startup/DB error and `/healthz` for
  `alive`. Common causes: TOML `${ENV_VAR}` unset (run `--validate`), `spawn.bin` not
  executable, or the DB itself down.
- **`AUTH_FAILED` / `SSL/TLS required` from a Render DB** — node-postgres does NOT
  auto-upgrade to TLS like psycopg; hosted DSNs need `?sslmode=require` in the TOML.
- **`env: node: No such file or directory` (exit 127)** — dbhub's npm launcher shebang
  needs node on PATH; the supervisor prepends the daemon's own node dir, and
  `~/.nvm/.../bin/dbhub` is a self-contained wrapper as a belt-and-braces.
- **Child shown `alive` but nothing listening** — can't happen anymore: `/healthz` and
  the supervisor pid-probe (signal 0) instead of trusting Node's `exitCode`, because a
  child once died without its `exit` event reaching us.
- **Port already in use on restart** — a crashed prior daemon left an orphan; the startup
  reaper SIGTERMs exact `--port <ours>` matches on our managed ports only.

## Running on Linux / WSL2 (teammate machine)

The daemon is OS-agnostic Node; only the wrapper is macOS-specific. Use a systemd user
service that execs `start-gateway.sh`, source secrets via `op read` exports instead of
Simon's 1Password setup, and `npm i -g @bytebase/dbhub` for the postgres children. WSL2's
localhost forwarding makes the gateway reachable from Windows-side clients at the same
URL, so client configs are identical. (Details of the analyst secret layout: the
read-only strings live in `op://TS/Thomas Local Agent Secrets`.)

## History

- Phase 1 (2026-07): remote HTTP servers (render/context7/autodev-memory) folded in,
  killing the per-session `mcp-remote` bridges.
- Phase 2 (2026-07): postgres folded in as daemon-owned children.
- 2026-07-12: crystaldba `postgres-mcp` (stdio/legacy-SSE, per-tier, access-mode
  machinery, SSE endpoint rewriting) replaced by per-project **dbhub** over Streamable
  HTTP; legacy routes retired; code split into `lib/`. Rollback: `git log` this directory.

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
| `lib/tool-policy.mjs` | route-scoped request allowlist and secret-free denial audit |
| `lib/tool-filter.mjs` | fail-closed `tools/list` response filter |
| `lib/supervisor.mjs` | dbhub child supervision (spawn, backoff respawn, pid-probing, reap) |
| `lib/render-preflight.mjs` | auto-select the Render workspace per MCP session |
| `waf-encode.mjs` | encode autodev-memory writes past Render's edge WAF |
| `routes.json` | the routing table (no secrets — env-var names only) |
| `dbhub/*.toml` | per-project dbhub configs: DB tiers as sources, prod readonly |
| `start-gateway.sh` | launchd entrypoint: one `op run` resolves `gateway.env`, execs node |
| `gateway.env` | `ENV_VAR=op://vault/item/field` refs resolved by that `op run` |
| `gateway.local.env` | optional gitignored replacement containing only this machine's accessible refs |
| `com.simon.mcp-gateway.plist` | launchd job |

Zero runtime dependencies; plain Node ≥ 20.

## Routes

`routes.json` maps `<project>/<server>` prefixes to one of three kinds:

- **remote**: `{ target, authEnv, authHeader?, authScheme? }` — proxied to a real remote
  URL with the client's credential swapped for the route's.
- **spawn**: `{ spawn: { kind: "dbhub", config, port, bin? } }` — a local dbhub child the
  daemon runs on `127.0.0.1:<port>` (Streamable HTTP at `/mcp`) and proxies to. One child
  per **project**; the project's DB tiers are sources in `dbhub/<project>.toml`, so tools
  are `execute_sql_<tier>` / `search_objects_<tier>` and prod tiers carry
  `readonly = true`. DSNs reach the child via `${ENV_VAR}` interpolation in the TOML —
  never argv, never this repo.
- **generic spawn**: `{ spawn: { kind: "generic", bin, args, port, reapPattern, env?,
  requiresEnv? } }` — any MCP server binary that serves Streamable HTTP on
  `127.0.0.1:<port>` (e.g. `ts/tailscale`). `args` is the child argv verbatim (must pass
  the port, never a secret); secrets reach the child only via env — inherited daemon env
  plus `env` entries whose `${VAR}` refs interpolate from it. `reapPattern` is the
  `pgrep -f` pattern for stray children and must end with the port + a space.

**Rule: any MCP server that needs a 1Password secret goes through this gateway** —
either as a remote route (token in `gateway.env`) or a spawn child. Never put
`op read` in a repo `.mcp.json` launcher: it runs per workspace session, resolves `op`
outside the audited shim (e.g. under `/bin/sh`), and each sandboxed process re-prompts
Touch ID/TCC — that is exactly the four-prompts-per-new-workspace storm this daemon
exists to prevent.

`SIGHUP` reloads routes.json live (additively for eager spawn routes: new children start,
running ones and their sessions are untouched). Spawn routes using a non-default
`clientTokenEnv` never start at daemon startup or reload; their child starts lazily only
after the proxy matches the route and authenticates a request.

### Route client authentication and tool policy

Every loaded route has a `clientTokenEnv`. When omitted it defaults to
`MCP_GATEWAY_TOKEN`, preserving existing trusted-route behavior. An explicit env name
selects a distinct local client principal. Tokens are compared only after route matching,
so a token accepted by one route is rejected by another route with a different env name.
`/healthz` remains unauthenticated.

`allowTools` is an optional, non-empty, duplicate-free positive inventory. When present:

- `tools/call` is the security boundary. Calls not named in the inventory, JSON-RPC batches,
  malformed JSON, compressed bodies, and oversized bodies fail with 403 before any upstream
  dispatch, autodev-memory encoding, or Render workspace preflight.
- `tools/list` filtering is defense in depth. Plain JSON responses are reduced to the original
  order intersection with the inventory. SSE, compressed, malformed, oversized, aborted, and
  unsupported response shapes fail closed without relaying partial bytes.
- Buffered allowlisted requests are isolated per route/principal: at most eight are active and
  at most 8 MiB is retained in aggregate. Excess work receives 429 before upstream dispatch.
  Request bodies have a 15-second deadline; only the buffered `tools/list` response branch has
  a 30-second body deadline, so transparent long-lived SSE remains exempt.

Omitting `allowTools` means unrestricted transparent behavior and is reserved for existing
trusted routes. Unrestricted request and response bytes remain on the existing relay path.

An explicitly configured but unset non-default `clientTokenEnv` disables that route with 503.
It never falls back to `MCP_GATEWAY_TOKEN`. If that route's upstream `authEnv` is also absent,
validation still succeeds because the route cannot activate; runtime also fails closed and never
uses another route's bearer. Every non-default-token spawn route is excluded from eager startup
and reload even when its token exists. When its token is absent, validation also skips runtime-only
child credential checks while retaining static shape, binary, config, port, and read-only-source
checks.

### Hermes routes

The checked-in `hermes/autodev-memory`, `hermes/render`, and `hermes/slack` routes all use
`HERMES_GATEWAY_TOKEN`. They are inert until their M3 secrets are provisioned.

`hermes/autodev-memory` uses `HERMES_AUTODEV_MEMORY_TOKEN` and permits ticket planning,
artifact, search, and knowledge/config read surfaces. It excludes deletes, reverts, merges,
superseding, approvals, crystallization decisions, epic surfaces, configuration mutation,
workflow batch mutation, and knowledge writes. `update_ticket` is retained for planning and
status work; the independently enforced F0032 server policy denies `approve_execution` and
execution-state transitions for the Hermes principal.

Exact inventory:

```text
create_artifact
create_ticket
expand_entries
get_all_tags
get_artifact
get_artifact_history
get_entry
get_project
get_repo
get_review_patterns
get_security_config_summary
get_similar_tickets
get_stats
get_ticket
get_ticket_contexts
list_artifact_comments
list_entries
list_projects
list_repos
list_tickets
next_ticket
reply_artifact_comment
search
search_tickets
update_artifact
update_ticket
```

`hermes/render` reuses the pinned `ts/render` workspace and permits only `get_*` and `list_*`
inventory entries. It excludes deploy triggers, environment changes, object creation,
client-selected workspaces, and Postgres queries. The gateway's internal pinned workspace
preflight is not a client tool and runs only after request policy accepts the client call.

Exact inventory:

```text
get_deploy
get_key_value
get_metrics
get_postgres
get_selected_workspace
get_service
list_deploys
list_key_value
list_log_label_values
list_logs
list_postgres_instances
list_services
list_workspaces
```

`hermes/slack` permits message/reaction operations plus the required read and search surface.
It excludes canvases, conversation creation, files, scheduled messages, drafts, channel
management, and administration. The Slack app manifest is unchanged.

Exact inventory:

```text
slack_add_reaction
slack_get_reactions
slack_list_channel_members
slack_read_channel
slack_read_thread
slack_read_user_profile
slack_search_channels
slack_search_emojis
slack_search_public
slack_search_public_and_private
slack_search_users
slack_send_message
```

This M2 change lands code and non-activating route definitions only. It does not add secrets,
edit `gateway.env`, reload the daemon, or publish a Hermes client configuration. F0021 owns
secret provisioning and the full runtime reload; F0022 owns real Hermes client wiring.

## Client config

Everything is native `type: http`; no client spawns any bridge process.

```json
// per-repo .mcp.json (project baked into the URL)
"postgres":  { "type": "http", "url": "http://127.0.0.1:8765/ts/postgres/mcp",
               "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } },
"render":    { "type": "http", "url": "http://127.0.0.1:8765/ts/render",
               "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } }
"slack":     { "type": "http", "url": "http://127.0.0.1:8765/shared/slack",
               "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" } }
// userland ~/.claude.json: shared/autodev-memory, shared/context7,
// shared/postgres_global, shared/slack
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

### Slack (shared across Claude, Codex, and Grok)

Slack uses the official hosted Streamable HTTP server at
`https://mcp.slack.com/mcp`, but clients never connect to it directly. They all use
`http://127.0.0.1:8765/shared/slack`; the gateway removes client credentials and injects
`SLACK_MCP_USER_TOKEN` from 1Password. This gives every local agent provider the same
tool surface without putting the Slack token in Claude, Codex, Grok, shell history, or a
repository.

One-time setup:

1. In Slack's app management UI, create an internal app **from an app manifest** using
   `slack-app-manifest.yaml`, select the workspace, and install it as Simon. The manifest
   is intentionally limited to message/channel/thread search and history, user lookup,
   message send, and reactions. It has no file access or conversation-management scopes.
2. Copy the resulting **User OAuth Token** (`xoxp-...`, not the bot token) into the
   service-account-readable 1Password item `op://MCP/SLACK_MCP_USER_TOKEN/value`.
   A user token is required because bot identity cannot search Simon's DMs/private
   conversations with Thomas.
3. Validate and restart the gateway once so `gateway.env` is resolved:

   ```bash
   cd ~/dev/agent-workflows/mcp-gateway
   GATEWAY_ENV_FILE="$PWD/gateway.env"
   [[ -f "$PWD/gateway.local.env" ]] && GATEWAY_ENV_FILE="$PWD/gateway.local.env"
   SENSITIVE_ACCESS_REASON="Validate the effective MCP gateway startup configuration" \
     ../bin/redacted-exec -- /usr/bin/env \
       -u HERMES_AUTODEV_MEMORY_TOKEN -u HERMES_GATEWAY_TOKEN \
       /opt/homebrew/bin/op run --account "${OP_ACCOUNT:-my.1password.com}" \
       --env-file="$GATEWAY_ENV_FILE" --no-masking -- \
       /bin/zsh "$PWD/finish-start.zsh" --validate
   launchctl kickstart -k gui/$(id -u)/com.simon.mcp-gateway
   ```

4. Add the same local route to each user-level client:

   ```json
   // ~/.claude.json, inside top-level "mcpServers"
   "slack": {
     "type": "http",
     "url": "http://127.0.0.1:8765/shared/slack",
     "headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" }
   }
   ```

   ```toml
   # ~/.codex/config.toml and ~/.grok/config.toml
   [mcp_servers.slack]
   url = "http://127.0.0.1:8765/shared/slack"
   env_http_headers = { "x-mcp-gateway-token" = "MCP_GATEWAY_TOKEN" } # Codex
   headers = { "x-mcp-gateway-token" = "${MCP_GATEWAY_TOKEN}" }      # Grok
   ```

   The TOML example shows the provider-specific header line alternatives; do not put
   both lines in the same file. Existing sessions do not reload a newly added server,
   so start fresh Claude/Codex sessions and refresh or restart Grok after activation.

## Operate

```bash
GATEWAY_ENV_FILE="$PWD/gateway.env"
[[ -f "$PWD/gateway.local.env" ]] && GATEWAY_ENV_FILE="$PWD/gateway.local.env"
SENSITIVE_ACCESS_REASON="Validate the effective MCP gateway startup configuration" \
  ../bin/redacted-exec -- /usr/bin/env \
    -u HERMES_AUTODEV_MEMORY_TOKEN -u HERMES_GATEWAY_TOKEN \
    /opt/homebrew/bin/op run --account "${OP_ACCOUNT:-my.1password.com}" \
    --env-file="$GATEWAY_ENV_FILE" --no-masking -- \
    /bin/zsh "$PWD/finish-start.zsh" --validate
curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool   # routes + children alive
kill -HUP <daemon pid>          # hot-reload routes.json (additive)
launchctl kickstart -k gui/$(id -u)/com.simon.mcp-gateway      # full restart — ONE Touch ID
```

**Always run resolved validation through `finish-start.zsh --validate` before a restart.**
This is the exact startup composition pipeline: it uses the same effective-env precedence as
`start-gateway.sh`, resolves the selected file, derives the production URLs, and exits before
opening the listener. Restarts cost a biometric prompt and re-resolve the effective env file's
`op://` refs. Validation checks routes.json shape, port collisions, spawn bins and TOML files on
disk, and every required environment variable after composition.

A failed daemon start exits **cleanly by design** (no KeepAlive retry — each retry would
be another Touch ID prompt); it posts one macOS notification and stays down until
manually kickstarted.

`start-gateway.sh` uses `gateway.local.env` instead of `gateway.env` when the local
file exists. This supports machines whose 1Password account intentionally lacks some
project vaults; unavailable routes fail explicitly instead of preventing every route
from starting.

For a deliberately headless host, `op run` may authenticate with a narrowly scoped
1Password service-account token supplied from the OS keychain. Keep the token out of
the repository, plist, shell history, and env files. Daily-driver Macs should retain
the interactive desktop-app/Touch ID path.

## Troubleshooting

- **502 `spawn route unavailable` / `ECONNREFUSED 127.0.0.1:88xx`** — the dbhub child
  isn't up. Check `/tmp/mcp-gateway.log` for its startup/DB error and `/healthz` for
  `alive`. Common causes: TOML `${ENV_VAR}` unset (run `--validate`), `spawn.bin` not
  executable, or the DB itself down.
- **`AUTH_FAILED` / `SSL/TLS required` from a Render DB** — the supervisor adds
  `sslmode=require` exactly once to remote Postgres DSNs before spawning dbhub. Check
  that the configured value is a valid Postgres URL and inspect the child environment
  setup; do not append a second query string in the TOML.
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

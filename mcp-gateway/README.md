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

## Install (macOS — launchd)
```
cp com.simon.mcp-gateway.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.simon.mcp-gateway.plist
# first start = ONE 1Password prompt; then:
curl -s http://127.0.0.1:8765/healthz   # {"ok":true,"routes":[...]}
```

## Running on Windows / WSL / Linux (a teammate's machine, agent-installable)

The daemon itself — `gateway.mjs` — is **zero-dependency, OS-agnostic Node**; it runs
unchanged anywhere Node runs. Only the *wrapper* is macOS-specific:

| Piece | macOS | Linux / WSL2 | Windows-native |
|---|---|---|---|
| Process manager | launchd (`.plist`) | **systemd user service** (below) | recommend WSL2; or Task Scheduler "At log on" → `wsl …` |
| Entrypoint | `start-gateway.sh` (zsh) | same script via `bash`/`zsh` | runs inside WSL |
| Secret source | 1Password **FIFO mount** (`TS_MCP_MOUNT_FILE`) + `op read` | **`op read` only** (no FIFO mount on a teammate's box) | `op.exe` (Windows Hello), surfaced into WSL |
| Biometric | Touch ID | 1Password desktop app ↔ WSL integration | Windows Hello |

**Recommended for Windows: run the daemon inside WSL2.** The whole toolchain (Node, the
`op` CLI, `postgres-mcp`, the bash/zsh entrypoint) works in WSL2 with no porting, and WSL2's
localhost forwarding means a gateway bound to `127.0.0.1:8765` *inside* WSL is reachable at
`http://127.0.0.1:8765` from **Windows-side** Claude Code — so `.mcp.json` URLs are identical
to macOS. A native-Windows port (PowerShell rewrite of `start-gateway.sh` + a Task Scheduler
job) is possible but unsupported; prefer WSL2.

### Prerequisites (per machine)
- **Node** ≥ 20 (`node -v`). Set `NODE_BIN` if it isn't on the service's `PATH`.
- **1Password CLI** `op`, signed in and unlocked. Two auth models (pick one):
  - **Interactive (default, daily-driver Mac):** enable desktop-app integration —
    1Password desktop app → **Settings → Developer → "Integrate with 1Password CLI"** (Touch
    ID) — then `op account add` / `op signin` for the account. Now `op read`/`op run` are
    biometric, not a password prompt (one Touch ID per daemon lifetime). Set `OP_BIN` /
    `OP_ACCOUNT` if needed.
  - **Headless (service account, no Touch ID):** for a boot-time / CI / no-desktop-app host,
    use a **1Password service account** token instead — see
    [Headless auth with a service account](#headless-auth-1password-service-account-no-touch-id)
    below.
  - WSL: enable "Integrate with 1Password CLI" + the WSL toggle in the Windows 1Password app
    so `op` inside WSL authorizes via Windows Hello.
- **`postgres-mcp`** binary on the box; `POSTGRES_MCP_BIN` must be a single absolute path to
  it (the daemon `spawn`s it directly — no shell, so `uvx postgres-mcp` as two words won't
  work). With `uv` installed: `uv tool install postgres-mcp`, then point
  `POSTGRES_MCP_BIN` at the resulting `~/.local/bin/postgres-mcp`.

### Headless auth: 1Password service account (no Touch ID) {#headless-auth-1password-service-account-no-touch-id}
The default resolves secrets **interactively** — `op run`/`op read` go through the desktop-app
integration and raise one Touch ID prompt per daemon lifetime. To run the gateway **fully
headless** (a fresh boot, a CI box, a host with no logged-in desktop app), authenticate `op`
with a **1Password service account** token instead: setting `OP_SERVICE_ACCOUNT_TOKEN` makes
every `op` call non-interactive — no desktop app, no biometric.

> **Security tradeoff.** The token is a bearer credential with *standing* read access to every
> vault you grant it, **with no biometric gate**. Anyone who can read it can read those
> secrets. Keep it in the login/System keychain (below) — never in a file, the plist, or
> `gateway.env`. Prefer the interactive Touch ID default on a daily-driver Mac; reach for the
> service account only for headless hosts.

**1. Create the service account (1Password web app).** Developer → Directory → **Other**
(under *Infrastructure Secrets Management*) → **Create a Service Account** (or the
[wizard](https://start.1password.com/developer-tools/infrastructure-secrets/serviceaccount/)).
Grant it **read** on every vault this host's routes need — `TS`, `TS-sensitive`, `AMARU`,
`AMARU-sensitive`, `WORKFLOW`, `WORKFLOW-sensitive`, `AUTODEV-sensitive`, `MCP` (a route whose
`op://` ref lives in an ungranted vault ends up empty → 502). A service account **cannot** be
granted the built-in Personal/Private vault or the default Shared vault; all gateway secrets
already live in the named vaults above, so that limit doesn't bite. Copy the `ops_…` token —
it's shown only once, at creation. Requires `op` ≥ 2.18.

**2. Store the token in the macOS keychain** (not a dotfile). Paste it at the `-w` prompt so it
never enters shell history:
```bash
security add-generic-password -a "$USER" -s mcp-gateway-op-service-account -U -w
# (paste ops_… at the prompt, press return)
```
Confirm it's retrievable without printing it:
```bash
security find-generic-password -a "$USER" -s mcp-gateway-op-service-account -w >/dev/null && echo ok
```

**3. Make the daemon read it before `op run`.** Add this near the top of `start-gateway.sh`,
*above* the `op run` block. When the keychain item exists, `op` uses the service account; when
it's absent, the script falls through to the interactive Touch ID path unchanged:
```bash
# Headless auth: prefer a service-account token from the keychain. Present → op runs
# non-interactively (no Touch ID). Absent → interactive desktop-app integration as before.
if _sa_tok="$(/usr/bin/security find-generic-password -a "$USER" -s mcp-gateway-op-service-account -w 2>/dev/null)"; then
  export OP_SERVICE_ACCOUNT_TOKEN="$_sa_tok"
fi
```
Then **drop `--account` when the token is set** — a service-account token identifies its own
account, so `op run --account …` is redundant and can error. The `op run` line becomes:
```bash
if [[ -n "${OP_SERVICE_ACCOUNT_TOKEN:-}" ]]; then
  exec "$OP_BIN" run --env-file="$HERE/gateway.env" --no-masking -- /bin/zsh "$HERE/finish-start.zsh"
else
  exec "$OP_BIN" run --account "$OP_ACCOUNT" --env-file="$HERE/gateway.env" --no-masking -- /bin/zsh "$HERE/finish-start.zsh"
fi
```
> **Keychain + launchd timing.** A launchd agent can't unlock the *login* keychain until you've
> logged in once after boot. For a truly boot-time start, put the item in the **System**
> keychain instead (`sudo security add-generic-password -A -s mcp-gateway-op-service-account -w
> /Library/Keychains/System.keychain`) and read from there; otherwise keep `RunAtLoad` and
> accept that the first successful start happens after your first login.

**4. Rotate / revoke** from the same web-app screen. Update the keychain item in place with the
same `security add-generic-password … -U` command, then restart the daemon
(`launchctl kickstart -k gui/$(id -u)/com.simon.mcp-gateway`). Service accounts also carry
request **rate limits/quotas** — irrelevant for the gateway's once-per-lifetime resolve, but
worth knowing if you script bulk `op read`s.

### Secret sourcing without the FIFO mount
`start-gateway.sh` reads most secrets from Simon's 1Password **FIFO mount** — a *Local
destination* secrets mount that exists only on his Mac. On any other machine that mount is
absent, so secrets must come from **`op read`** instead. The script already resolves the
high-sensitivity values (`*_RENDER_API_KEY`, the prod postgres base) via `op read`; the
remaining mount-backed vars must be exported before the daemon starts.

For a **read-only analyst like Thomas**, the read-only connection strings + scoped tokens
live in one item — `op://TS/Thomas Local Agent Secrets` (the same item the `ts:*_ro`
`project-mcp` entries use). Export the env vars `start-gateway.sh` expects from that item, e.g.:

```bash
# names below are the env vars the gateway reads; map each to the matching field in the
# analyst 1Password item (confirm field names with `op item get "Thomas Local Agent Secrets" --vault TS`)
export AUTODEV_MEMORY_API_TOKEN="$(op read 'op://TS/Thomas Local Agent Secrets/AUTODEV_MEMORY_API_TOKEN')"
export CONTEXT7_API_KEY="$(op read 'op://TS/Thomas Local Agent Secrets/CONTEXT7_API_KEY')"
export TS_POSTGRES_DEV_URL="$(op read 'op://TS/Thomas Local Agent Secrets/TS_DEV_DATABASE_URL')"
export TS_POSTGRES_STAGING_URL="$(op read 'op://TS/Thomas Local Agent Secrets/TS_STAGING_DATABASE_URL')"
export TS_POSTGRES_PROD_URL="$(op read 'op://TS/Thomas Local Agent Secrets/TS_PROD_DATABASE_URL')"
# …repeat for any other route in routes.json the teammate needs
```

To skip the FIFO entirely, point the mount path at an empty file so `load_mount` no-ops, and
let the exports above provide everything:
```bash
export TS_MCP_MOUNT_FILE=/dev/null    # FIFO absent on this machine; secrets come from op read exports
```
> Heads-up for an installing agent: `start-gateway.sh` currently **`exit 2`s if
> `TS_MCP_MOUNT_FILE` isn't readable** (it assumes Simon's mount). `/dev/null` is readable, so
> the override above satisfies that check while contributing no keys. Any route whose env var
> ends up empty is skipped and returns 502 — that's expected for routes the teammate lacks
> access to (e.g. an analyst with no amaru/workflow DBs).

### systemd user service (Linux / WSL2) — the launchd replacement
Create `~/.config/systemd/user/mcp-gateway.service` (adjust the path and the `op read`
exports; put the exports in `~/.config/mcp-gateway/secrets.env` referenced via `EnvironmentFile`,
or in a small wrapper the service execs):
```ini
[Unit]
Description=mcp-gateway (local MCP reverse proxy)
After=network-online.target

[Service]
Type=simple
# A wrapper that does the `op read` exports above, then execs start-gateway.sh:
ExecStart=%h/dev/agent-workflows/mcp-gateway/start-gateway.sh
Environment=TS_MCP_MOUNT_FILE=/dev/null
Environment=MCP_GATEWAY_HOST=127.0.0.1
Environment=MCP_GATEWAY_PORT=8765
# Environment=POSTGRES_MCP_BIN=%h/.local/bin/postgres-mcp
Restart=on-failure
RestartSec=3
StandardOutput=append:/tmp/mcp-gateway.log
StandardError=append:/tmp/mcp-gateway.err

[Install]
WantedBy=default.target
```
```bash
loginctl enable-linger "$USER"            # keep the user service alive across logout (WSL: ensure systemd is on)
systemctl --user daemon-reload
systemctl --user enable --now mcp-gateway
curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool   # same verification as macOS
```
> WSL2 needs systemd enabled (`/etc/wsl.conf` → `[boot]\nsystemd=true`, then `wsl --shutdown`).
> Without systemd, run the wrapper from `~/.profile`/a startup task and rely on the gateway's
> own child-supervision instead.

After install, client config (`.mcp.json` / `~/.claude.json`) is **identical to macOS** —
the URLs all point at `http://127.0.0.1:8765/…` (see next section).

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
client's message POSTs come back through the same prefix. The default access mode lives on
the daemon (`routes.json`). Unprotected development/staging routes let a client select a
mode with `?access_mode=restricted` or `?access_mode=unrestricted`.

Protected routes (`ts/postgres_prod`, `ts/postgres_prod_prefect`,
`ts/postgres_autodev_ts`, and `shared/postgres_autodev_global`) have
`maxAccessMode: "restricted"`. An unrestricted request can never start an unrestricted
child. During the compatibility window the daemon clamps it to restricted and emits a
structured `protected_access_mode_ceiling` audit event. The separately controlled hard-reject
flip is `MCP_GATEWAY_PROTECTED_ACCESS_MODE_POLICY=reject`; the safe default is `clamp`.

```json
"postgres_dev":          { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_dev/sse?access_mode=unrestricted" },
"postgres_staging":      { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_staging/sse?access_mode=unrestricted" },
"postgres_prod":         { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_prod/sse?access_mode=restricted" },
"postgres_prod_prefect": { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_prod_prefect/sse?access_mode=restricted" },
"postgres_autodev_ts":   { "type": "sse", "url": "http://127.0.0.1:8765/ts/postgres_autodev_ts/sse?access_mode=restricted" }
```

Accepted parameter names are `access_mode`, `accessMode`, `postgres_access_mode`, and
`postgresAccessMode`; values are only `restricted` or `unrestricted`. The gateway strips
this selector before proxying to `postgres-mcp` and lazily starts a sibling child when a
client asks for the non-default mode (alternate port = configured route port +
`MCP_GATEWAY_ALT_ACCESS_MODE_PORT_OFFSET`, default `1000`).
Startup and SIGHUP reconciliation also reap the current and historical offset ports. Add
old offsets as a comma-separated list in
`MCP_GATEWAY_HISTORICAL_ALT_ACCESS_MODE_PORT_OFFSETS` before changing the current offset.
(Add `"headers": { "x-mcp-gateway-token": "${MCP_GATEWAY_TOKEN}" }` to each only if you
turn on `MCP_GATEWAY_REQUIRE_TOKEN=1`; default is off / localhost-only, matching `render`.)

**Codex — `.codex/config.toml`** uses a mixed gateway shape:

- Gateway streamable HTTP routes (`render`, `shared/autodev-memory`, `shared/context7`) can be
  configured directly with `url = "http://127.0.0.1:8765/…"`.
- Gateway postgres routes are legacy SSE (`…/sse`). Codex's direct `url` transport is
  streamable HTTP and fails against those SSE endpoints with HTTP 405 / Method Not Allowed.
  For postgres, keep Codex's local side as stdio, but point the stdio bridge at the gateway
  SSE endpoint with pinned `mcp-remote@0.1.38`. This still avoids all per-workspace
  1Password reads and per-workspace `postgres-mcp` children; Codex only spawns a lightweight
  local bridge to the daemon-owned postgres child.

Example ts repo:
```toml
[mcp_servers.render]
url = "http://127.0.0.1:8765/ts/render"

[mcp_servers.postgres_dev]
command = "/Users/simon/.nvm/versions/node/v24.14.1/bin/npx"
args = ["-y", "mcp-remote@0.1.38", "http://127.0.0.1:8765/ts/postgres_dev/sse?access_mode=unrestricted", "--transport", "sse-only", "--silent"]
```

Userland Codex entries follow the same rule:
```toml
[mcp_servers.context7]
url = "http://127.0.0.1:8765/shared/context7"

[mcp_servers.autodev-memory]
url = "http://127.0.0.1:8765/shared/autodev-memory"

[mcp_servers.postgres_autodev_global]
command = "/Users/simon/.nvm/versions/node/v24.14.1/bin/npx"
args = ["-y", "mcp-remote@0.1.38", "http://127.0.0.1:8765/shared/postgres_autodev_global/sse?access_mode=restricted", "--transport", "sse-only", "--silent"]
```

Before the hard-reject flip, run `mcp-protected-route-inventory` over consuming repository
roots and `/tmp/mcp-gateway.log`. Its JSON maps every protected-route requester to an owning
configuration ticket and reports remaining unrestricted requesters/clamp events. The installer
also treats `bin/.protected-route-security-floor` as a forward-only floor: on first activation
it removes pre-floor immutable version trees so their direct `project-mcp` launchers cannot
bypass the gateway ceiling. Later floor-aware versions remain rollback-capable.

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
3. Once proven, propagate: userland servers to `~/.claude.json` and `~/.codex/config.toml`;
   per-repo render + postgres to each repo's `.mcp.json` and `.codex/config.toml` (commit so
   Conductor copies pick it up). For ts-prefect this is one `.mcp.json`/`.codex/config.toml`
   shared by all workspaces; already-created workspaces may also need their copied
   `.codex/config.toml` updated or the session restarted.
4. Once postgres is fully cut over, the `project-mcp` postgres paths + their per-session
   `postgres-mcp` orphan reaping are no longer exercised; the `mcp-remote-reaper` launchd
   job can be dropped (no more orphan stdio proxies to reap).

## Rollback
Revert the `.mcp.json` / `.codex/config.toml` / `~/.claude.json` / `~/.codex/config.toml`
entries to the `project-mcp` command form (above) and `launchctl unload` the gateway.
`project-mcp` still works unchanged.

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

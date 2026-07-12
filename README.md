# Agent Workflows

Shared agent workflows, skills, hooks, and tool-specific agent definitions for all projects.

## Contents

- **Skills** - Shared methodology and knowledge (review patterns, research methods, etc.)
- **Agents** - Tool-specific specialized agent roles (reviewer, planner, researcher, etc.)
- **Hooks** - Shared shell hooks for autodev-memory context injection
- **Commands** - Legacy Claude command wrappers kept only where still needed
- **Workflows** - Claude Code dynamic workflow scripts (`plan-fanout`, `review-collect`,
  `review-synthesize`, etc.) for
  heavy-path fan-out; skills invoke them via `Workflow({ name: "..." })` on Claude, or run the
  equivalent logic inline on Codex/Grok
- **bin/** - Shared executables including `project-mcp` (legacy/fallback MCP launcher),
  `external-agent` (cross-provider adapter), `compact-exec` (bounded command output), `wait-ci`
  (single-call CI waiting), and `workflow-efficiency-report` (whole-agent-tree usage accounting)

## Distribution

| Environment     | Mechanism                                      | Direction |
| --------------- | ---------------------------------------------- | --------- |
| Local dev       | Versioned installer + stable per-item symlinks | One-way, rollback-safe |
| Cloud sessions  | SessionStart hook clones + copies              | One-way   |
| NanoClaw        | Volume mount into container                    | Two-way   |

### Local setup (once per machine)

```bash
git clone git@github.com:simonszalai/agent-workflows.git ~/dev/agent-workflows
~/dev/agent-workflows/bin/install-agent-workflows

# Roll back atomically to the previously installed immutable version:
~/.local/bin/install-agent-workflows --rollback
```

The installer exports the exact resolved git commit (never the dirty working tree), validates a
checksum manifest, and stores the read-only artifact under
`~/.local/share/agent-workflows/versions/`, atomically switches `current`, creates only
managed per-item links (it refuses to overwrite unrelated files), and merges Claude/Codex hook
configuration without deleting unrelated settings. CI tests use `--home <temporary-dir>` for
fresh install, legacy-root-symlink migration, upgrade, corruption rejection, and rollback; never
test installation against the operator's real HOME. The complete previous transaction is written
before activation so a rollback can restore either the previous commit or the documented legacy
root-symlink layout.

`external-agent` shells out to peer provider CLIs (`claude`, `codex`, and/or `grok`), so the
providers you want as peers must be installed and authenticated. `/review` and `/investigate`
start with bounded native analysis and add peer providers only for explicit high-risk scope,
material uncertainty, or unresolved disagreement. `/research` retains cross-provider fan-out by
default (opt out per-run with `mode:solo` / `--solo`). When peers are used, the model is symmetric:

- if Claude runs the main workflow, external peers are Codex + Grok;
- if Codex runs the main workflow, external peers are Claude + Grok;
- if Grok runs the main workflow, external peers are Claude + Codex.

The current main runner is autodetected by `agent-workflow-provider` (override only when needed
with `AGENT_WORKFLOW_PROVIDER=claude|codex|grok`). Skills should use
`agent-workflow-provider --peers` instead of hard-coding Codex/Grok.

All peer providers run **read-only with repo access** so they can grep/read code to ground their
output — Claude via `claude -p` with only Read/Grep/Glob tools, Codex via `-s read-only`, and
Grok via a read/search-only tool allowlist (`--tools Read,Grep,Glob`, no Bash/Write/Edit).
None can modify the repo.

External calls must receive the required, separately generated `--memory-context-file` (maximum 3K) and set
the adapter's ambient-hook suppression automatically. See
[`docs/memory-provider-matrix.md`](docs/memory-provider-matrix.md). Fable is a workflow/model
variant, not a fourth provider.

### MCP gateway daemon — 1Password secrets loaded once (once per machine)

Postgres and the remote MCP servers (autodev-memory, render, context7) get their secrets from
**1Password**. Without the daemon, every `.mcp.json` server spawns a fresh `project-mcp` child
**per session**, and each postgres child **re-reads 1Password on every spawn** — so launching
several Conductor workspaces fires a *burst* of biometric prompts (with ~25 workspaces × 5 DBs
that was ~114 `postgres-mcp` processes and a wall of prompts on every multi-workspace launch).

The `mcp-gateway` launchd daemon fixes this: it resolves **all** MCP secrets from 1Password
**once at daemon start** (a single biometric prompt), holds them in one long-lived process, and
fronts every MCP server over localhost HTTP/SSE. Clients connect to `127.0.0.1:8765` and carry
**no secrets** — so starting a workspace never re-prompts. Install it once per machine:

```bash
cd ~/dev/agent-workflows/mcp-gateway
cp com.simon.mcp-gateway.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.simon.mcp-gateway.plist
# first start = ONE 1Password prompt; then verify (all 5 postgres children should be alive):
curl -s http://127.0.0.1:8765/healthz | python3 -m json.tool

# Clients read the local listener token from the shell env — export it from your rc file:
echo 'export MCP_GATEWAY_TOKEN="$(cat ~/dev/agent-workflows/mcp-gateway/.gateway-token)"' >> ~/.zshrc
```

After that, `.mcp.json` / `~/.claude.json` server entries point at the gateway
(`type: http` for remote servers, `type: sse` for postgres) instead of running `project-mcp`.
See **`mcp-gateway/README.md`** for the full client-config entries, the per-DB route table, the
deliberate cutover plan, rollback, and troubleshooting. `project-mcp` (below) still works
unchanged as the fallback / rollback path for any server not yet migrated.

**On a teammate's non-Mac machine (Windows / WSL / Linux):** the daemon is plain Node and runs
anywhere — only the launchd wrapper and the 1Password FIFO mount are Mac-specific. The
`mcp-gateway/README.md` section **"Running on Windows / WSL / Linux"** has the agent-installable
recipe: a systemd user service (launchd replacement), running it under WSL2 on Windows, the
1Password biometric prerequisites per OS, and how to source secrets via `op read` (e.g. the
read-only analyst item) when the Mac FIFO mount isn't present.

### Cloud setup (automatic)

Each project's `deploy/cloud-setup.sh` handles cloning this repo and copying files into
the tool-specific config directory when running in a remote environment. The GitHub app for
that environment must be installed on this repo for the clone to work.
Cloud setup must pin the reviewed commit and invoke `bin/install-agent-workflows --home "$HOME"
--version "$AGENT_WORKFLOWS_COMMIT"`; a clone/copy alone is not activation evidence. The required
real-provider canaries and metadata-only evidence contract are documented in
[`docs/memory-provider-matrix.md`](docs/memory-provider-matrix.md#deployment-time-evidence-gate-not-satisfied-by-this-repositorys-unit-tests).

### NanoClaw setup

Mount this repo's directories into the container at the tool-specific config locations:

```yaml
volumes:
  - source: /path/to/agent-workflows/agents
    target: /home/user/.claude/agents
  - source: /path/to/agent-workflows/commands
    target: /home/user/.claude/commands
  - source: /path/to/agent-workflows/skills
    target: /home/user/.claude/skills
```

## Resolution precedence

Claude Code checks project `.claude/` first, then user `~/.claude/`. Project-specific
agents/skills/commands override shared ones of the same name.

Codex reads shared skills from `.agents/skills` and tool-specific agents from `.codex/agents`.
Keep skills shared, but keep agent definitions in the format each tool expects.

## Adding items

Put new shared skills and hooks directly in this repo. They become available immediately in
all projects locally via symlinks, and in cloud sessions on next session start. Keep new
agents tool-specific unless/until a generator owns the conversion.

## Project-specific items

Items that only make sense for one project stay in that project's config directories:

- Project-specific agents (e.g., `investigator-prefect.md` in ts-prefect)
- Project-specific skills (e.g., `tool-prefect` in ts-prefect)
- Legacy Claude command wrappers, only when a slash command still needs to exist

## Hooks

Memory system hooks live in `hooks/` and are symlinked to `~/.claude/hooks/` and
`~/.codex/hooks/`.

### Required: `~/.config/autodev-memory/.env`

Hooks need API credentials to reach the autodev-memory service. These **must** be
in a dedicated `.env` file — not just in `~/.zshrc` — because hooks run as bash
subprocesses that do not inherit zsh shell exports (especially when launched from
GUI apps like Conductor).

```bash
# Create once per machine:
mkdir -p ~/.config/autodev-memory
cat > ~/.config/autodev-memory/.env << 'EOF'
AUTODEV_MEMORY_API_TOKEN=<your-token>
AUTODEV_MEMORY_API_URL=https://autodev-memory.onrender.com
EOF
```

`mem-lib.sh` sources this file on every hook invocation (line 83-85). Without it,
hooks fail silently on resume/compact triggers with "AUTODEV_MEMORY_API_TOKEN not set".

### Hook files

| File | Event | Purpose |
|---|---|---|
| `autodev-memory-session-start.sh` | SessionStart | Validates/injects one server-rendered packet v2 (bounded v1 digest fallback) |
| `autodev-memory-pre-agent.sh` | PreToolUse (Agent) | Adds one <=3K skill-scoped task packet to managed Claude children |
| `memory_context.py` | helper | Validates counts/hash, renders wrappers, manages atomic 0600 session cache |
| `task_packet.py` | helper | Calls strict repo-scoped `/entries/by-skill` and renders task packets |
| `mem-lib.sh` | (shared library) | Logging, env parsing, HTTP, entry loading |
| `mem-err-trap.sh` | (shared library) | Error trapping for clean hook output |


## project-mcp launcher (`bin/project-mcp`)

> **Note:** the **mcp-gateway daemon** (above) is now the preferred path — it loads 1Password
> secrets once instead of re-prompting per spawn. `project-mcp` remains the fallback for servers
> not yet cut over to the gateway, and the rollback target. It is still the canonical record of
> *which* 1Password items back each server.

Legacy MCP configs used to set every `.mcp.json` / `.codex/config.toml` server `command`
to `~/.local/bin/project-mcp <project> <server>` (e.g. `shared autodev-memory`,
`ts postgres_prod`). New configs should prefer **`mcp-gateway`** instead:

- Claude / `.mcp.json`: HTTP servers use direct gateway URLs; postgres uses gateway SSE URLs.
- Codex / `.codex/config.toml`: HTTP servers use direct `url = "http://127.0.0.1:8765/…"`
  entries; postgres still needs a stdio bridge because Codex's `url` transport is streamable
  HTTP and does not speak the gateway's legacy SSE endpoint directly, so use pinned
  `mcp-remote@0.1.38 …/sse --transport sse-only --silent`.

`project-mcp` remains the rollback/fallback target. The `~/.local/bin/project-mcp` path is a
**symlink to `bin/project-mcp` in this repo** — so the launcher is versioned here alongside
the hooks and skills it sits next to.

What it does, per invocation:

1. Resolves secrets from **1Password** — either from a mounted `.env` FIFO (`mount_value`) or a
   direct vault read by item ID (`op_read`), serialized with a lock so a parallel MCP startup
   burst raises at most one biometric prompt.
2. `guard_project_context` refuses to start a project's MCP from another project's workspace
   (override with `ALLOW_CROSS_PROJECT_MCP=1`).
3. `exec`s into the real backend: `mcp-remote` for remote HTTP servers (autodev-memory, render,
   context7) or `postgres-mcp` for databases.

It contains **no secrets** — only 1Password item-ID pointers and a mount path. Safe to commit.

### Where it goes

```bash
ln -s ~/dev/agent-workflows/bin/project-mcp ~/.local/bin/project-mcp
chmod +x ~/dev/agent-workflows/bin/project-mcp   # if needed
```

`~/.local/bin` must be on `PATH`. The mounted 1Password env item must be configured per the
paths near the top of the script (`TS_MCP_MOUNT_FILE`, etc.).

### mcp-remote orphan reaping

Remote servers run via `npx mcp-remote ... --transport http-only`. Because the launcher
`exec`s into `mcp-remote` (no trap survives `exec`), a reconnect/crash can orphan the old
proxy (reparented to PID 1). Orphans accumulate — each holds an HTTP client to a
single-instance remote — and eventually starve real requests until MCP calls hang.

Two defenses:

- **In-launcher (primary):** `run_remote_bearer` calls `reap_stale_remote "$url"` before
  spawning, killing stale proxies for that exact URL (scoped; never touches other servers).
  `mcp-remote` is version-pinned via `MCP_REMOTE_VERSION` for reproducibility.
- **launchd safety net (per machine, not in this repo):** `~/.local/bin/mcp-remote-reaper`
  + `~/Library/LaunchAgents/com.simon.mcp-remote-reaper.plist` (runs every 30 min) reaps
  `mcp-remote` processes that are **both** old (>3h) **and** orphaned (PPID 1), catching the
  pure-crash case where the launcher never re-runs. An active session's proxy has a live
  parent and is always spared.

## Updating shared workflows

Edit this repository, commit the change, then run `bin/install-agent-workflows` to atomically
activate the new version. Installed copies are immutable deployment artifacts, not editing
surfaces.

In cloud sessions, file changes are ephemeral. Learnings persist via the memory service
(autodev-memory) instead.

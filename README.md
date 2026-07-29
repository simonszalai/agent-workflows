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
  (single-call CI waiting), `workflow-efficiency-report` (whole-agent-tree usage accounting), and
  the reviewed [`hermes-activation`](docs/hermes-activation.md) secret-safe activation provider

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

### MCP access — two loopback proxies + CLI wrappers (2026-07-28 consolidation)

Only two MCP servers exist: **autodev-memory** (`127.0.0.1:8792`) and **context7**
(`127.0.0.1:8793`). Each is a single-upstream loopback auth proxy
(`mcp-proxies/mcp-proxy.mjs`) started under `op run` with the Keychain
service-account token (`op-dev-token`) — silent, no biometric prompts; credentials
live only in the proxy's process memory. Repos check in static-URL project configs
(`.mcp.json`, `.codex/config.toml`, `.grok/config.toml`); clients hold no secrets
and there is no user-scope MCP config. Install once per machine:

```bash
cp ~/dev/agent-workflows/mcp-proxies/com.simon.mcp-proxies.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.simon.mcp-proxies.plist
~/dev/agent-workflows/mcp-proxies/start-proxies.sh status   # both healthy
```

Everything else is a **CLI via the shell**, with the same silent per-call credential
resolution (see the matching `skills/tool-*` references):

| Service   | Access |
| --------- | ------ |
| render    | `bin/render-cli` (official CLI + `render-cli api GET /v1/...` REST passthrough) |
| tailscale | `tailscale` CLI (local, credential-free) + `bin/tailscale-admin` (control-plane API) |
| slack     | `bin/slack-api` (any Web API method) |
| github    | `gh` CLI |
| postgres  | per-repo psql wrappers (reference: ts-prefect `scripts/db/sql.sh`) |

The old `mcp-gateway` daemon (`127.0.0.1:8765`) is **retired and booted out of
launchd** (2026-07-28); `mcp-gateway/` stays in-tree as history only. Its hermes
(filtered analyst) routes died with it — analyst access needs a new design before
re-onboarding.

Legacy MCP configs used to set every `.mcp.json` / `.codex/config.toml` server `command`
to `~/.local/bin/project-mcp <project> <server>`; a later generation routed through the
mcp-gateway daemon. Both are superseded by the static loopback-proxy URLs above.

`project-mcp` is retained in-tree as history. The `~/.local/bin/project-mcp` path is a
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

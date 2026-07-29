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
- **bin/** - Shared executables including the CLI service wrappers (`render-cli`,
  `tailscale-admin`, `slack-api`), `external-agent` (cross-provider adapter), `compact-exec`
  (bounded command output), `wait-ci` (single-call CI waiting), and
  `workflow-efficiency-report` (whole-agent-tree usage accounting)

## Distribution

| Environment     | Mechanism                                      | Direction |
| --------------- | ---------------------------------------------- | --------- |
| Local dev       | Direct folder symlinks into the live checkout | Two-way |
| Cloud sessions  | SessionStart hook clones + copies              | One-way   |
| NanoClaw        | Volume mount into container                    | Two-way   |

### Local setup (once per machine)

```bash
git clone git@github.com:simonszalai/agent-workflows.git ~/dev/agent-workflows
~/dev/agent-workflows/bin/link-agent-workflows-live
```

The live linker makes the dedicated roots (`~/.claude/{agents,skills,hooks,workflows}`,
`~/.agents/skills`, and `~/.codex/hooks`) folder symlinks to the checkout. Adding any file or
skill directory under the corresponding repository folder is therefore visible immediately,
without rerunning an installer. Codex's skills root also contains Codex-managed and personal
skills, so it keeps that directory and uses one folder link at
`~/.codex/skills/agent-workflows`. `~/.local/bin` is shared too, so executables remain direct
per-file links.

Running `bin/install-agent-workflows` without `--version` now performs this same live-folder setup,
so an old setup command cannot silently repin the machine. Pinned, one-way environments must pass
an explicit `--version <commit>`; that mode exports the exact commit into an immutable version tree.

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
launchd** and fully deleted from this repo (2026-07-29), along with its `project-mcp`
predecessor, the `mcp-remote` reaper, and the hermes analyst routes. All prior MCP config
generations are superseded by the static loopback-proxy URLs above.

## Updating shared workflows

Edit this repository and commit the change. Folder-linked local clients see new files immediately;
cloud sessions receive the merged revision on their next SessionStart.

In cloud sessions, file changes are ephemeral. Learnings persist via the memory service
(autodev-memory) instead.

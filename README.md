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
- **bin/** - Shared executables including the CLI service wrappers (`render-cli`, `resend-cli`,
  `psql-cli`, `tailscale-admin`, `slack-api`), `external-agent` (cross-provider adapter),
  `compact-exec`
  (bounded command output), `wait-ci` (single-call CI waiting), and
  `workflow-efficiency-report` (whole-agent-tree usage accounting)
- **config/** - Trusted non-secret registries used by shared wrappers, including exact
  repository-to-project credential mappings
- **hermes/** - Reproducible, secret-safe systemd services and configuration for the Hermes host

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
per-file links. The migration deletes the superseded immutable snapshot store after every live
link has been switched, so stale pinned copies cannot become active again.

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

Only two shared development MCP servers exist: **autodev-memory** (`127.0.0.1:8792`) and
**context7** (`127.0.0.1:8793`). Each is a single-upstream loopback auth proxy
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
| render    | `bin/render-cli` (project-aware official CLI + guarded `/v1` REST passthrough) |
| resend    | `bin/resend-cli` (project-aware official CLI with guarded mutations) |
| tailscale | `tailscale` CLI (local, credential-free) + `bin/tailscale-admin` (registry-scoped control-plane API) |
| slack     | `bin/slack-api` (registry-scoped Web API methods) |
| github    | `gh` CLI |
| postgres  | `bin/psql-cli` (registry-scoped, single-statement read-only queries) |

`render-cli` never trusts the raw Render CLI's user-global login. It matches the exact
Git origin against `config/project-tools.json`, selects the corresponding 1Password
reference and Render workspace, and passes the credential only to the child process.
Run `render-cli context` for a credential-free selection check. Mutations require an
explicit project, `--write`, and `--reason`; unknown repos and project mismatches fail
closed. See `skills/tool-render/SKILL.md`.

`psql-cli` resolves the project by exact origin and exposes only explicitly configured tiers.
`psql-cli context [tier]` performs a credential-free selection check. Query execution accepts
only one read-only SQL statement, parses the configured URI into dedicated libpq `PG*` variables,
strips 1Password credentials from the `psql` child, enforces a read-only transaction/session timeout,
and caps output. There is no default/fuzzy tier, sensitive-reference route, or mutation mode.
Projects without a PostgreSQL profile, and tiers absent from a profile, fail closed.

`resend-cli` applies the same exact-origin selection and per-invocation credential injection to
the official Resend CLI. Saved CLI profiles and credential flags are blocked. Known reads are
allowed automatically; mutations require explicit project, write, and reason flags. See
`skills/tool-resend/SKILL.md`.

Project-aware credential-bearing wrappers authenticate their 1Password reads with the **calling
project's own**
service-account token. Each project in `config/project-tools.json` declares one
`service_account.token_env` (a project-prefixed `<PROJECT>_OP_SERVICE_ACCOUNT_TOKEN`, set in
cloud workspaces) and an optional `service_account.keychain_item` (its Mac Keychain service
name). There is no fallback chain: an unprefixed ambient `OP_SERVICE_ACCOUNT_TOKEN` is never
consulted, the registry rejects unprefixed and duplicated `token_env` names, and running a
wrapper from another project's repo demands that project's token rather than silently reusing
the previous one.

Credential *references* are registry-owned too: `render`, `resend`, and optional `postgres`,
`slack`, and `tailscale` profiles carry their own `op://` refs per project, so no wrapper hardcodes
another project's vault path. PostgreSQL and Slack refs must be non-sensitive. A project without
the requested optional tool profile fails closed instead of reaching for another project's
service.

The old `mcp-gateway` daemon (`127.0.0.1:8765`) is **retired and booted out of
launchd** and fully deleted from this repo (2026-07-29), along with its `project-mcp`
predecessor, the `mcp-remote` reaper, and the hermes analyst routes. All prior MCP config
generations are superseded by the static loopback-proxy URLs above.

The separate Hermes host reuses the same autodev-memory proxy and also runs a dedicated
Conductor API MCP. Its reviewed source, hardened systemd units, installer, and operational
contract live in [`hermes/`](hermes/README.md); these host-specific services are not added to
developer MCP client configurations.

## Updating shared workflows

Edit this repository and commit the change. Folder-linked local clients see new files immediately;
cloud sessions receive the merged revision on their next SessionStart.

In cloud sessions, file changes are ephemeral. Learnings persist via the memory service
(autodev-memory) instead.

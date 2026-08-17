# Agent Workflows

Shared agent workflows, skills, hooks, and tool-specific agent definitions for all projects.

## Contents

- **Skills** - Safety contracts, lifecycle references, and tool wrappers (the 2026-08 purge
  removed methodology/choreography skills; models own their own process now)
- **Agents** - Tool-specific agent roles (`ticket-curator`)
- **Hooks** - Shared shell hooks for autodev-memory context injection
- **bin/** - Shared executables including the CLI service wrappers (`render-cli`, `resend-cli`,
  `psql-cli`, `tailscale-admin`, `slack-api`), `compact-exec` (bounded command output),
  `wait-ci` (single-call CI waiting), and `session-usage-report` (usage accounting)
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

The live linker makes the dedicated roots (`~/.claude/{agents,skills,hooks}`,
`~/.agents/skills`, `~/.codex/hooks`, and `~/.cursor/{agents,skills,hooks}`) folder
symlinks to the checkout. Adding any file or skill directory under the corresponding
repository folder is therefore visible immediately, without rerunning an installer. Codex's
skills root also contains Codex-managed and personal skills, so it keeps that directory and
uses one folder link at `~/.codex/skills/agent-workflows`. Cursor's built-in skills live in
`~/.cursor/skills-cursor`, so `~/.cursor/skills` stays a dedicated folder link. `~/.local/bin`
is shared too, so executables remain direct per-file links. The migration deletes the
superseded immutable snapshot store after every live link has been switched, so stale pinned
copies cannot become active again.

Running `bin/install-agent-workflows` without `--version` now performs this same live-folder setup,
so an old setup command cannot silently repin the machine. Pinned, one-way environments must pass
an explicit `--version <commit>`; that mode exports the exact commit into an immutable version tree.

### MCP access — two loopback proxies + CLI wrappers (2026-07-28 consolidation)

Only two shared development proxy processes exist: **autodev-memory**
(`127.0.0.1:8792/<project>/*`) and **context7** (`127.0.0.1:8793`). AutoDEV's one process
routes the checked-in project prefixes `amaru`, `autodev`, `ts`, and `workflow-pro` to
separate project-restricted bearers. The upstream service pins every tool/REST request to
the selected bearer, so a model-supplied wrong project argument cannot cross the route.
There is no default route.

Both processes use `mcp-proxies/mcp-proxy.mjs` and resolve their values-free env files once
at startup. Each AutoDEV bearer is read with its own project's Keychain service-account token;
Context7 uses `op-ts-token`. The launcher then replaces itself with Node, so only two proxy
processes remain. Bearers remain only in process memory and no 1Password call occurs per MCP request. Repos check in
static project URLs in `.mcp.json`, `.codex/config.toml`, and `.grok/config.toml`; clients
hold no secrets and there is no user-scope MCP config. Install once per machine:

```bash
cp ~/dev/agent-workflows/mcp-proxies/com.simon.mcp-proxies.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.simon.mcp-proxies.plist
~/dev/agent-workflows/mcp-proxies/start-proxies.sh status   # routes pinned + context7 healthy
```

AutoDEV route URLs use the project registry identity, for example
`http://127.0.0.1:8792/amaru/mcp`; REST hooks use the same prefix, for example the
base URL `http://127.0.0.1:8792/amaru`. The explicit route is the client-side identity;
the restricted bearer is the server-side enforcement. Adding a project requires both a
route entry and a server-recognized restricted bearer, followed by the identity canary in
`start-proxies.sh status`.

Conductor cloud workspaces run `mcp-proxies/start-cloud-proxies.sh`. It resolves the exact
Git origin through `config/project-tools.json`, reads only that project's restricted bearer,
and starts a fixed-prefix AutoDEV proxy on the same port. The script also starts Context7,
using an injected key when one exists and its documented lower unauthenticated rate limit
otherwise. Cloud and Mac client files therefore use identical loopback URLs.

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

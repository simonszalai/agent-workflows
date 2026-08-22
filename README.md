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

### MCP access — native HTTP plus per-session bridge

`config/mcp.json` is the single values-free manifest for all four supported clients. `bin/sync-mcp`
renders it into Claude (`.mcp.json`), Codex (`.codex/config.toml`), Cursor
(`.cursor/mcp.json`), and Grok (`.grok/config.toml`) without replacing unrelated client settings.
Project configs include the global servers so a fresh cloud workspace is self-contained:

- Conductor uses its native HTTPS/OAuth endpoint.
- Context7 uses its native unauthenticated HTTPS endpoint.
- Amaru repositories add Amaru's native HTTPS/OAuth endpoint.
- Autodev-memory runs through `bin/mcp-bridge`, one stdio child per client session.

The bridge resolves the exact Git origin through `config/project-tools.json`, accepts only the
matching project identity, reads only that project's restricted bearer from 1Password, and holds it
in memory. Local sessions get the project service-account token from the exact Mac Keychain item;
cloud sessions get it from the exact project-prefixed environment variable. Ambient unprefixed or
cross-project 1Password credentials are removed before access. Client files contain no secrets,
ports, daemons, health-check races, or shell-expanded bearer values. Autodev write fields retain the
WAF-safe base64 transform.

Local setup synchronizes only global user-scope servers; each repository owns its project servers:

```bash
~/dev/agent-workflows/bin/link-agent-workflows-live
~/dev/agent-workflows/bin/sync-mcp --project --cwd /path/to/repository
```

Cloud setup installs an exact agent-workflows snapshot and the small `op`/`jq` runtime, then syncs
global and project servers at user scope as well as using the checked-in project files. The duplicate
cloud registration intentionally avoids Codex/Grok folder-trust timing races; it contains the same
values-free commands and endpoints. OAuth servers require each client's normal one-time browser
login.

Autodev-memory hooks use the same exact-origin resolver but fetch their restricted bearer inline per
hook invocation. The extra 1Password read is deliberate: no credential-bearing background process
survives the hook or client session.

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

The old `mcp-gateway`, `project-mcp`, `mcp-remote`, shared launchd router, and cloud proxy
generations are retired. The only remaining loopback proxy is the fixed-upstream service used by
the separate Hermes host; interactive coding clients never use it.

The separate Hermes host reuses the same autodev-memory proxy and also runs a dedicated
Conductor API MCP. Its reviewed source, hardened systemd units, installer, and operational
contract live in [`hermes/`](hermes/README.md); these host-specific services are not added to
developer MCP client configurations.

## Updating shared workflows

Edit this repository and commit the change. Folder-linked local clients see new files immediately;
cloud sessions receive the merged revision on their next SessionStart.

In cloud sessions, file changes are ephemeral. Learnings persist via the memory service
(autodev-memory) instead.

# The Atom: Explicit Per-Repo Tool Access

Status: design, 2026-09-07. First target: the Amaru repositories.

## Goal

An agent, in any harness on any host, runs a command against a service with the credential the
repository declares, and no secret exists at rest. Nothing is inferred from git remotes, directory
names, naming conventions, or a central registry. Every capability is delivered one way.

## Constraints accepted

| Constraint | Why it is real |
| --- | --- |
| Harnesses read config at startup from fixed per-harness files | Physical property of Claude, Codex, Grok, Cursor |
| Codex strips the environment of stdio MCP children unless names are allowlisted | Physical property of Codex |
| One 1Password service account cannot span accounts | Physical property of 1Password |
| The sensitive tier requires Touch ID on the Mac | Physical property; makes the tier human-only by construction |
| The TOML standard-library parser needs Python 3.11 or newer | Physical; system Python on the Mac is 3.9 |
| Conductor cloud does not wait for the setup script before the first turn | Observed; setup must be fast and side-effect free |
| Render logins differ per project (three separate user accounts today) | Observed; multi-account is unavoidable |

## Constraints eliminated

| Removed | Replaced by |
| --- | --- |
| SessionStart, SubagentStart, and all other hooks | Nothing. Memory is pull-only through skills |
| Start packet, packet telemetry, starred Tier 2 memory | Committed instruction files per repo |
| Central `config/project-tools.json` registry | The per-repo descriptor |
| Central tool table and naming conventions | Explicit `exec`, `env`, `args` per tool in the descriptor |
| Per-service wrappers (`render-cli`, `psql-cli`, `resend-cli`, `slack-api`, `tailscale-admin`) | One launcher |
| Per-repo rendered MCP config files | One user-global stanza per harness, rendered once per machine |
| `extends` chains between sibling checkouts | Self-contained descriptor per repo |
| Git-remote project resolution | Nearest `agent-workflows.toml` above the working directory |
| Fast-forward pull of the checkout at cloud setup | The Cloud Computer build's copy, refreshed by rebuild |
| Separate shim and launcher | The launcher itself on PATH |
| Sensitive notifier daemon | A one-line notification call inside the launcher |
| Project-level `secrets.yaml` rotation manifest | `[secrets.*]` sections in the same descriptor |
| Fly hosting entries | Deprecated; removed with amaruplatform-website |
| Amaru OAuth MCP in developer config | Not a developer tool; coaches only |

## Components

Four things exist. Nothing else.

1. **Descriptor**: `agent-workflows.toml` at each repository root. Owned by that repository.
2. **Launcher**: `aw`, one Python script in the agent-workflows checkout, on PATH.
3. **Render step**: one command that writes per-harness symlinks and MCP stanzas once per machine.
4. **Skills**: methodology documents in the checkout, linked into each harness's skills directory.

Per 1Password account, outside the repository: one service-account token in the Mac Keychain, and
the same token in each Conductor project's environment map.

## Descriptor

Path: `agent-workflows.toml` in the repository root. Discovery: the launcher walks up from the
working directory to the nearest file with that exact name and stops at the first match. No file
means every command fails with the path list it searched. Nothing else is inferred.

```toml
schema = 1

[onepassword]
account = "fulcrumtechnologies.1password.com"
service_account_token_env = "AMARU_OP_SERVICE_ACCOUNT_TOKEN"
service_account_keychain_item = "op-amaru-token"

[secrets.autodev-token]
ref = "op://AMARU/Autodev/api_token"
provider = "self_minted"
routes = [
  { kind = "render", dest = "srv-xxxxxxxxxxxxxxxxxxxx", env = "AUTODEV_API_TOKEN" },
]

[secrets.render-api-key]
ref = "op://AMARU/Render/api_key"
provider = "manual"
routes = []

[secrets.postgres-staging-ro]
ref = "op://AMARU/Postgres staging/ro"
provider = "postgres"
routes = []

[secrets.postgres-prod-app]
ref = "op://AMARU-sensitive/Postgres prod/amaru_web"
provider = "postgres"
sensitive = true
routes = [
  { kind = "render", dest = "srv-d508pta4d50c738fubl0", env = "DATABASE_URL" },
]

[secrets.website-api-dev-token]
ref = "op://AMARU/Website API/dev_token"
provider = "self_minted"
routes = []

[tools.autodev-mcp]
exec = "mcp-remote"
args = ["https://autodev-amaru.onrender.com/mcp", "--header", "Authorization: Bearer ${AUTODEV_TOKEN}"]
env = { AUTODEV_TOKEN = "secrets.autodev-token" }

[tools.render]
exec = "render"
args = ["--output", "json"]
env = { RENDER_API_KEY = "secrets.render-api-key" }

[tools.postgres-staging]
exec = "psql"
args = ["--set", "ON_ERROR_STOP=1"]
env = { PGCONNECT = "secrets.postgres-staging-ro" }

[tools.postgres-prod-write]
exec = "psql"
sensitive = true
env = { PGCONNECT = "secrets.postgres-prod-app" }

[tools.dev]
exec = "bun"
args = ["run", "dev"]
env = { AMARU_API_URL = "http://localhost:3000", WEBSITE_API_TOKEN = "secrets.website-api-dev-token" }
```

### Schema

`schema` (integer, required). Currently `1`.

`[onepassword]` (required):

| Key | Type | Meaning |
| --- | --- | --- |
| `account` | string | 1Password account URL. Used for the human path only |
| `service_account_token_env` | string | Environment variable holding the service-account token in cloud |
| `service_account_keychain_item` | string | Mac Keychain service name holding the same token locally |

`[secrets.<name>]` (zero or more). One entry per 1Password field this repository owns or reads:

| Key | Type | Meaning |
| --- | --- | --- |
| `ref` | string | `op://Vault/Item/field`. Written exactly once in the file |
| `provider` | string | Rotation provider name, or `manual` |
| `sensitive` | bool, default false | Read through the human path, never the service account |
| `routes` | array of tables | Where rotation pushes the new value. Empty when this repo only reads |

Route table: `kind` (`render`, `github`, `prefect`), `dest` (service or repository id), `env`
(destination variable name). Additional rotation keys (`mode`, `playbook`, `verify`, `health`)
carry over from the current manifest unchanged.

`[tools.<name>]` (one or more). The name is what agents type after `aw`:

| Key | Type | Meaning |
| --- | --- | --- |
| `exec` | string | Binary to execute, resolved on PATH |
| `args` | array of strings, default empty | Prepended to the agent's arguments verbatim |
| `env` | table of string to string | Child environment. A value of the form `secrets.<name>` resolves to that secret's field value. Any other string is a literal |
| `sensitive` | bool, default false | Required true when any referenced secret is sensitive |

Values in `args` may contain `${VAR}` where `VAR` is a key in the tool's `env`; the launcher
substitutes it after resolution. Nothing else is interpolated.

### Validation

The launcher rejects the file when:

- `schema` is not `1`.
- Any `secrets.<name>` referenced from a tool does not exist.
- A tool references a sensitive secret without `sensitive = true`.
- A `ref` does not match `op://<vault>/<item>/<field>`.
- The same `ref` string appears in two `[secrets.*]` entries.

No other validation. No vault allowlist, no exec allowlist, no command allowlist.

## Launcher

Name: `aw`. Location: `bin/aw` in the checkout, symlinked onto PATH by the render step.

```
aw <tool> [-- <args...>]
aw <tool> --reason "<text>" [-- <args...>]     # required when the tool is sensitive
aw --list                                      # tool names from the nearest descriptor
```

Behaviour, in order:

1. Find the descriptor by walking up from the working directory. Fail if none.
2. Parse and validate.
3. Look up `<tool>`. Fail with the list of declared tools if absent.
4. Resolve the token. Regular tools: read `service_account_token_env`, else on Darwin the Keychain
   item, else fail naming both. Sensitive tools: require `--reason`, post a macOS notification with
   the reason and tool name, then read through the human account with `op --account`. In cloud the
   human path fails with "human-only".
5. Read each referenced secret's field with `op read`. Values enter memory only.
6. Build the child environment: the parent environment, minus every variable ending in
   `_OP_SERVICE_ACCOUNT_TOKEN`, plus the tool's `env` table with secrets substituted.
7. Substitute `${VAR}` in `args`.
8. `exec` the binary with `args` followed by the agent's arguments. The launcher process is
   replaced; nothing is logged, cached, or written.

The launcher never prints a resolved value. It never inspects git. It never reads any file other
than the descriptor.

### Runtime

The script declares its interpreter with uv inline metadata and is executed via
`#!/usr/bin/env -S uv run --script` with `requires-python = ">=3.11"`. uv is the only machine
dependency, installed by Homebrew locally and by the Cloud Computer install script in cloud. No
virtualenv, no version file. The same header is applied to every other Python script in the
checkout.

## Render step

Name: `render-harness-config`. Run once per machine locally, and by every Conductor project's setup
script in cloud. It takes the checkout path and writes, per harness:

| Harness | Written |
| --- | --- |
| Claude | skills symlink, `aw` on PATH, user-scope stdio MCP entry `aw autodev-mcp` |
| Codex | skills symlink, `aw` on PATH, `[mcp_servers.autodev]` stanza with `env_vars` listing every `service_account_token_env` |
| Grok | skills symlink, `aw` on PATH, stdio MCP entry `aw autodev-mcp` |
| Cursor | skills symlink, `aw` on PATH, stdio MCP entry `aw autodev-mcp` |

Codex's `env_vars` list is the one place account names reach rendered config. The render step
takes them from a machine-level file, `~/.config/agent-workflows/accounts.toml`, listing the token
variable names explicitly. That file holds names only.

Context7 stays as a user-global HTTP entry in each harness. No other MCP servers are rendered.

The step is idempotent, takes under a second, performs no network access, and runs no git command.
Cloud freshness is the Cloud Computer build; a merge reaches cloud on the next rebuild.

## Autodev

One autodev deployment per project. The URL identifies the project, so the bridge sends no slug and
no restricted-token scheme exists. The bridge is the generic `mcp-remote` proxy launched as a tool
row; agent-workflows ships no bridge code. The MCP stanza in every harness is the constant command
`aw autodev-mcp`, which resolves the descriptor of whatever repository the harness was started in.

## Skills

Tool skills describe the vendor CLI and refer to "the tool this repository declares", showing
`aw <tool> -- ...` examples. They contain no credential, no project name, and no wrapper name.
Methodology skills are unchanged. Skills are linked, never copied.

## Rotation

Rotation runs per repository against the same descriptor. `rotate-secret` reads `[secrets.*]`,
rotates through the named provider, writes the vault in place, and fans out along `routes`.
A secret consumed by several repositories is owned by exactly one descriptor, which carries its
routes; other repositories reference the same `ref` string in their own `[secrets.*]` entry with
`provider = "manual"` and empty routes. The rotation engine reads TOML instead of YAML; its
providers and writers are unchanged.

## Application dev secrets

The application's own local run is a tool row, `aw dev`, whose `env` mixes literals and secret
references. The dotenv file is deleted from disk and from the ignore list. The descriptor is now
the complete statement of what the app needs to run.

## Invariants carried as tests

- Rendered harness configs contain no values, only commands and variable names.
- A resolved secret exists only in the exec'd child's environment.
- No descriptor above the working directory fails every command.
- A tool referencing an undeclared secret fails validation.
- A sensitive tool without `--reason` fails before any 1Password call.
- The launcher's environment scrub removes every `*_OP_SERVICE_ACCOUNT_TOKEN` from the child.

## Rollout, Amaru first

1. Land `bin/aw`, `render-harness-config`, and the tests in agent-workflows.
2. Write `agent-workflows.toml` for amaru-websites, then amaru-web, amaru-mcp, amaru-website,
   amaru-mobile. Migrate each repository's rotation entries from the shared manifest into its own
   `[secrets.*]` sections.
3. Rewrite tool skills to the `aw <tool>` form.
4. Delete: `hooks/`, `config/project-tools.json`, `config/mcp.json`, the five wrappers,
   `bin/mcp-bridge`, `bin/sync-mcp`, `bin/project-context`, `mcp-proxies/`, per-repo `.mcp.json`,
   `.codex/config.toml`, `.cursor/mcp.json`, `.grok/` files, and amaru-web's `secrets.yaml`.
5. Replace each Conductor project's cloud setup script with the single render command.
6. Rotate the amaru-websites website API dev token, which was on disk in plaintext.
7. Repeat for TS, Workflow Pro, and Autodev.

## Decided facts

- 1Password plan is Business; refs stay by name.
- Autodev remains an MCP server, one deployment per project.
- Hosting is per repository, not per project. Amaru uses Render for its services and Vercel for
  the mobile web export. Cortex uses Vercel and Neon. Both fit as tool rows.
- Render, Vercel, Neon, Fly, psql, Resend, Slack, and Tailscale all accept a per-invocation
  credential in the environment. No saved login is ever used.

## Open

- Which harnesses to render for beyond Claude and Codex.
- Confirm uv as the single runtime dependency on Hermes.

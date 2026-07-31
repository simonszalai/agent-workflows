# Hermes infrastructure

This directory preserves the reviewed, deployed Hermes-specific integration code. It replaces the
large retired `mcp-gateway`/activation subsystem with two small loopback services:

- `hermes-autodev-mcp`: the shared `mcp-proxies/mcp-proxy.mjs` plus WAF encoder, configured with
  Hermes' restricted autodev-memory credential.
- `hermes-conductor`: a dedicated MCP server wrapping the official Conductor API.

The Conductor tools can launch arbitrary tasks in any `TS-Value-Software` repository, list
Hermes-created launches, inspect session status, and read session messages. Repository URLs are
constructed server-side, caller-supplied environment variables are not supported, and
`ts-prefect` defaults to `staging`.

## Secret boundary

No secret values or secret-fetching commands are committed here.

| Runtime credential | Canonical source | Root-only runtime file |
|---|---|---|
| Autodev restricted token | `AUTODEV-sensitive/HERMES_AUTODEV_MEMORY_TOKEN` | `/etc/hermes-mcp/autodev-memory.token` |
| Conductor API key | `TS/CONDUCTOR_API_KEY` | `/etc/hermes-conductor/conductor-api.token` |

Both runtime files must be regular, non-empty, `root:root` mode `0400`. systemd `LoadCredential`
makes each secret readable only by its dedicated service. The `hermes` account and messaging
platform users receive only unauthenticated loopback MCP URLs.

## Layout

- `conductor/server.py`: Conductor API MCP implementation deployed to
  `/opt/hermes-conductor/server.py`.
- `conductor/requirements.txt`: exact dependency versions from the deployed virtual environment.
- `bin/run-autodev-memory`: systemd credential-to-process boundary for the generic MCP proxy.
- `systemd/`: hardened service definitions.
- `configure.py`: idempotently merges the two MCPs and Slack toolsets into Hermes `config.yaml`.
- `install.sh`: reconciles code, dependencies, configuration, and services after credentials are
  staged separately.

The generic proxy and WAF encoder remain canonical in `mcp-proxies/`; the installer deploys those
files rather than duplicating them here.

## Install or reconcile

Stage both credential files through a protected, non-logging channel, then run as root from a
clean, reviewed checkout:

```bash
hermes/install.sh
```

The installer refuses missing, symlinked, empty, non-root-owned, or incorrectly permissioned
credentials. It does not create, fetch, print, or rotate secrets.

## Verification

```bash
systemctl is-active hermes-autodev-mcp hermes-conductor hermes-gateway
systemctl is-enabled hermes-autodev-mcp hermes-conductor
sudo -u hermes -H /home/hermes/.hermes/hermes-agent/venv/bin/python \
  -m hermes_cli.main mcp test autodev-memory
sudo -u hermes -H /home/hermes/.hermes/hermes-agent/venv/bin/python \
  -m hermes_cli.main mcp test conductor
ss -ltn | grep -E '127[.]0[.]0[.]1:(8792|8794)'
```

Expected Conductor tools:

- `get_launch_policy`
- `launch_workspace`
- `list_launches`
- `get_session_status`
- `read_session_messages`

## Rotation

Replace only the corresponding root-only runtime file through protected stdin, restore
`root:root` mode `0400`, and restart its dedicated service. Never place either value in Hermes
`.env`, `config.yaml`, an MCP client configuration, argv, logs, or this repository.

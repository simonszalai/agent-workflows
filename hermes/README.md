# Hermes infrastructure

This directory preserves the reviewed, deployed Hermes-specific integration code. It replaces the
large retired `mcp-gateway`/activation subsystem with two small loopback services:

- `hermes-autodev-mcp`: the shared `mcp-proxies/mcp-proxy.mjs` plus WAF encoder, configured with
  Hermes' restricted autodev-memory credential.
- `hermes-conductor`: a complete typed MCP facade over the official Conductor API.

The Conductor MCP covers every operation in the current public OpenAPI contract: account and
project reads; workspace listing, creation, status, rename, archive, and sessions; session
creation, status, rename, archive, cancel, transcript reads, and messages; plus organization-wide
read-only transcript SQL. Workspace creation supports either a Conductor project or repository URL
and includes the official branch, agent, model, effort, channel, and environment options.

## Secret boundary

No secret values or secret-fetching commands are committed here.

| Runtime credential | Canonical source | Root-only runtime file |
|---|---|---|
| TS autodev token | `TS/TS_AUTODEV_MEMORY_API_TOKEN` (`value`) | `/etc/hermes-mcp/autodev-memory.token` |
| Conductor API key | `TS/CONDUCTOR_API_KEY` | `/etc/hermes-conductor/conductor-api.token` |
| Slack token (schedule reporting) | `TS/TS_SLACK_MCP_USER_TOKEN` (`value`) | `/etc/hermes-schedules/slack.token` |

Both runtime files must be regular, non-empty, `root:root` mode `0400`. systemd `LoadCredential`
makes each secret readable only by its dedicated service. The `hermes` account and messaging
platform users receive only unauthenticated loopback MCP URLs.

Autodev-memory uses separate restricted tokens for `ts`, `amaru`, and `workflow_pro`. This Hermes
endpoint is intentionally TS-scoped: the server pins it to `ts` even if a caller supplies another
project name. Adding another project requires a separate credential boundary and MCP endpoint; do
not replace this file with an admin or cross-project token.

## Layout

- `conductor/server.py`: Conductor API MCP implementation deployed to
  `/opt/hermes-conductor/server.py`.
- `conductor/requirements.txt`: exact dependency versions from the deployed virtual environment.
- `bin/run-autodev-memory`: systemd credential-to-process boundary for the generic MCP proxy.
- `schedules/`: the scheduled-run manifest, thin prompt files, and `runner.py` — the timer-driven
  runner deployed to `/opt/hermes-schedules` (see `schedules/README.md`).
- `systemd/`: hardened service definitions, plus the schedule template service
  (`hermes-schedule@.service`), one instantiated timer per manifest entry, the OnFailure alert
  template, and the watchdog service/timer pair.
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
systemctl list-timers 'hermes-schedule*' --all
systemd-analyze verify /etc/systemd/system/hermes-schedule@health-6h.timer
```

To manually trigger one scheduled run under the real unit environment (the M3 gate check):

```bash
systemctl start hermes-schedule@health-6h.service
journalctl -u hermes-schedule@health-6h.service -f
```

Expected Conductor tools are locked by `OFFICIAL_OPERATION_TOOLS` in
`hermes/conductor/server.py`. There is one typed tool for each current OpenAPI operation. Use
`list_projects` followed by `list_project_workspaces` to enumerate cloud workspaces. For
organization-wide activity, use `query_conductor_sql` over `session_transcripts_view`, then resolve
workspace IDs with `get_workspace`.

## Rotation

Replace only the corresponding root-only runtime file through protected stdin, restore
`root:root` mode `0400`, and restart its dedicated service. Never place either value in Hermes
`.env`, `config.yaml`, an MCP client configuration, argv, logs, or this repository.

# Hermes infrastructure

This directory is the rebuild and runtime source of truth for the standalone Hermes host. It
contains the two small loopback services, gateway configuration, scheduled runs, and the scripts
needed to repeatably configure a reachable Ubuntu 24.04 x86_64 machine. Protected credentials,
cloud creation, and messaging/provider re-pairing remain explicit external boundaries below.

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
| TS autodev token | `op://TS/Autodev memory restricted/api_token` | `/etc/hermes-mcp/autodev-memory.token` |
| Conductor API key | `op://TS/CONDUCTOR_API_KEY/value` | `/etc/hermes-conductor/conductor-api.token` |
| Slack token (schedule reporting) | `op://TS/Slack/mcp_user_token` | `/etc/hermes-schedules/slack.token` |
| TS 1Password service-account token | `op://TS/1Password service account/token` | `/etc/hermes-schedules/op.token` |

These files are manifest-routed consumers (`kind: hermes` rows in
`ts-prefect/secrets.yaml`, pushed by `secrets/lib/writers/hermes` over SSH with
passwordless sudo): rotations and `sync-secrets` sweeps update them
automatically, including a `hermes-autodev-mcp` / `hermes-conductor` restart
where needed. Manual staging remains the bootstrap path only.

All four runtime files must be regular, non-empty, `root:root` mode `0400`. systemd `LoadCredential`
makes each secret readable only by its dedicated service. The `hermes` account and messaging
platform users receive only unauthenticated loopback MCP URLs.

Autodev-memory uses separate restricted tokens for `amaru`, `autodev`, `ts`, and `workflow_pro`. This Hermes
endpoint is intentionally TS-scoped: the server pins it to `ts` even if a caller supplies another
project name. Adding another project requires a separate credential boundary and MCP endpoint; do
not replace this file with an admin or cross-project token.

## Layout

- `conductor/server.py`: Conductor API MCP implementation deployed to
  `/opt/hermes-conductor/server.py`.
- `conductor/requirements.txt`: exact dependency versions from the deployed virtual environment.
  The companion `requirements.in` is the readable pin set; regenerate the install file with the
  checked-in `uv pip compile --generate-hashes --universal` command in its header.
- `bin/run-autodev-memory`: systemd credential-to-process boundary for the generic MCP proxy.
- `schedules/`: the scheduled-run manifest, thin prompt files, and `runner.py` — the timer-driven
  runner deployed as immutable releases under `/opt/hermes-schedules/releases` (see
  `schedules/README.md`).
- `bin/hermes-schedule-release`: fixed, root-owned schedule release manager. It fetches only
  public `agent-workflows/main`, rejects history rewrites, validates a staged schedule bundle as
  the secretless builder account, and atomically moves `current` only after every check passes.
- `bin/hermes-schedule-alert`: fixed alert path outside schedule releases, so a broken candidate
  cannot suppress its own failure notification; sync alerts are deduplicated only after Slack
  acknowledges delivery.
- `bin/run-schedule-release`: resolves `current` to an absolute release before Python starts, so
  an already-running job keeps its original runner, dependencies, manifest, and prompts.
- `bin/gateway-watchdog`: root oneshot (5-minute timer) that restarts `hermes-gateway` when its
  Slack socket-mode connection is provably dead (process alive but deaf), and posts a one-time
  alert to `#autodev-incidents` when the WhatsApp adapter is in the logged-out state that only
  manual QR re-pairing can fix.
- `patches/`: local `git format-patch` fixes to the hermes-agent checkout that upstream lacks
  (currently: WhatsApp `format_message` rewrites GFM tables into bold-heading bullet groups,
  because WhatsApp renders pipe tables as raw text). `install.sh` re-applies them idempotently,
  so they survive `hermes update`; the SOUL.md "never use markdown tables" line is the
  prompt-side half of the same fix.
- `systemd/`: the gateway and hardened integration services, plus the schedule template service
  (`hermes-schedule@.service`), one instantiated timer per manifest entry, the OnFailure alert
  template, and the watchdog service/timer pair.
- `config/`: the non-secret Hermes config, SOUL, Slack app manifest, and custom ops skill copied
  from the known-good host. `gateway.env.example` documents secret input names, never values.
- `versions.env`: pinned host contract, upstream Hermes commit and patch result, Python, uv, Node,
  and upstream archive hashes.
- `bootstrap.sh`: idempotent clean-host provisioner. It validates secure external inputs, installs
  pinned runtimes, reconstructs the exact patched Hermes checkout, installs configuration, and
  calls the reconciler and verifier.
- `verify.sh`: non-secret drift and service readiness checks.
- `configure.py`: idempotently merges the two MCPs and Slack toolsets into Hermes `config.yaml`.
- `install.sh`: reconciles code, dependencies, configuration, and services after credentials are
  staged separately.

The generic proxy and WAF encoder remain canonical in `mcp-proxies/`; the installer deploys those
files rather than duplicating them here.

## Clean-host rebuild

Docker is intentionally not the rebuild boundary. Hermes depends on host systemd credentials,
journald and socket watchdogs, loopback MCP services, persistent messaging sessions, and local
terminal execution. Containerizing that safely would require a multi-container redesign and
would still not provision SSH, Tailscale, or secret recovery. The deterministic configuration
boundary is a reviewed host bootstrap plus immutable schedule releases. EC2/AMI creation and the
Ubuntu apt repository snapshot remain external inputs, so this does not claim a byte-identical
machine image.

Start with a reachable Ubuntu 24.04 x86_64 host. Establish SSH and, if required, Tailscale outside
this repository. The known-good AWS shape is `t3.small` in `eu-central-1` with a 60 GiB root disk;
the bootstrap creates and verifies 2 GiB of swap. At capture time the host ran Tailscale 1.102.2,
but the script deliberately does not enroll a node or assume whether the SSH alias uses a tailnet
or public route. Clone a clean reviewed `agent-workflows/main` checkout. Before invoking the
bootstrap, stage these regular, non-empty `root:root` mode `0400` files through a non-logging
channel:

- `/etc/hermes-bootstrap/gateway.env`: populated from `config/gateway.env.example`; contains the
  Slack gateway tokens, channel/user allowlists, WhatsApp settings, and non-secret runtime flags.
- `/etc/hermes-bootstrap/auth.json`: current Hermes provider authentication state.
- `/etc/hermes-mcp/autodev-memory.token`, `/etc/hermes-conductor/conductor-api.token`,
  `/etc/hermes-schedules/slack.token`, and `/etc/hermes-schedules/op.token`: the four manifest-
  routed service credentials listed above.

Then run:

```bash
sudo hermes/bootstrap.sh
```

The script refuses an unexpected OS, architecture, secret mode, upstream origin, agent revision,
dirty agent checkout, patch result, or download checksum. It does not reset, stash, or overwrite
an unrecognized Hermes checkout. Re-running it against a host it created is supported.

Two recovery boundaries cannot safely live in Git:

- WhatsApp pairing/session state requires a new QR pairing after a total loss unless it was
  restored from a separately encrypted backup. Re-pair with
  `sudo -u hermes -H /home/hermes/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main
  whatsapp`.
- `auth.json`, gateway tokens, SSH identity, Tailscale enrollment, message/session history, and
  user memories are secret or mutable state. The bootstrap consumes current protected inputs but
  does not pretend source control can recreate them. If provider state cannot be restored, use
  `sudo -u hermes -H /home/hermes/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main auth
  add xai-oauth --type oauth` through an interactive protected session, then rerun verification.

The checked-in Slack manifest records the desired app scopes and socket-mode configuration. If
the Slack app itself was deleted, recreate or update it from `config/slack-manifest.json` before
expecting the gateway to connect.

## Install or reconcile an existing host

Ensure the existing Hermes config and the four service credential files listed above are present,
then run as root from a clean, reviewed checkout:

```bash
hermes/install.sh
```

The installer refuses missing, symlinked, empty, non-root-owned, or incorrectly permissioned
credentials. It also refuses any dirty checkout or a revision other than the freshly queried
public `main`, and exports privileged inputs from that exact commit rather than the worktree. It
installs the fixed sync machinery, seeds an immutable release from the checked-out Git commit, and
never creates, fetches, prints, or rotates secrets.

## Automatic prompt and schedule updates

`hermes-schedule-sync.timer` checks public `agent-workflows/main` every 15 minutes with up to five
minutes of jitter. It does not run a fetched shell script, `git pull` a working tree, or restart an
active schedule. It exports only committed top-level runtime assets from `hermes/schedules/`,
requires a fast-forward from the last observed main commit (including candidates that fail
validation), requires hash-locked binary Python
dependencies, validates the manifest against the installed timer inventory and deployment
contract, and builds the candidate as the secretless `hermes-schedule-builder` account. A single
symlink rename makes a valid release current; failures leave the prior release untouched.

Runtime and host topology changes remain manual. A new schedule/timer, cron change, host-runtime
requirement, systemd change, MCP change, or bootstrap change must first be applied from a reviewed
checkout with `hermes/install.sh`. A `deployment_contract_version` bump deliberately blocks
automatic activation until that manual update occurs.

Useful commands:

```bash
sudo /opt/hermes-schedules/bin/hermes-schedule-release status
sudo systemctl start hermes-schedule-sync.service
sudo journalctl -u hermes-schedule-sync.service
sudo /opt/hermes-schedules/bin/hermes-schedule-release rollback
sudo /opt/hermes-schedules/bin/hermes-schedule-release unquarantine BUNDLE_HASH
```

Rollback switches to `previous` and quarantines the bad runtime-bundle hash. The timer will not
immediately redeploy that bundle; a later main commit must actually change runtime schedule assets.
An operator can explicitly unquarantine the exact hash after diagnosing an accidental rollback.
Releases are not automatically pruned because a health run and its remediation children may keep
opening their pinned prompt bundle for up to ten hours. Repeated identical sync failures generate
at most one Slack incident per 24 hours; a successful check clears the failure fingerprint.

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
sudo /opt/hermes-schedules/bin/hermes-schedule-release status
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

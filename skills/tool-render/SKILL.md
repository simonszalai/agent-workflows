---
name: tool-render
description: Render CLI reference for infrastructure investigation (render-cli wrapper — the render MCP server was retired). Portable to any project using Render.
---

# Render CLI Reference

How to inspect Render infrastructure via the CLI. The render MCP server was retired
(2026-07-28) — use `render-cli` (agent-workflows/bin, on PATH) through the Bash tool.

## The wrapper: `render-cli`

`render-cli` is the official Render CLI with credentials injected silently per call
(1Password service-account token; no Touch ID, nothing stored in your environment).
It pins the single workspace and never prompts. Pass any official CLI args through it:

```bash
render-cli services -o json                                  # list all services
render-cli deploys list <srv-id> -o json --confirm           # deploy history
render-cli logs -r <srv-id> --limit 50 -o json --confirm     # recent logs
render-cli psql <postgres-id>                                # never use for app DBs — use the project's sql wrapper
```

- **Always pass `-o json --confirm`** on list/query commands: `-o json` gives parseable
  output, `--confirm` suppresses interactive prompts (headless safety).
- Pipe through `jq` and bound output — logs and service lists are large. Never dump
  raw output into context; select fields.
- If `render-cli` reports the CLI missing: `brew install render` (Mac) or the
  install script it prints (Linux/cloud).

## Access rules (unchanged from the MCP era)

**Render read access is durably pre-authorized by Simon**: services, deploys, logs,
metrics, and env-var **names**. Never ask "may I read X" — even when a plan or ticket
lists the Render step as "parked" or "pending approval"; treat reads as already
approved. Env-var **values** stay unprintable; mutations (env-var changes, triggering
deploys, service changes) require explicit instruction.

There is exactly ONE workspace: `tea-ct11rp0gph6c73bf2kf0` ("Thomas's workspace") —
the wrapper pins it; workspace selection can never be a reason to stop or ask.

Render inventory is account-scoped, not global. `ts-decrypt-proxy` production is
intentionally owned in Thomas's separate security boundary and may be absent from this
workspace. Never infer it does not exist, create a substitute, or attempt its
deployment; land verified code on `main` and hand the commit SHA to Thomas (project
memory `216431b0`).

## Common commands

| Task | Command |
| ---- | ------- |
| List services | `render-cli services -o json` |
| Service details | `render-cli services -o json \| jq '.[] \| select(.service.id=="srv-xxx")'` |
| Deploy history | `render-cli deploys list srv-xxx -o json --confirm` |
| Recent logs | `render-cli logs -r srv-xxx --limit 50 -o json --confirm` |
| Error logs | `render-cli logs -r srv-xxx --level error --limit 50 -o json --confirm` |
| Time-windowed logs | `render-cli logs -r srv-xxx --start 2026-01-13T14:00:00Z --end 2026-01-13T15:00:00Z -o json --confirm` |
| Text search in logs | `render-cli logs -r srv-xxx --text "ConnectionError" --limit 50 -o json --confirm` |
| Restart service (mutation — explicit instruction only) | `render-cli restart srv-xxx --confirm` |

`render-cli logs --help` lists all filters (level, type, statusCode, method, host...).

## Metrics

The CLI has no metrics command. For triage, logs almost always carry the signal
(exit code -9 = OOM SIGKILL; correlate restarts via `deploys list` + logs). When a
human needs graphs, give them the service's `dashboardUrl` from `render-cli services
-o json`. If a numeric CPU/memory answer is truly required, say so — the REST metrics
endpoint can be added to the wrapper, but is deliberately not there yet.

## Deployment model reminder (ts-prefect)

Flows pull latest code from git at runtime. Code changes need NO Render deploy;
`ts-prefect-worker` redeploys only for pyproject.toml / Dockerfile / env-var changes.
Never use Render deploy timestamps to judge whether code is live.

## Render SSH access and host-key diagnostics

Render service SSH uses the normal OpenSSH client:

```text
ssh <service-id>@ssh.<region>.render.com
```

On Simon's Mac, `~/.ssh/config` routes client authentication through the 1Password SSH
agent. Do not `op read` or copy a private key into a file/argv. A successful remote
command proves the client key authenticated; do not relabel a later protocol failure
as "missing 1Password access."

Render's gateway may fail OpenSSH's **post-authentication** host-key rotation with
`client_global_hostkeys_prove_confirm: server gave bad signature`. That concerns
Render's proof for an additional **server** host key. Retry with:

```text
-o StrictHostKeyChecking=yes -o UpdateHostKeys=no
```

Never "fix" it with `StrictHostKeyChecking=no` or `UserKnownHostsFile=/dev/null`.
For ts-scraper Docker services invoke `/app/.venv/bin/python` explicitly.

Before any cohort/fan-out/bulk SSH operation, run **one real canary through the exact
final argv, interpreter, stdin/protocol, and cleanup path** and keep a bounded,
credential-free failure excerpt before spending the fan-out budget.

## Common Patterns

**OOM Detection:** exit code -9 + memory climb before restart + flow failures in the
same window.

**Connection issues:** "keepalive ping failed" in logs, WebSocket disconnects,
correlated DB connection errors.

**Deploy failures:** `deploys list` status + `render-cli deploys` build logs; separate
build-time errors from runtime crashes by timing against service restarts.

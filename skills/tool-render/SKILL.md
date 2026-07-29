---
name: tool-render
description: Project-aware Render CLI reference for infrastructure investigation across TS, Autodev, Amaru, and WorkFlow Pro.
---

# Render CLI Reference

How to inspect Render infrastructure via the CLI. The render MCP server was retired
(2026-07-28) — use `render-cli` (agent-workflows/bin, on PATH) through the Bash tool.

## Project and authentication contract

Never call the raw `render` binary for project work. Its locally logged-in token and
workspace are user-global and may belong to a different project.

`render-cli` resolves the exact Git `origin` through the committed
`config/project-tools.json` registry. There is no default profile and no fuzzy
directory-name matching. The registered projects are `amaru`, `autodev`, `ts`, and
`workflow-pro`; every known repository remote for those projects maps to exactly one
profile.

The skill contains no credential. The wrapper:

1. selects the project from the exact repository remote;
2. reads only that profile's committed `op://...` reference through the audited
   `bin/op` shim, or accepts an already-approved process-local `RENDER_API_KEY`;
3. discovers or pins the matching Render workspace;
4. exports the key and workspace only to the official CLI child process.

It never writes a token to a repository, dotenv file, CLI config, command argument,
or shell profile. A raw Render CLI login cannot override the selected credential.

Render does not provide per-key read scopes. The TS profile is deliberately routed
through the service-account-readable `op://TS/TS_RENDER_API_KEY/value` so agents can
perform unattended infrastructure reads; the wrapper's command allowlist still
requires an explicit matching project, `--write`, and `--reason` for mutations.
Profiles whose keys remain in `*-sensitive` are human-only: agent shells fail closed
unless an approved process-local `RENDER_API_KEY` is provided. A human can run those
profiles from a normal terminal through the reason/notification/Touch ID contract.
Do not bypass this with `/opt/homebrew/bin/op` or the raw Render CLI.

Safe, credential-free selection check:

```bash
render-cli context
```

Authenticated profile/workspace check:

```bash
render-cli doctor
```

Read commands auto-detect the project:

```bash
render-cli services -o json                                  # list all services
render-cli deploys list <srv-id> -o json --confirm           # deploy history
render-cli logs -r <srv-id> --limit 50 -o json --confirm     # recent logs
```

- **Do not use `render-cli psql` for application databases** — use the project's
  reviewed SQL wrapper.
- **Always pass `-o json --confirm`** on list/query commands: `-o json` gives parseable
  output, `--confirm` suppresses interactive prompts (headless safety).
- Pipe through `jq` and bound output — logs and service lists are large. Never dump
  raw output into context; select fields.
- If `render-cli` reports the CLI missing: `brew install render` (Mac) or the
  install script it prints (Linux/cloud).

## Mutation and override guardrails

The wrapper maintains a read-command allowlist. Unknown, interactive, or mutating
commands fail unless all three safeguards are present:

```bash
render-cli --project workflow-pro --write \
  --reason "Restart the reviewed workflow-pro service for F0123" \
  restart srv-xxx --confirm
```

- the user explicitly instructed the mutation;
- `--project` names the intended credential profile;
- `--reason` explains the authorized change.

Inside any Git repo, an explicit project must match its registered origin; unregistered
and mismatching origins are rejected. A deliberate cross-project operation additionally
requires `--allow-cross-project`; do not use it to work around a mapping error. Fix
`config/project-tools.json` instead.

Env-var **values** remain unprintable. Service, deploy, log, metrics, and env-var-name
reads may be performed only through an available approved credential route.

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
| Show selected profile without auth | `render-cli context` |
| Validate credential and workspace | `render-cli doctor` |
| Restart service (mutation — explicit instruction only) | `render-cli --project <id> --write --reason "<purpose>" restart srv-xxx --confirm` |

`render-cli logs --help` lists all filters (level, type, statusCode, method, host...).

## Metrics (REST passthrough)

The CLI has no metrics command; use the wrapper's REST passthrough:

```bash
render-cli api GET "/v1/metrics/cpu?resource=srv-xxx"
render-cli api GET "/v1/metrics/memory?resource=srv-xxx"
render-cli api GET "/v1/metrics/instance-count?resource=srv-xxx"
render-cli api GET "/v1/metrics/http-request-count?resource=srv-xxx"
# optional: &startTime=<RFC3339>&endTime=<RFC3339>&resolutionSeconds=300
```

Output is `[{labels, unit, values:[{timestamp,value}...]}]` — summarize (min/max/last),
never dump the raw series. `render-cli api` works for any `/v1` endpoint the CLI lacks.
Non-GET/HEAD API calls are mutations and require the normal explicit project, write,
and reason flags; their JSON request body is read from stdin.

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

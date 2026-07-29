---
name: tool-tailscale
description: Tailscale CLI + admin API reference (tailscale CLI for local/net state, tailscale-admin wrapper for control-plane — the tailscale MCP server was retired). Portable to any project using Tailscale.
---

# Tailscale CLI Reference

How to inspect and manage Tailscale via the CLI. The tailscale MCP server (and its
local npm upstream) was retired (2026-07-28) — everything is two commands via Bash:

1. **`tailscale`** — the local CLI. No credentials at all; talks to the local daemon.
2. **`tailscale-admin`** — control-plane (admin) API wrapper (agent-workflows/bin, on
   PATH). Credentials injected silently per call (1Password service-account token, no
   Touch ID). Signature: `tailscale-admin <METHOD> </api/v2 path> [curl args...]`;
   `-` in the path = "this tailnet".

## Local state (`tailscale`, no credentials)

```bash
tailscale status                      # peers, IPs, connection state
tailscale status --json | jq ...     # machine-readable (bound the output)
tailscale ping <host-or-ip>          # connectivity + relay/derp vs direct
tailscale version
tailscale netcheck                   # NAT/derp diagnostics
tailscale ip -4 <hostname>           # resolve a peer's tailnet IP
tailscale whois <ip>                 # who owns an IP on the tailnet
```

If `tailscale` is missing: `brew install tailscale` (CLI only) — on Simon's Mac the
app is installed and the CLI is at `/opt/homebrew/bin/tailscale`.

## Control-plane (`tailscale-admin`, silent credential injection)

```bash
tailscale-admin GET /tailnet/-/devices | jq -r '.devices[].hostname'
tailscale-admin GET /tailnet/-/devices | jq '.devices[] | select(.hostname=="x")'
tailscale-admin GET /tailnet/-/keys                       # auth keys (names/ids only)
tailscale-admin GET /tailnet/-/acl                        # ACL/policy file (HuJSON)
tailscale-admin GET /tailnet/-/dns/nameservers
tailscale-admin GET /device/<node-id>                     # device details
tailscale-admin POST /device/<node-id>/tags -d '{"tags":["tag:x"]}'   # mutation
tailscale-admin DELETE /device/<node-id>                  # remove device (mutation)
```

Full endpoint list: https://tailscale.com/api (it is a thin passthrough — any
`/api/v2` endpoint works).

## Rules

- **Reads are routine** (status, devices, ACL inspection, key *names*). **Mutations
  (ACL changes, key creation/revocation, device deletion/tags, DNS changes) require
  explicit instruction** — they can sever connectivity for running services.
- Never print auth-key secrets or the OAuth credentials; ids and names only.
- ts-prefect context: production decrypt-proxy Tailscale runs on **Thomas's tailnet**
  (his security boundary — see the prod-tailscale-service-setup skill). The
  credential here reaches Simon's tailnet only; absence of prod nodes is expected,
  not a gap.

## Common Patterns

**"Is host X reachable?"** — `tailscale status | grep -i x`, then `tailscale ping x`.
Direct connection vs DERP relay matters for throughput problems.

**Worker cannot reach a tailnet service** — check the device list for the node
(online? key expired?), then `tailscale ping` from the affected side if you have a
shell there; inspect the ACL for the service's grants.

**Key expiry incidents** — `tailscale-admin GET /tailnet/-/devices | jq '.devices[]
| {hostname, expires, keyExpiryDisabled}'` — expired node keys silently drop nodes.

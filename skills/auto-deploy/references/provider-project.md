# Provider and project-specific deployment details

Load this reference only when `.claude/commands/deploy.md` exists or project
instructions/memory name a provider-specific or manual deployment boundary.

### Phase 3: Load Project-Specific Deploy Command

Check if a project-specific `/deploy` command exists:

```bash
ls .claude/commands/deploy.md 2>/dev/null
```

If it exists, **read it** to understand the full deployment process for this
project. The project-specific deploy command defines:

- What change categories to detect (migrations, config, dependencies, etc.)
- What deployment steps to run and in what order
- What verification to perform
- What manual steps to flag to the user
- **Environment-specific commands** for staging vs production

Use this as the authoritative guide for Phases 6-9. The phases below describe
the generic process; the project-specific command overrides where it differs.


## Project-specific detection and execution

Detect every additional category named by the project command, including blocks, Prefect config,
DAG nodes, services, or provider configuration. P6b still requires a safe preflight for every
resulting command. In P8, follow the project steps in order with the environment-specific files,
API endpoints, credentials, and YAML. The project command overrides the generic fallback but never
overrides the compact skill's safety gates.

Execute every automatable CLI step instead of printing it. Skip a project guide's interactive
confirmation only because an eligible lifecycle state or explicit target argument already supplies
deploy authorization. Stop at the first failure and revert lifecycle state per
`verification-and-status.md`. Authenticated production mutations retain the audited-remote /
`bin/redacted-exec` boundary.

## External or manual deployment boundaries

Also detect **external/manual deploy blockers**. These do not prevent advancing the ticket to the
next verification status after all automatable deploy work is complete, but they must be recorded
as blocker metadata before returning.

Detect project-specific manual-deploy blockers from the project's own context — search project
memory and read the project `CLAUDE.md` / `AGENTS.md` / deployment guide for any repo or service
that a specific person must deploy by hand. Detect via: the ticket's primary repo; the ticket
artifacts/deployment guide; coordinated changes in the dependency repo's diff/PR; or an explicit
project-memory note. When one applies, record blocker metadata (`blocked_by`, `blocked_reason`,
`blocked_context`) before returning, and never deploy that service yourself.

*Example (ts-prefect):* `ts-decrypt-proxy` production deployment is **Thomas-only** (project memory
entry `216431b0`). Set `blocked_by="Thomas"`,
`blocked_reason="Waiting for Thomas to deploy ts-decrypt-proxy to production"`,
`blocked_context={"repo":"ts-decrypt-proxy","target":"production","manual_deploy_owner":"Thomas"}`,
and do not deploy `ts-decrypt-proxy` production yourself. The agent-owned boundary ends after a
verified commit is pushed/merged to the proxy repo's `main`: never create/clone/reconnect/
reauthorize/reconfigure a proxy service in an accessible Render workspace, never ask Simon to
reauthorize its GitHub integration, and never infer that production does not exist because it is
absent from the selected account. Production is intentionally in Thomas's separate security
boundary; persist the required commit SHA and hand deployment to Thomas.

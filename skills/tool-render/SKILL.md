---
name: tool-render
description: Render MCP tool reference for infrastructure investigation. Portable to any project using Render.
---

# Render MCP Tool Reference

How to use Render MCP tools for infrastructure investigation.

## Workspace Bootstrap (do this first)

The Render MCP requires a workspace to be selected before most queries work,
but `get_selected_workspace` errors with "no workspace set" when none is
selected, and `mcp__render__select_workspace` refuses to be called from
automation (it returns: "This tool should only be used after explicitly asking
the user to select one").

**The workaround:** call `mcp__render__list_workspaces` once at the start of
any Render investigation. When the account has only one workspace, that call
auto-selects it as a side effect — the common case for most single-team
projects. After that, `list_services`, `list_logs`, `get_metrics`,
`list_postgres_instances`, etc. all work normally.

```
mcp__render__list_workspaces()  # idempotent; auto-selects if single workspace
```

If the response lists multiple workspaces, stop and ask the user which one to
use — do NOT call `select_workspace` autonomously.

## Available Tools

| Tool                                 | Purpose                          |
| ------------------------------------ | -------------------------------- |
| `mcp__render__list_services`         | List all services in workspace   |
| `mcp__render__get_service`           | Get service details by ID        |
| `mcp__render__list_logs`             | Query service logs with filters  |
| `mcp__render__list_log_label_values` | Discover available filter values |
| `mcp__render__get_metrics`           | CPU, memory, HTTP metrics        |
| `mcp__render__list_deploys`          | List deployment history          |
| `mcp__render__get_deploy`            | Get specific deploy details      |

## Log Investigation Patterns

**Error hunting:**

```
list_logs(resource=[service-id], level=["error"], limit=50)
```

**HTTP error analysis:**

```
list_logs(resource=[service-id], statusCode=["5.*"], limit=50)
```

**Time-windowed search:**

```
list_logs(
  resource=[service-id],
  startTime="2026-01-13T14:00:00Z",
  endTime="2026-01-13T15:00:00Z",
  limit=100
)
```

**Text pattern search:**

```
list_logs(resource=[service-id], text=["ConnectionError", "timeout"])
```

**Discover filter values:**

```
list_log_label_values(resource=[service-id], label="level")
list_log_label_values(resource=[service-id], label="statusCode")
```

## Metrics Investigation Patterns

**Resource usage:**

```
get_metrics(
  resourceId="srv-xxx",
  metricTypes=["cpu_usage", "memory_usage"],
  startTime="2026-01-13T12:00:00Z"
)
```

**HTTP performance:**

```
get_metrics(
  resourceId="srv-xxx",
  metricTypes=["http_latency", "http_request_count"],
  httpLatencyQuantile=0.95
)
```

**Error rate by status:**

```
get_metrics(
  resourceId="srv-xxx",
  metricTypes=["http_request_count"],
  aggregateHttpRequestCountsBy="statusCode"
)
```

## Deployment Investigation

**Recent deploys:**

```
list_deploys(serviceId="srv-xxx", limit=5)
```

**Deploy details (build logs):**

```
get_deploy(serviceId="srv-xxx", deployId="dep-xxx")
```

## Common Patterns

**OOM Detection:**

- Exit code -9 = SIGKILL from Linux OOM killer
- Check memory_usage metrics for spikes above limit
- Correlate with flow failures in same time window

**Connection Issues:**

- Look for "keepalive ping failed" in logs
- Check for WebSocket disconnection patterns
- Correlate with database connection errors

**Deploy Failures:**

- Check deploy status and build logs
- Look for build-time errors vs runtime crashes
- Compare timing with service restarts

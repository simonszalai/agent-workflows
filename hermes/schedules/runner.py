#!/usr/bin/env python3
"""Hermes schedule runner: launch unattended Conductor runs and report to Slack.

Invoked by systemd (see hermes/systemd/hermes-schedule@.service):

    runner.py run <schedule-name>   one scheduled run, end to end
    runner.py alert <unit-suffix>   OnFailure hook: post a unit-failure line
    runner.py watchdog              missing-post check + workspace retention

The manifest (schedules.yaml, deployed alongside this file) is canonical. The
runner talks only to loopback services and the Slack Web API: the Conductor API
key stays inside hermes-conductor, and the Slack token arrives via systemd
LoadCredential. No secret ever appears in argv, environment, or logs.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict, cast

import yaml

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "schedules.yaml"
CONDUCTOR_URL = os.environ.get("HERMES_CONDUCTOR_URL", "http://127.0.0.1:8794/")
SLACK_API_ROOT = "https://slack.com/api"
SLACK_MENTION_SIMON = "<@U09T4LELYES>"
INCIDENTS_CHANNEL_NAME = "#autodev-incidents"
RESULT_MARKER = "SCHEDULED_RUN_RESULT"
RESULT_LIST_KEYS = ("tickets_touched", "rc_fingerprints")
RESULT_JSON_KEYS = ("issues", "dream_report")
STATUS_ICONS = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "⛔", "NEEDS_MORE_TIME": "⏳"}
DEFAULT_POLL_SECONDS = 60
DEFAULT_RETENTION_PASS_DAYS = 3
DEFAULT_RETENTION_FAIL_DAYS = 14
WATCHDOG_GRACE_MINUTES = 60
TICKET_ID_PATTERN = re.compile(r"^[A-Z]\d{4}$")

JsonObject = dict[str, object]


class HealthIssue(TypedDict):
    title: str
    proof: str
    example: str
    next_step: str
    ticket_id: str | None


class DreamReport(TypedDict):
    what: str
    why: str
    how: str
    memory_actions: list[str]
    ticket_consolidations: list[str]
    proposals: list[str]
    graph_plan: str
    scope: list[str]

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("hermes-schedules")


class RunnerError(RuntimeError):
    """A failure whose message is safe for logs and Slack."""


def state_dir() -> Path:
    return Path(os.environ.get("STATE_DIRECTORY", "/var/lib/hermes-schedules"))


def read_slack_token() -> str:
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    if not credentials:
        raise RunnerError("CREDENTIALS_DIRECTORY is not set; run under systemd.")
    token = (Path(credentials) / "slack.token").read_text().strip()
    if not token:
        raise RunnerError("Slack credential is empty.")
    return token


def load_manifest() -> JsonObject:
    data = yaml.safe_load(MANIFEST_PATH.read_text())
    if not isinstance(data, dict):
        raise RunnerError("schedules.yaml must be a YAML object.")
    return cast(JsonObject, data)


def manifest_entry(manifest: JsonObject, name: str) -> JsonObject:
    for entry in cast(list[JsonObject], manifest.get("schedules") or []):
        if entry.get("name") == name:
            return entry
    raise RunnerError(f"schedule {name!r} is not in schedules.yaml")


def channel_id(manifest: JsonObject, channel_name: str) -> str:
    channels = cast(dict[str, str], manifest.get("slack_channels") or {})
    identifier = channels.get(channel_name)
    if not identifier:
        raise RunnerError(f"no Slack channel ID recorded for {channel_name!r}")
    return identifier


def runner_settings(manifest: JsonObject) -> JsonObject:
    return cast(JsonObject, manifest.get("runner") or {})


# --- Slack -------------------------------------------------------------------


def slack_call(token: str, method: str, **params: object) -> JsonObject:
    body = urllib.parse.urlencode(
        {key: value for key, value in params.items() if value is not None}
    ).encode()
    request = urllib.request.Request(
        f"{SLACK_API_ROOT}/{method}",
        data=body,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
    if not isinstance(payload, dict) or not payload.get("ok"):
        error = payload.get("error") if isinstance(payload, dict) else "bad response"
        raise RunnerError(f"Slack {method} failed: {error}")
    return cast(JsonObject, payload)


def post_message(
    token: str,
    channel: str,
    text: str,
    thread_ts: str | None = None,
) -> str:
    payload = slack_call(
        token,
        "chat.postMessage",
        channel=channel,
        text=text,
        thread_ts=thread_ts,
        unfurl_links="false",
    )
    return cast(str, payload["ts"])


def message_permalink(token: str, channel: str, ts: str) -> str | None:
    try:
        payload = slack_call(
            token, "chat.getPermalink", channel=channel, message_ts=ts
        )
    except (RunnerError, OSError):
        return None
    permalink = payload.get("permalink")
    return permalink if isinstance(permalink, str) else None


# --- Conductor MCP (loopback; stateless streamable HTTP) ---------------------


def conductor_call(tool: str, arguments: JsonObject) -> JsonObject:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()
    request = urllib.request.Request(
        CONDUCTOR_URL,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode())
    except (urllib.error.URLError, OSError) as error:
        raise RunnerError(f"Conductor MCP unreachable for {tool}: {error}") from error
    if not isinstance(data, dict):
        raise RunnerError(f"Conductor {tool} returned a non-object response.")
    if "error" in data:
        message = cast(JsonObject, data["error"]).get("message", "unknown error")
        raise RunnerError(f"Conductor {tool} failed: {message}")
    result = cast(JsonObject, data.get("result") or {})
    content = cast(list[JsonObject], result.get("content") or [])
    if result.get("isError"):
        detail = content[0].get("text", "unknown error") if content else "unknown error"
        raise RunnerError(f"Conductor {tool} failed: {detail}")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return cast(JsonObject, structured["result"])
        return cast(JsonObject, structured)
    if content and isinstance(content[0].get("text"), str):
        parsed = json.loads(cast(str, content[0]["text"]))
        if isinstance(parsed, dict):
            return cast(JsonObject, parsed)
    raise RunnerError(f"Conductor {tool} returned an unexpected payload.")


def iterate_projects(payload: JsonObject) -> list[JsonObject]:
    for key in ("data", "projects", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return cast(list[JsonObject], value)
    return []


def project_matches_repo(project: JsonObject, repo: str) -> bool:
    for value in project.values():
        if not isinstance(value, str):
            continue
        candidate = value.rstrip("/")
        if candidate.endswith(".git"):
            candidate = candidate[: -len(".git")]
        if candidate == repo or candidate.rsplit("/", 1)[-1] == repo:
            return True
    return False


def resolve_project_id(repo: str) -> str:
    payload = conductor_call("list_projects", {"limit": 100})
    for project in iterate_projects(payload):
        if project_matches_repo(project, repo):
            identifier = project.get("id") or project.get("projectId")
            if isinstance(identifier, str) and identifier:
                return identifier
    raise RunnerError(f"no Conductor project matches repo {repo!r}")


def first_string(payload: JsonObject, *keys: str) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def workspace_session_id(workspace: JsonObject, workspace_id: str) -> str:
    session_id = first_string(workspace, "sessionId", "defaultSessionId")
    if session_id:
        return session_id
    sessions = conductor_call(
        "list_workspace_sessions", {"workspace_id": workspace_id, "limit": 1}
    )
    for key in ("data", "sessions", "items"):
        value = sessions.get(key)
        if isinstance(value, list) and value:
            candidate = first_string(cast(JsonObject, value[0]), "id", "sessionId")
            if candidate:
                return candidate
    raise RunnerError(f"workspace {workspace_id} has no session to prompt")


def session_transcript_tail(session_id: str, limit: int = 50) -> list[str]:
    payload = conductor_call(
        "list_session_messages", {"session_id": session_id, "limit": limit}
    )
    texts: list[str] = []
    for key in ("data", "messages", "items"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for message in cast(list[JsonObject], value):
            text = message.get("message") or message.get("text") or message.get("content")
            if isinstance(text, dict):
                # The official API nests the body under content.{message,text}.
                text = text.get("message") or text.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
        break
    # Assistant output is not reliably present in the messages endpoint; the
    # rendered transcript view is the authoritative source for the result block.
    try:
        payload = conductor_call(
            "query_conductor_sql",
            {
                "query": (
                    "SELECT transcript FROM session_transcripts_view "
                    f"WHERE session_id = '{session_id}'"
                )
            },
        )
        rows = payload.get("rows")
        if isinstance(rows, list):
            for row in cast(list[JsonObject], rows):
                transcript = row.get("transcript")
                if isinstance(transcript, str) and transcript:
                    texts.append(transcript)
    except (RunnerError, urllib.error.URLError):
        pass  # messages-endpoint texts remain the fallback
    return texts


# --- Result parsing ----------------------------------------------------------


def parse_result_block(text: str) -> JsonObject | None:
    """Parse the last SCHEDULED_RUN_RESULT block in a transcript message."""
    if RESULT_MARKER not in text:
        return None
    block = text[text.rindex(RESULT_MARKER) + len(RESULT_MARKER) :]
    block = block.split("```", 1)[0]
    parsed: JsonObject = {}
    for line in block.splitlines():
        match = re.match(r"^([a-z_]+):\s*(.*)$", line.strip())
        if not match:
            continue
        key, value = match.group(1), match.group(2).strip()
        if key in RESULT_JSON_KEYS:
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                return None
            if key == "issues":
                normalized_issues = parse_health_issues(decoded)
                if normalized_issues is None:
                    return None
                parsed[key] = normalized_issues
            elif key == "dream_report":
                normalized_report = parse_dream_report(decoded)
                if normalized_report is None:
                    return None
                parsed[key] = normalized_report
            else:
                parsed[key] = decoded
        elif key in RESULT_LIST_KEYS:
            parsed[key] = [
                item.strip()
                for item in value.strip("[]").split(",")
                if item.strip()
            ]
        else:
            parsed[key] = value
    if str(parsed.get("status", "")).upper() not in STATUS_ICONS:
        return None
    parsed["status"] = str(parsed["status"]).upper()
    if parsed["status"] == "NEEDS_MORE_TIME" and not str(
        parsed.get("resume_command", "")
    ).strip():
        return None
    return parsed


def parse_dream_report(value: object) -> DreamReport | None:
    """Validate the structured human-readable report emitted by night-dream."""
    if not isinstance(value, dict):
        return None

    text_fields: dict[str, str] = {}
    for key in ("what", "why", "how", "graph_plan"):
        raw_value = value.get(key)
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        text_fields[key] = raw_value.strip()

    list_fields: dict[str, list[str]] = {}
    for key in ("memory_actions", "ticket_consolidations", "proposals", "scope"):
        raw_value = value.get(key)
        if not isinstance(raw_value, list):
            return None
        items: list[str] = []
        for item in raw_value:
            if not isinstance(item, str) or not item.strip():
                return None
            items.append(item.strip())
        if key == "scope" and not items:
            return None
        list_fields[key] = items

    return {
        "what": text_fields["what"],
        "why": text_fields["why"],
        "how": text_fields["how"],
        "memory_actions": list_fields["memory_actions"],
        "ticket_consolidations": list_fields["ticket_consolidations"],
        "proposals": list_fields["proposals"],
        "graph_plan": text_fields["graph_plan"],
        "scope": list_fields["scope"],
    }


def parse_health_issues(value: object) -> list[HealthIssue] | None:
    if not isinstance(value, list):
        return None
    issues: list[HealthIssue] = []
    for raw_issue in value:
        if not isinstance(raw_issue, dict):
            return None
        title = raw_issue.get("title")
        next_step = raw_issue.get("next_step")
        if not isinstance(title, str) or not title.strip():
            return None
        if not isinstance(next_step, str) or not next_step.strip():
            return None

        proof_ok, proof = normalize_issue_alias(
            raw_issue, "concrete_proof", "proof", required=True
        )
        example_ok, example = normalize_issue_alias(
            raw_issue, "representative_example", "example", required=True
        )
        ticket_ok, ticket_id = normalize_issue_alias(
            raw_issue, "owning_ticket_id", "ticket_id", required=False
        )
        if not proof_ok or not example_ok or not ticket_ok:
            return None
        if proof is None or example is None:
            return None
        issues.append(
            {
                "title": title.strip(),
                "proof": proof,
                "example": example,
                "next_step": next_step.strip(),
                "ticket_id": ticket_id,
            }
        )
    return issues


def normalize_issue_alias(
    issue: dict[object, object],
    canonical_key: str,
    legacy_key: str,
    *,
    required: bool,
) -> tuple[bool, str | None]:
    normalized_values: list[str | None] = []
    for key in (canonical_key, legacy_key):
        if key not in issue:
            continue
        value = issue[key]
        if value is None:
            if required:
                return False, None
            normalized_values.append(None)
            continue
        if not isinstance(value, str):
            return False, None
        normalized = value.strip()
        if required and not normalized:
            return False, None
        normalized_values.append(normalized or None)

    if not normalized_values:
        return (not required), None
    if len(normalized_values) == 2 and normalized_values[0] != normalized_values[1]:
        return False, None
    return True, normalized_values[0]


def health_issues(result: JsonObject | None, summary: str, status: str) -> list[HealthIssue]:
    """Return validated health issues, including a runner-failure fallback."""
    raw_issues = result.get("issues") if result is not None else None
    issues = parse_health_issues(raw_issues) or []
    if not issues and status in {"FAIL", "BLOCKED"}:
        issues.append(
            {
                "title": "Scheduled health run failed",
                "proof": summary,
                "example": "The run did not return structured issue evidence.",
                "next_step": "Open the run thread and inspect the scheduler failure.",
                "ticket_id": None,
            }
        )
    return issues


def health_parent_message(icon: str, issues: list[HealthIssue], summary: str) -> str:
    if not issues:
        return f"{icon} [health-6h] {summary}"
    noun = "issue" if len(issues) == 1 else "issues"
    lines = [f"{icon} [health-6h] {len(issues)} {noun}"]
    for issue in issues:
        ticket = issue["ticket_id"] or "no ticket"
        lines.append(f"• {issue['title']} — ticket `{ticket}`")
    return "\n".join(lines)


def health_issue_reply(issue: HealthIssue) -> str:
    ticket = issue["ticket_id"] or "No ticket assigned"
    return (
        f"*{issue['title']}*\n"
        f"• *Proof:* {issue['proof']}\n"
        f"• *Example:* {issue['example']}\n"
        f"• *Next:* {issue['next_step']}\n"
        f"• *Ticket:* `{ticket}`"
    )


def count_label(count: int, singular: str, plural: str | None = None) -> str:
    noun = singular if count == 1 else plural or f"{singular}s"
    return f"{count} {noun}"


def nightly_dream_parent_message(icon: str, report: DreamReport) -> str:
    memory_count = len(report["memory_actions"])
    ticket_count = len(report["ticket_consolidations"])
    proposal_count = len(report["proposals"])
    applied_count = memory_count + ticket_count
    outcome = (
        "No changes applied"
        if applied_count == 0
        else f"{count_label(applied_count, 'change')} applied"
    )
    return (
        f"{icon} [nightly-dream] {outcome} · "
        f"{count_label(memory_count, 'memory action')} · "
        f"{count_label(ticket_count, 'ticket')} consolidated · 0 graph writes · "
        f"{count_label(proposal_count, 'proposal')}"
    )


def report_items(items: list[str], empty_message: str, limit: int = 20) -> list[str]:
    if not items:
        return [f"• {empty_message}"]
    lines = [f"• {item}" for item in items[:limit]]
    if len(items) > limit:
        lines.append(f"• {len(items) - limit} more; open the workspace for the full result.")
    return lines


def nightly_dream_reply(
    report: DreamReport,
    result: JsonObject,
    started: datetime,
    workspace_id: str | None,
    deep_link: str | None,
) -> str:
    memory_actions = report["memory_actions"]
    ticket_consolidations = report["ticket_consolidations"]
    proposals = report["proposals"]
    checks_total = result.get("checks_total", "unknown")
    checks_failed = result.get("checks_failed", "unknown")

    lines = [
        "*What was done*",
        report["what"],
        "",
        "*Why*",
        report["why"],
        "",
        "*How*",
        report["how"],
        "",
        f"*Memory actions ({len(memory_actions)})*",
        *report_items(memory_actions, "None."),
        "",
        f"*Tickets consolidated ({len(ticket_consolidations)})*",
        *report_items(ticket_consolidations, "None."),
        "",
        "*Graph writes (0)*",
        "• None — the graph lane is proposal-only by policy.",
        "",
        f"*Proposals ({len(proposals)})*",
        *report_items(proposals, "None."),
        "",
        "*Graph plan*",
        report["graph_plan"],
        "",
        "*Scope reviewed*",
        *report_items(report["scope"], "No scope reported."),
        "",
        "*Run details*",
        f"• Checks: {checks_total} total · {checks_failed} failed",
        f"• Started: {started.isoformat()}",
        f"• Workspace: {workspace_id or 'not created'}",
    ]
    if deep_link:
        lines.append(f"• <{deep_link}|Open in Conductor>")
    return "\n".join(lines)


def nightly_dream_fallback_reply(
    summary: str,
    started: datetime,
    workspace_id: str | None,
    deep_link: str | None,
) -> str:
    lines = [
        "*What happened*",
        summary,
        "",
        "*Why*",
        "The run did not return a valid structured nightly-dream report.",
        "",
        "*How to investigate*",
        "Open the workspace and inspect the final agent message and failed checks.",
        "",
        "*Run details*",
        f"• Started: {started.isoformat()}",
        f"• Workspace: {workspace_id or 'not created'}",
    ]
    if deep_link:
        lines.append(f"• <{deep_link}|Open in Conductor>")
    return "\n".join(lines)


def incident_ticket_text(ticket_id: str | None) -> str:
    if not ticket_id:
        return "No ticket assigned"
    if TICKET_ID_PATTERN.fullmatch(ticket_id):
        return f"`{ticket_id}`"
    return ticket_id


def incident_message(
    name: str,
    status: str,
    summary: str,
    result: JsonObject | None,
    issues: list[HealthIssue],
    permalink: str | None,
) -> str:
    """Render a concise, evidence-first incident alert for a human reader."""
    icon = {"FAIL": "❌", "BLOCKED": "⛔"}.get(status, "⚠️")
    lines = [f"{icon} *{name} needs attention* {SLACK_MENTION_SIMON}"]
    if issues:
        for index, issue in enumerate(issues[:3]):
            if index:
                lines.append("")
            lines.extend(
                [
                    f"*{issue['title']}*",
                    f"> *Proof:* {issue['proof']}",
                    f"> *Example:* {issue['example']}",
                    f"> *Next:* {issue['next_step']}",
                    f"> *Ticket:* {incident_ticket_text(issue['ticket_id'])}",
                ]
            )
        if len(issues) > 3:
            lines.extend(
                ["", f"*{len(issues) - 3} more issues:* See the linked run thread."]
            )
    else:
        lines.append(f"• *What happened:* {summary}")
        checks_total = result.get("checks_total") if result else None
        checks_failed = result.get("checks_failed") if result else None
        if checks_total is not None and checks_failed is not None:
            lines.append(
                f"• *Proof:* The run reported {checks_failed} failed checks out of "
                f"{checks_total}."
            )
        else:
            lines.append(f"• *Proof:* The scheduler classified the run as {status}.")
        tickets = result.get("tickets_touched") if result else None
        if isinstance(tickets, list) and tickets:
            lines.append(f"• *Tickets:* {', '.join(f'`{ticket}`' for ticket in tickets[:3])}")
        blocked_on = result.get("blocked_on") if result else None
        if isinstance(blocked_on, str) and blocked_on:
            lines.append(f"• *Next:* {blocked_on}")
        else:
            lines.append("• *Next:* Open the run thread and review the failed checks.")
    if permalink:
        if issues:
            lines.append("")
        lines.append(f"• *Details:* <{permalink}|Open the run thread>")
    return "\n".join(lines)


def unit_failure_message(suffix: str, unit: str) -> str:
    return (
        f"❌ *{suffix} scheduler service failed* {SLACK_MENTION_SIMON}\n"
        f"• *Proof:* systemd marked `{unit}` as failed.\n"
        f"• *Example:* `journalctl -u {unit}` shows the traceback.\n"
        "• *Next:* Inspect the traceback, fix the service, then restart the unit."
    )


def watchdog_message(name: str, detail: str, interval_hours: int) -> str:
    unit = f"hermes-schedule@{name}.service"
    return (
        f"⚠️ *{name} has stopped reporting* {SLACK_MENTION_SIMON}\n"
        f"• *Proof:* {detail}; expected a report every {interval_hours}h.\n"
        f"• *Example:* Check `systemctl status {unit}` on Hermes.\n"
        f"• *Next:* Restore the timer or runner, then confirm the next Slack report arrives."
    )


def find_result(transcript_tail: list[str]) -> JsonObject | None:
    for text in reversed(transcript_tail):
        parsed = parse_result_block(text)
        if parsed is not None:
            return parsed
    return None


def cron_interval_hours(cron: str) -> int:
    """Expected firing interval for the cron shapes this manifest uses."""
    fields = cron.split()
    if len(fields) != 5:
        raise RunnerError(f"unsupported cron expression: {cron!r}")
    hour = fields[1]
    step = re.fullmatch(r"\*/(\d+)", hour)
    if step:
        return int(step.group(1))
    return 24


# --- State + retention -------------------------------------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def state_path(name: str) -> Path:
    return state_dir() / f"{name}.json"


def history_path(name: str) -> Path:
    return state_dir() / f"{name}.history.jsonl"


def record_run(name: str, status: str, workspace_id: str | None) -> None:
    record = {
        "completed_at": utc_now().isoformat(),
        "status": status,
        "workspace_id": workspace_id,
    }
    state_path(name).write_text(json.dumps(record) + "\n")
    if workspace_id:
        with history_path(name).open("a") as history:
            history.write(json.dumps({**record, "archived": False}) + "\n")


# --- run mode ----------------------------------------------------------------


def launch_workspace(entry: JsonObject, name: str) -> tuple[str, str, str | None]:
    workspace_spec = cast(JsonObject, entry.get("workspace") or {})
    repo = cast(str, workspace_spec.get("repo"))
    stamp = utc_now().strftime("%Y%m%d-%H%M")
    # Orgs without Conductor projects create workspaces from a repository URL;
    # supply exactly one of project_id / repository_url (server enforces this).
    source: JsonObject
    try:
        source = {"project_id": resolve_project_id(repo)}
    except RunnerError:
        repo_url = workspace_spec.get("repo_url")
        if not isinstance(repo_url, str) or not repo_url:
            raise
        source = {"repository_url": repo_url}
    request: JsonObject = {
        **source,
        "branch": workspace_spec.get("branch"),
        "name": f"sched-{name}-{stamp}",
        "session_name": f"{name} {stamp}",
    }
    # Cloud sandboxes have no Keychain; the per-project 1Password service-account
    # token must arrive via the workspace environment (consumed by cloud-mcp.sh).
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials:
        op_token_path = Path(credentials) / "op.token"
        if op_token_path.exists():
            token = op_token_path.read_text().strip()
            if token:
                request["env"] = {"TS_OP_SERVICE_ACCOUNT_TOKEN": token}
    workspace = conductor_call("create_workspace", request)
    workspace_id = first_string(workspace, "workspaceId", "id")
    if not workspace_id:
        raise RunnerError("create_workspace returned no workspace id")
    session_id = workspace_session_id(workspace, workspace_id)
    deep_link = first_string(workspace, "url", "deepLink", "webUrl", "appUrl")
    return workspace_id, session_id, deep_link


def poll_session(
    session_id: str,
    max_runtime_minutes: int,
    poll_seconds: int,
) -> tuple[str, JsonObject | None]:
    """Poll until the run ends. Returns (outcome, parsed result block or None).

    outcome is "finished", "timeout", or "errored". A queued prompt reports idle
    until it starts, so idle only ends the run after we observed working or the
    transcript already carries a result block.
    """
    deadline = time.monotonic() + max_runtime_minutes * 60
    saw_working = False
    while time.monotonic() < deadline:
        status_payload = conductor_call("get_session_status", {"session_id": session_id})
        status = str(
            first_string(status_payload, "status", "state") or ""
        ).lower()
        if status in {"error", "errored", "failed"}:
            return "errored", find_result(session_transcript_tail(session_id))
        if status in {"working", "running", "busy"}:
            saw_working = True
        elif status in {"idle", "completed", "done"}:
            result = find_result(session_transcript_tail(session_id))
            if result is not None:
                return "finished", result
            if saw_working:
                return "finished", None
        time.sleep(poll_seconds)
    return "timeout", None


def run_schedule(name: str) -> int:
    manifest = load_manifest()
    entry = manifest_entry(manifest, name)
    if not entry.get("enabled"):
        log.info("schedule %s is disabled (enabled: false); skipping", name)
        return 0

    state_dir().mkdir(parents=True, exist_ok=True)
    lock_file = (state_dir() / f"{name}.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        log.warning("schedule %s: previous run still active; skipping", name)
        return 0

    slack_token = read_slack_token()
    channel = channel_id(manifest, cast(str, entry["slack_channel"]))
    incidents = channel_id(manifest, INCIDENTS_CHANNEL_NAME)
    settings = runner_settings(manifest)
    poll_seconds = int(cast(int, settings.get("poll_seconds", DEFAULT_POLL_SECONDS)))
    max_runtime = int(cast(int, entry.get("max_runtime_minutes", 120)))

    workspace_id: str | None = None
    started = utc_now()
    try:
        prompt_text = (HERE / cast(str, entry["prompt"])).read_text()
        workspace_id, session_id, deep_link = launch_workspace(entry, name)
        conductor_call(
            "send_session_message",
            {"session_id": session_id, "message": prompt_text},
        )
        outcome, result = poll_session(session_id, max_runtime, poll_seconds)
        if outcome == "timeout":
            try:
                conductor_call("cancel_session", {"session_id": session_id})
            except RunnerError as error:
                log.warning("cancel after timeout failed: %s", error)
        status, summary = interpret_outcome(name, outcome, result, max_runtime)
    except (RunnerError, OSError) as error:
        status = "FAIL"
        summary = f"runner error: {error}"
        result = None
        deep_link = None

    detail_lines = [
        f"schedule: {name}",
        f"started: {started.isoformat()}",
        f"workspace: {workspace_id or 'not created'}",
    ]
    if deep_link:
        detail_lines.append(f"link: {deep_link}")
    if result is not None:
        detail_lines.append("")
        detail_lines.append("```")
        detail_lines.append(RESULT_MARKER)
        detail_lines.extend(
            f"{key}: {value}" for key, value in result.items()
        )
        detail_lines.append("```")

    issues: list[HealthIssue] = []
    if name == "health-6h":
        issues = health_issues(result, summary, status)
        if status == "PASS" and issues:
            status = "FAIL"
            summary = "run reported issues with PASS status"
        icon = STATUS_ICONS[status]
        line = health_parent_message(icon, issues, summary)
        parent_ts = post_message(slack_token, channel, line)
        for issue in issues:
            post_message(
                slack_token,
                channel,
                health_issue_reply(issue),
                thread_ts=parent_ts,
            )
    elif name == "nightly-dream":
        raw_report = result.get("dream_report") if result is not None else None
        icon = STATUS_ICONS[status]
        if isinstance(raw_report, dict) and result is not None:
            report = cast(DreamReport, raw_report)
            line = nightly_dream_parent_message(icon, report)
            reply = nightly_dream_reply(
                report, result, started, workspace_id, deep_link
            )
        else:
            line = f"{icon} [nightly-dream] {summary}"
            reply = nightly_dream_fallback_reply(
                summary, started, workspace_id, deep_link
            )
        parent_ts = post_message(slack_token, channel, line)
        post_message(slack_token, channel, reply, thread_ts=parent_ts)
    else:
        icon = STATUS_ICONS[status]
        line = f"{icon} [{name}] {summary}"
        parent_ts = post_message(slack_token, channel, line)
        post_message(slack_token, channel, "\n".join(detail_lines), thread_ts=parent_ts)
    if status in {"FAIL", "BLOCKED"}:
        permalink = message_permalink(slack_token, channel, parent_ts)
        if channel != incidents:
            post_message(
                slack_token,
                incidents,
                incident_message(name, status, summary, result, issues, permalink),
            )

    record_run(name, status, workspace_id)
    log.info("schedule %s finished: %s — %s", name, status, summary)
    lock_file.close()
    return 0


def interpret_outcome(
    name: str,
    outcome: str,
    result: JsonObject | None,
    max_runtime: int,
) -> tuple[str, str]:
    if outcome == "timeout":
        return "FAIL", f"timed out after {max_runtime} minutes; session cancelled"
    if outcome == "errored":
        return "FAIL", "agent session errored"
    if result is None:
        return "FAIL", "run ended without a SCHEDULED_RUN_RESULT block"
    if name == "nightly-dream" and not isinstance(result.get("dream_report"), dict):
        return "FAIL", "run ended without a valid dream_report"
    status = cast(str, result["status"])
    summary = cast(str, result.get("summary") or f"{name} ended {status}")
    if status == "BLOCKED" and result.get("blocked_on"):
        summary = f"{summary} (blocked_on: {result['blocked_on']})"
    return status, summary


# --- alert mode (systemd OnFailure) ------------------------------------------


def alert_unit_failure(suffix: str) -> int:
    manifest = load_manifest()
    incidents = channel_id(manifest, INCIDENTS_CHANNEL_NAME)
    token = read_slack_token()
    unit = (
        f"hermes-schedule@{suffix}.service"
        if suffix != "watchdog"
        else "hermes-schedule-watchdog.service"
    )
    post_message(
        token,
        incidents,
        unit_failure_message(suffix, unit),
    )
    return 0


# --- watchdog + retention ----------------------------------------------------


def check_staleness(manifest: JsonObject, token: str, incidents: str) -> None:
    for entry in cast(list[JsonObject], manifest.get("schedules") or []):
        if not entry.get("enabled"):
            continue
        name = cast(str, entry["name"])
        interval_hours = cron_interval_hours(cast(str, entry["cron"]))
        max_runtime = int(cast(int, entry.get("max_runtime_minutes", 120)))
        allowed = interval_hours * 3600 + (max_runtime + WATCHDOG_GRACE_MINUTES) * 60
        path = state_path(name)
        if path.exists():
            completed = datetime.fromisoformat(
                cast(str, json.loads(path.read_text())["completed_at"])
            )
            age = (utc_now() - completed).total_seconds()
            stale = age > allowed
            detail = f"last report {age / 3600:.1f}h ago"
        else:
            boot_marker = state_dir() / ".watchdog-first-seen"
            if not boot_marker.exists():
                boot_marker.write_text(utc_now().isoformat() + "\n")
            first_seen = datetime.fromisoformat(
                boot_marker.read_text().strip()
            )
            stale = (utc_now() - first_seen).total_seconds() > allowed
            detail = "no report recorded since deploy"
        if stale:
            post_message(
                token,
                incidents,
                watchdog_message(name, detail, interval_hours),
            )


def apply_retention(manifest: JsonObject) -> None:
    settings = runner_settings(manifest)
    pass_days = int(
        cast(int, settings.get("retention_days_pass", DEFAULT_RETENTION_PASS_DAYS))
    )
    fail_days = int(
        cast(int, settings.get("retention_days_fail", DEFAULT_RETENTION_FAIL_DAYS))
    )
    for entry in cast(list[JsonObject], manifest.get("schedules") or []):
        path = history_path(cast(str, entry["name"]))
        if not path.exists():
            continue
        records = [
            cast(JsonObject, json.loads(line))
            for line in path.read_text().splitlines()
            if line.strip()
        ]
        changed = False
        for record in records:
            if record.get("archived") or not record.get("workspace_id"):
                continue
            completed = datetime.fromisoformat(cast(str, record["completed_at"]))
            age_days = (utc_now() - completed).total_seconds() / 86400
            limit = pass_days if record.get("status") == "PASS" else fail_days
            if age_days <= limit:
                continue
            try:
                conductor_call(
                    "archive_workspace",
                    {"workspace_id": record["workspace_id"]},
                )
            except RunnerError as error:
                log.warning(
                    "retention: archiving %s failed: %s", record["workspace_id"], error
                )
                continue
            record["archived"] = True
            changed = True
        if changed:
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records)
            )


def watchdog() -> int:
    manifest = load_manifest()
    state_dir().mkdir(parents=True, exist_ok=True)
    token = read_slack_token()
    incidents = channel_id(manifest, INCIDENTS_CHANNEL_NAME)
    check_staleness(manifest, token, incidents)
    apply_retention(manifest)
    return 0


def main(argv: list[str]) -> int:
    if len(argv) == 3 and argv[1] == "run":
        return run_schedule(argv[2])
    if len(argv) == 3 and argv[1] == "alert":
        return alert_unit_failure(argv[2])
    if len(argv) == 2 and argv[1] == "watchdog":
        return watchdog()
    print(
        "usage: runner.py run <schedule> | alert <unit-suffix> | watchdog",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

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

from collections.abc import Iterator
import fcntl
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict, cast
from uuid import NAMESPACE_URL, uuid5

import yaml

HERE = Path(__file__).resolve().parent
MANIFEST_PATH = HERE / "schedules.yaml"
CONDUCTOR_URL = os.environ.get("HERMES_CONDUCTOR_URL", "http://127.0.0.1:8794/")
AUTODEV_URL = os.environ.get("HERMES_AUTODEV_URL", "http://127.0.0.1:8792/")
SLACK_API_ROOT = "https://slack.com/api"
SLACK_MENTION_SIMON = "<@U09T4LELYES>"
INCIDENTS_CHANNEL_NAME = "#autodev-incidents"
RESULT_MARKER = "SCHEDULED_RUN_RESULT"
REMEDIATION_RESULT_MARKER = "HEALTH_REMEDIATION_RESULT"
PRODUCTION_RESULT_MARKER = "HEALTH_PRODUCTION_RESULT"
PRODUCTION_APPROVAL_MARKER = "HUMAN_PRODUCTION_APPROVAL"
RESULT_LIST_KEYS = ("tickets_touched", "rc_fingerprints")
RESULT_JSON_KEYS = ("issues", "dream_report")
STATUS_ICONS = {"PASS": "✅", "FAIL": "❌", "BLOCKED": "⛔", "NEEDS_MORE_TIME": "⏳"}
REMEDIATION_STATUS_ICONS = {
    "STAGING_VERIFIED": "✅",
    "STOPPED": "⛔",
    "FAILED": "❌",
}
DEFAULT_POLL_SECONDS = 60
DEFAULT_RETENTION_PASS_DAYS = 3
DEFAULT_RETENTION_FAIL_DAYS = 14
# Statuses whose workspace is archived as soon as the run finishes; everything
# else waits for the watchdog's day-based retention sweep.
DEFAULT_ARCHIVE_ON_COMPLETE = ("PASS",)
WATCHDOG_GRACE_MINUTES = 60
TICKET_ID_PATTERN = re.compile(r"^[A-Z]\d{4}$")
SESSION_MESSAGE_PAGE_SIZE = 100
MAX_SESSION_MESSAGE_PAGES = 500
TERMINAL_IDLE_CONFIRMATIONS = 2
EXECUTABLE_TICKET_ID_PATTERN = re.compile(r"^[FBR]\d{4}$")
PRODUCTION_APPROVAL_PATTERN = re.compile(
    r"^approve[ ]+prod[ ]+([FBR]\d{4})$", re.IGNORECASE
)
SLACK_TIMESTAMP_PATTERN = re.compile(r"^\d+[.]\d{6}$")
PRODUCTION_TERMINAL_STATUSES = {"PROD_VERIFIED", "STOPPED", "FAILED"}

JsonObject = dict[str, object]


class HealthIssue(TypedDict):
    title: str
    proof: str
    example: str
    next_step: str
    ticket_id: str | None
    remediation_ready: bool


class RemediationResult(TypedDict):
    status: str
    ticket_id: str
    issue: str
    fix: str
    verification: str


class RemediationJob(TypedDict):
    issue: HealthIssue
    workspace_id: str | None
    session_id: str | None
    deep_link: str | None
    launch_error: str | None
    saw_working: bool
    terminal_idle_confirmations: int


class ProductionResult(TypedDict):
    status: str
    ticket_id: str
    issue: str
    fix: str
    verification: str


class ApprovalCandidate(TypedDict):
    ticket_id: str
    title: str
    channel: str
    thread_ts: str
    staging_reply_ts: str
    approval_not_before_ts: str
    workspace_id: str
    workspace_link: str | None
    state: str
    created_at: str
    expires_at: str
    approval_message_ts: str | None
    approved_by: str | None
    promotion_session_id: str | None
    promotion_session_link: str | None
    deadline_at: str | None
    start_attempts: int
    terminal_idle_confirmations: int


class DreamReport(TypedDict):
    what: str
    why: str
    how: str
    memory_actions: list[str]
    ticket_consolidations: list[str]
    proposals: list[str]
    graph_plan: str
    scope: list[str]


class SessionMessageSnapshot(TypedDict):
    texts: list[str]
    turn_completed: bool


class SessionResultSnapshot(TypedDict):
    result: JsonObject | None
    turn_completed: bool

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
    client_msg_id: str | None = None,
) -> str:
    payload = slack_call(
        token,
        "chat.postMessage",
        channel=channel,
        text=text,
        thread_ts=thread_ts,
        client_msg_id=client_msg_id,
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


def slack_thread_page(
    token: str,
    channel: str,
    thread_ts: str,
    oldest: str,
) -> list[JsonObject]:
    """Read one rate-limit-safe page of new replies from a Slack thread."""
    payload = slack_call(
        token,
        "conversations.replies",
        channel=channel,
        ts=thread_ts,
        oldest=oldest,
        inclusive="false",
        limit=15,
    )
    page = payload.get("messages")
    if not isinstance(page, list):
        raise RunnerError("Slack conversations.replies returned no messages array.")
    return cast(list[JsonObject], page)


# --- Loopback MCP clients (stateless streamable HTTP) ------------------------


def mcp_call(url: str, label: str, tool: str, arguments: JsonObject) -> JsonObject:
    payload = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool, "arguments": arguments},
        }
    ).encode()
    request = urllib.request.Request(
        url,
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
        raise RunnerError(f"{label} MCP unreachable for {tool}: {error}") from error
    if not isinstance(data, dict):
        raise RunnerError(f"{label} {tool} returned a non-object response.")
    if "error" in data:
        message = cast(JsonObject, data["error"]).get("message", "unknown error")
        raise RunnerError(f"{label} {tool} failed: {message}")
    result = cast(JsonObject, data.get("result") or {})
    content = cast(list[JsonObject], result.get("content") or [])
    if result.get("isError"):
        detail = content[0].get("text", "unknown error") if content else "unknown error"
        raise RunnerError(f"{label} {tool} failed: {detail}")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        if set(structured) == {"result"} and isinstance(structured["result"], dict):
            return cast(JsonObject, structured["result"])
        return cast(JsonObject, structured)
    if content and isinstance(content[0].get("text"), str):
        parsed = json.loads(cast(str, content[0]["text"]))
        if isinstance(parsed, dict):
            return cast(JsonObject, parsed)
    raise RunnerError(f"{label} {tool} returned an unexpected payload.")


def conductor_call(tool: str, arguments: JsonObject) -> JsonObject:
    return mcp_call(CONDUCTOR_URL, "Conductor", tool, arguments)


def autodev_call(tool: str, arguments: JsonObject) -> JsonObject:
    return mcp_call(AUTODEV_URL, "Autodev", tool, arguments)


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


def session_message_event(message: JsonObject) -> JsonObject | None:
    content = message.get("content")
    if not isinstance(content, dict):
        return None
    raw_payload = content.get("rawPayload")
    if not isinstance(raw_payload, dict):
        return None
    event = raw_payload.get("event")
    return cast(JsonObject, event) if isinstance(event, dict) else None


def session_message_text(message: JsonObject) -> str | None:
    text = message.get("message") or message.get("text")
    content = message.get("content")
    if not isinstance(text, str) and isinstance(content, str):
        text = content
    if not isinstance(text, str) and isinstance(content, dict):
        text = content.get("message") or content.get("text")
    if not isinstance(text, str):
        event = session_message_event(message)
        item = event.get("item") if event is not None else None
        if (
            event is not None
            and event.get("type") == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agentMessage"
        ):
            text = item.get("text")
    return text if isinstance(text, str) and text else None


def session_message_rows(payload: JsonObject) -> list[JsonObject]:
    for key in ("data", "messages", "items"):
        value = payload.get(key)
        if isinstance(value, list):
            return cast(list[JsonObject], value)
    return []


def session_message_snapshot(session_id: str) -> SessionMessageSnapshot:
    texts: list[str] = []
    turn_completed = False
    offset = 0
    for _ in range(MAX_SESSION_MESSAGE_PAGES):
        payload = conductor_call(
            "list_session_messages",
            {
                "session_id": session_id,
                "limit": SESSION_MESSAGE_PAGE_SIZE,
                "offset": offset,
            },
        )
        messages = session_message_rows(payload)
        for message in messages:
            text = session_message_text(message)
            if text is not None:
                texts.append(text)
            event = session_message_event(message)
            if event is not None and event.get("type") == "turn.completed":
                turn_completed = True
        if not payload.get("hasMore"):
            return {"texts": texts, "turn_completed": turn_completed}
        if not messages:
            raise RunnerError("Conductor session-message pagination did not advance.")
        offset += len(messages)
    raise RunnerError(
        "Conductor session-message history exceeded the 50,000-event safety cap."
    )


def rendered_session_transcript(session_id: str) -> list[str]:
    texts: list[str] = []
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
        pass
    return texts


def read_session_result(session_id: str) -> SessionResultSnapshot:
    messages = session_message_snapshot(session_id)
    result = find_result(messages["texts"])
    if result is None:
        result = find_result(rendered_session_transcript(session_id))
    return {"result": result, "turn_completed": messages["turn_completed"]}


def read_session_remediation_result(
    session_id: str,
) -> tuple[RemediationResult | None, bool]:
    messages = session_message_snapshot(session_id)
    result = find_remediation_result(messages["texts"])
    if result is None:
        result = find_remediation_result(rendered_session_transcript(session_id))
    return result, messages["turn_completed"]


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
        remediation_ready = raw_issue.get("remediation_ready", False)
        if not proof_ok or not example_ok or not ticket_ok:
            return None
        if proof is None or example is None:
            return None
        if not isinstance(remediation_ready, bool):
            return None
        issues.append(
            {
                "title": title.strip(),
                "proof": proof,
                "example": example,
                "next_step": next_step.strip(),
                "ticket_id": ticket_id,
                "remediation_ready": remediation_ready,
            }
        )
    return issues


def parse_remediation_result(text: str) -> RemediationResult | None:
    """Parse and validate the last one-line remediation JSON object in a transcript."""
    if REMEDIATION_RESULT_MARKER not in text:
        return None
    block = text[text.rindex(REMEDIATION_RESULT_MARKER) + len(REMEDIATION_RESULT_MARKER) :]
    object_start = block.find("{")
    if object_start < 0:
        return None
    try:
        decoded, end = json.JSONDecoder().raw_decode(block[object_start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(decoded, dict) or block[object_start + end :].strip():
        return None

    values: dict[str, str] = {}
    for key in ("status", "ticket_id", "issue", "fix", "verification"):
        value = decoded.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        values[key] = value.strip()
    status = values["status"].upper()
    if status not in REMEDIATION_STATUS_ICONS:
        return None
    if not EXECUTABLE_TICKET_ID_PATTERN.fullmatch(values["ticket_id"]):
        return None
    return {
        "status": status,
        "ticket_id": values["ticket_id"],
        "issue": values["issue"],
        "fix": values["fix"],
        "verification": values["verification"],
    }


def find_remediation_result(transcript_tail: list[str]) -> RemediationResult | None:
    for text in reversed(transcript_tail):
        parsed = parse_remediation_result(text)
        if parsed is not None:
            return parsed
    return None


def parse_production_result(text: str) -> ProductionResult | None:
    """Parse a terminal result from a human-approved production session."""
    if PRODUCTION_RESULT_MARKER not in text:
        return None
    block = text[text.rindex(PRODUCTION_RESULT_MARKER) + len(PRODUCTION_RESULT_MARKER) :]
    object_start = block.find("{")
    if object_start < 0:
        return None
    try:
        decoded, consumed = json.JSONDecoder().raw_decode(block[object_start:])
    except json.JSONDecodeError:
        return None
    if block[object_start + consumed :].strip():
        return None
    if not isinstance(decoded, dict):
        return None

    required_keys = {"status", "ticket_id", "issue", "fix", "verification"}
    if set(decoded) != required_keys:
        return None
    values: dict[str, str] = {}
    for key in required_keys:
        value = decoded.get(key)
        if (
            not isinstance(value, str)
            or not value.strip()
            or "\n" in value
            or "\r" in value
            or len(value) > 600
        ):
            return None
        values[key] = value.strip()
    status = values["status"].upper()
    if status not in PRODUCTION_TERMINAL_STATUSES:
        return None
    if not EXECUTABLE_TICKET_ID_PATTERN.fullmatch(values["ticket_id"]):
        return None
    return {
        "status": status,
        "ticket_id": values["ticket_id"],
        "issue": values["issue"],
        "fix": values["fix"],
        "verification": values["verification"],
    }


def find_production_result(transcript_tail: list[str]) -> ProductionResult | None:
    for text in reversed(transcript_tail):
        if PRODUCTION_RESULT_MARKER in text:
            return parse_production_result(text)
    return None


def read_session_production_result(
    session_id: str,
) -> tuple[ProductionResult | None, bool]:
    messages = session_message_snapshot(session_id)
    result = find_production_result(messages["texts"])
    if result is None:
        result = find_production_result(rendered_session_transcript(session_id))
    return result, messages["turn_completed"]


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
                "remediation_ready": False,
            }
        )
    return issues


def health_parent_message(
    icon: str,
    issues: list[HealthIssue],
    summary: str,
    jobs: list[RemediationJob] | None = None,
) -> str:
    if not issues:
        return f"{icon} [health-6h] {summary}"
    noun = "issue" if len(issues) == 1 else "issues"
    launched = sum(
        job["session_id"] is not None and job["launch_error"] is None for job in jobs or []
    )
    launch_suffix = (
        f" — {launched}/{len(issues)} remediation workspaces started" if jobs else ""
    )
    lines = [f"{icon} [health-6h] {len(issues)} {noun}{launch_suffix}"]
    for index, issue in enumerate(issues):
        ticket = issue["ticket_id"] or "no ticket"
        line = f"• {issue['title']} — ticket `{ticket}`"
        if jobs and jobs[index]["deep_link"]:
            line += f" — <{jobs[index]['deep_link']}|Open workspace>"
        lines.append(line)
    return "\n".join(lines)


def health_remediation_reply(job: RemediationJob, result: RemediationResult) -> str:
    icon = REMEDIATION_STATUS_ICONS[result["status"]]
    status_label = result["status"].lower().replace("_", " ")
    lines = [
        f"{icon} *{result['ticket_id']} — {job['issue']['title']} — {status_label}*",
        f"• *Issue:* {result['issue']}",
        f"• *Fix:* {result['fix']}",
        f"• *Verification:* {result['verification']}",
    ]
    if job["deep_link"]:
        lines.append(f"• *Workspace:* <{job['deep_link']}|Open in Conductor>")
    if result["status"] == "STAGING_VERIFIED":
        lines.append(
            "• *Approve production:* Reply in this thread with "
            f"`approve prod {result['ticket_id']}`."
        )
    return "\n".join(lines)


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


def approval_db_path() -> Path:
    return state_dir() / "production-approvals.sqlite3"


def approval_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(approval_db_path(), timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_candidates (
            ticket_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            channel TEXT NOT NULL,
            thread_ts TEXT NOT NULL,
            staging_reply_ts TEXT NOT NULL,
            approval_not_before_ts TEXT,
            workspace_id TEXT NOT NULL,
            workspace_link TEXT,
            state TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            approval_message_ts TEXT UNIQUE,
            approved_by TEXT,
            promotion_session_id TEXT UNIQUE,
            promotion_session_link TEXT,
            deadline_at TEXT,
            start_attempts INTEGER NOT NULL DEFAULT 0,
            terminal_idle_confirmations INTEGER NOT NULL DEFAULT 0,
            last_error TEXT,
            terminal_result_json TEXT,
            result_posted_at TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS one_active_production_promotion
        ON approval_candidates ((1))
        WHERE state IN ('launching', 'running')
        """
    )
    columns = {
        cast(str, row["name"])
        for row in connection.execute("PRAGMA table_info(approval_candidates)")
    }
    if "approval_not_before_ts" not in columns:
        connection.execute(
            "ALTER TABLE approval_candidates ADD COLUMN approval_not_before_ts TEXT"
        )
    connection.execute(
        """
        UPDATE approval_candidates
        SET approval_not_before_ts = staging_reply_ts
        WHERE approval_not_before_ts IS NULL
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_approval_messages (
            channel TEXT NOT NULL,
            message_ts TEXT NOT NULL,
            ticket_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            outcome TEXT NOT NULL,
            processed_at TEXT NOT NULL,
            PRIMARY KEY (channel, message_ts)
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approval_thread_cursors (
            channel TEXT NOT NULL,
            thread_ts TEXT NOT NULL,
            last_seen_ts TEXT NOT NULL,
            last_polled_at TEXT,
            PRIMARY KEY (channel, thread_ts)
        )
        """
    )
    connection.commit()
    return connection


def approval_candidate(row: sqlite3.Row) -> ApprovalCandidate:
    return {
        "ticket_id": cast(str, row["ticket_id"]),
        "title": cast(str, row["title"]),
        "channel": cast(str, row["channel"]),
        "thread_ts": cast(str, row["thread_ts"]),
        "staging_reply_ts": cast(str, row["staging_reply_ts"]),
        "approval_not_before_ts": cast(str, row["approval_not_before_ts"]),
        "workspace_id": cast(str, row["workspace_id"]),
        "workspace_link": row["workspace_link"],
        "state": cast(str, row["state"]),
        "created_at": cast(str, row["created_at"]),
        "expires_at": cast(str, row["expires_at"]),
        "approval_message_ts": row["approval_message_ts"],
        "approved_by": row["approved_by"],
        "promotion_session_id": row["promotion_session_id"],
        "promotion_session_link": row["promotion_session_link"],
        "deadline_at": row["deadline_at"],
        "start_attempts": int(row["start_attempts"]),
        "terminal_idle_confirmations": int(row["terminal_idle_confirmations"]),
    }


def register_production_candidate(
    job: RemediationJob,
    *,
    channel: str,
    thread_ts: str,
    staging_reply_ts: str,
    expires_days: int,
) -> None:
    ticket_id = job["issue"]["ticket_id"]
    workspace_id = job["workspace_id"]
    if not ticket_id or not workspace_id:
        return
    now = utc_now()
    with approval_connection() as connection:
        connection.execute(
            """
            INSERT INTO approval_candidates (
                ticket_id, title, channel, thread_ts, staging_reply_ts,
                approval_not_before_ts,
                workspace_id, workspace_link, state, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'awaiting_approval', ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                title = excluded.title,
                channel = excluded.channel,
                thread_ts = excluded.thread_ts,
                staging_reply_ts = excluded.staging_reply_ts,
                approval_not_before_ts = excluded.approval_not_before_ts,
                workspace_id = excluded.workspace_id,
                workspace_link = excluded.workspace_link,
                state = 'awaiting_approval',
                created_at = excluded.created_at,
                expires_at = excluded.expires_at,
                approval_message_ts = NULL,
                approved_by = NULL,
                promotion_session_id = NULL,
                promotion_session_link = NULL,
                deadline_at = NULL,
                start_attempts = 0,
                terminal_idle_confirmations = 0,
                last_error = NULL,
                terminal_result_json = NULL,
                result_posted_at = NULL
            WHERE approval_candidates.state IN (
                'awaiting_approval', 'expired', 'rejected', 'stopped', 'failed',
                'prod_verified'
            )
            """,
            (
                ticket_id,
                job["issue"]["title"],
                channel,
                thread_ts,
                staging_reply_ts,
                staging_reply_ts,
                workspace_id,
                job["deep_link"],
                now.isoformat(),
                (now + timedelta(days=expires_days)).isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO approval_thread_cursors (
                channel, thread_ts, last_seen_ts, last_polled_at
            ) VALUES (?, ?, ?, NULL)
            ON CONFLICT(channel, thread_ts) DO UPDATE SET
                last_seen_ts = CASE
                    WHEN approval_thread_cursors.last_seen_ts < excluded.last_seen_ts
                    THEN approval_thread_cursors.last_seen_ts
                    ELSE excluded.last_seen_ts
                END
            """,
            (channel, thread_ts, staging_reply_ts),
        )


def candidates_in_states(*states: str) -> list[ApprovalCandidate]:
    if not states:
        return []
    placeholders = ", ".join("?" for _ in states)
    with approval_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT * FROM approval_candidates
            WHERE state IN ({placeholders})
            ORDER BY created_at, ticket_id
            """,
            states,
        ).fetchall()
    return [approval_candidate(row) for row in rows]


def approval_protected_workspace_ids() -> set[str]:
    with approval_connection() as connection:
        rows = connection.execute(
            """
            SELECT workspace_id FROM approval_candidates
            WHERE state IN (
                'awaiting_approval', 'queued', 'launching', 'running',
                'stopped', 'failed', 'rejected'
            )
               OR (terminal_result_json IS NOT NULL AND result_posted_at IS NULL)
            """
        ).fetchall()
    return {cast(str, row["workspace_id"]) for row in rows}


def set_candidate_state(
    ticket_id: str,
    state: str,
    *,
    last_error: str | None = None,
    idle_confirmations: int | None = None,
) -> None:
    assignments = ["state = ?", "last_error = ?"]
    values: list[object] = [state, last_error]
    if idle_confirmations is not None:
        assignments.append("terminal_idle_confirmations = ?")
        values.append(idle_confirmations)
    values.append(ticket_id)
    with approval_connection() as connection:
        connection.execute(
            f"UPDATE approval_candidates SET {', '.join(assignments)} WHERE ticket_id = ?",
            values,
        )


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


def record_remediation(
    name: str, job: RemediationJob, result: RemediationResult
) -> None:
    if not job["workspace_id"]:
        return
    record = {
        "completed_at": utc_now().isoformat(),
        "status": (
            "AWAITING_PROD_APPROVAL"
            if result["status"] == "STAGING_VERIFIED"
            else "FAIL"
        ),
        "workspace_id": job["workspace_id"],
        "ticket_id": job["issue"]["ticket_id"],
        "kind": "health-remediation",
        "archived": False,
    }
    with history_path(name).open("a") as history:
        history.write(json.dumps(record) + "\n")


def mark_archived(name: str, workspace_id: str) -> None:
    """Flag *workspace_id* as archived in the schedule's history file."""
    path = history_path(name)
    if not path.exists():
        return
    records = [
        cast(JsonObject, json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    for record in records:
        if record.get("workspace_id") == workspace_id:
            record["archived"] = True
    path.write_text("".join(json.dumps(record) + "\n" for record in records))


def archive_on_complete_statuses(manifest: JsonObject) -> set[str]:
    raw = runner_settings(manifest).get("archive_on_complete")
    if isinstance(raw, list):
        return {str(item) for item in raw}
    return set(DEFAULT_ARCHIVE_ON_COMPLETE)


def archive_completed_workspace(
    manifest: JsonObject, name: str, status: str, workspace_id: str | None
) -> bool:
    """Archive the run's workspace immediately when its status is configured.

    Best-effort: a failure is logged and left to the retention sweep, which
    retries every unarchived history record.
    """
    if not workspace_id or status not in archive_on_complete_statuses(manifest):
        return False
    try:
        conductor_call("archive_workspace", {"workspace_id": workspace_id})
    except RunnerError as error:
        log.warning("archive-on-complete: %s failed: %s", workspace_id, error)
        return False
    mark_archived(name, workspace_id)
    log.info("schedule %s: archived workspace %s (%s)", name, workspace_id, status)
    return True


# --- run mode ----------------------------------------------------------------


def launch_cloud_workspace(
    workspace_spec: JsonObject,
    *,
    workspace_name: str,
    session_name: str,
) -> tuple[str, str, str | None]:
    repo = cast(str, workspace_spec.get("repo"))
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
        "name": workspace_name,
        "session_name": session_name,
    }
    # Agent/model/effort are reviewed manifest fields (schedules.yaml); when
    # present they pin which coding agent runs the scheduled prompt.
    for key in ("agent", "model", "effort"):
        value = workspace_spec.get(key)
        if isinstance(value, str) and value:
            request[key] = value
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


def launch_workspace(entry: JsonObject, name: str) -> tuple[str, str, str | None]:
    workspace_spec = cast(JsonObject, entry.get("workspace") or {})
    stamp = utc_now().strftime("%Y%m%d-%H%M")
    return launch_cloud_workspace(
        workspace_spec,
        workspace_name=f"sched-{name}-{stamp}",
        session_name=f"{name} {stamp}",
    )


def remediation_prompt(issue: HealthIssue) -> str:
    ticket_id = cast(str, issue["ticket_id"])
    context = json.dumps(
        {
            "title": issue["title"],
            "concrete_proof": issue["proof"],
            "representative_example": issue["example"],
            "triage_next_step": issue["next_step"],
        },
        separators=(",", ":"),
    )
    return (
        (HERE / "health-remediation.md")
        .read_text()
        .replace("__TICKET_ID__", ticket_id)
        .replace("__ISSUE_CONTEXT_JSON__", context)
    )


def launch_health_remediations(
    entry: JsonObject, issues: list[HealthIssue]
) -> list[RemediationJob]:
    """Launch one independent cloud ticket-flow workspace per health issue."""
    jobs: list[RemediationJob] = []
    workspace_spec = cast(JsonObject, entry.get("workspace") or {})
    stamp = utc_now().strftime("%Y%m%d-%H%M")
    seen_tickets: set[str] = set()
    for ordinal, issue in enumerate(issues, start=1):
        ticket_id = issue["ticket_id"]
        launch_error: str | None = None
        workspace_id: str | None = None
        session_id: str | None = None
        deep_link: str | None = None
        if ticket_id is None or not EXECUTABLE_TICKET_ID_PATTERN.fullmatch(ticket_id):
            launch_error = "No executable F/B/R owning ticket was assigned during health triage."
        elif not issue["remediation_ready"]:
            launch_error = (
                "Health triage did not attest that ticket assignment, flow-run tagging, and "
                "artifacts completed."
            )
        elif ticket_id in seen_tickets:
            launch_error = (
                f"Health triage emitted duplicate owning ticket {ticket_id}; one issue per "
                "ticket is required."
            )
        else:
            seen_tickets.add(ticket_id)
            try:
                workspace_id, session_id, deep_link = launch_cloud_workspace(
                    workspace_spec,
                    workspace_name=f"health-{ticket_id.lower()}-{stamp}-{ordinal:02d}",
                    session_name=f"health remediation {ticket_id}",
                )
                conductor_call(
                    "send_session_message",
                    {"session_id": session_id, "message": remediation_prompt(issue)},
                )
            except (RunnerError, OSError) as error:
                launch_error = str(error)
        jobs.append(
            {
                "issue": issue,
                "workspace_id": workspace_id,
                "session_id": session_id,
                "deep_link": deep_link,
                "launch_error": launch_error,
                "saw_working": False,
                "terminal_idle_confirmations": 0,
            }
        )
    return jobs


def stopped_remediation(job: RemediationJob, reason: str) -> RemediationResult:
    ticket_id = job["issue"]["ticket_id"] or "No ticket assigned"
    return {
        "status": "STOPPED",
        "ticket_id": ticket_id,
        "issue": job["issue"]["proof"],
        "fix": f"No complete fix was landed because {reason}",
        "verification": "Staging verification did not complete; open the workspace for evidence.",
    }


def supervise_health_remediations(
    jobs: list[RemediationJob],
    max_runtime_minutes: int,
    poll_seconds: int,
) -> Iterator[tuple[RemediationJob, RemediationResult]]:
    """Yield child results as parallel remediation sessions reach a terminal state."""
    pending = list(jobs)
    deadline = time.monotonic() + max_runtime_minutes * 60
    while pending and time.monotonic() < deadline:
        completed: list[RemediationJob] = []
        for job in pending:
            if job["launch_error"]:
                completed.append(job)
                yield job, stopped_remediation(job, job["launch_error"])
                continue
            session_id = cast(str, job["session_id"])
            try:
                status_payload = conductor_call(
                    "get_session_status", {"session_id": session_id}
                )
                status = str(
                    first_string(status_payload, "status", "state") or ""
                ).lower()
                if status in {"error", "errored", "failed"}:
                    completed.append(job)
                    result, _ = read_session_remediation_result(session_id)
                    if result is not None and result["status"] in {"STOPPED", "FAILED"}:
                        yield job, result
                    else:
                        yield job, stopped_remediation(
                            job, "the Conductor agent session errored."
                        )
                elif status in {"working", "running", "busy"}:
                    job["saw_working"] = True
                    job["terminal_idle_confirmations"] = 0
                elif status in {"idle", "completed", "done"}:
                    result, turn_completed = read_session_remediation_result(session_id)
                    if result is not None:
                        completed.append(job)
                        if result["ticket_id"] != job["issue"]["ticket_id"]:
                            yield job, stopped_remediation(
                                job, "the agent returned a result for a different ticket."
                            )
                        else:
                            yield job, result
                    elif job["saw_working"] or status in {"completed", "done"}:
                        job["terminal_idle_confirmations"] += 1
                        if (
                            turn_completed
                            or job["terminal_idle_confirmations"]
                            >= TERMINAL_IDLE_CONFIRMATIONS
                        ):
                            completed.append(job)
                            yield job, stopped_remediation(
                                job,
                                "the agent finished without a structured remediation result.",
                            )
            except (RunnerError, OSError) as error:
                completed.append(job)
                yield job, stopped_remediation(job, f"Conductor polling failed: {error}.")
        for job in completed:
            pending.remove(job)
        if pending:
            time.sleep(poll_seconds)

    for job in pending:
        session_id = job["session_id"]
        if session_id:
            try:
                conductor_call("cancel_session", {"session_id": session_id})
            except RunnerError as error:
                log.warning("cancel remediation after timeout failed: %s", error)
        yield job, stopped_remediation(
            job, f"the {max_runtime_minutes}-minute remediation deadline expired."
        )


def production_approval_settings(manifest: JsonObject) -> JsonObject:
    value = manifest.get("production_approval")
    return cast(JsonObject, value) if isinstance(value, dict) else {}


def positive_approval_setting(
    settings: JsonObject,
    name: str,
    default: int,
) -> int:
    value = settings.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RunnerError(f"production_approval.{name} must be a positive integer.")
    return value


def slack_ts_key(value: str) -> tuple[int, int]:
    if not SLACK_TIMESTAMP_PATTERN.fullmatch(value):
        raise RunnerError(f"Invalid Slack message timestamp: {value!r}.")
    seconds, fraction = value.split(".", 1)
    return int(seconds), int(fraction)


def record_processed_approval(
    *,
    channel: str,
    message_ts: str,
    ticket_id: str,
    user_id: str,
    outcome: str,
) -> bool:
    with approval_connection() as connection:
        cursor = connection.execute(
            """
            INSERT OR IGNORE INTO processed_approval_messages (
                channel, message_ts, ticket_id, user_id, outcome, processed_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (channel, message_ts, ticket_id, user_id, outcome, utc_now().isoformat()),
        )
    return cursor.rowcount == 1


def claim_approval(
    candidate: ApprovalCandidate,
    *,
    message_ts: str,
    user_id: str,
) -> bool:
    with approval_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")
        inserted = connection.execute(
            """
            INSERT OR IGNORE INTO processed_approval_messages (
                channel, message_ts, ticket_id, user_id, outcome, processed_at
            ) VALUES (?, ?, ?, ?, 'accepted', ?)
            """,
            (
                candidate["channel"],
                message_ts,
                candidate["ticket_id"],
                user_id,
                utc_now().isoformat(),
            ),
        )
        if inserted.rowcount != 1:
            return False
        updated = connection.execute(
            """
            UPDATE approval_candidates
            SET state = 'queued', approval_message_ts = ?, approved_by = ?,
                promotion_session_id = NULL, promotion_session_link = NULL,
                deadline_at = NULL, start_attempts = 0,
                terminal_idle_confirmations = 0, last_error = NULL,
                terminal_result_json = NULL, result_posted_at = NULL
            WHERE ticket_id = ?
              AND state IN ('awaiting_approval', 'stopped', 'failed', 'rejected')
              AND expires_at > ?
            """,
            (message_ts, user_id, candidate["ticket_id"], utc_now().isoformat()),
        )
        if updated.rowcount != 1:
            connection.execute(
                """
                UPDATE processed_approval_messages
                SET outcome = 'stale'
                WHERE channel = ? AND message_ts = ?
                """,
                (candidate["channel"], message_ts),
            )
            return False
    return True


def expire_approval_candidates() -> None:
    now = utc_now()
    expired_queued = [
        candidate
        for candidate in candidates_in_states("queued")
        if datetime.fromisoformat(candidate["expires_at"]) <= now
    ]
    for candidate in expired_queued:
        finalize_production_candidate(
            candidate,
            stopped_production(
                candidate, "the production approval window expired before launch"
            ),
        )
    with approval_connection() as connection:
        connection.execute(
            """
            UPDATE approval_candidates
            SET state = 'expired', last_error = 'The production approval window expired.'
            WHERE state IN ('awaiting_approval', 'stopped', 'failed', 'rejected')
              AND expires_at <= ?
            """,
            (now.isoformat(),),
        )


def scan_slack_approvals(
    token: str,
    settings: JsonObject,
) -> None:
    raw_users = settings.get("authorized_slack_users")
    if not isinstance(raw_users, list) or not raw_users or not all(
        isinstance(user, str) and user for user in raw_users
    ):
        raise RunnerError("production_approval.authorized_slack_users is invalid.")
    authorized_users = set(cast(list[str], raw_users))
    candidates = candidates_in_states(
        "awaiting_approval", "stopped", "failed", "rejected"
    )
    by_thread: dict[tuple[str, str], dict[str, ApprovalCandidate]] = {}
    for candidate in candidates:
        key = (candidate["channel"], candidate["thread_ts"])
        by_thread.setdefault(key, {})[candidate["ticket_id"]] = candidate
    if not by_thread:
        return

    with approval_connection() as connection:
        rows = connection.execute(
            """
            SELECT channel, thread_ts, last_seen_ts
            FROM approval_thread_cursors
            ORDER BY COALESCE(last_polled_at, ''), channel, thread_ts
            """
        ).fetchall()
    selected = next(
        (
            row
            for row in rows
            if (cast(str, row["channel"]), cast(str, row["thread_ts"])) in by_thread
        ),
        None,
    )
    if selected is None:
        raise RunnerError("No Slack cursor exists for an approval candidate thread.")
    channel = cast(str, selected["channel"])
    thread_ts = cast(str, selected["thread_ts"])
    last_seen_ts = cast(str, selected["last_seen_ts"])
    messages = slack_thread_page(token, channel, thread_ts, last_seen_ts)
    thread_candidates = by_thread[(channel, thread_ts)]
    newest_ts = last_seen_ts
    for message in messages:
        text = message.get("text")
        message_ts = message.get("ts")
        user_id = message.get("user")
        if isinstance(message_ts, str) and slack_ts_key(message_ts) > slack_ts_key(
            newest_ts
        ):
            newest_ts = message_ts
        if not all(isinstance(value, str) for value in (text, message_ts, user_id)):
            continue
        match = PRODUCTION_APPROVAL_PATTERN.fullmatch(cast(str, text).strip())
        if match is None:
            continue
        ticket_id = match.group(1).upper()
        candidate = thread_candidates.get(ticket_id)
        if candidate is None:
            continue
        if slack_ts_key(cast(str, message_ts)) <= slack_ts_key(
            candidate["approval_not_before_ts"]
        ):
            continue
        if cast(str, user_id) not in authorized_users:
            if record_processed_approval(
                channel=channel,
                message_ts=cast(str, message_ts),
                ticket_id=ticket_id,
                user_id=cast(str, user_id),
                outcome="unauthorized",
            ):
                post_message(
                    token,
                    channel,
                    f"⛔ Production approval for `{ticket_id}` was rejected: "
                    "the Slack member is not authorized.",
                    thread_ts=thread_ts,
                )
            continue
        if claim_approval(
            candidate,
            message_ts=cast(str, message_ts),
            user_id=cast(str, user_id),
        ):
            post_message(
                token,
                channel,
                f"✅ Production approval recorded for `{ticket_id}` from "
                f"<@{user_id}>. Promotions run one at a time.",
                thread_ts=thread_ts,
            )
    with approval_connection() as connection:
        connection.execute(
            """
            UPDATE approval_thread_cursors
            SET last_seen_ts = ?, last_polled_at = ?
            WHERE channel = ? AND thread_ts = ?
            """,
            (newest_ts, utc_now().isoformat(), channel, thread_ts),
        )


def ticket_payload(ticket_id: str) -> JsonObject:
    payload = autodev_call(
        "get_ticket",
        {
            "project": "ts",
            "repo": "ts-prefect",
            "ticket_id": ticket_id,
            "detail": "light",
            "include_events": False,
        },
    )
    ticket = payload.get("ticket")
    if not isinstance(ticket, dict):
        raise RunnerError(f"Autodev returned no ticket object for {ticket_id}.")
    return payload


def staging_ticket_preflight(ticket_id: str) -> tuple[bool, str]:
    payload = ticket_payload(ticket_id)
    ticket = cast(JsonObject, payload["ticket"])
    if ticket.get("id") != ticket_id or ticket.get("repo") != "ts-prefect":
        return False, "the approval does not resolve to that ts-prefect ticket"
    if ticket.get("status") != "staging_verified":
        return False, f"ticket status is {ticket.get('status')!r}, not 'staging_verified'"
    evidence = verification_artifact(payload, environment="staging")
    if evidence is None:
        return False, "ticket has no exact staging PASS verification evidence artifact"
    return True, f"ticket is staging_verified with PASS evidence {evidence.get('id')}"


def artifact_recorded_at(artifact: JsonObject) -> datetime | None:
    value = artifact.get("updated_at") or artifact.get("created_at")
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def verification_artifact(
    payload: JsonObject,
    *,
    environment: str,
    recorded_after: datetime | None = None,
) -> JsonObject | None:
    artifacts = payload.get("artifacts")
    if not isinstance(artifacts, list):
        return None
    matches: list[JsonObject] = []
    for artifact in cast(list[JsonObject], artifacts):
        if artifact.get("artifact_type") != "verification_evidence":
            continue
        if not isinstance(artifact.get("id"), str) or not artifact["id"]:
            continue
        metadata = artifact.get("metadata")
        if not isinstance(metadata, dict):
            continue
        artifact_environment = str(metadata.get("environment", "")).lower()
        verdict = str(metadata.get("verdict", "")).upper()
        accepted_environments = (
            {"production", "prod"} if environment == "production" else {environment}
        )
        if artifact_environment not in accepted_environments:
            continue
        if verdict != "PASS":
            continue
        recorded_at = artifact_recorded_at(artifact)
        if recorded_after is not None and (
            recorded_at is None or recorded_at <= recorded_after
        ):
            continue
        matches.append(artifact)
    return max(
        matches,
        key=lambda artifact: artifact_recorded_at(artifact) or datetime.min.replace(
            tzinfo=timezone.utc
        ),
        default=None,
    )


def production_ticket_verified(
    ticket_id: str,
    approval_message_ts: str,
) -> tuple[bool, str]:
    payload = ticket_payload(ticket_id)
    ticket = cast(JsonObject, payload["ticket"])
    if (
        ticket.get("id") != ticket_id
        or ticket.get("repo") != "ts-prefect"
        or ticket.get("status") != "completed"
    ):
        return False, "ticket did not re-read as completed"
    seconds, fraction = approval_message_ts.split(".", 1)
    slack_ts_key(approval_message_ts)
    approved_at = datetime.fromtimestamp(
        int(seconds) + int(fraction) / 1_000_000,
        timezone.utc,
    )
    evidence = verification_artifact(
        payload,
        environment="production",
        recorded_after=approved_at,
    )
    if evidence is None:
        return False, "ticket has no new production PASS evidence recorded after approval"
    return (
        True,
        "ticket re-read as completed with production PASS evidence artifact "
        f"{evidence.get('id')} recorded after approval",
    )


def promotion_session_id(candidate: ApprovalCandidate) -> str:
    approval_ts = cast(str, candidate["approval_message_ts"])
    seed = (
        f"hermes-health-prod:{candidate['channel']}:{candidate['thread_ts']}:"
        f"{approval_ts}:{candidate['ticket_id']}"
    )
    return str(uuid5(NAMESPACE_URL, seed))


def promotion_message_id(candidate: ApprovalCandidate) -> str:
    return str(uuid5(NAMESPACE_URL, f"{promotion_session_id(candidate)}:prompt"))


def production_prompt(candidate: ApprovalCandidate) -> str:
    receipt = json.dumps(
        {
            "source": "slack_thread_comment",
            "slack_user_id": candidate["approved_by"],
            "slack_channel_id": candidate["channel"],
            "slack_thread_ts": candidate["thread_ts"],
            "slack_message_ts": candidate["approval_message_ts"],
            "ticket_id": candidate["ticket_id"],
        },
        separators=(",", ":"),
    )
    return f"""/ticket-promote {candidate['ticket_id']}

{PRODUCTION_APPROVAL_MARKER}
{receipt}

This is a single-ticket production authorization transported by the deterministic Hermes
approval bridge after it authenticated the Slack member, thread, ticket, and one-use message.
Re-read the ticket and staging PASS evidence before mutation. Promote only this ticket through
the normal `/ticket-promote` lifecycle and its production verification handoff. This approval
does not authorize a parity bypass, scope widening, another ticket, or a new product decision.

End the final message with `{PRODUCTION_RESULT_MARKER}` on its own line followed by one single-line
JSON object and nothing after it. Use exactly `status`, `ticket_id`, `issue`, `fix`, and
`verification`. Status is `PROD_VERIFIED` only after the ticket re-reads as `completed` and a new
production PASS verification artifact is recorded after this Slack approval; otherwise use
`STOPPED` or `FAILED`. Keep the issue, fix, and verification values to one concise sentence each.
"""


def mark_candidate_running(
    candidate: ApprovalCandidate,
    *,
    session_id: str,
    session_link: str | None,
    max_runtime_minutes: int,
) -> None:
    with approval_connection() as connection:
        connection.execute(
            """
            UPDATE approval_candidates
            SET state = 'running', promotion_session_id = ?,
                promotion_session_link = ?, deadline_at = ?,
                start_attempts = 0, terminal_idle_confirmations = 0,
                last_error = NULL
            WHERE ticket_id = ? AND state IN ('queued', 'launching')
            """,
            (
                session_id,
                session_link,
                (utc_now() + timedelta(minutes=max_runtime_minutes)).isoformat(),
                candidate["ticket_id"],
            ),
        )


def session_not_found(error: RunnerError) -> bool:
    lowered = str(error).lower()
    return "404" in lowered or "not found" in lowered or "does not exist" in lowered


def ensure_promotion_session(
    candidate: ApprovalCandidate,
    workspace_spec: JsonObject,
    max_runtime_minutes: int,
) -> tuple[str, str | None]:
    session_id = promotion_session_id(candidate)
    session: JsonObject
    try:
        session = conductor_call("get_session", {"session_id": session_id})
    except RunnerError as error:
        if not session_not_found(error):
            raise
        request: JsonObject = {
            "workspace_id": candidate["workspace_id"],
            "session_id": session_id,
            "agent": workspace_spec.get("agent"),
            "name": f"production approval {candidate['ticket_id']}",
        }
        for key in ("model", "effort"):
            value = workspace_spec.get(key)
            if isinstance(value, str) and value:
                request[key] = value
        session = conductor_call("create_session", request)
    session_link = first_string(session, "url", "deepLink", "webUrl", "appUrl")
    snapshot = session_message_snapshot(session_id)
    approval_ts = cast(str, candidate["approval_message_ts"])
    already_sent = any(
        PRODUCTION_APPROVAL_MARKER in text and approval_ts in text
        for text in snapshot["texts"]
    )
    if not already_sent:
        conductor_call(
            "send_session_message",
            {
                "session_id": session_id,
                "message": production_prompt(candidate),
                "message_id": promotion_message_id(candidate),
            },
        )
    mark_candidate_running(
        candidate,
        session_id=session_id,
        session_link=session_link,
        max_runtime_minutes=max_runtime_minutes,
    )
    return session_id, session_link


def production_result_reply(
    candidate: ApprovalCandidate,
    result: ProductionResult,
) -> str:
    icon = {"PROD_VERIFIED": "✅", "STOPPED": "⛔", "FAILED": "❌"}[result["status"]]
    status_label = {
        "PROD_VERIFIED": "production verified",
        "STOPPED": "production stopped",
        "FAILED": "production failed",
    }[result["status"]]
    lines = [
        f"{icon} *{candidate['ticket_id']} — {status_label}*",
        f"• *Issue:* {slack_plain_text(result['issue'])}",
        f"• *Fix:* {slack_plain_text(result['fix'])}",
        f"• *Production verification:* {slack_plain_text(result['verification'])}",
    ]
    link = candidate["promotion_session_link"] or candidate["workspace_link"]
    if link:
        lines.append(f"• *Workspace:* <{link}|Open in Conductor>")
    if result["status"] != "PROD_VERIFIED":
        lines.append(
            "• *Queue:* Later approvals were reset. After reviewing this stop, reply again "
            f"with `approve prod {candidate['ticket_id']}`."
        )
    return "\n".join(lines)


def slack_plain_text(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def mark_history_workspace_status(workspace_id: str, status: str) -> None:
    path = history_path("health-6h")
    if not path.exists():
        return
    records = [
        cast(JsonObject, json.loads(line))
        for line in path.read_text().splitlines()
        if line.strip()
    ]
    changed = False
    for record in records:
        if record.get("workspace_id") == workspace_id:
            record["status"] = status
            record["completed_at"] = utc_now().isoformat()
            changed = True
    if changed:
        path.write_text("".join(json.dumps(record) + "\n" for record in records))


def finalize_production_candidate(
    candidate: ApprovalCandidate,
    result: ProductionResult,
) -> None:
    if result["ticket_id"] != candidate["ticket_id"]:
        result = {
            "status": "STOPPED",
            "ticket_id": candidate["ticket_id"],
            "issue": "The production session returned a result for a different ticket.",
            "fix": "No additional production action was authorized.",
            "verification": "The mismatched result was rejected before success was recorded.",
        }
    if result["status"] == "PROD_VERIFIED":
        approval_ts = candidate["approval_message_ts"]
        if approval_ts is None:
            verified, evidence = False, "the approval message timestamp is missing"
        else:
            verified, evidence = production_ticket_verified(
                candidate["ticket_id"], approval_ts
            )
        if not verified:
            result = {
                "status": "STOPPED",
                "ticket_id": candidate["ticket_id"],
                "issue": "The promotion session claimed success without durable ticket proof.",
                "fix": "The success claim was rejected by the approval bridge.",
                "verification": evidence.capitalize() + ".",
            }
        else:
            result["verification"] = evidence.capitalize() + "."
    terminal_state = {
        "PROD_VERIFIED": "prod_verified",
        "STOPPED": "stopped",
        "FAILED": "failed",
    }[result["status"]]
    with approval_connection() as connection:
        connection.execute(
            """
            UPDATE approval_candidates
            SET state = ?, terminal_result_json = ?, result_posted_at = NULL,
                last_error = NULL
            WHERE ticket_id = ?
            """,
            (terminal_state, json.dumps(result), candidate["ticket_id"]),
        )
        if result["status"] != "PROD_VERIFIED":
            connection.execute(
                """
                UPDATE approval_candidates
                SET state = 'awaiting_approval', approval_message_ts = NULL,
                    approved_by = NULL, promotion_session_id = NULL,
                    promotion_session_link = NULL, deadline_at = NULL,
                    start_attempts = 0, terminal_idle_confirmations = 0,
                    last_error = 'A prior production promotion did not verify.',
                    terminal_result_json = NULL, result_posted_at = NULL
                WHERE state = 'queued'
                """
            )
    mark_history_workspace_status(
        candidate["workspace_id"],
        "PASS" if result["status"] == "PROD_VERIFIED" else "FAIL",
    )


def post_pending_production_results(token: str) -> None:
    with approval_connection() as connection:
        rows = connection.execute(
            """
            SELECT * FROM approval_candidates
            WHERE state IN ('prod_verified', 'stopped', 'failed', 'expired')
              AND terminal_result_json IS NOT NULL
              AND result_posted_at IS NULL
            ORDER BY created_at, ticket_id
            """
        ).fetchall()
    for row in rows:
        candidate = approval_candidate(row)
        raw_result = cast(str, row["terminal_result_json"])
        result = parse_production_result(
            f"{PRODUCTION_RESULT_MARKER}\n{raw_result}"
        )
        if result is None:
            raise RunnerError(
                f"Stored production result is invalid for {candidate['ticket_id']}."
            )
        posted_ts = post_message(
            token,
            candidate["channel"],
            production_result_reply(candidate, result),
            thread_ts=candidate["thread_ts"],
            client_msg_id=str(
                uuid5(
                    NAMESPACE_URL,
                    f"hermes-health-prod:{candidate['ticket_id']}:"
                    f"{candidate['approval_message_ts']}:result",
                )
            ),
        )
        with approval_connection() as connection:
            if result["status"] != "PROD_VERIFIED":
                connection.execute(
                    """
                    UPDATE approval_candidates
                    SET approval_not_before_ts = ?
                    WHERE ticket_id = ?
                       OR (
                            state = 'awaiting_approval'
                            AND last_error = 'A prior production promotion did not verify.'
                       )
                    """,
                    (posted_ts, candidate["ticket_id"]),
                )
            connection.execute(
                """
                UPDATE approval_candidates
                SET result_posted_at = ?
                WHERE ticket_id = ? AND result_posted_at IS NULL
                """,
                (utc_now().isoformat(), candidate["ticket_id"]),
            )


def stopped_production(
    candidate: ApprovalCandidate,
    reason: str,
) -> ProductionResult:
    return {
        "status": "STOPPED",
        "ticket_id": candidate["ticket_id"],
        "issue": "The approved production promotion did not reach verified completion.",
        "fix": f"The promotion stopped because {reason.rstrip('.')}.",
        "verification": "No production PASS was recorded; inspect the Conductor session.",
    }


def supervise_active_production() -> bool:
    active = candidates_in_states("running", "launching")
    if not active:
        return False
    candidate = active[0]
    session_id = candidate["promotion_session_id"]
    if not session_id:
        set_candidate_state(
            candidate["ticket_id"],
            "queued",
            last_error="Promotion session creation did not complete.",
        )
        return False
    deadline = candidate["deadline_at"]
    if deadline and utc_now() >= datetime.fromisoformat(deadline):
        try:
            conductor_call("cancel_session", {"session_id": session_id})
        except RunnerError as error:
            log.warning("cancel production promotion after timeout failed: %s", error)
        finalize_production_candidate(
            candidate,
            stopped_production(candidate, "the production deadline expired."),
        )
        return False
    status_payload = conductor_call("get_session_status", {"session_id": session_id})
    status = str(first_string(status_payload, "status", "state") or "").lower()
    if status in {"working", "running", "busy"}:
        set_candidate_state(candidate["ticket_id"], "running", idle_confirmations=0)
        return True
    if status in {"error", "errored", "failed"}:
        result, _ = read_session_production_result(session_id)
        if result is None or result["status"] == "PROD_VERIFIED":
            result = stopped_production(candidate, "the Conductor session errored.")
        finalize_production_candidate(candidate, result)
        return False
    if status in {"idle", "completed", "done"}:
        result, turn_completed = read_session_production_result(session_id)
        if result is not None:
            finalize_production_candidate(candidate, result)
            return False
        confirmations = candidate["terminal_idle_confirmations"] + 1
        if turn_completed or confirmations >= TERMINAL_IDLE_CONFIRMATIONS:
            finalize_production_candidate(
                candidate,
                stopped_production(
                    candidate, "the agent finished without a structured production result."
                ),
            )
            return False
        set_candidate_state(
            candidate["ticket_id"], "running", idle_confirmations=confirmations
        )
    return True


def start_next_production(
    token: str,
    settings: JsonObject,
    workspace_spec: JsonObject,
) -> bool:
    queued = candidates_in_states("queued")
    if not queued:
        return False
    candidate = min(
        queued,
        key=lambda item: slack_ts_key(cast(str, item["approval_message_ts"])),
    )
    try:
        ready, reason = staging_ticket_preflight(candidate["ticket_id"])
    except RunnerError as error:
        record_start_failure(candidate, f"production preflight failed: {error}", settings)
        return False
    if not ready:
        set_candidate_state(candidate["ticket_id"], "rejected", last_error=reason)
        post_message(
            token,
            candidate["channel"],
            f"⛔ Production approval for `{candidate['ticket_id']}` was rejected: {reason}.",
            thread_ts=candidate["thread_ts"],
        )
        return False
    set_candidate_state(candidate["ticket_id"], "launching")
    try:
        session_id, session_link = ensure_promotion_session(
            candidate,
            workspace_spec,
            positive_approval_setting(settings, "max_runtime_minutes", 480),
        )
    except RunnerError as error:
        record_start_failure(candidate, f"Conductor session launch failed: {error}", settings)
        return False
    post_message(
        token,
        candidate["channel"],
        f"🚀 Production promotion started for `{candidate['ticket_id']}`."
        + (f" <{session_link}|Open in Conductor>" if session_link else ""),
        thread_ts=candidate["thread_ts"],
    )
    log.info("production promotion %s started in session %s", candidate["ticket_id"], session_id)
    return True


def record_start_failure(
    candidate: ApprovalCandidate,
    reason: str,
    settings: JsonObject,
) -> None:
    attempts = candidate["start_attempts"] + 1
    max_attempts = positive_approval_setting(settings, "max_start_attempts", 10)
    with approval_connection() as connection:
        connection.execute(
            """
            UPDATE approval_candidates
            SET state = 'queued', start_attempts = ?, last_error = ?
            WHERE ticket_id = ?
            """,
            (attempts, reason, candidate["ticket_id"]),
        )
    if attempts < max_attempts:
        log.warning(
            "production start attempt %s/%s deferred for %s: %s",
            attempts,
            max_attempts,
            candidate["ticket_id"],
            reason,
        )
        return
    refreshed = next(
        item
        for item in candidates_in_states("queued")
        if item["ticket_id"] == candidate["ticket_id"]
    )
    finalize_production_candidate(
        refreshed,
        stopped_production(
            refreshed,
            f"startup could not complete after {attempts} attempts",
        ),
    )


def process_production_approvals() -> int:
    manifest = load_manifest()
    settings = production_approval_settings(manifest)
    if not settings.get("enabled"):
        log.info("production approval bridge is disabled; skipping")
        return 0
    positive_approval_setting(settings, "expires_days", 14)
    positive_approval_setting(settings, "max_runtime_minutes", 480)
    positive_approval_setting(settings, "max_start_attempts", 10)
    state_dir().mkdir(parents=True, exist_ok=True)
    lock_file = (state_dir() / "production-approvals.lock").open("w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        log.info("production approval bridge: previous poll still active; skipping")
        return 0
    try:
        token = read_slack_token()
        post_pending_production_results(token)
        expire_approval_candidates()
        scan_slack_approvals(token, settings)
        active = supervise_active_production()
        post_pending_production_results(token)
        if not active:
            health = manifest_entry(manifest, "health-6h")
            start_next_production(
                token,
                settings,
                cast(JsonObject, health.get("workspace") or {}),
            )
            post_pending_production_results(token)
        return 0
    finally:
        lock_file.close()


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
    terminal_idle_confirmations = 0
    while time.monotonic() < deadline:
        status_payload = conductor_call("get_session_status", {"session_id": session_id})
        status = str(
            first_string(status_payload, "status", "state") or ""
        ).lower()
        if status in {"error", "errored", "failed"}:
            return "errored", read_session_result(session_id)["result"]
        if status in {"working", "running", "busy"}:
            saw_working = True
            terminal_idle_confirmations = 0
        elif status in {"idle", "completed", "done"}:
            snapshot = read_session_result(session_id)
            if snapshot["result"] is not None:
                return "finished", snapshot["result"]
            if snapshot["turn_completed"]:
                return "finished", None
            if saw_working or status in {"completed", "done"}:
                terminal_idle_confirmations += 1
                if terminal_idle_confirmations >= TERMINAL_IDLE_CONFIRMATIONS:
                    return "finished", None
        else:
            terminal_idle_confirmations = 0
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
    remediation_max_runtime = int(
        cast(int, entry.get("remediation_max_runtime_minutes", 0))
    )

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
    incident_posted = False
    if name == "health-6h":
        issues = health_issues(result, summary, status)
        if status == "PASS" and issues:
            status = "FAIL"
            summary = "run reported issues with PASS status"
        jobs = launch_health_remediations(entry, issues)
        icon = STATUS_ICONS[status]
        line = health_parent_message(icon, issues, summary, jobs)
        parent_ts = post_message(slack_token, channel, line)
        if status in {"FAIL", "BLOCKED"} and channel != incidents:
            permalink = message_permalink(slack_token, channel, parent_ts)
            post_message(
                slack_token,
                incidents,
                incident_message(name, status, summary, result, issues, permalink),
            )
            incident_posted = True
        for job, remediation in supervise_health_remediations(
            jobs, remediation_max_runtime, poll_seconds
        ):
            remediation_reply_ts = post_message(
                slack_token,
                channel,
                health_remediation_reply(job, remediation),
                thread_ts=parent_ts,
            )
            record_remediation(name, job, remediation)
            if remediation["status"] == "STAGING_VERIFIED":
                approval_settings = production_approval_settings(manifest)
                register_production_candidate(
                    job,
                    channel=channel,
                    thread_ts=parent_ts,
                    staging_reply_ts=remediation_reply_ts,
                    expires_days=positive_approval_setting(
                        approval_settings, "expires_days", 14
                    ),
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
    if status in {"FAIL", "BLOCKED"} and not incident_posted:
        permalink = message_permalink(slack_token, channel, parent_ts)
        if channel != incidents:
            post_message(
                slack_token,
                incidents,
                incident_message(name, status, summary, result, issues, permalink),
            )

    record_run(name, status, workspace_id)
    archive_completed_workspace(manifest, name, status, workspace_id)
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
    if suffix == "watchdog":
        unit = "hermes-schedule-watchdog.service"
    elif suffix == "approval":
        unit = "hermes-schedule-approval.service"
    else:
        unit = f"hermes-schedule@{suffix}.service"
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
        remediation_runtime = int(
            cast(int, entry.get("remediation_max_runtime_minutes", 0))
        )
        allowed = interval_hours * 3600 + (
            max_runtime + remediation_runtime + WATCHDOG_GRACE_MINUTES
        ) * 60
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
    protected_workspaces = approval_protected_workspace_ids()
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
            if record["workspace_id"] in protected_workspaces:
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
    if len(argv) == 2 and argv[1] == "approvals":
        return process_production_approvals()
    print(
        "usage: runner.py run <schedule> | alert <unit-suffix> | watchdog | approvals",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))

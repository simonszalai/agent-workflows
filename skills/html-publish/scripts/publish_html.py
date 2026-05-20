#!/usr/bin/env python3
"""Publish a standalone HTML artifact to the workflow_pro S3 artifact bucket."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

DEFAULT_BUCKET = "workflow-pro-html-artifacts-526640104985"
DEFAULT_REGION = "eu-central-1"
DEFAULT_BASE_URL = f"https://{DEFAULT_BUCKET}.s3.{DEFAULT_REGION}.amazonaws.com"
TICKET_RE = re.compile(r"^[A-Z]+\d+")


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, cwd=cwd, check=False, text=True, capture_output=True)
    if result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout)
        raise SystemExit(result.returncode)
    return result


def git_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=start,
        check=False,
        text=True,
        capture_output=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        return Path(result.stdout.strip()).resolve()
    return start.resolve()


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "html-artifact"


def ensure_html(path: Path) -> None:
    if path.suffix.lower() not in {".html", ".htm"}:
        raise SystemExit(f"Expected an .html file, got: {path}")
    if not path.exists() or not path.is_file():
        raise SystemExit(f"File not found: {path}")
    if path.stat().st_size == 0:
        raise SystemExit(f"File is empty: {path}")
    sample = path.read_text(errors="ignore")[:2048].lower()
    if "<html" not in sample and "<!doctype html" not in sample:
        raise SystemExit(f"File does not look like a standalone HTML document: {path}")


def infer_ticket(filename: str) -> str | None:
    match = TICKET_RE.match(filename)
    return match.group(0) if match else None


def build_filename(input_path: Path, ticket: str | None, slug: str | None) -> str:
    existing_name = input_path.name
    existing_stem = input_path.stem
    if slug:
        stem = slugify(slug)
        if ticket:
            prefix = ticket.lower()
            if stem == prefix:
                return f"{ticket}.html"
            if stem.startswith(prefix + "-"):
                return f"{ticket}-{stem[len(prefix) + 1:]}.html"
            return f"{ticket}-{stem}.html"
        return f"{stem}.html"

    if ticket:
        if existing_stem.startswith(ticket):
            rest = existing_stem[len(ticket):].lstrip("-_ ")
            return f"{ticket}-{slugify(rest)}.html" if rest else f"{ticket}.html"
        return f"{ticket}-{slugify(existing_stem)}.html"

    if existing_name.lower().endswith((".html", ".htm")):
        return f"{slugify(existing_stem)}.html"
    return f"{slugify(existing_name)}.html"


def load_registry(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, dict) and isinstance(data.get("artifacts"), list):
        return data["artifacts"]
    if isinstance(data, list):
        return data
    raise SystemExit(f"Unsupported registry format: {path}")


def write_registry(path: Path, artifacts: list[dict[str, Any]]) -> None:
    payload = {
        "schema": 1,
        "updatedAt": dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "artifacts": artifacts,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_index_html(path: Path, artifacts: list[dict[str, Any]]) -> None:
    rows = []
    for item in sorted(artifacts, key=lambda x: (x.get("ticket") or "ZZZ", x.get("title") or x.get("file") or "")):
        ticket = html.escape(item.get("ticket") or "—")
        title = html.escape(item.get("title") or item.get("file") or "Untitled")
        file_name = html.escape(item.get("file") or "")
        url = html.escape(item.get("url") or "")
        updated = html.escape(item.get("updatedAt") or item.get("createdAt") or "")
        rows.append(
            f"<tr><td>{ticket}</td><td><a href=\"{url}\">{title}</a></td><td><code>{file_name}</code></td><td>{updated}</td></tr>"
        )
    body = "\n".join(rows) or '<tr><td colspan="4">No published artifacts yet.</td></tr>'
    path.write_text(
        """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>workflow_pro HTML artifacts</title>
  <style>
    :root { color-scheme: light; --bg: #f6f4f0; --card: #fff; --text: #171717; --muted: #6f6a61; --line: #ddd6ca; --accent: #3157d5; }
    body { margin: 0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background: var(--bg); color: var(--text); }
    main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 48px 0; }
    h1 { margin: 0 0 8px; font-size: clamp(2rem, 4vw, 3.4rem); letter-spacing: -0.04em; }
    p { margin: 0 0 28px; color: var(--muted); }
    table { width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); border-radius: 16px; overflow: hidden; box-shadow: 0 16px 50px rgba(35, 30, 22, 0.08); }
    th, td { padding: 14px 16px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); background: #fbfaf7; }
    tr:last-child td { border-bottom: 0; }
    a { color: var(--accent); font-weight: 650; text-decoration: none; }
    a:hover { text-decoration: underline; }
    code { font-family: "SFMono-Regular", Consolas, "Liberation Mono", monospace; font-size: 0.86rem; }
  </style>
</head>
<body>
  <main>
    <h1>workflow_pro HTML artifacts</h1>
    <p>Generated index of published standalone HTML explainers and charts.</p>
    <table>
      <thead><tr><th>Ticket</th><th>Artifact</th><th>File</th><th>Updated</th></tr></thead>
      <tbody>
"""
        + body
        + """
      </tbody>
    </table>
  </main>
</body>
</html>
"""
    )


def upload(path: Path, bucket: str, key: str, region: str, content_type: str) -> None:
    run(
        [
            "aws",
            "s3",
            "cp",
            str(path),
            f"s3://{bucket}/{key}",
            "--region",
            region,
            "--content-type",
            content_type,
            "--cache-control",
            "no-cache, max-age=0",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", help="HTML file to publish")
    parser.add_argument("--ticket", help="Ticket prefix, e.g. F123")
    parser.add_argument("--slug", help="Stable slug/filename stem. Reuse to overwrite during iteration.")
    parser.add_argument("--title", help="Human-readable title for the index")
    parser.add_argument("--repo-root", help="Repo root. Defaults to git root from cwd.")
    parser.add_argument("--artifact-dir", default="artifacts/html", help="Repo-relative artifact directory")
    parser.add_argument("--bucket", default=os.getenv("HTML_PUBLISH_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--region", default=os.getenv("HTML_PUBLISH_REGION", DEFAULT_REGION))
    parser.add_argument("--base-url", default=os.getenv("HTML_PUBLISH_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--no-save", action="store_true", help="Upload the input file directly without copying it into artifacts/html")
    args = parser.parse_args()

    input_path = Path(args.file).expanduser().resolve()
    ensure_html(input_path)

    cwd_root = Path(args.repo_root).expanduser().resolve() if args.repo_root else git_root(input_path.parent)
    artifact_dir = (cwd_root / args.artifact_dir).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    ticket = args.ticket or infer_ticket(input_path.name)
    if ticket:
        ticket = ticket.upper()
    filename = build_filename(input_path, ticket, args.slug)
    saved_path = artifact_dir / filename

    if args.no_save:
        publish_path = input_path
    else:
        if input_path != saved_path:
            saved_path.write_bytes(input_path.read_bytes())
        publish_path = saved_path

    key_prefix = f"html/{ticket}" if ticket else "html/uncategorized"
    key = f"{key_prefix}/{filename}"
    base_url = args.base_url.rstrip("/")
    url = f"{base_url}/{key}"

    upload(publish_path, args.bucket, key, args.region, "text/html; charset=utf-8")

    registry_path = artifact_dir / "index.json"
    index_html_path = artifact_dir / "index.html"
    artifacts = load_registry(registry_path)
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    title = args.title or filename.removesuffix(".html").replace("-", " ").title()
    if args.no_save:
        source = str(publish_path)
    else:
        source = str(saved_path.relative_to(cwd_root)) if saved_path.is_relative_to(cwd_root) else str(publish_path)
    record = {
        "ticket": ticket,
        "title": title,
        "file": filename,
        "source": source,
        "s3Key": key,
        "url": url,
        "updatedAt": now,
    }

    replaced = False
    for idx, item in enumerate(artifacts):
        if item.get("s3Key") == key or item.get("file") == filename:
            record["createdAt"] = item.get("createdAt") or now
            artifacts[idx] = record
            replaced = True
            break
    if not replaced:
        record["createdAt"] = now
        artifacts.append(record)

    write_registry(registry_path, artifacts)
    write_index_html(index_html_path, artifacts)
    upload(registry_path, args.bucket, "index.json", args.region, "application/json; charset=utf-8")
    upload(index_html_path, args.bucket, "index.html", args.region, "text/html; charset=utf-8")

    print(url)


if __name__ == "__main__":
    main()

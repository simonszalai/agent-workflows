---
name: html-publish
description: Publish a standalone HTML artifact from artifacts/html or a provided file path to the workflow_pro S3 HTML artifacts bucket, update the shareable index, and return a stable URL. Use when the user asks to upload, publish, share, or create a URL for an HTML artifact, HTML chart, visual explainer, or generated .html file.
---

# HTML Publish

Publish a standalone `.html` artifact to the workflow_pro HTML artifacts S3 bucket and return a shareable URL.

## Defaults

- Bucket: `workflow-pro-html-artifacts-526640104985`
- Region: `eu-central-1`
- Public HTTPS base URL: `https://workflow-pro-html-artifacts-526640104985.s3.eu-central-1.amazonaws.com`
- Repo artifact directory: `artifacts/html/`
- Bucket layout:
  - Ticketed: `html/<ticket>/<ticket>-<slug>.html`
  - Unticketed: `html/uncategorized/<slug>.html`
  - Index files: `index.html` and `index.json` at the bucket root

Override defaults with `HTML_PUBLISH_BUCKET`, `HTML_PUBLISH_REGION`, and `HTML_PUBLISH_BASE_URL` when needed.

## Naming rules

- If attached to a ticket, the HTML filename must start with that ticket prefix: `F123-short-slug.html`.
- Multiple artifacts for the same ticket use a differentiating suffix: `F123-flow-map.html`, `F123-data-model.html`.
- Iteration overwrites the same file. Do not create timestamped or numbered versions unless the user explicitly asks for separate versions.
- Unticketed artifacts use a descriptive slug, optionally date-prefixed if useful.

## Workflow

1. Identify the HTML file to publish. Prefer a file already under `artifacts/html/` (the `$html-chart` skill writes there).
2. If the artifact is ticketed but the filename does not start with the ticket prefix, rename or copy it so it does.
3. Publish with the bundled script from this skill directory:

```bash
python3 scripts/publish_html.py /absolute/or/relative/file.html --ticket F123 --title "Readable title"
```

Use `--slug <slug>` to choose or stabilize the destination filename. Reusing the same slug overwrites the same repo file and S3 object.

4. The script:
   - validates the input is HTML,
   - optionally copies/normalizes it into `artifacts/html/`,
   - uploads it with `Content-Type: text/html; charset=utf-8`,
   - updates `artifacts/html/index.json` and `artifacts/html/index.html`,
   - uploads both index files to the bucket root,
   - prints the final shareable URL.
5. Verify the printed URL with a lightweight request when practical:

```bash
curl -I <url>
```

Do not start a dev server for this workflow.

## First-time bucket setup reference

The current bucket was created as a public-read static artifact bucket with AES256 server-side encryption and S3 website index support. If recreating in another account, use a globally unique bucket name, disable public-access blocks only for this dedicated artifact bucket, attach a public `s3:GetObject` bucket policy, and prefer CloudFront later if HTTPS custom-domain serving is needed.

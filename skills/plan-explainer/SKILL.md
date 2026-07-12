---
name: plan-explainer
description: Generate or refresh the single access-gated HTML explainer artifact for an autodev ticket or epic plan. Use when asked to make, refresh, regenerate, or view a plan as a page/HTML, especially for canonical source/plan artifacts stored in autodev-memory.
---

# Plan Explainer

Generate one **self-contained, dashboard-served HTML explainer** from the canonical Markdown `plan` artifact for an autodev ticket or epic, then write it back to autodev-memory as the parent’s singleton `html` artifact.

This skill is the plan-specific adaptation of `arch-artifact`: keep the plan Markdown lean, but make the HTML teach the plan to a human who does not know the terms.

## Non-negotiables

1. **Source of truth is the stored plan artifact.** Fetch it with the MCP tools (`get_epic` for epics, `get_ticket` for tickets). Do not use stale local files unless the user explicitly provides them as the source.
2. **Exactly one HTML artifact per parent.** Update the existing `html` artifact in place via `update_artifact`; create it only if none exists.
3. **HTML has no version history.** It is regenerate-and-replace. Do not preserve old HTML renders unless the user explicitly asks.
4. **Self-contained output.** No external scripts, modules, stylesheets, fonts, CDN assets, or network fetches. Inline CSS/JS only. All diagrams must be static HTML/CSS or inline SVG.
5. **No runtime Mermaid.** If the plan contains fenced `mermaid` blocks, render/translate them to static inline SVG before storing the HTML.
6. **Write back to MCP, not a file.** The final artifact content lives in autodev-memory. Return the dashboard route/URL for the `html` artifact.

## Inputs

Resolve from the user’s request:

- `project` (from repo instructions or explicit user input)
- parent scope: `epic` (`E####` or UUID) or `ticket` (`F####`/`B####`/`R####` + repo)
- optional dashboard base URL; if unknown, return the route path

Fetch:

- Epic: `get_epic(project, epic_id)` and inspect `artifacts`
- Ticket: `get_ticket(project, ticket_id, repo, detail="full",
  artifact_types=["source", "plan", "html"], include_events=false)` and inspect `artifacts`

Plan selection:

- Prefer the singleton `artifact_type == "plan"` row.
- If legacy duplicates exist, prefer a row titled/marked canonical/current, then the newest `updated_at`.
- If ambiguity would change content materially, stop and state the candidate plan artifact IDs/titles; otherwise choose and note your choice.

Existing HTML selection:

- Find `artifact_type == "html"` on the same parent.
- If multiple legacy HTML rows exist, update the one marked current/newest and report the duplicates as cleanup candidates; do not delete them unless explicitly asked.

## HTML design

Use the dark high-tech design system and rules from `../arch-artifact/SKILL.md`; start from `../arch-artifact/assets/template.html` if present. Keep these plan-specific additions:

- Above the fold: eyebrow, H1, one-sentence thesis, 3–5 decision/takeaway cards.
- Body: 3–6 sections that explain the plan’s model, data flow, operational rules, edge cases, and rollout/testing.
- Human layer: add explanatory diagrams/illustrations and concept tooltips that are **not** inserted back into the Markdown plan.
- Tooltips: CSS-only or semantic `<details>`/`<summary>`; acronyms spelled out on first use.
- Mermaid: replace each code fence with a static inline SVG or robust CSS diagram; preserve the meaning, labels, arrow direction, and legend.
- Content must be visible with JavaScript disabled. Inline JS is allowed only for progressive enhancement.

## Mermaid to inline SVG workflow

For every fenced block like:

````markdown
```mermaid
flowchart TD
  A --> B
```
````

Use one of these approaches, in order:

1. If a local Mermaid renderer is already available, render to SVG and inline the sanitized SVG.
2. If not, manually translate simple flowcharts/sequence/state diagrams into inline SVG or CSS boxes.
3. If a diagram is too complex, split it into smaller static diagrams; never embed Mermaid source as the rendered diagram.

Sanitize generated SVG:

- Include `viewBox` and `width="100%"`; avoid fixed pixel-only layouts.
- Remove external font/image refs, scripts, and event handlers.
- Use current design tokens (`var(--tx)`, `var(--bd)`, `var(--ac)`) where practical.
- Add `role="img"` and `aria-label`, plus a visible caption.

## Write-back protocol

Build metadata:

```json
{
  "derived_from": {
    "plan_artifact_id": "<plan artifact uuid>",
    "plan_version_id": null,
    "generated_at": "<UTC ISO timestamp>"
  }
}
```

Upsert algorithm:

1. Generate the complete HTML string.
2. If an HTML artifact exists:
   - `update_artifact(project, artifact_id=<html_id>, content=<html>, metadata=<metadata>, change_note="regenerate plan explainer", command="/plan-explainer")`
3. If no HTML artifact exists:
   - Epic: `create_epic_artifact(project, epic_id=<E####>, artifact_type="html", content=<html>, title="Plan explainer", metadata=<metadata>, command="/plan-explainer")`
   - Ticket: `create_artifact(project, ticket_id=<id>, repo=<repo>, artifact_type="html", content=<html>, title="Plan explainer", metadata=<metadata>, command="/plan-explainer")`
4. If create returns `existing_artifact_id` because of a race/singleton guard, immediately update that artifact.

Dashboard route:

- Epic HTML: `/epic-artifacts/<artifact_id>/html?project=<project>`
- Ticket HTML: `/ticket-artifacts/<artifact_id>/html?project=<project>`

Return that route (or absolute URL if the dashboard base URL is known) and the source plan artifact ID.

## Quality checklist

Before returning:

- [ ] Stored HTML is a full document: `<!doctype html>`, `<html>`, `<head>`, charset, viewport, inline `<style>`.
- [ ] No `<script src>`, `type="module"`, CDN, `@import`, web font, external stylesheet, or network fetch.
- [ ] No runtime Mermaid/D3/Chart.js/marked/etc.; diagrams are static inline SVG/CSS.
- [ ] The page remains readable with JS disabled.
- [ ] Non-obvious terms have human explanations; common words are not over-tooltipped.
- [ ] `metadata.derived_from.plan_artifact_id` matches the canonical plan used.
- [ ] The result was written via MCP as the singleton `html` artifact.
- [ ] Final response includes the dashboard route/URL and any duplicate legacy HTML cleanup candidates.

---
name: html-chart
description: Create a standalone, well-designed, interactive HTML visual explainer from the current conversation thread or provided context. Use when the user asks to visualize, explain, summarize, map, chart, diagram, synthesize, or make a high-bandwidth HTML artifact from discussion, plans, concepts, decisions, tradeoffs, workflows, research, or complex ideas; especially when they want an absolute path to the generated HTML file.
---

# HTML Chart

Create a single self-contained `.html` document that helps a reader understand a system,
decision, or concept faster than reading the source material. The output is a bespoke
explainer designed *for this specific content* — not a template filled in, not a Markdown
export, not a transcript.

## Two non-negotiables

1. **Truth.** Every fact in the artifact comes from the source context. Mark inferences as
   inferences. Don't invent data points, numbers, or relationships to make a visual look
   complete.
2. **Design the artifact around the content, not the content around a layout.** Decide what
   the reader needs to understand, in what order, and let that dictate the structure. There
   is no required set of sections. A great explainer might be one big annotated diagram, a
   scrollytelling narrative, a single dense comparison table, or an interactive playground —
   whatever fits.

## Distill before you draw

- Use the conversation thread and any referenced files as the source. Don't ask the user to
  restate context.
- Present the **final outcome** (the arrived-at model/decision/system), not the winding path
  that led there — unless the user explicitly wants a history or postmortem. If process
  context helps, collapse it into a small appendix.
- Before writing HTML, get the conceptual model straight: what the entities are, what each
  relationship actually means (containment vs dependency vs reference vs sequence), and
  which invariants matter. A diagram that encodes a wrong relationship is worse than prose.
  When multiple relationship types appear in one diagram, differentiate them visually and
  add a legend.
- Lead with the answer. Whatever the layout, the core thesis should be understood within
  the first screenful.

## Design quality

This is the part that separates a good artifact from generated-looking slop. Principles,
not a formula:

- **Commit to one aesthetic direction** chosen for the content and audience — e.g. calm
  editorial light, technical dark, print-like report, playful. Execute it consistently:
  one type scale, one spacing rhythm, one corner radius, one shadow style, a small
  deliberate palette. Vary the direction between artifacts; don't converge on a house
  style.
- **Typography does most of the work.** Strong size contrast between levels (not
  everything 13–15px), generous line-height for reading text, tight letter-spacing only
  on large headings, tabular/monospace numerals for data. System font stacks are fine;
  pick weights deliberately.
- **Whitespace over boxes.** Prefer spacing and alignment to separate content. Reach for
  borders, cards, and panels only when grouping genuinely needs enclosure. Nested
  box-in-box-in-box layouts are a smell.
- **Color is information.** Use accent colors to encode meaning (states, series,
  good/bad) and almost nowhere else. Ensure readable contrast in whatever scheme you
  pick. Semantic colors must stay consistent throughout the artifact.
- **Charts and diagrams get real design attention:** direct-label instead of relying on
  legends where possible, gridlines lighter than data, axes labeled with units, data ink
  dominant over decoration. If a dataviz/design skill is available in the environment,
  apply its palette and mark guidance.
- **Avoid the generated look:** emoji as section bullets, badge/pill clutter, gradient
  blob backgrounds, glassmorphism blur, uniform card grids of three, centered-everything,
  decorative icons that carry no meaning. None of these are banned tools — but each must
  earn its place.
- **Density with hierarchy.** Don't dilute content into fragments-per-card; a well-set
  paragraph or a dense labeled table often beats six cards. Use progressive disclosure
  (`<details>`, tabs, toggles) for depth that would slow the first read.

## Interaction

Add interaction only where it reveals structure that's hard to show statically: toggling
scenarios or layers, focusing a path through a diagram, filtering many items, comparing
before/after. Essential information must be readable with zero interaction. Controls must
be real focusable elements with visible focus states, deterministic, and fully local.

## Engineering requirements

- Standalone file: inline CSS/JS, no external network dependencies, no dev server.
- Semantic HTML; responsive down to mobile widths; respect `prefers-reduced-motion`;
  print-friendly enough to save as a PDF.
- SVG for diagrams whose spatial relationships must be exact. For hand-positioned SVG,
  verify geometry before finalizing: every label/node fits inside its container with
  padding, nothing overlaps, lines don't cut through node interiors. Overflow is a hard
  blocker — resize, wrap, or reposition until it fits.
- Charts drawn from data should be *computed* from the data values (even if hand-written
  into coordinates) — never eyeballed shapes that contradict the numbers.

## Output contract

- Write repo artifacts to `<repo-root>/artifacts/html/<filename>.html` (create the
  directory if needed); fall back to `.context/` or cwd only when there is no repo.
- Ticket-attached artifacts: filename starts with the ticket ID, e.g. `F123-flow-map.html`;
  use descriptive suffixes when a ticket has several artifacts.
- When iterating, overwrite the same file in place — no timestamped or numbered copies
  unless the user asks for versions.
- Before replying, verify the file exists and is non-empty (open it in a browser tool if
  one is available and the artifact is non-trivial), placeholders are gone, the thesis is
  visible immediately, diagrams are conceptually and geometrically correct, and
  interactions work.
- `assets/template.html` is an optional minimal skeleton (reset, print/reduced-motion
  handling). It carries no visual design on purpose — the design is yours to make.

## Final response format

Briefly explain what the artifact shows, then end with the absolute path in a fenced code
block, with nothing after it:

```text
/absolute/path/to/file.html
```

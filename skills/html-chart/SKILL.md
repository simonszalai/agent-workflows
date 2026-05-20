---
name: html-chart
description: Create a standalone, modern, minimal, interactive HTML visual explainer from the current conversation thread or provided context. Use when the user asks to visualize, explain, summarize, map, chart, diagram, synthesize, or make a high-bandwidth HTML artifact from discussion, plans, concepts, decisions, tradeoffs, workflows, research, or complex ideas; especially when they want an absolute path to the generated HTML file.
---

# HTML Chart

Create a single self-contained `.html` document that turns available context into a concise, complete, visually structured explainer optimized for fast human comprehension.

The goal is **not** a pretty Markdown export and not a transcript of the conversation. The goal is a high-bandwidth cognition surface: clear hierarchy, spatial grouping, diagrams, comparison surfaces, progressive disclosure, and lightweight interaction that helps a reader understand the **final system, decision, or concept** faster than reading the thread.

## Core principle: outcome over process

When the source is a long conversation, do **not** document the whole path taken to reach the conclusion unless the user explicitly asks for a history or postmortem. Most HTML explainers should present the **arrived-at model** as if it were a clean reference artifact.

Prioritize:

- The final canonical system/model/decision.
- The key entities and their definitions.
- The exact relationships between entities.
- The rules, invariants, and constraints.
- The few caveats/open questions that matter for using the model correctly.

Avoid by default:

- “First we thought X, then we corrected Y...” chronology.
- Conversation recap sections.
- Repeated caveats from earlier false starts.
- Process-heavy workflow narrative when the user needs a clean system explanation.

If historical context is useful, put it in a short collapsed `<details>` appendix titled “How we got here” — never make it the spine of the artifact.

## Output contract

- Generate an actual `.html` file; do not stop at a Markdown summary.
- Make the file standalone: inline CSS and JavaScript; avoid external network dependencies.
- Write repo artifacts to `artifacts/html/<filename>.html` when working in a git repo; create the directory if needed. Only fall back to `.context/` or the current directory when there is no repo/artifacts location available.
- If the artifact is attached to a ticket, the filename must start with the ticket prefix, e.g. `F123-flow-map.html`. If there are multiple artifacts for the same ticket, use a descriptive suffix such as `F123-data-model.html` or `F123-mobile-layout.html`.
- When iterating on an existing artifact, overwrite the same `artifacts/html/<filename>.html` file directly. Do not create timestamped, numbered, or duplicate versions unless the user explicitly asks for separate versions.
- End the final response with the absolute path in a fenced code block, and put nothing after that code block.
- If browser tools are available and the task is non-trivial, open or inspect the file once before final response. If not, at minimum verify the file exists and is non-empty.

## Workflow

### 1. Gather and distill the context

Use the visible conversation thread as the primary source. Also load any directly referenced local files, attached artifacts, prior generated plans, or previous HTML artifacts if they are needed to understand or improve the output. Do not ask the user to restate context unless the source material is truly unavailable.

Extract two layers:

1. **Final outcome layer** — the canonical model, entities, relationships, rules, decisions, constraints, outcomes.
2. **Source/evidence layer** — why those decisions are true, corrections made, caveats, uncertain inferences.

Render the final outcome layer prominently. Render source/evidence only when it helps trust or prevents misuse.

Mark uncertain inferences as inferences. Do not invent facts to make the visualization look complete.

### 2. Build an information model before drawing

Before writing HTML, make the artifact’s conceptual model explicit in your own reasoning:

- What are the entity types?
- Which things are containers vs line items vs properties vs states vs events?
- Which relationships mean containment, dependency, rollup, reference, snapshot, capability, or lifecycle transition?
- Which fields are columns/properties rather than child entities?
- What are the invariants that must never be violated?

The final diagram must respect this model. **Correctness beats visual cleverness.** If a relationship has a different meaning, show it with a different visual encoding and a legend.

Recommended relationship encodings:

- Solid line/arrow: parent-child containment or rollup.
- Dashed line: snapshot/copy-from/template source.
- Dotted line: indirect capability or eligibility.
- Double-line or highlighted path: active calculation path.
- Group boundary/lane: category, layer, or ownership boundary.

### 3. Choose the best visual model

Select visual structures based on the information shape, not habit:

| Information shape | Use |
| --- | --- |
| Final system ontology | Entity map, layered diagram, glossary cards |
| Architecture or dependencies | Node-link SVG, layered dependency grid, ownership map |
| Hierarchy or rollup | Tree, nested lanes, expandable node graph |
| Pricing/cost rules | Calculation ladder, active-path diagram, formula cards |
| Template vs instance | Split-pane snapshot map, before/after copy diagram |
| Capability/eligibility | Indirect relationship map, matrix, dependency chain |
| Tradeoffs or options | Comparison matrix, scorecards, decision tree |
| Process/lifecycle | Timeline, swimlane, state machine — only when lifecycle is central |
| Many related concepts | Searchable/filterable cards or concept index |
| Before/after change | Split panels, delta table, annotated callouts |

Use 3-6 complementary sections rather than one overloaded mega-diagram. Every section should answer a distinct comprehension question.

### 4. Design for high-bandwidth comprehension

Apply these rules aggressively:

- Put the answer above the fold: title, one-sentence thesis, and 3-5 key takeaways.
- Make it a reference artifact: a reader should understand the final system without reading the conversation.
- Replace walls of prose with visual chunks: cards, lanes, matrices, callouts, SVG diagrams, and concise labels.
- Use progressive disclosure for details: concise visible summary, expandable evidence/details.
- Encode relationships spatially: proximity for related items, arrows/lines for dependencies, columns for contrast, lanes for categories.
- Use a restrained visual system: neutral canvas, one accent palette, consistent radius, spacing, and type scale.
- When using semantic badges/tags, make them content-sized with consistent horizontal/vertical padding. Do not use arbitrary fixed widths that leave empty space around short labels. Tags with equal semantic weight (for example estimate vs actual cost) should have comparable visual intensity; do not make one filled/strong and the other pale/secondary unless that difference is meaningful.
- Make scanning easy: strong headings, short labels, bold only for signal, no decorative noise.
- Keep it concise but complete: include every material concept; remove filler and repeated phrasing.
- Optimize for information transfer and likelihood of being read, not minimal HTML length.

### 5. Add sophisticated interaction only where it improves understanding

For complex concepts, at least one interaction should reveal structure that would be hard to read statically. Good interactions:

- Click a diagram node to show definition, fields, relationships, and examples.
- Toggle diagram layers such as structure / snapshots / pricing / capability.
- Highlight a rollup path or dependency chain.
- Search/filter when there are many cards or concepts.
- Tabs for alternate views of the same system, not unrelated hidden sections.
- Expand/collapse details for caveats, examples, evidence, or open questions.
- Copy buttons for commands, paths, IDs, formulas, or generated prompts.

Interaction requirements:

- Essential information must still be visible without interaction.
- Controls must be accessible real buttons/inputs with visible focus states.
- Interactions must be deterministic and local; no external libraries or network calls.
- A chart is “interactive” only if the interaction improves comprehension, not if it merely hides text.

### 6. Build the HTML

Start from `assets/template.html` when useful. Replace all placeholder content with task-specific content and remove unused sections.

Before writing, choose the stable output path:

1. Find the repo root with `git rev-parse --show-toplevel` when available.
2. Use `<repo-root>/artifacts/html/` as the output directory and create it if missing.
3. Reuse the existing artifact path when the user is iterating. Overwrite it in place.
4. For ticketed artifacts, ensure the basename starts with the ticket prefix.


Implementation requirements:

- Use semantic HTML (`header`, `main`, `section`, `article`, `details`, `button`, `figure`, `figcaption`).
- Prefer SVG for diagrams where relationships must be spatially correct; use HTML/CSS cards for supporting summaries.
- **Never allow diagram elements to protrude from their containers.** For lane/grid diagrams, every node, badge, label, halo, and callout must have explicit coordinates and dimensions that stay inside its containing lane/card with visible padding. If a node cannot fit, widen the container, shrink the node, wrap text, or move the node; do not accept overflow as a tradeoff.
- For manually positioned SVG, create a small geometry check before finalizing: define container boxes and child boxes, then verify each child box is fully contained by its parent and no node boxes overlap. Treat any failure as a hard blocker and regenerate the layout.
- Keep CSS in a `<style>` block and JS in a `<script>` block.
- Support mobile and desktop with responsive CSS Grid/Flexbox/SVG scaling.
- Use accessible controls: real buttons, visible focus states, `aria-selected`, `aria-controls`, `aria-expanded`, and `aria-live` where relevant.
- Respect `prefers-reduced-motion`.
- Use print-friendly styles so the artifact can be saved as PDF.
- Never depend on a running dev server.

### 7. Quality check before final

Before replying, inspect the generated file for:

- No template placeholders remain.
- The main thesis and key takeaways are visible immediately.
- The artifact explains the **final outcome**, not the whole conversation process.
- The visual structures match the actual information shape.
- Diagrams are conceptually correct: no columns shown as child entities, no references shown as containment, no lifecycle shown as ownership.
- Diagram geometry is valid: no node/card/badge/callout protrudes outside its lane/container, no node overlaps another node, and relationship lines do not cross through node interiors.
- Relationship line styles have a legend when multiple relationship types appear.
- Interactions work without external dependencies.
- The file exists, is non-empty, and the absolute path is copyable.

## Final response format

```text
Created the interactive HTML explainer.

`/absolute/path/to/file.html`
```

The path must be the last thing in the response.

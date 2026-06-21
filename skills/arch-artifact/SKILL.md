---
name: arch-artifact
description: Create a polished, fully self-contained, dark "high-tech" (Linear / xAI / SpaceX / Vercel vibe) single-file HTML artifact that explains a software architecture, system design, data model, or technical plan. Use when the user asks to visualize, diagram, map, or make a shareable HTML page of an architecture / design / technical plan, or wants an architecture explainer with a sleek dark aesthetic. Produces static HTML+CSS that renders anywhere (sandboxed preview panes, file://) — no CDN, no web fonts, no JS-gated content.
---

# Architecture Artifact

Build a **single, self-contained `.html` file** that explains an architecture or technical design as a crisp reference document, in a refined **dark high-tech** aesthetic (Linear/Vercel restraint, xAI/SpaceX starkness). Optimized for fast comprehension and for looking genuinely premium.

This skill is opinionated where the generic `html-chart` skill is not: (1) a specific dark high-tech design system, and (2) **hard self-containment** so the artifact never renders blank in a sandboxed preview.

Default output path: `<repo>/artifacts/html/<name>.html` (create dir if needed; fall back to `.context/` or cwd if no repo). If tied to a ticket/epic, prefix the filename with its id (e.g. `E0013-architecture.html`). End your final reply with the absolute path in a fenced block.

---

## Rule 0 — Self-contained, or it's broken (NON-NEGOTIABLE)

Architecture artifacts are viewed in **sandboxed preview panes and `file://`** that block external scripts, JS modules, and network fonts. A page that renders content via a runtime library (Mermaid, D3, Chart.js, marked) **shows a blank box**. This has bitten us — do not repeat it.

**DO**
- Inline **all** CSS in one `<style>` in `<head>`. Inline any JS in `<script>`.
- Draw every diagram with **static HTML/CSS or inline `<svg>`** — never a runtime diagram library.
- Use a **system font stack** (below). No `@import`/`<link>` to Google Fonts or any CDN.
- Make **all content visible with JS disabled.** JS is progressive enhancement only (a toggle, a copy button) — never the thing that renders the content. Use `<details>`/`<summary>` for collapse-without-JS.
- Include `<meta charset="utf-8">` and the viewport meta.

**DON'T**
- `<script type="module">` or `import()` (blocked by `script-src 'self'`).
- `<script src="https://cdn...">`, `<link rel="stylesheet" href="http...">`, `@import url(...fonts...)`.
- Gate readable content behind `DOMContentLoaded` rendering.
- Rely on `localStorage` for first render.

**Acceptance:** open it from `file://` with JS off — the full document, including diagrams, must be there.

---

## The aesthetic — dark high-tech design system

Fused from Linear (refined warm-dark + indigo + near-invisible borders), xAI/SpaceX (stark black, uppercase thin eyebrows, big negative space, mono), Vercel/Geist (neutral ramp, mono for data, tight tracking). Use these tokens verbatim:

```css
:root{
  /* canvas & surfaces — elevate by LIGHTNESS, not shadow (shadows vanish on black) */
  --bg-canvas:#0a0a0a; --bg-base:#111114; --bg-raised:#18181c; --bg-overlay:#222227;
  /* borders — hairline, low-contrast */
  --bd-subtle:rgba(255,255,255,.06); --bd:rgba(255,255,255,.10); --bd-strong:rgba(255,255,255,.18);
  /* text — off-white, NEVER pure #fff (halation/glare on black) */
  --tx:#ededef; --tx-2:#a1a1a8; --tx-3:#62626b; --tx-inv:#0a0a0a;
  /* accent — ONE cool accent, desaturated; indigo default (Linear). For xAI/SpaceX mode use #fff. */
  --ac:#5e6ad2; --ac-hi:#7880e0; --ac-mut:rgba(94,106,210,.14);
  --font-sans:"Geist","Inter",ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
  --font-mono:"Geist Mono","JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;
  --r-sm:4px; --r:6px; --r-lg:10px; --r-xl:14px; --r-full:9999px;
  --glow:0 0 24px rgba(94,106,210,.22);            /* interactive/emphasis only */
  --elev:0 1px 0 rgba(255,255,255,.04) inset, 0 8px 30px rgba(0,0,0,.45);
}
```

Type & feel rules:
- **Body `font-weight:400` minimum on dark** (300 vanishes). Headings 500–600; reserve 700 for display numbers.
- **Tracking:** display/H1 `letter-spacing:-.03em`; H2/H3 `-.02em`; **eyebrow/overline labels UPPERCASE `letter-spacing:.12em`** (the SpaceX move) — use eyebrows for section kickers, never for body or H1.
- **Mono for all technical tokens**: identifiers, table/IDs, numbers, file paths, node labels.
- **Generous negative space.** Section gaps 40–64px. Don't crowd.
- **Restraint with color**: accent is *punctuation* (one output box, one link, one active ring), not fill everywhere. Use **one subtle accent glow** for the single most important element max. Encode at most one dimension with color.
- **Borders are hairlines** (`--bd`). Prefer surface-lightness steps over visible dividers.
- Near-black canvas `#0a0a0a`, not `#000` (softer). Surfaces step up in lightness for elevation.

Two presets: **Indigo** (default; `--ac:#5e6ad2`) for product/design feel; **Mono** (`--ac:#ffffff`, sharper `--r:4px`/`0`) for a starker xAI/SpaceX feel. Pick one per artifact.

---

## Structure (outcome over process)

Present the **arrived-at** design as a clean reference — not the conversation that produced it. Top to bottom:

1. **Eyebrow** (uppercase tracked) → **H1** → **one-sentence thesis** → 3–5 **takeaway cards**. The answer is above the fold.
2. **3–6 sections**, each answering one comprehension question, each ideally anchored by one diagram or table.
3. End with **invariants / open decisions** if relevant. Put any history in a collapsed `<details>` "How we got here" — never the spine.

---

## Diagrams

Choose by shape: **CSS-box** primitives for rectangular/lane/layer/grid layouts (robust, text reflows); **inline SVG** for arbitrary paths / node-link graphs / DAGs (set `viewBox` + `width:100%`). Hybrid is fine. Never a runtime lib.

Provide the reusable primitives (in `assets/template.html`): `.flow` (vertical box stack), `.lanes` (parallel tracks), `.chiprow` (horizontal pipeline), `.er` (entity cards), `.rail` (milestone columns), `.box`/`.box.out`/`.box.em`.

**Geometry rules (correctness beats cleverness):**
- **Connectors must be centered and colinear.** This is the #1 bug. A connector element (`↓`/`→`) must be **full-width with `text-align:center`** — do NOT rely on `align-self:center`, which silently does nothing unless the parent is `display:flex`. All vertical connectors in a column must sit on one axis.

  ```css
  .flow{display:flex;flex-direction:column}
  .conn{text-align:center;color:var(--tx-3);font-size:18px;line-height:1;margin:8px 0;user-select:none}
  ```
  (If you keep nested groups, make them `display:flex;flex-direction:column` too — but `text-align:center` is the real fix and works in any parent.)
- **No node overflow.** Every node/badge/label stays inside its container with padding. Give nodes a min-height; truncate or wrap long labels; never let text spill past the box edge (it misaligns connectors).
- **Legend** whenever line styles encode meaning (solid = data flow, dashed = async/optional, thick = dependency).
- **≤ ~15 nodes per diagram.** Split a mega-diagram into scoped views (overall / data flow / deployment).
- **Direction always shown** (arrowhead or label). Label connectors mid-path, not at endpoints.
- Add `role="img"` + `aria-label` (or `<figcaption>`) to each diagram.

---

## Glossary tooltips — explain non-obvious terms inline (GENERIC RULE)

Readers won't know every acronym/term. For any term a non-expert in the room wouldn't instantly know (e.g. CRPS, AUC, Brier, isotonic/Platt, Murphy decomposition, idempotent, MMR, p99, CRDT…):

- **Spell out acronyms on first use**: `CRPS (Continuous Ranked Probability Score)`.
- **Mark the term** with a **subtle dashed underline + a small superscript `?`** and attach a **CSS-only hover/focus tooltip** giving a plain-language definition *and how it works in one line*. CSS-only (no JS) so it survives static/sandboxed rendering. Keyboard-accessible (`tabindex="0"` + `:focus-visible`).
- **The popover must never clip off-screen.** Pure CSS can't read where the term sits, so a term-anchored (`position:absolute`) tip overflows for right-side terms and on narrow panes. **Pin the popover to the viewport** (bottom-center) and cap its width to `calc(100vw - 28px)` — guaranteed on-screen at any width, for any term, with zero per-term tagging. (Don't place the popover inside a `transform`ed ancestor, or `position:fixed` anchors to it instead of the viewport.)

```css
.term{border-bottom:1px dashed var(--bd-strong);cursor:help}
.term::after{content:"?";font:700 .58em/1 var(--font-sans);vertical-align:super;color:var(--ac);margin-left:2px}
/* viewport-pinned popover — never clips. Do NOT anchor under the term: pure CSS can't measure its position. */
.term>.def{position:fixed;left:50%;bottom:20px;transform:translateX(-50%) translateY(6px);
  width:min(440px,calc(100vw - 28px));max-height:42vh;overflow:auto;
  background:var(--bg-overlay);border:1px solid var(--bd);border-radius:10px;padding:13px 15px;
  font:400 13px/1.55 var(--font-sans);letter-spacing:normal;text-transform:none;color:var(--tx-2);
  box-shadow:var(--elev);opacity:0;visibility:hidden;transition:opacity .14s ease, transform .14s ease;z-index:60;pointer-events:none}
.term>.def b{color:var(--tx)}
.term:hover>.def,.term:focus-visible>.def{opacity:1;visibility:visible;transform:translateX(-50%) translateY(0)}
```
```html
<span class="term" tabindex="0">CRPS<span class="def"><b>Continuous Ranked Probability Score.</b> Generalizes the Brier score to a whole predicted distribution — the sum of per-threshold Brier scores across the ladder. Lower is better; proper.</span></span>
```

Keep definitions to ~1–2 sentences. Don't tooltip common words — only genuinely non-obvious ones, and only the **first** prominent occurrence.

---

## Workflow

1. Distill the source into the final model: entities, relationships, rules, the few caveats that matter.
2. Pick preset (Indigo vs Mono) and the 3–6 sections.
3. Build from `assets/template.html` (copy it, replace content, delete unused primitives).
4. Mark non-obvious terms with glossary tooltips; spell out acronyms.
5. Verify (below), then write the file and return its absolute path.

## Quality checklist (before returning)

- [ ] **Renders from `file://` with JS disabled** — full content + diagrams present (Rule 0).
- [ ] No `<script src>`, no `type="module"`, no CDN/`@import`/web-font/external `url()`.
- [ ] **All connectors centered and colinear** (no left-hugging `↓`); no node/badge overflow at desktop *and* narrow widths.
- [ ] Non-obvious terms have a `?` tooltip; acronyms spelled out on first use.
- [ ] Glossary popovers **never clip off-screen** at any width — viewport-pinned + width-capped, not term-anchored (test a right-edge term on a narrow pane).
- [ ] Dark tokens used; text is off-white not `#fff`; no `font-weight:300` under 24px; accent used sparingly.
- [ ] Thesis + takeaways above the fold; outcome (not process) is the spine.
- [ ] Print-friendly (`@media print`) and `prefers-reduced-motion` respected.
- [ ] No template placeholders remain.

## Template

Start from `assets/template.html` (next to this file): a complete dark high-tech, self-contained example demonstrating every primitive, correctly-centered connectors, and the glossary tooltip.

## Sources (design language)

- Linear brand & 2024 dark refresh — linear.app/brand, linear.app/now/behind-the-latest-design-refresh
- Vercel Geist design system (colors, Geist/Geist Mono, tracking) — vercel.com/geist/colors
- Dark-mode legibility (near-black canvas, off-white text, weight, elevation-by-lightness) — Smashing Magazine "Inclusive Dark Mode"; LogRocket dark-mode best practices
- Accessible color on dark — Stripe "Designing accessible color systems"
- All-caps tracking — pimpmytype.com/spacing-all-caps

# Foundations — Static Visual Fundamentals

**Part of [Interface Craft](SKILL.md).**

The composition rules that hold whether or not anything moves. **Get these right before
reaching for polish** — [shipping-polished-ui.md](shipping-polished-ui.md) layers motion and
depth on top of solid fundamentals; it cannot rescue broken ones. Squint at any screen: if you
can't tell where to look, what groups, and what's interactive, no easing curve will save it.

These are medium-agnostic — web, mobile, desktop, print. Apply them every time code touches UI.

---

## The 10 principles

### 1. Whitespace
Space is a design element, not absence. More whitespace signals quality and importance.
Generous padding *inside* elements, generous margins *between* them. Group related items
tightly; separate unrelated items with space. When in doubt, add more — cramped always reads
cheap. **Catch:** edge-to-edge cramming, equal spacing everywhere (monotony), text walls.

### 2. Visual hierarchy
Not everything can be important. Every screen has exactly one primary focal point. Use size,
weight, color, and position deliberately; three levels max (primary/secondary/tertiary).
De-emphasize secondary content as hard as you emphasize primary. If everything is bold, nothing
is. **Catch:** multiple elements competing at one level, no entry point, hierarchy inflation.

### 3. Alignment
Invisible lines connect elements. Every element aligns to at least one other. Use one grid;
never place things arbitrarily. Left-align text by default (LTR); center only with intent.
Prefer optical over mathematical alignment — trust the eye. **Catch:** "almost" aligned (off a
few px), mixed alignment systems, centered long-form body text.

### 4. Contrast
Difference creates meaning — and it's not just color (size, weight, shape, texture, density).
High contrast for primary content, low for secondary. The most important thing gets the most
contrast against its surroundings. **Squint test:** if elements blur together, contrast is
insufficient. **Catch:** light-gray-on-white body text, interactive elements that don't stand
out, headers barely distinct from body.

### 5. Rhythm & repetition
Consistent patterns create comfort. Use a spacing scale — don't invent values (4, 8, 12, 16,
24, 32, 48, 64). If cards look one way, all cards look that way. Equal gaps between repeated
elements. Rhythm breaks must be intentional. **Catch:** random spacing (13px here, 17px there),
inconsistent treatment of similar elements, uneven list/grid gaps.

### 6. Proximity
Things close together are read as related. A label sits closer to its field than to the
previous field; a section header closer to its content than to the section above. Use proximity
before dividers — space usually suffices. **Catch:** labels equidistant between two fields,
dividers where spacing would do, headers floating with equal space above and below.

### 7. Balance
Distribute visual weight intentionally. Symmetry for formal/stable/trustworthy; asymmetry for
dynamic/modern. Larger/darker/more-complex elements carry more weight. Don't leave one side
heavy and the other empty. **Catch:** all heavy elements on one side, one area packed and
another barren, internally lopsided components.

### 8. Consistency
Same thing, same way, every time. Same action → same appearance. Same content type → same
treatment. Pick spacing/color/type/radius values and reuse them. Break consistency only to draw
attention to something genuinely different. **Catch:** one action styled differently in
different places, arbitrary radius mixing, color meaning different things in different contexts.

### 9. Scale & proportion
Size relationships communicate importance. Use a type scale with consistent ratios (1.25×,
1.333×, 1.5×). Size jumps must be noticeable — 14px and 15px aren't distinct levels. Larger
elements need proportionally more padding. Icons match the optical size of adjacent text.
**Catch:** type sizes too similar to read as hierarchy, tiny padding in large containers,
mismatched icon/text sizing.

### 10. Unity & cohesion
Every element looks like it belongs to one family. Establish a limited visual language —
few colors, shapes, spacing values, type styles. When adding something new, *derive* it from
existing patterns rather than inventing. It should feel like one designer made it. **Catch:**
elements imported from a different design system, too many competing styles, mixed shape
language (round buttons + sharp cards).

---

## The squint test

Squint (or step back) until you can't read text. You should still see:

1. **Where to look first** — hierarchy works
2. **What groups together** — proximity works
3. **What's interactive vs. static** — contrast works
4. **An overall sense of order** — alignment and rhythm work

If any fails, the fundamentals need work — no amount of polish will fix them.

---

## Professional-UI gotchas (the cheap tells)

Frequently-overlooked details that make otherwise-fine UI look amateur:

- **No emoji as icons.** Use a single SVG icon set (Heroicons, Lucide, Simple Icons) at a
  consistent size (e.g. 24×24 viewBox, `w-6 h-6`). Mixed icon families/weights is a tell.
- **Cursor + hover feedback.** Every clickable element gets `cursor-pointer` *and* a visible
  hover response (color/shadow/border). No hover affordance = "is this even a button?"
- **Never zoom/scale on hover.** No `scale()` or `transform` growth on `:hover`, ever — not
  even a non-reflowing one. It reads as cheap and twitchy. Give hover feedback with color,
  opacity, shadow, or border instead. (Scaling is fine for *click* feedback: a press-down
  `:active` `scale(0.98)` is transform-only, layout-safe, and encouraged — see
  [shipping-polished-ui.md](shipping-polished-ui.md) Rule 7. The distinction is hover = no
  scale; press = scale down.)
- **Correct brand logos.** Pull official SVGs (Simple Icons); don't guess paths.
- **Light/dark contrast — actually test both.** Body text ≥ 4.5:1 (e.g. slate-900 `#0F172A`
  on light, never slate-400 for body). Glass/transparent surfaces need real opacity in light
  mode (`bg-white/80`+, not `/10`). Borders must be visible in both modes.
- **Floating elements need edge spacing** (e.g. a floating navbar at `top-4 left-4 right-4`,
  not flush `top-0`), and fixed elements must not cover content — reserve their height.
- **Consistent container widths** — pick one `max-w` and stick to it.
- **Readable type** — body ≥ 16px on mobile, line-height 1.5–1.75, line length 65–75 chars.

---

## Pre-delivery checklist

Before shipping UI, verify:

**Fundamentals (squint test)**
- [ ] Clear primary focal point; eye knows where to start
- [ ] Related things close, unrelated apart; everything on an alignment line
- [ ] Primary content pops, secondary recedes; spacing follows one scale
- [ ] Everything feels like one family

**Visual quality**
- [ ] No emoji icons; one consistent icon set; correct brand logos
- [ ] Hover states don't cause layout shift
- [ ] Shadows use the layered recipe, not one muddy blur (see polish Rule 6)

**Interaction**
- [ ] All clickable elements have `cursor-pointer` and clear hover feedback
- [ ] Hover feedback uses color/opacity/shadow/border — **never** `scale`/zoom on hover
- [ ] Transitions use the house easing/duration tokens, never the default `ease` (polish Rule 1)
- [ ] Visible focus states for keyboard nav
- [ ] Pressed elements feel tactile (polish Rule 7)

**Light/dark**
- [ ] Body text ≥ 4.5:1 in both modes; glass/borders visible in both; both tested

**Layout & responsive**
- [ ] No content hidden behind fixed navbars; floating elements spaced from edges
- [ ] Works at 375 / 768 / 1024 / 1440px; no horizontal scroll on mobile

**Accessibility**
- [ ] Images have alt text; inputs have labels; color isn't the only signal
- [ ] `prefers-reduced-motion` respected (polish Rule 9)

---

## When principles conflict

Resolve in this order: **Hierarchy → Contrast → Proximity → Alignment → Consistency →
Whitespace → Rhythm → Balance → Scale → Unity.** The user must first know where to look and be
able to perceive the information; cohesion polish comes last.

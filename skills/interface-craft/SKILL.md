---
name: interface-craft
description: "The one UI/UX skill: foundations, polished-UI craft, storyboard animation, DialKit, design critique. Use whenever code touches UI. Triggers on: UI, UX, interface, component, layout, design, hierarchy, whitespace, spacing, alignment, contrast, typography, color, shadow, depth, accessibility, responsive, dark mode, animate, animation, transition, storyboard, entrance, motion, spring, easing, timing, tokens, design tokens, blur, drag, snap, momentum, tactile, press, haptics, reveal, FLIP, dialkit, sliders, controls, tune, tweak, critique, review, feedback, audit, improve, polish, refine, redesign."
argument-hint: "[description, file path, or sub-skill name]"
---

# Interface Craft

**The single UI skill — one coherent set of principles that produce great UI in any project.**
No competing skills, no contradictions. It runs in three layers, foundations first:

1. **Foundations** — the static composition that must be right before anything else.
2. **Polish** — the motion, depth, and tactility that make it feel premium.
3. **Tooling** — readable animation structure, live tuning, and systematic critique.

Animation/critique methodology by Josh Puckett; foundations and polish rules curated alongside.

---

## Skills

| Skill | When to Use | Invoke |
| --- | --- | --- |
| [Foundations](foundations.md) | **Start here for any UI work.** Static fundamentals (hierarchy, whitespace, alignment, contrast, rhythm, proximity, balance, scale, unity), the professional-UI gotchas, and the pre-delivery checklist. Get these right *before* polish. | `/interface-craft foundations` or any "design / lay out / review this UI" request |
| [Shipping Polished UI](shipping-polished-ui.md) | The craft layer — easing/shadow/duration tokens, drag physics, snap points, blur entrances, layered shadows, tactile press, grid reveals, state-driven design. Reach for it once foundations are solid and the goal is "make it feel premium." | `/interface-craft polish` or ask to make UI feel polished/premium |
| [Storyboard Animation](storyboard-animation.md) | Writing or refactoring multi-stage animations into a human-readable DSL | `/interface-craft storyboard` or describe an animation |
| [DialKit](dialkit.md) | Adding live control panels to tune animation/style values | `/interface-craft dialkit` or mention dials/sliders/controls |
| [Design Critique](design-critique.md) | Systematic UI critique of a screenshot, component, or page | `/interface-craft critique` or paste a screenshot for review |

## Quick Start

### Foundations (do this first)

Squint at the screen until you can't read text. You should still see where to look first, what
groups together, and what's interactive. If not, fix composition before any motion — polish
cannot rescue broken fundamentals. Full principles, gotchas, and checklist in
[foundations.md](foundations.md).

### Storyboard Animation

Turn any animation into a readable storyboard with named timing, config objects, and stage-driven sequencing:

```tsx
/* ─────────────────────────────────────────────────────────
 * ANIMATION STORYBOARD
 *
 *    0ms   waiting for scroll into view
 *  300ms   card fades in, scale 0.85 → 1.0
 *  900ms   heading highlights
 * 1500ms   rows slide up (staggered 200ms)
 * ───────────────────────────────────────────────────────── */

const TIMING = {
  cardAppear:  300,   // card fades in
  heading:     900,   // heading highlights
  rows:        1500,  // rows start staggering
};
```

See [storyboard-animation.md](storyboard-animation.md) for the full pattern spec.

### DialKit

Generate live control panels for tuning values in real time:

```tsx
const params = useDialKit('Card', {
  scale: [1, 0.5, 2],
  blur: [0, 0, 100],
  spring: { type: 'spring', visualDuration: 0.3, bounce: 0.2 },
})
```

See [dialkit.md](dialkit.md) for all control types and patterns.

## Sub-Skill Routing

When the user invokes `/interface-craft`:

1. **With `foundations` argument, or any "design / lay out / structure / review this UI" request** → Load and follow [foundations.md](foundations.md)
2. **With `polish` argument, or any "make it feel premium/polished/tactile/iOS" request** → Load and follow [shipping-polished-ui.md](shipping-polished-ui.md)
3. **With `storyboard` argument or animation-related context** → Load and follow [storyboard-animation.md](storyboard-animation.md)
4. **With `dialkit` argument or control-panel-related context** → Load and follow [dialkit.md](dialkit.md)
5. **With `critique` argument, a pasted image, or review-related context** → Load and follow [design-critique.md](design-critique.md)
6. **With a file path** → Read the file, detect whether it needs foundations review, polish rules, storyboard refactoring, dialkit controls, or a design critique, and apply the appropriate skill
7. **With a plain-English description of an animation** → Use storyboard-animation to write it
8. **Building new UI from scratch** → Foundations first, then polish, then animation tooling
9. **Ambiguous** → Ask which skill to use

[shipping-polished-ui.md](shipping-polished-ui.md) is the source of truth for the house
easing/shadow/duration tokens; storyboard-animation and dialkit consume those tokens rather than
inventing their own.

## Design Principles

How great UI gets built here, in order:

1. **Foundations before polish** — Composition (hierarchy, spacing, alignment, contrast) is the
   ground floor. Motion and depth layer on top; they never substitute for it.
2. **Numbers, never adjectives** — "Smooth" is unbuildable; a specific curve at 280ms is. Define
   tokens once and forbid one-off values — that alone kills most of the "AI slop" look.
3. **Readable over clever** — Anyone should scan the top of a file and understand the animation
   sequence without reading implementation code.
4. **Tunable by default** — Every value that affects timing or appearance is a named constant,
   trivially adjustable (and live-tunable via DialKit).
5. **Data-driven** — Repeated elements use arrays and `.map()`, not copy-pasted blocks.
6. **Stage-driven** — A single integer state drives a sequence; no scattered boolean flags.
7. **Spring-first for physical motion** — Prefer spring physics for interactive/draggable motion;
   use the house cubic-bezier curves for duration-based CSS transitions.
8. **State-driven design** — A component is a system of states (idle/hover/pressed/loading/
   disabled/success), and you discover the missing ones by *building*, not speccing.
9. **Accessible polish** — Honor `prefers-reduced-motion`; favor transform/opacity on large
   surfaces. Polish that ignores these isn't polished.

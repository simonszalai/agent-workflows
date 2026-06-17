# Shipping Polished UI — 10 Rules

**Part of [Interface Craft](SKILL.md).** Adapted from "The 10 rules to ship truly polished UI."

Polish is not a feature you can prompt for. You can't type "make it premium and smooth" and
get there. The model is a phenomenal pair of hands, but the taste, the rules, and the hundred
tiny decisions are still yours. This doc is the system: concrete, numeric, reusable rules for
the *craft layer* — the motion, depth, and tactility that separate "an LLM built this" from "a
human with taste built this."

Each rule is given three ways where it helps: **the rule**, **how to prompt it**, and **how to
prep it in Figma**.

> **Lane.** This doc owns the *polish/motion craft* of [Interface Craft](SKILL.md), and assumes
> the static fundamentals in [foundations.md](foundations.md) are already solid — polish cannot
> rescue broken composition. For the readable storyboard structure of a multi-stage animation,
> use [storyboard-animation.md](storyboard-animation.md); to tune these values live, use
> [dialkit.md](dialkit.md); to audit a built screen against these rules, use
> [design-critique.md](design-critique.md).

---

## House motion tokens (define once, reuse everywhere)

These are the canonical easing + duration tokens for Interface Craft work. Every entrance,
hover, press, and reveal below inherits from this set — define the feel once and everything is
consistent. (Spring-driven motion uses Framer Motion springs per
[storyboard-animation.md](storyboard-animation.md); these CSS curves are for duration-based
transitions where a spring isn't available or isn't warranted.)

```css
:root {
  /* Easing — tuned by feel, not derived. A curve 0.02 off feels subtly wrong. */
  --ease-smooth: cubic-bezier(0.22, 1, 0.36, 1);   /* default for almost everything */
  --ease-out:    cubic-bezier(0.17, 1, 0.32, 1);   /* decorative entrances */
  --ease-spring: cubic-bezier(0.35, 1.55, 0.65, 1);/* badges, pops, overshoot */
  --ease-in-out: cubic-bezier(0.66, 0, 0.34, 1);   /* symmetric moves */

  /* Corner radius */
  --radius-sm: 6px;
  --radius-md: 12px;
  --radius-lg: 24px;

  /* Duration */
  --duration-fast:   150ms;
  --duration-normal: 200ms;
  --duration-slow:   280ms;

  /* Depth — layered light, never one blur (see Rule 6) */
  --shadow-card:
    0 1px 2px rgba(0, 0, 0, 0.05),       /* close drop  */
    0 2px 4px rgba(0, 0, 0, 0.02),       /* soft spread */
    0 0 0 0.5px rgba(0, 0, 0, 0.08);     /* hairline ring, not a border */
  --shadow-elevated:
    0 4px 8px  rgba(0, 0, 0, 0.02),      /* spread       */
    0 8px 12px rgba(0, 0, 0, 0.02),      /* wide ambient */
    0 2px 4px  rgba(0, 0, 0, 0.02),      /* mid          */
    0 1px 2px  rgba(0, 0, 0, 0.04),      /* contact      */
    0 0 0 0.5px #e0e0e0;                 /* hairline ring */
}
```

These aren't sacred numbers — they're tuned by feel. Nudge each until presses, reveals, and
entrances feel right. That tuning *is* the work.

---

## Rule 1: Easing is everything. The default ease is banned.

The single biggest difference between "an LLM built this" and "a human with taste built this"
is the easing curve — how movement starts, speeds up, and settles. The browser defaults
(`ease`, `ease-in-out`) scream generic. Never use them; use the house set above.

**Prompt it:** Never say "smooth." Give the exact curve: *"Use cubic-bezier(0.22, 1, 0.36, 1)
for all transitions, and a slight overshoot curve cubic-bezier(0.35, 1.55, 0.65, 1) for
anything that pops in, like a badge appearing with a tiny bounce."* Specificity is the whole
game.

## Rule 2: Define your design-system variables before you build a single component.

Polish reads as consistency, and consistency comes from a shared vocabulary: tokens. Define
colors, corner radius, durations, motion curves, and shadow stacks *before* any component.
Every state, hover, and dark-mode variant then pulls from the same set. Once these exist, the
model stops inventing one-off 13px radii and random 0.3s timings; the whole UI snaps into
rhythm.

**Prompt it:** Hand the model your variable block first and say *"use only these tokens, no
one-off values."* This one instruction kills 80% of the "AI slop" look.

**Figma prep:** Build Figma variables that mirror your tokens 1:1 (same names). Then design→build
is a translation, not a reinvention.

## Rule 3: For anything draggable, use real physics — not simple fades and slides.

A basic timed animation on a drag handle feels dead. Real interfaces have momentum, friction,
and resistance. Three things make a drag feel alive:

- **Velocity tracking**, smoothed over time, so a flick has weight.
- **Momentum on release** — keep moving and slow to rest, like sliding something across a table.
- **Soft boundaries** — at the edge, don't stop hard; stretch a little and spring back. That
  single touch is the difference between "web slider" and "iOS."

For values that can't be animated with a simple duration (counters, live numbers), use a spring
tuned for stiffness/bounce/weight instead of a fixed time.

**Prompt it:** Forget the jargon — describe the feel: *"Make the slider feel like a real
physical object, not a web input. When I flick it, it should keep gliding and slowly coast to a
stop on its own. When it hits the edge, it shouldn't stop dead — it should stretch a little and
spring back."* The model knows the physics; it just needs to know what you want it to feel like.

## Rule 4: Add snap points. Magnetic snapping is free haptics.

Hardware gives haptic clicks; on the web you fake the same satisfaction with snap points — as
the handle nears a meaningful value (a month boundary, a preset), it gently magnetizes to it.
The trick that makes it feel real is a **two-zone system**: a tight pull-in zone to snap in, and
a larger release zone to break free. Once snapped, you have to mean it to pull away. Pulse the
label when it catches for a micro flash of feedback. That tiny resistance reads, subconsciously,
as quality.

**Prompt it:** *"Add magnetic snap points at [these values]. Use a smaller pull-in zone and a
larger release zone so it locks and resists, and flash the label when it catches."*

## Rule 5: Entrances blur in. They never just fade.

A plain fade is the most overused, least premium entrance. Combine three things instead:

```
opacity:   0 → 1
translateY: 6px → 0
filter:    blur(2px) → blur(0)
duration:  ~280ms with --ease-smooth
```

No new easing here — the curve is just your smooth preset from Rule 1. That's the point of the
motion set: define the feel once and every entrance, hover, and reveal inherits it. The blur is
the secret ingredient — content *focuses* into place instead of flicking on.

**Prompt it:** *"Entrance = fade + 6px rise + a 2px blur that clears, ~320ms on the smooth
curve."*

**Figma prep:** Design the "before" frame explicitly (offset + blur effect) so the motion intent
is visible to anyone reading the file.

## Rule 6: One shadow is a sticker. Real depth is layered light.

A flat single-blur shadow is an instant tell. Physical objects cast several shadows at once: a
hairline where they meet the surface, a tight contact shadow, and a wide soft ambient. Use the
`--shadow-card` and `--shadow-elevated` presets above. Three things make them read as real, not
"default Material elevation":

1. **A hairline ring replaces the border.** The single biggest tell of a hand-made UI: the edge
   is defined by light (`0 0 0 0.5px`), not a 1px stroke.
2. **Opacities stay tiny — roughly 2–8%.** Heavy shadows look cheap. Depth is the sum of many
   faint layers, not one dark one.
3. **Stack several blurs at different sizes** — a tight one for the contact edge, a wider soft
   one for the ambient spread. The overlap of faint layers is what reads as real depth.

**Prompt it:** *"Don't use a single drop shadow. Stack a hairline ring instead of a border, a
tight contact shadow, and a wide soft ambient, all at very low opacity (2–8%): 0 1px 2px
rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.02), 0 0 0 0.5px rgba(0,0,0,0.08). Animate the whole
stack on hover."*

## Rule 7: Make everything tactile. Press should be felt.

Every interactive element gets a press response. The default is a subtle scale-*down* on press:

```css
.button:active { transform: scale(0.98); }  /* 0.98, not 0.9 — a firm press, not a collapse */
```

Buttons, swatches, tabs, footer rows — all of them. Combine with hover shifts and tooltips that
blur + lift in (never instant pop-in) and the whole surface starts to feel responsive to touch.

> **Hover vs. press — keep them distinct.** Scale belongs to *press*, never *hover*. A
> `scale(0.98)` on `:active` is click feedback on the pressed element itself — layout-safe and
> encouraged. But do **not** scale/zoom on `:hover` (see [foundations.md](foundations.md)); hover
> gets color/opacity/shadow/border only. Hover = no scale; press = scale down.

**Prompt it:** *"Every clickable element scales down slightly (to 98%) when pressed, using the
fast duration. Tooltips fade + lift 4px + clear a 2px blur, never appear instantly."*

## Rule 8: Reveal height the right way. No fake expand tricks.

`max-height: 9999px` is jittery and times wrong. Animate CSS grid rows instead:

```css
.reveal              { display: grid; grid-template-rows: 0fr;
                       transition: grid-template-rows .22s var(--ease-smooth); }
.reveal[data-open="true"] { grid-template-rows: 1fr; }
.reveal > *          { overflow: hidden; }
```

It animates to the content's real height, perfectly smooth, no guesswork. For an element that
moves *across* the layout (a card flying into a different container), use **FLIP** (First → Last
→ Invert → Play): measure where it starts, measure where it ends, jump it back to the start
visually, then animate to the end. Impossibly smooth, and it's just two position measurements.

**Prompt it:** *"Use the grid-template-rows: 0fr → 1fr technique for expand/collapse, not a
max-height hack. For the card moving between containers, use a FLIP animation."*

## Rule 9: Respect performance and accessibility, or it's not polished.

Polish includes people who prefer less motion. Every animation system honors
`prefers-reduced-motion`: animations collapse to instant, decorative loops stop entirely. For
smooth 60fps, favor the lightweight properties — **transform and opacity** — over heavy ones
(shadow stacks, height reveals). Heavier effects are worth it in small, deliberate moments; just
don't animate them across long lists or large surfaces.

**Prompt it:** *"Honor reduced-motion preferences everywhere. Favor movement and fade for
anything on long lists or large surfaces."*

## Rule 10: State-driven design is the actual job.

The one nobody tells you, and the most important. A component is not a picture — it's a system
of states. A button isn't "a button," it's idle / hover / pressed / loading / disabled / success.

And the real insight: **you might not know all the states you need until you start building.**
The Figma concept always looks complete. Then you build, you drag the thing, and you feel the
holes: "this needs a working state," "the number should roll, not swap," "this label should
shimmer while busy," "the icon should cross-fade between play and pause." Those micro-interactions
are *discovered through use*, never specced up front. Examples that came straight out of building:

- Numbers that roll digit-by-digit instead of hard-cutting.
- A shimmer sweep across a label while a task is working.
- Play/pause icons that cross-fade and scale between each other rather than swapping.

**Prompt it:** *"While it's working, don't add a spinner. Let the label text itself glow softly,
like a light slowly sweeping across the word from one side to the other and back, looping about
every 2 seconds. It should feel calm and alive, not flashy."*

**Figma prep:** Use component variants for the states you know. Then accept that the build will
surface two or three more — and that's where the polish actually lives. This is the rule that
separates a mockup from a product; treat it as the mindset you carry into the other nine.

---

## How to actually prompt for this

- **Give numbers, never adjectives.** "Smooth" is meaningless; a specific curve at 280ms is
  buildable.
- **Lead with your design tokens.** Paste the variable block first and forbid one-off values.
- **Think in states, then list them.** The model builds exactly the states you name and no more.
- **Isolate when iterating.** "Now only tune the shadow stack." "Now only the entrance." One
  variable at a time is how you reach polish without thrashing. (This is exactly what
  [dialkit.md](dialkit.md) is for.)
- **Describe the feeling and a reference.** "Should feel like an iOS sheet: weighty, slightly
  springy, settles fast." Reference-anchored requests land far better than abstract ones.
- **Handing off from Figma? Name every property to copy.** Point the model at the current
  selection and list exactly what to read off it: padding, gaps, tokens, colors, corner radius,
  type sizes and weights. Never assume the handoff tool carries it all over perfectly — it won't.
  The more explicit you are about what to read off the design, the closer the first build lands.

## On Figma

Figma is where the concept lives, and it's worth prepping: variables mirroring your tokens,
auto-layout, variants for known states. But be honest about its limit: **a Figma file is a
hypothesis.** The real states, the micro-interactions, the moments that need a roll or a shimmer
or a snap point only reveal themselves once you're holding the live thing and dragging it around.
The design tells you where to start; the build tells you what it actually needs.

## The part that doesn't come out of the model

These models will build a flawless spring animation or a card-flight transition faster than
anyone could by hand. But not one of them decided the press should be 98% and not 95%, or that
the entrance needed a 2px blur, or that the slider wanted a release zone bigger than its pull-in
zone, or that this component was missing a working state until you felt the gap.

That judgment is **taste**, and taste is earned — from shipping, from staring at things that feel
almost right and knowing the fix. The model is the hands; the eye is still yours. Prompts get you
90% of the way in minutes. The last 10% — the part people actually celebrate — is you.

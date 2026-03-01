---
name: ui-design-principles
description: "Timeless visual design principles. Whitespace, rhythm, alignment, hierarchy, contrast, proximity, balance, consistency. Apply every time code touches UI — any platform, any medium."
---

# Visual Design Principles

Timeless principles that govern effective visual design. These are medium-agnostic — they
apply to web, mobile, desktop, print, and any visual interface. Apply these every time code
touches UI.

## When to Apply

**Every time you create or modify UI.** These are not optional guidelines — they are the
physics of visual design. Violating them produces interfaces that feel "off" even when users
can't articulate why.

Check these principles when:
- Creating new components or screens
- Modifying layout, spacing, or visual properties
- Reviewing UI code
- Making design decisions

## The Principles

### 1. Whitespace (Negative Space)

Space is not empty — it is a design element. It creates breathing room, directs attention,
and communicates relationships.

**Rules:**
- More whitespace signals higher quality and importance
- Generous padding inside elements; generous margins between them
- When in doubt, add more space — cramped layouts always feel cheap
- Content-to-whitespace ratio: important content gets more surrounding space
- Group related items tightly; separate unrelated items with space

**Violations to catch:**
- Elements crammed edge-to-edge with no breathing room
- Equal spacing everywhere (creates visual monotony)
- Insufficient padding inside interactive elements
- Text walls with no paragraph spacing

### 2. Visual Hierarchy

Not everything can be important. Hierarchy tells the eye where to look first, second, third.

**Rules:**
- Every screen has exactly one primary focal point
- Size, weight, color, and position all establish hierarchy — use them deliberately
- Three levels maximum for most interfaces: primary, secondary, tertiary
- De-emphasize secondary content as much as you emphasize primary content
- If everything is bold, nothing is bold

**Violations to catch:**
- Multiple elements competing for attention at the same level
- No clear entry point — the eye doesn't know where to start
- Overuse of bold, color, or large text (hierarchy inflation)
- Important actions visually buried among decorative elements

### 3. Alignment

Invisible lines connect elements. Alignment creates order from chaos.

**Rules:**
- Every element should align to at least one other element
- Use a consistent grid or alignment system — never place elements arbitrarily
- Left-align text by default (in LTR languages); center-align only with intention
- Optical alignment over mathematical alignment — trust the eye, not the pixel ruler
- Fewer alignment points means cleaner design

**Violations to catch:**
- Elements that are "almost" aligned but off by a few pixels
- Mixing alignment systems (some left-aligned, some centered, no pattern)
- Content that doesn't sit on any grid line
- Centered text in long-form content (reduces readability)

### 4. Contrast

Difference creates meaning. Without sufficient contrast, information is lost.

**Rules:**
- Contrast is not just color — it includes size, weight, shape, texture, and density
- High contrast for primary content; low contrast for secondary content
- Foreground must be clearly distinguishable from background
- Use contrast to create the hierarchy — the most important thing should have the most
  contrast against its surroundings
- Squint test: if you squint and can't tell elements apart, contrast is insufficient

**Violations to catch:**
- Low-contrast text (especially light gray on white)
- Interactive elements that don't stand out from static content
- Headers that barely differ from body text
- Important information conveyed only through subtle color differences

### 5. Rhythm and Repetition

Consistent patterns create rhythm. Rhythm creates comfort and predictability.

**Rules:**
- Use a spacing scale — don't invent new values (e.g., 4, 8, 12, 16, 24, 32, 48, 64)
- Repeat visual patterns: if cards look one way, all cards look that way
- Consistent spacing between repeated elements (lists, grids, card collections)
- Rhythm breaks should be intentional — they signal a change in content type
- Vertical rhythm: align baselines and spacing to a consistent baseline grid

**Violations to catch:**
- Random spacing values (13px here, 17px there, 22px elsewhere)
- Inconsistent treatment of similar elements
- Visual patterns that break without reason
- Uneven gaps in lists or grids

### 6. Proximity

Things that are close together are perceived as related. Distance implies separation.

**Rules:**
- Group related elements closer together than unrelated ones
- A label must be closer to its field than to the previous field
- Section headers must be closer to their content than to the previous section
- Use proximity before using dividers — space alone often suffices
- Proximity should mirror the information architecture

**Violations to catch:**
- Labels equidistant between two fields (ambiguous ownership)
- Related actions scattered across the interface
- Dividers or borders used where spacing alone would communicate grouping
- Section headers that float between sections with equal spacing above and below

### 7. Balance

Visual weight should be distributed intentionally. Imbalance creates tension.

**Rules:**
- Symmetrical balance for formal, stable, trustworthy interfaces
- Asymmetrical balance for dynamic, modern, interesting interfaces
- Larger/darker/more complex elements carry more visual weight
- Balance the overall composition — don't leave one side heavy and the other empty
- Balance applies at every level: the screen, sections, and individual components

**Violations to catch:**
- All heavy elements clustered on one side
- One area packed with content while another is barren
- Visual weight distribution that creates unintentional tension
- Components that feel lopsided internally

### 8. Consistency

Same thing, same way, every time. Consistency builds trust and reduces cognitive load.

**Rules:**
- Same action, same appearance — don't style the same interaction differently
- Same type of content, same treatment — headings look like headings everywhere
- Spacing, colors, typography, border-radius: pick values and reuse them
- Break consistency only with purpose (to draw attention to something different)
- Internal consistency (within your interface) matters more than external conventions

**Violations to catch:**
- Same action styled differently in different places
- Inconsistent border-radius (rounded here, sharp there, for no reason)
- Color used to mean different things in different contexts
- Typography that varies without semantic reason

### 9. Scale and Proportion

Size relationships communicate importance and create visual interest.

**Rules:**
- Use a type scale with consistent ratios (e.g., 1.25x, 1.333x, 1.5x between levels)
- Size jumps should be noticeable — don't use 14px and 15px as distinct levels
- Larger elements need proportionally more internal padding
- Icons should scale with their context — match the optical size of adjacent text
- Proportion applies to everything: padding ratios, image aspect ratios, column widths

**Violations to catch:**
- Type sizes too similar to create meaningful hierarchy
- Tiny padding in large containers or vice versa
- Icons that are visually larger or smaller than adjacent text
- Elements that feel disproportionate to their context

### 10. Unity and Cohesion

Every element should look like it belongs to the same family.

**Rules:**
- Establish a visual language: a limited set of colors, shapes, spacing values, and type
  styles
- Every element should share at least one visual property with neighboring elements
- Limit the number of distinct styles — fewer is almost always better
- The interface should feel like one designer made it, not a committee
- When adding something new, derive it from existing patterns rather than inventing fresh

**Violations to catch:**
- Elements that look imported from a different design system
- Too many competing visual styles on one screen
- Inconsistent shape language (round buttons, sharp cards, mixed corners)
- Color palette that feels arbitrary rather than curated

## The Squint Test

Squint at the interface (or step back from the screen) until you can't read text. You should
still be able to identify:

1. **Where to look first** (hierarchy is working)
2. **What groups together** (proximity is working)
3. **What's interactive vs. static** (contrast is working)
4. **An overall sense of order** (alignment and rhythm are working)

If any of these fail, the fundamentals need work — no amount of polish will fix them.

## Design Review Checklist

When reviewing UI changes, verify:

- [ ] **Whitespace**: Generous breathing room; space used to group and separate
- [ ] **Hierarchy**: Clear primary focal point; eye knows where to start
- [ ] **Alignment**: All elements sit on consistent alignment lines
- [ ] **Contrast**: Primary content pops; secondary content recedes
- [ ] **Rhythm**: Spacing follows a consistent scale; patterns repeat predictably
- [ ] **Proximity**: Related things close; unrelated things apart
- [ ] **Balance**: Visual weight distributed intentionally
- [ ] **Consistency**: Same patterns for same purposes throughout
- [ ] **Scale**: Size differences are meaningful and proportional
- [ ] **Unity**: Everything feels like part of the same family

## Priority of Principles

When principles conflict (they sometimes do), resolve in this order:

1. **Hierarchy** — The user must know where to look
2. **Contrast** — Information must be perceivable
3. **Proximity** — Relationships must be clear
4. **Alignment** — Structure must be visible
5. **Consistency** — Patterns must be trustworthy
6. **Whitespace** — Breathing room must exist
7. **Rhythm** — Patterns should be predictable
8. **Balance** — Composition should feel stable
9. **Scale** — Proportions should feel right
10. **Unity** — Everything should feel cohesive

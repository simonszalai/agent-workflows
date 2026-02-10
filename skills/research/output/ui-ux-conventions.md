---
title: "Research: UI/UX Conventions"
status: complete
created: 2026-01-21
zones_searched: 5
total_files: 192
files_with_matches: 124
patterns_found: 14
inconsistencies: 8
---

# Research: UI/UX Conventions

> **Scope:** This document catalogs how UI/UX conventions are implemented across the codebase,
> including design tokens, reusable components, layout patterns, and styling approaches.
> For fixing issues, create a work item and use `/plan`.

## Executive Summary

The codebase uses a **well-centralized design token system** in `app/app.css` using oklch() color
space with Tailwind CSS v4. Component styling follows **shadcn/ui patterns** with CVA (Class
Variance Authority) for variants. The system has good foundational architecture but shows
**inconsistency in color usage** between semantic tokens and hardcoded Tailwind colors, and
**duplicated layout patterns** that could be extracted into reusable components.

**Coverage:** Searched 192 files across 5 zones. 124 files contained relevant patterns.

---

## Pattern Catalog

### Pattern 1: Centralized Design Tokens (oklch Color Space)

**Usage:** Single source of truth in `app/app.css`
**Description:** All color tokens defined as CSS custom properties using oklch() for perceptual
uniformity. Enables dynamic theming via hue rotation.

```css
/* Canonical example from app/app.css:6-69 */
:root {
  --radius: 0.625rem;
  --background: oklch(0.14 0.008 136);
  --foreground: oklch(0.95 0.005 136);
  --primary: oklch(0.65 0.25 136);
  --primary-foreground: oklch(0.1 0.01 136);
  --muted: oklch(0.2 0.008 136);
  --muted-foreground: oklch(0.58 0.015 136);
  --destructive: oklch(0.55 0.22 25);
  --success: oklch(0.65 0.25 155);
  --warning: oklch(0.78 0.16 75);
  --danger: oklch(0.62 0.24 25);
  /* ... 30+ more tokens */
}
```

**Locations:**
- `app/app.css:6-69` - Primary token definitions
- `app/app.css:71-121` - Tailwind @theme integration
- `app/hooks/use-accent-color.ts:87-122` - Dynamic token generation from hue

---

### Pattern 2: CVA Component Variants

**Usage:** All 75 component files in `app/components/ui/`
**Description:** Components use Class Variance Authority (CVA) for type-safe variant management.
All accept className prop and use cn() for merging.

```typescript
/* Canonical example from app/components/ui/button.tsx:7-36 */
const buttonVariants = cva(
  "inline-flex items-center justify-center rounded-md text-sm font-medium...",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground shadow-xs hover:bg-primary/90",
        destructive: "bg-destructive text-destructive-foreground shadow-xs",
        outline: "border border-border bg-background shadow-xs hover:bg-accent",
        secondary: "bg-secondary text-secondary-foreground shadow-xs",
        ghost: "hover:bg-accent hover:text-accent-foreground",
        link: "text-primary underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-8 rounded-md px-3 text-xs",
        lg: "h-10 rounded-md px-6",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
)
```

**Locations:**
- `app/components/ui/button.tsx` - Button variants
- `app/components/ui/badge.tsx` - Badge variants
- `app/components/ui/input.tsx` - Input states
- `app/components/ui/card.tsx` - Card structure
- `app/components/ui/empty.tsx` - Empty state variants

---

### Pattern 3: Ambient Gradient Background

**Usage:** 6 occurrences across Routes zone
**Description:** Decorative gradient orbs create visual depth. Pattern is repeated inline rather
than extracted.

```tsx
/* Canonical example from app/routes/home.tsx:16-21 */
<div className="min-h-screen bg-background bg-grid relative">
  <div className="pointer-events-none fixed inset-0 overflow-hidden">
    <div className="absolute -top-40 -right-40 h-96 w-96 rounded-full bg-primary/8 blur-[120px]" />
    <div className="absolute bottom-0 -left-40 h-80 w-80 rounded-full bg-chart-3/8 blur-[100px]" />
  </div>
  {/* Page content */}
</div>
```

**Locations:**
- `app/routes/home.tsx:16-21` - Home page
- `app/routes/ticker._index.tsx:36-41` - Ticker index
- `app/routes/prompts.tsx` - Prompts page
- `app/routes/metrics.tsx` - Metrics page
- `app/routes/processing-times.tsx` - Processing times
- `app/routes/llm-costs.tsx` - LLM costs

---

### Pattern 4: Score-Based Color Coding

**Usage:** 4 occurrences in records components
**Description:** Consistent color mapping for score visualization using semantic thresholds.

```typescript
/* Canonical example from app/components/records/ScorePill.tsx:19-29 */
const getScoreColor = (score: number) => {
  if (score >= 80) return "bg-green-500/20 text-green-400 border-green-500/30"  // High
  if (score >= 60) return "bg-blue-500/20 text-blue-400 border-blue-500/30"    // Moderate
  if (score >= 40) return "bg-orange-500/20 text-orange-400 border-orange-500/30" // Low
  return "bg-red-500/20 text-red-400 border-red-500/30"                        // Very Low
}
```

**Locations:**
- `app/components/records/ScorePill.tsx:19-29` - Score pill colors
- `app/components/records/ScoreGroup.tsx` - Score groupings
- `app/components/records/PriceDisplay.tsx:33-34` - Price change colors
- `app/routes/ticker._index.tsx:59` - Success rate colors

---

### Pattern 5: Compound Component Architecture

**Usage:** All complex UI components
**Description:** Components split into logical sub-components (Card → CardHeader + CardContent).

```typescript
/* Canonical example from app/components/ui/card.tsx */
function Card({ className, ...props }) {
  return <div data-slot="card" className={cn("rounded-xl border...", className)} {...props} />
}

function CardHeader({ className, ...props }) {
  return <div data-slot="card-header" className={cn("grid gap-1.5...", className)} {...props} />
}

function CardTitle({ className, ...props }) {
  return <div data-slot="card-title" className={cn("font-semibold...", className)} {...props} />
}
```

**Locations:**
- `app/components/ui/card.tsx` - Card + CardHeader + CardTitle + CardContent + CardFooter
- `app/components/ui/dialog.tsx` - Dialog + DialogTrigger + DialogContent + DialogHeader
- `app/components/ui/field.tsx` - Field + FieldLabel + FieldContent + FieldDescription
- `app/components/ui/sidebar.tsx` - Sidebar + SidebarContent + SidebarMenu + SidebarMenuItem

---

### Pattern 6: Glass Card Effect

**Usage:** CSS utility in `app/app.css`
**Description:** Reusable glass morphism effect using backdrop blur and color mixing.

```css
/* Canonical example from app/app.css:174-182 */
.glass-card {
  background: linear-gradient(
    135deg,
    color-mix(in oklch, var(--card) 80%, transparent),
    color-mix(in oklch, var(--card) 60%, transparent)
  );
  backdrop-filter: blur(12px);
  border: 1px solid color-mix(in oklch, var(--border) 60%, transparent);
}
```

**Locations:**
- `app/app.css:174-182` - Glass card utility definition
- Used implicitly via `.glass-card` class in components

---

### Pattern 7: Form Action Button Layout

**Usage:** Documented pattern for form buttons
**Description:** Standardized button ordering and spacing for form actions.

```tsx
/* Canonical example from .claude/knowledge/references/form-action-buttons.md */
<div className="flex justify-end gap-3">
  <CancelButton className="min-w-24" onClick={() => history.back()} />
  <SaveButton className="min-w-24" isLoading={isSubmitting}>Save Changes</SaveButton>
</div>
```

**Locations:**
- `.claude/knowledge/references/form-action-buttons.md` - Pattern documentation
- `app/components/ui/action-buttons.tsx` - Implementation

---

### Pattern 8: Dynamic Theming via useAccentColor

**Usage:** Ticker pages
**Description:** Extracts dominant hue from company logo and generates full theme via oklch.

```typescript
/* Canonical example from app/hooks/use-accent-color.ts:87-122 */
function generateColorsFromHue(hue: number) {
  const h = Math.round(hue)
  return {
    "--background": `oklch(0.14 0.008 ${h})`,
    "--primary": `oklch(0.65 0.25 ${h})`,
    "--card": `oklch(0.18 0.012 ${h})`,
    // ... 25+ more tokens
  }
}
```

**Locations:**
- `app/hooks/use-accent-color.ts` - Hook implementation
- `app/routes/ticker.$symbol.tsx:118-125` - Usage in ticker page

---

## Zone Findings

### Routes (`app/routes/`)

**Files searched:** 25
**Matches found:** 25

| Pattern | Count | Notes |
| ------- | ----- | ----- |
| Gradient orbs | 6 | Repeated inline, not extracted |
| Card layouts | 15+ | Consistent use of Card component |
| TimeFilter header | 5 | Standard header + filter pattern |
| Responsive grids | 12 | Varying breakpoint conventions |
| Sidebar layout | 1 | _app.tsx provides shell |

**Zone summary:** Routes consistently use Card-based layouts with TimeFilter headers. Gradient orb
pattern is duplicated across 6 files and should be extracted. Grid breakpoints vary between
`md:grid-cols-2` and `lg:grid-cols-2`.

---

### Components (`app/components/`)

**Files searched:** 75
**Matches found:** 75

| Pattern | Count | Notes |
| ------- | ----- | ----- |
| CVA variants | 40+ | Standard for all base components |
| data-slot attrs | 30+ | Consistent identification |
| Compound components | 8 | Card, Dialog, Field, Sidebar, etc. |
| Hardcoded colors | 15 | green-400, red-400, blue-400 |
| cn() utility | 75 | Universal class merging |

**Zone summary:** Strong adherence to shadcn/ui patterns. CVA provides type-safe variants. Main
issue is mixed usage of semantic tokens vs hardcoded Tailwind colors (e.g., `text-green-400`
instead of `text-success`).

---

### Models (`app/models/`)

**Files searched:** 19
**Matches found:** 11

| Pattern | Count | Notes |
| ------- | ----- | ----- |
| Visualization types | 5 | TreemapNode, HistogramBin, etc. |
| Label mappings | 2 | COST_TYPE_LABELS constant |
| Pagination types | 3 | Cursor-based pattern |

**Zone summary:** Models define data structures for UI visualization (treemaps, histograms, time
series). Label mappings like `COST_TYPE_LABELS` provide UI-friendly names but could be
centralized.

---

### Core (`app/lib/`, `app/hooks/`, `app/types/`)

**Files searched:** 11
**Matches found:** 6

| Pattern | Count | Notes |
| ------- | ----- | ----- |
| oklch theming | 1 | use-accent-color.ts |
| cn() utility | 1 | utils.ts |
| Metric colors | 1 | metrics.ts (hex palette) |
| Mobile hook | 1 | use-mobile.ts (768px) |

**Zone summary:** Core utilities are well-organized. Dynamic theming via oklch is sophisticated.
Metric colors use hex instead of oklch, creating inconsistency with main theme system.

---

### Config (root, `prisma/`, `.claude/`)

**Files searched:** 62
**Matches found:** 7

| Pattern | Count | Notes |
| ------- | ----- | ----- |
| Token definitions | 1 | app/app.css (centralized) |
| @theme inline | 1 | Tailwind v4 integration |
| Component docs | 1 | form-action-buttons.md |
| CSS utilities | 5 | glass-card, glow-hover, etc. |

**Zone summary:** Design tokens are fully centralized in `app/app.css`. Tailwind v4 configuration
uses @theme inline block. Pattern documentation exists in `.claude/knowledge/`.

---

## Inconsistencies

| #   | Issue | Severity | Locations | Impact |
| --- | ----- | -------- | --------- | ------ |
| 1   | Hardcoded colors vs semantic tokens | MEDIUM | 15+ files | Theming breaks |
| 2   | Gradient orb duplication | LOW | 6 routes | DRY violation |
| 3   | Mixed grid breakpoints | LOW | 12 routes | UX inconsistency |
| 4   | Metric colors use hex (not oklch) | MEDIUM | metrics.ts | Style mismatch |
| 5   | Border opacity inconsistency | LOW | 50+ files | Visual variance |
| 6   | No semantic success/warning tokens usage | MEDIUM | 10+ files | Token waste |
| 7   | SVG inline stroke values | LOW | TaskDAG.tsx | Not themeable |
| 8   | Typography not documented | MEDIUM | N/A | Implicit knowledge |

### 1. Hardcoded Colors vs Semantic Tokens

**Severity:** MEDIUM
**Pattern A:** Using semantic tokens (correct)
```tsx
// From app/components/ui/button.tsx
className="bg-destructive text-destructive-foreground"
```

**Pattern B:** Using hardcoded Tailwind colors (inconsistent)
```tsx
// From app/components/records/PriceDisplay.tsx:33-34
const color = change >= 0 ? "text-green-400" : "text-red-400"
```

**Impact:** Dynamic theming via `useAccentColor` won't affect hardcoded colors. Dashboard looks
inconsistent when theme changes.
**Recommendation:** Replace `text-green-400/500` with `text-success`, `text-red-400/500` with
`text-danger`. Tokens already exist in app/app.css but aren't used.

---

### 2. Gradient Orb Duplication

**Severity:** LOW
**Pattern A:** Inline gradient orbs (current)
```tsx
// From app/routes/home.tsx:17-20
<div className="pointer-events-none fixed inset-0 overflow-hidden">
  <div className="absolute -top-40 -right-40 h-96 w-96 rounded-full bg-primary/8 blur-[120px]" />
  <div className="absolute bottom-0 -left-40 h-80 w-80 rounded-full bg-chart-3/8 blur-[100px]" />
</div>
```

**Pattern B:** Extracted component (recommended)
```tsx
// Proposed: app/components/ui/ambient-background.tsx
export function AmbientBackground() {
  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden">
      <div className="absolute -top-40 -right-40 h-96 w-96 rounded-full bg-primary/8 blur-[120px]" />
      <div className="absolute bottom-0 -left-40 h-80 w-80 rounded-full bg-chart-3/8 blur-[100px]" />
    </div>
  )
}
```

**Impact:** 6 files have identical or near-identical code. Changes require 6 edits.
**Recommendation:** Extract to `<AmbientBackground />` component.

---

### 3. Metric Colors Use Hex Instead of oklch

**Severity:** MEDIUM
**Pattern A:** Main theme uses oklch
```css
/* From app/app.css */
--chart-1: oklch(0.65 0.25 136);
```

**Pattern B:** Metrics use hex
```typescript
// From app/lib/metrics.ts:15
color: "#0ea5e9",  // cyan-500
```

**Impact:** Two color systems that don't align. Metric charts won't adapt to dynamic themes.
**Recommendation:** Either convert metrics to use CSS variables (`var(--chart-1)`) or generate hex
from oklch at runtime.

---

## Recommendations

### Standardization Opportunities

1. **Replace hardcoded colors with semantic tokens**
   - Current state: `text-green-400`, `text-red-400` used directly
   - Recommended pattern: `text-success`, `text-danger` (tokens exist)
   - Files to update: ~15
   - Risk: Low

2. **Extract AmbientBackground component**
   - Current state: Gradient orb code duplicated in 6 routes
   - Recommended pattern: Single `<AmbientBackground />` component
   - Files to update: 6
   - Risk: Low

3. **Standardize grid breakpoints**
   - Current state: Mix of `md:` and `lg:` for 2-column layouts
   - Recommended pattern: Document convention (e.g., always `md:grid-cols-2` for cards)
   - Files to update: ~10
   - Risk: Low

4. **Migrate metric colors to CSS variables**
   - Current state: Hex colors in `metrics.ts`
   - Recommended pattern: Use `var(--chart-1)` through `var(--chart-5)`
   - Files to update: 1 (metrics.ts)
   - Risk: Medium (requires chart library compatibility check)

### Missing Patterns

- **Typography scale documentation** - Font sizes/weights used but not formally documented
- **Spacing scale reference** - Gap/padding conventions exist but aren't codified
- **Score color semantic tokens** - `--score-high`, `--score-medium`, `--score-low` could be added
- **Component storybook** - No visual documentation of component variants

---

## Metrics

| Metric | Value |
| ------ | ----- |
| Total files searched | 192 |
| Files with pattern | 124 |
| Unique pattern variants | 14 |
| HIGH severity issues | 0 |
| MEDIUM severity issues | 4 |
| LOW severity issues | 4 |

---

## Design System Summary

### What's Working Well

1. **Centralized tokens** - Single source of truth in `app/app.css`
2. **oklch color space** - Perceptually uniform, supports dynamic theming
3. **CVA components** - Type-safe, consistent variant API
4. **Compound components** - Clean separation of concerns
5. **data-slot attributes** - Testable, identifiable components
6. **Form button pattern** - Documented and standardized

### Token Reference

| Category | Tokens |
| -------- | ------ |
| Backgrounds | `--background`, `--card`, `--popover`, `--muted`, `--accent`, `--sidebar` |
| Foregrounds | `--foreground`, `--muted-foreground`, `--primary-foreground` |
| Semantic | `--primary`, `--destructive`, `--success`, `--warning`, `--danger` |
| Charts | `--chart-1` through `--chart-5` |
| Effects | `--glow-primary`, `--glow-success`, `--glow-danger` |
| Radius | `--radius-sm` (0.375rem), `--radius-md` (0.5rem), `--radius-lg` (0.625rem) |
| Fonts | `--font-sans` (Inter), `--font-mono` (JetBrains Mono) |

### Spacing Convention (Tailwind units)

| Use Case | Pattern |
| -------- | ------- |
| Card padding | `p-6` (24px) |
| Section gap | `gap-6` (24px) |
| Element gap | `gap-2` to `gap-4` (8-16px) |
| Button padding | `px-4 py-2` (16px × 8px) |
| Form field gap | `gap-1.5` (6px) |

### Typography Convention

| Use Case | Pattern |
| -------- | ------- |
| Page title | `text-2xl font-bold` or `text-3xl font-bold` |
| Section title | `text-lg font-semibold` |
| Card title | `text-sm font-medium` |
| Body text | `text-sm` (default) |
| Labels | `text-xs uppercase tracking-wide text-muted-foreground` |
| Monospace | `font-mono` |

---

## Next Steps

- [ ] Review findings with team
- [ ] Decide on standardization approach for hardcoded colors
- [ ] Create work item for AmbientBackground extraction
- [ ] Document typography/spacing scales in `.claude/knowledge/`
- [ ] Consider adding score color semantic tokens

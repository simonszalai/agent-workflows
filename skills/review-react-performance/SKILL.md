---
name: review-react-performance
description: React performance review checklist. Eliminating waterfalls, re-render optimization, bundle size, client-side fetching patterns.
---

# React Performance Review Checklist

Review checklist for React application performance. Organized by impact level from CRITICAL to LOW.

## CRITICAL: Eliminating Waterfalls

Waterfalls are the #1 performance killer. Each sequential await adds full network latency.

- [ ] No waterfall chains in loaders/actions (sequential awaits for independent data)
- [ ] `Promise.all()` used for independent operations
- [ ] Promises started immediately, awaited only when needed (defer await)
- [ ] Dependency-based parallelization for mixed independent/dependent data

**Defer await pattern:**

```typescript
// Start immediately, await only when needed
const sessionPromise = auth(request);
const configPromise = fetchConfig();
const session = await sessionPromise;
const [config, data] = await Promise.all([
  configPromise,
  fetchData(session.user.id), // depends on session
]);
```

- [ ] Strategic Suspense boundaries (don't block entire page on slow data)

## CRITICAL: Bundle Size

- [ ] No barrel file imports from large libraries (200-800ms cost)
- [ ] Direct imports for icons and components

**Bad (imports entire library):**

```typescript
import { IconSettings } from "@tabler/icons-react";
```

**Good (imports single module):**

```typescript
import { IconSettings } from "@tabler/icons-react/dist/esm/icons/IconSettings";
```

- [ ] Heavy components use `React.lazy()` with `Suspense`
- [ ] Conditional module loading for feature-gated code
- [ ] Preload on hover/focus for predictable navigation

## MEDIUM-HIGH: Client-Side Data Fetching

- [ ] SWR or similar for automatic request deduplication and caching
- [ ] Global event listeners deduplicated (N instances = 1 listener)
- [ ] Passive event listeners for scroll handlers (`{ passive: true }`)
- [ ] localStorage/sessionStorage wrapped in try-catch (synchronous, can fail in incognito)
- [ ] Storage data versioned for schema evolution

## MEDIUM: Re-render Optimization

### Derived State

- [ ] Derived values calculated during rendering, not stored in state
- [ ] No `useEffect` to sync state from props (causes extra render)

**Bad:**

```typescript
const [fullName, setFullName] = useState("");
useEffect(() => setFullName(`${first} ${last}`), [first, last]);
```

**Good:**

```typescript
const fullName = `${first} ${last}`;
```

### Memoization

- [ ] Don't `useMemo` simple primitives (hook overhead > expression cost)
- [ ] Non-primitive default values extracted to module-level constants
- [ ] Components extracted and memoized when parent re-renders unnecessarily

**Bad (new object every render, breaks memoization):**

```typescript
function Component({ options = { limit: 10 } }) { ... }
```

**Good (stable reference):**

```typescript
const DEFAULT_OPTIONS = { limit: 10 }
function Component({ options = DEFAULT_OPTIONS }) { ... }
```

### Effect Dependencies

- [ ] Effect dependencies use primitives, not objects (narrow dependencies)
- [ ] Interaction logic in event handlers, not effects
- [ ] `useRef` for transient values that don't need re-renders
- [ ] Lazy state initialization for expensive initial values

**Bad (runs on any user object change):**

```typescript
useEffect(() => {
  updateTitle(user.name);
}, [user]);
```

**Good (runs only when name changes):**

```typescript
useEffect(() => {
  updateTitle(user.name);
}, [user.name]);
```

### State Updates

- [ ] Functional `setState` for updates based on previous state (prevents stale closures)
- [ ] `useTransition` for non-urgent updates (maintains UI responsiveness)
- [ ] Subscribe to derived/filtered state to reduce re-render frequency

## MEDIUM: Rendering Performance

- [ ] CSS `content-visibility: auto` for long lists (10x faster initial render)
- [ ] Static JSX elements hoisted outside component (reuse, not recreate)
- [ ] SVG animations on wrapper element (hardware acceleration)
- [ ] Explicit conditional rendering (no reliance on falsy value behavior)
- [ ] `useTransition` over manual loading states for better UX

## LOW-MEDIUM: JavaScript Micro-optimizations

- [ ] Index maps (Map/Set) for repeated lookups instead of array.find()
- [ ] RegExp instances hoisted outside functions/loops
- [ ] Multiple array iterations combined into single pass
- [ ] `toSorted()` instead of `sort()` for immutability
- [ ] Loop-based min/max instead of sort for single value (O(n) vs O(n log n))
- [ ] No layout thrashing (batch DOM writes, then reads)

## LOW: Advanced Patterns

- [ ] App initialization in module scope, not `useEffect([], ...)`
- [ ] Event handlers stored in refs for stable subscriptions
- [ ] `useEffectEvent` for callbacks that shouldn't trigger effect re-runs

## Quick Reference: Most Common Issues

| Issue                  | Impact   | Fix                                         |
| ---------------------- | -------- | ------------------------------------------- |
| Sequential awaits      | CRITICAL | `Promise.all()` for independent operations  |
| Barrel imports         | CRITICAL | Direct path imports for large libraries     |
| State-syncing effects  | MEDIUM   | Calculate derived values during render      |
| Object default props   | MEDIUM   | Extract to module-level constants           |
| Object effect deps     | MEDIUM   | Use primitive properties, not whole objects |
| N+1 queries in loaders | HIGH     | Batch functions with `IN` clauses           |
| Missing Suspense       | MEDIUM   | Wrap slow data loads in Suspense boundaries |

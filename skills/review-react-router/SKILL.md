---
name: review-react-router
description: React Router v7 review checklist. Server/client module boundaries, route registration, fetcher patterns, loader optimization, and common gotchas.
---

# React Router Review Checklist

Review checklist for React Router v7 / Remix applications. Covers server/client boundaries, data
loading, form handling, and common pitfalls.

## Route Registration

- [ ] All new routes are registered in the route configuration file (e.g., `app/routes.ts`)
- [ ] Missing registration causes silent 404 errors and fetcher failures
- [ ] Route paths match the expected URL structure
- [ ] Layout routes wrap the correct child routes

## Server/Client Module Boundaries

### .server.ts Import Rules

- [ ] No client component imports from `.server.ts` files (even pure functions)
- [ ] Shared types and pure functions live in non-server files (e.g., `records.ts`)
- [ ] Only server-only code (DB queries, secrets) stays in `.server.ts` files

**Correct structure:**

```
app/models/
├── records.ts          # Shared types + pure functions
└── records.server.ts   # Server-only code (DB queries)
```

### Re-export Rules (Vite)

- [ ] No VALUE re-exports from `.server.ts` files (constants, functions)
- [ ] Type re-exports from `.server.ts` are safe (erased at compile time)
- [ ] Client imports shared values directly from the non-server file

**Why:** Vite's bundler "taints" re-exported symbols, associating them with the server module
even when the original source is a shared file.

## Data Loading

### Loader Optimization

- [ ] Independent queries use `Promise.all()` for parallel execution
- [ ] No waterfall chains (sequential awaits for independent data)
- [ ] Promises started immediately, awaited only when needed

**Bad - waterfall:**

```typescript
const session = await auth(request);
const config = await fetchConfig(); // waits for auth unnecessarily
const data = await fetchData(session.user.id);
```

**Good - parallel:**

```typescript
const sessionPromise = auth(request);
const configPromise = fetchConfig();
const session = await sessionPromise;
const [config, data] = await Promise.all([
  configPromise,
  fetchData(session.user.id),
]);
```

### N+1 Query Prevention

- [ ] No `.map()` over arrays to make individual queries
- [ ] Batch functions exist for repeated lookups (e.g., `getItemsByIds(ids)`)
- [ ] Database queries use `IN` clauses or joins for batch access

**Bad:**

```typescript
const trees = await Promise.all(groups.map((g) => getTreeForGroup(g.id)));
```

**Good:**

```typescript
const trees = await getTreesForGroups(groups.map((g) => g.id));
```

### Batch Mutations

- [ ] Multiple mutations use `db.$transaction()` for atomicity
- [ ] No loops of individual update calls

## Form Handling

### Fetcher Patterns

- [ ] Use `<fetcher.Form>` inside Radix/Portal dialogs (not manual `fetcher.submit()`)
- [ ] Hidden inputs for intent and IDs in fetcher forms
- [ ] `defaultValue` used for pre-populated fields (not `value`)

**Why `fetcher.Form` in dialogs:** Radix Dialog renders in a React Portal (outside normal DOM
hierarchy). Manual `fetcher.submit()` has issues with event handling in portals.

**Close-on-success pattern:**

```tsx
const fetcher = useFetcher();
const prevFetcherState = useRef(fetcher.state);

useEffect(() => {
  if (prevFetcherState.current !== "idle" && fetcher.state === "idle" && open) {
    if (fetcher.data?.success) {
      onOpenChange(false);
    }
  }
  prevFetcherState.current = fetcher.state;
}, [fetcher.state, fetcher.data, open, onOpenChange]);
```

### Route Patterns

- [ ] Use `resources.*` routes for internal fetcher endpoints
- [ ] Only create `api.*` routes for external API access or different auth requirements
- [ ] No duplicate `api.*` and `resources.*` routes for the same resource

## Loading States

- [ ] Single loading spinner strategy (global OR local, not both)
- [ ] `useNavigation()` returns global state - parent and child both see it
- [ ] Choose: layout spinner (recommended) OR page-level spinners

**Why:** Both layout and page showing spinners simultaneously creates duplicate loading
indicators during navigation.

## Sidebar Layout

- [ ] Sidebar uses `h-full overflow-y-auto`, not `min-h-screen`
- [ ] Content area scrolls independently from sidebar

## Card Content

- [ ] Card components use consistent internal padding
- [ ] Action buttons within cards have adequate spacing

## Summary Checklist (Quick Reference)

| Area             | Key Check                                             |
| ---------------- | ----------------------------------------------------- |
| Routes           | Registered in route config file                       |
| Server boundary  | No client imports from `.server.ts`                   |
| Re-exports       | No VALUE re-exports from `.server.ts`                 |
| Loaders          | `Promise.all()` for independent queries               |
| N+1              | Batch functions for repeated lookups                  |
| Mutations        | `$transaction()` for multiple writes                  |
| Dialog forms     | `<fetcher.Form>` not `fetcher.submit()`               |
| Loading spinners | One strategy (global or local), not both              |
| Route patterns   | `resources.*` for fetchers, `api.*` for external only |

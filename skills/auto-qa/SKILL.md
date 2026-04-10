---
name: auto-qa
description: Full E2E QA. Creates test data, tests every page/action/integration, then cleans up. Works on empty databases.
max_turns: 200
---

# Auto-QA Command

Full end-to-end QA of the target environment. Self-sufficient — creates all test data it needs,
tests every flow, then cleans up after itself.

## Usage

```
/auto-qa staging                     # Full E2E QA on staging
/auto-qa local                       # Full E2E QA on local
/auto-qa staging --quick             # Critical paths only (phases 1-6, skip integrations)
```

First argument is the environment: `staging` or `local`.

## Environment Config

**Read `.claude/{env}.md`** (e.g., `.claude/staging.md` or `.claude/local.md`) for:
- URL, service IDs, credentials
- DB MCP tool name
- Auth/login flow

**Read `.claude/staging.md`** for the shared **project map** (routes, entities, dependencies,
test data templates, integrations, known console errors, UI localization) — it's the same
across all environments.

## Philosophy: Discovery-First Testing

The project map documents known routes, entities, and flows. But the app evolves.

**Before starting the predefined phases**, do a quick discovery pass:

1. Read the route tree to find any routes not listed in the project map:
   ```bash
   ls app/routes/
   ```
2. Check the sidebar navigation for new menu items by snapshotting after login.

If you find new routes or entities not in the project map, **test them too** and add them to the
report under a "Discovered" section.

## Test Execution

Use the gstack browse tool (`$B = ~/.claude/skills/gstack/browse/dist/browse`) for all browser
tests. Chain commands in a single `echo '[...]' | $B chain` call to preserve session state.

### Browse Tool Notes

- Does NOT support `sleep` or `find` commands. Use `wait` for page load only.
- To wait between steps, use shell `sleep N` between separate `$B chain` calls.
- Use snapshot `@e` element refs (e.g., `@e15`) for selectors, NOT CSS selectors.
  Always snapshot first to discover the actual element refs.

### Login Flow

**Staging:** Real Kinde auth (no dev-login bypass). Credentials in `.claude/staging.md`.

```bash
B=~/.claude/skills/gstack/browse/dist/browse

# 1. Navigate to /home to trigger Kinde redirect
echo '[["goto","$URL/home"],["wait","--load"]]' | $B chain
sleep 3
echo '[["snapshot"]]' | $B chain

# 2. Fill email (use @e refs from snapshot)
echo '[["fill","@eN","$EMAIL"],["click","@eN"],["wait","--load"]]' | $B chain
sleep 2
echo '[["snapshot"]]' | $B chain

# 3. Fill password
echo '[["fill","@eN","$PASSWORD"],["click","@eN"],["wait","--load"]]' | $B chain
sleep 5
echo '[["snapshot"]]' | $B chain
```

**Local:** Dev login bypass. No password needed.

```bash
echo '[["goto","$URL/dev-login?user=simon"],["wait","--load"]]' | $B chain
sleep 2
echo '[["snapshot"]]' | $B chain
```

**Post-login routing:**
- `/home` — Org exists, proceed to Phase 2+
- `/signup` — Empty DB. Complete signup using the values in `.claude/staging.md` (Signup section)

### Phase 1: Infrastructure Health

```bash
curl -sf $URL/resources/healthcheck && echo "PASS" || echo "FAIL"
```

For staging: if it fails, the service may be starting up (Render spins down after inactivity).
Wait 30-60s and retry.

### Phase 2: Seed Test Data

Create the minimum entities needed for testing. Use the test data templates from the project map
in `.claude/staging.md`. **Track all created entity IDs for cleanup in the final phase.**

Creation order (from Entity Dependencies):
1. Client
2. Items (2, linked to client)
3. One of each document type: Offer, Invoice, Order

For each: navigate to `/$entity/new`, fill the form, submit, record ID.
Verify seeded data via DB queries using the env's MCP tool.

### Phase 3: All List Pages

Navigate to every list page from the project map and verify:
- Page loads without error
- Table renders (`document.querySelector(".mantine-Table-tbody")?.childElementCount`)
- No error boundary (no "Hiba" text or stack traces)
- No console errors

Skip routes listed under "Non-testable Routes" in the project map.

### Phase 4: Detail Pages

Navigate to detail pages for seeded entities + one of each entity type from the DB.
If the DB has no data for a given entity, mark as SKIPPED.

### Phase 5: New Entity Pages

Navigate to `/$entity/new` for every entity with `Has /new = Yes` in the project map.
Verify the form renders without crash.

### Phase 6: System Pages

Test every system page from the project map. Verify content renders.

### Phase 6b: Mobile Responsive Spot-Check

Spot-check 4 key pages at 375x812 viewport: `/home`, `/offer`, `/client`, and `/` (landing).
Check for layout breaks, unreadable text, unusable controls.

### Phase 7: Public Pages

Test public pages from the project map **without authentication** (fresh browser session).

### Phase 8: Table Actions

On the offers list page:
1. **Search** — type "QA Test" in global filter, verify filtering
2. **Sort** — click column header, verify reorder
3. **Clone** — row action "Klonoz", verify row count +1
4. **Delete** — delete clone via "Torles", confirm modal, verify row count -1

### Phase 9: Document Finalization

Finalize the seeded offer:
1. Click "Vegleges" (Finalize)
2. Verify `readableId` generated, edit disabled, PDF/Email buttons visible
3. Confirm in DB

### Phase 10: PDF Generation

Click the PDF button on the finalized offer. Verify no error.

For local: skip if PDF service is not running.

### Phase 11: Email Sending

1. Click "Email" on finalized offer
2. Enter the test email address from config — **never any other address**
3. Submit, verify success
4. Confirm in DB (`emailSentTo` field)

### Phase 12: Invoice Finalization (NAV)

Finalize the seeded invoice. Verify NAV submission:
```sql
SELECT i."taxTransactionId", i."taxSubmissionStatus"
FROM "Invoice" i WHERE i.id = '$INVOICE_ID';
```
Expected: `taxTransactionId` not null.

### Phase 13: Stripe Checkout

1. Navigate to `/org/billing`
2. If subscription already exists, SKIP
3. Click subscription CTA, fill Stripe checkout with test card from config
4. Verify redirect back and subscription created in DB
5. Clean up: delete subscription and webhook events from DB

### Phase 14: Cleanup

**Mandatory** — even if earlier phases fail.

Delete in reverse dependency order (see Entity Dependencies in project map):
Docs -> doc-type tables -> Items -> Client -> Stripe data

Match test entities by `QA Test` name prefix. Verify cleanup (all counts = 0).

**Do NOT delete** the Org or UserAccount — those are permanent.

## Health Score

Compute weighted health score (0-100):

| Category | Weight | Scoring |
|----------|--------|---------|
| Console | 10% | 0 errors=100, 1-3=70, 4-10=40, 10+=10 |
| Pages | 25% | Each failing page deducts 5 |
| Data Creation | 15% | Each entity failure deducts 20 |
| Functional | 20% | Each failing action deducts 15 |
| Integrations | 15% | PDF/NAV/email/Stripe failure deducts 25 each |
| Mobile | 10% | Each broken layout deducts 25 |
| Public | 5% | Each failing public page deducts 50 |

Ignore known console errors listed in the project map.

## Reporting

Output a summary table with phase-by-phase results, health score, and details for each failure.

Save baseline to `.context/smoke-{env}-baseline.json` for regression comparison on future runs.

If a previous baseline exists, include a Regression section showing delta.

## Safety Rules

All credentials are test-mode — safe to finalize invoices, generate PDFs, test Stripe.

**Only restriction:** never send email to any address other than the test email in the env config.

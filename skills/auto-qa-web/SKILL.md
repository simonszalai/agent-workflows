---
name: auto-qa-web
description: Full E2E QA for web projects. Exercises every form, every action, every integration — not just "does the page render". Creates test data, probes validation with good and bad values, drives integrations end-to-end, then cleans up. Composes a repo-level plugin for all repo-specific knowledge.
max_turns: 250
---

# Auto-QA-Web

Full end-to-end QA of a web app target environment. **Render-only checks are not enough.**
A form that renders but silently swallows keystrokes, a button that appears but does
nothing, a validation rule that accepts garbage, or a submit that never persists — all of
those are bugs users see and QA must catch.

Auto-QA-Web tests **functionality**, not presence. For every form it types and submits.
For every button it clicks and verifies the effect. For every validation rule it probes
with bad values AND good values. For every integration it drives the flow end-to-end and
confirms the external side-effect.

**Platform scope:** web only. Mobile/native QA would be separate skills.

## Composition Pattern

This skill OWNS the phase structure, the philosophy (three non-negotiable rules), the
browser tooling, the scoring, and the reporting. Repo-specific content comes from a
repo-level plugin invoked via slash-command.

- Plugin location: `.claude/skills/repo-plugin/SKILL.md` in the target repo
- Invocation: `/repo-plugin <subcommand> [args]`
- If the plugin is absent, this skill EXITS cleanly with status `skipped` — no fallback
  to defaults. QA without a repo-specific project map (routes, entities, integrations,
  localization) produces false results, not quality.

## Usage

```
/auto-qa-web staging              # Full E2E QA on staging
/auto-qa-web local                # Full E2E QA on local
/auto-qa-web staging --quick      # Critical paths only (phases 1-7, skip integrations)
```

First argument is the environment: `staging` or `local`.

## Philosophy

Three non-negotiable rules.

### 1. Never trust presence as evidence of function.

Rendering is the cheapest possible check — it confirms the server returned HTML and
React hydrated, nothing more. Every page must also be *exercised*. An input that is
focusable but swallows keystrokes passes render-only QA and reaches production. A button
that appears but has a no-op handler passes render-only QA and reaches production.
`fill()` succeeding and `click()` returning without error are not evidence that anything
happened.

For each interactive element, follow up the interaction with a state read — DOM value,
URL change, database row, console error, network response — that can only be true if the
feature actually worked.

### 2. Validation is a feature. Test it.

If the schema says a prefix must be exactly 3 characters, submit with 2 characters and
verify the UI rejects it with the right message. If a tax number must match a specific
format, submit a garbage string and verify rejection. If an email field is required,
submit empty and verify the required-field error. **Validation that nobody tests is
validation that drifts silently** — schemas get weakened, error messages go stale,
client-side rules fall out of sync with the server.

For every form, QA covers three flows: invalid input rejected, valid input accepted,
record persisted.

### 3. Discovery over checklist.

The project map (from the plugin) documents known routes. But the app evolves — new
routes appear, old ones change shape. Before executing phases, walk the actual route
tree and the sidebar nav. Anything new gets tested; anything changed gets its flow
re-exercised. The map is a starting point, not a ceiling.

## Prerequisites

- Target repo has `.claude/skills/repo-plugin/SKILL.md`
- Environment file exists: `.claude/environments/{env}.md`
- gstack is installed: `~/.claude/skills/gstack/browse/dist/browse`

## Process

### Phase 0: Gating

1. Verify plugin exists at `.claude/skills/repo-plugin/SKILL.md`.
   - If missing: emit `skipped: no repo-plugin in repo`, exit 0.
2. Invoke `/repo-plugin qa-env {env}` → get URL, DB MCP, credentials, test email,
   healthcheck URL.
   - If error: STOP, report.
3. Invoke `/repo-plugin qa-login {env}` → get login flow.
4. Invoke `/repo-plugin qa-project-map` → get project map (routes, entities,
   dependencies, test data templates, UI localization, known errors, integrations,
   row action trigger).
   - If error: STOP, report. QA cannot proceed without a project map.
5. Invoke `/repo-plugin qa-seed` → get seed instructions.
6. Invoke `/repo-plugin qa-integrations {env}` → get integration phase definitions.
7. Invoke `/repo-plugin qa-cleanup` → get cleanup rules.

### Phase 1: Infrastructure Health

```bash
curl -sf $URL$HEALTHCHECK_PATH && echo "PASS" || echo "FAIL"
```

For staging: if fails, the service may be cold-starting. Wait 30-60s and retry once.

### Phase 2: Discovery

Walk the actual app before executing later phases.

1. Route tree:
   ```bash
   ls app/routes/
   ```
   Diff against project map's entity list. New `{entity}+/` dirs get added to Phase
   5/6/9 rotations.
2. Sidebar navigation: snapshot after login, collect every link. Diff against project
   map — new menu items mean new surfaces to test.
3. DB schema:
   ```sql
   SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' ORDER BY 1;
   ```
   New tables usually map to new entities.

Log anything discovered under a **Discovered** section in the report.

### Phase 3: Login

Execute the login flow from `qa-login`. Handle post-login routing:
- `/home` (or main authenticated route): proceed.
- `/signup` (empty DB): complete signup using env file's Signup section.

### Phase 4: Seed Test Data

Follow `qa-seed` output. Usually this means running a CLI seed script that creates
deterministic, idempotent test rows.

**CLI seeding bypasses the UI.** It does not validate that forms work. UI form
interactivity is validated in Phases 6 and 7.

Verify seeded data via DB queries.

### Phase 5: List Pages

For every list page in the project map:

#### 5.1 Render
- Page loads without error
- No error boundary (project map documents the local error-boundary text marker)
- No unexpected console errors (ignore known errors from project map)

#### 5.2 Table renders
- Table body has children (use project map's table body selector, commonly
  `.mantine-Table-tbody` for Mantine apps)
- At least the seeded test row is visible

#### 5.3 Table interactions — every table must pass all
- **Global search**: type the seed prefix in the filter, verify row count decreases to
  seeded matches only; clear filter, verify row count restored.
- **Column sort**: click first sortable column header; capture top row before and after,
  assert different. Click again; assert reversed.
- **Row click**: click a seeded row; verify navigation to detail (URL changes to
  `/{entity}/{id}`).
- **Row action menu**: open per project map's row-action trigger convention (hover vs
  click). Verify menu opens with expected actions. Close without action.

Skip routes listed under "Non-testable Routes" in the project map.

### Phase 6: New Entity Forms — full validation matrix

Navigate to `/{entity}/new` for every entity with `Has /new = Yes`.

**Rendering alone is not sufficient.** Every form must pass all of:

#### 6.1 Render
No error boundary, form element exists, at least one unmasked text input is enabled.

#### 6.2 Form Interactivity Check (mandatory)

For the first enabled, unformatted text input:

1. Focus it (`$B click @eN`).
2. Type a unique sentinel (`$B type "QA_TYPE_$(date +%s)"`).
3. Read back via `$B js 'document.querySelector("input[name=\"<field>\"]").value'`.
4. Assert the returned value contains (or equals after predictable formatting) the
   sentinel.

If empty or unchanged: **FORM_INTERACTIVITY_BROKEN** — P0 regression. Record route,
field, sentinel. Do not continue to 6.3 for this form — nothing to submit.

**Why this catches bugs render-only does not:** controlled inputs (Conform, React Hook
Form, Formik) can appear interactive — focus works, native setter succeeds — yet React
resets the value because the state layer never updated. Render-only and `fill()`-only
interaction both report success in this state.

#### 6.3 Bad-value submission — validation rejects

Submit the form in at least one invalid state. Pick the cheapest that exercises the
most rules:

- **Empty form**: click Submit with no fields filled. Verify every required field
  surfaces its validation error. Verify URL did NOT change.
- **Wrong format**: for formatted fields (tax numbers, email addresses, prefix
  lengths), type an obviously wrong value and submit. Verify field-level error with
  the expected message from the schema (Zod schema in `prisma/zod/` or equivalent
  per project map).
- **Boundary**: if the schema has min/max lengths, submit one-under-min and
  one-over-max; verify rejection.

Any field that accepted bad input → **VALIDATION_GAP** finding. Either the schema
is too loose or the error surfacing is broken.

#### 6.4 Good-value submission — record persists

Fill every required field with realistic valid values from the project map's test
data templates. Submit.

- Verify URL navigates to list (or detail).
- Verify new row appears in list.
- Confirm record in DB via SQL: primary key exists, key fields match submitted.
- Record created ID for Phase 15 cleanup.

If the form has nested sub-forms (e.g. Contacts/Addresses on Client), the good-value
run must populate at least one item in each — an empty sub-form save often silently
drops the fieldset.

### Phase 7: Detail / Edit Pages

For each entity with a detail page:

#### 7.1 Load and render
Open detail for seed entity. Loader data populates the form — values match seed.

#### 7.2 Form Interactivity Check
Same as 6.2 on the first editable field. Edit and new render through different code
paths — a regression can hit one but not the other. Both must be exercised.

#### 7.3 Good edit
Change one field. Submit. Verify redirect / success. Reload detail and assert new
value persisted. Confirm in DB.

#### 7.4 Bad edit
Clear a required field or set invalid value. Submit. Verify validation error.

#### 7.5 Cancel / back navigation
Navigate away without saving intentional change. Return to detail. Verify change did
NOT persist. Catches accidentally-autosaving forms.

### Phase 8: System Pages

Test every system page from the project map (settings, org profile, billing, etc.).

For pages with forms: run the Phase 6 sequence (render → interactivity → bad → good).
For pure-display pages: verify key content present with plausible values (e.g. counts
match DB).

### Phase 8b: Mobile Responsive Spot-Check

At 375x812 viewport, spot-check 4-5 key pages listed in project map.

- No horizontal scroll on body (except declared scroll regions)
- Primary controls reachable (not clipped)
- At least one `/new` form is fillable at 375px — catches responsive-break-form case

### Phase 9: Public Pages

Test public pages without authentication (fresh browser session). Verify render, no
redirect to login on landing, signup form accepts valid input (don't complete signup —
that mutates shared state).

### Phase 10: Table Actions — Clone, Delete

On seeded documents (per project map's row-action trigger convention):

#### 10.1 Clone
On doc detail, click Clone action. Confirm dialog. Verify new draft in list with
same items, fresh ID. DB: new row referencing same client.

#### 10.2 Delete
Open row action menu using the trigger convention from project map. Click Delete,
confirm modal. Verify row removed, count -1, DB row gone.

### Phase 11: Repo-specific Integration Phases

Execute each integration phase from `qa-integrations`. Each has its own verification
logic defined by the plugin. Common examples (actual content comes from plugin):

- Document finalization (Vegleges / Finalize flows)
- PDF generation (click PDF button, verify response + file)
- Email sending (send to the env-defined test address ONLY — never any other)
- External API submission (tax authority, payment gateway, etc.)
- Billing / subscription flows (including trial-auto-convert detection)

Do NOT skip integrations silently. If an integration cannot run (e.g. local PDF
service not running), record SKIPPED_{REASON} — not pass.

### Phase 15: Cleanup

**Mandatory** — even if earlier phases fail. Follow `qa-cleanup` output.

- Delete in reverse dependency order
- Match by test-entity prefix (per project map) AND by IDs tracked during Phase 6.4/7.3
- Verify cleanup (all counts = 0)
- Do NOT delete permanent entities listed in project map (Org, UserAccount, etc.)

**Cleanup failures are P0 findings.** Non-zero leftover counts → next run collides
with stale data and mis-attributes results.

## Test Execution Notes

### gstack browse tool

```bash
B=~/.claude/skills/gstack/browse/dist/browse
```

Chain commands in a single `echo '[...]' | $B chain` call to preserve session state.

- No `sleep` or `find` — use `wait` for page load only
- Between separate `chain` calls, use shell `sleep N` to let the page settle
- Use snapshot `@e` element refs (e.g. `@e15`), NOT CSS selectors — always snapshot first

### Controlled-input gotcha

`fill` uses the native value setter and dispatches an `input` event. This can APPEAR
to succeed against a controlled input that is silently rejecting the change (React
resets on next render). **Never trust `fill` alone.** Always follow up with a DOM
value read.

For controlled inputs backed by Conform / Formik / React Hook Form, prefer
`click` + `type` (simulates real keystrokes) over `fill`, and always read back via
`$B js 'document.querySelector(...).value'`.

## Health Score

Weighted 0-100. Weights reflect **functional testing as the primary signal**.

| Category        | Weight | Covers                                                         | Scoring                                                                               |
| --------------- | ------ | -------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Functional**  | 40%    | Interactivity, table actions, navigation, validation (6.2, 6.3, 7.2–7.4, 5.3, 10, email) | Each failing interaction -10; each FORM_INTERACTIVITY_BROKEN -25; each VALIDATION_GAP -15 |
| **Data Creation** | 20% | Good-value submits + persistence (6.4, 7.3)                     | Each failed create/edit -20                                                           |
| **Integrations** | 20%   | Integration phases (Phase 11 — varies by repo)                  | Each integration failure -25                                                          |
| **Pages**       | 10%    | Render-only (5.1, 5.2, 8 render, 9 render)                      | Each failing page -5                                                                  |
| **Console**     | 5%     | Unexpected console errors                                       | 0=100, 1-3=70, 4-10=40, 10+=10                                                       |
| **Mobile**      | 3%     | 375px spot-check (8b)                                           | Each broken layout -25                                                                |
| **Public**      | 2%     | Public pages render (9)                                         | Each failing public page -50                                                          |

Ignore known console errors listed in the project map.

### Thresholds

- **≥ 90**: green. Deploy-ready.
- **70–89**: yellow. Ship with care; surface top 3 findings.
- **< 70**: red. Block deploys.

A single **FORM_INTERACTIVITY_BROKEN** anywhere drops score below 70 regardless of
everything else — this class of bug is user-blocking and must halt a deploy.

## Reporting

Output format:

1. **Top banner** — score, threshold colour, P0 findings (FORM_INTERACTIVITY_BROKEN,
   VALIDATION_GAP on a required field, integration total failure). P0s must be
   impossible to miss.
2. **Phase table** — one row per phase with pass/partial/fail + issue count.
3. **Findings detail** — for every non-pass: phase, route, field name (if relevant),
   expected, observed, sentinel/payload used, and absolute path to an actual-browser screenshot
   of the observed state.
4. **Screenshot evidence** — absolute paths for representative pass states and every failure/P0;
   screenshots must come from the real browser session used for QA, not mocked renders.
5. **Discovered** section — new routes/entities found in Phase 2 not in project map.
6. **Regression** section — if `.context/smoke-{env}-baseline.json` exists, delta vs.
   previous run (new failures, newly-passing, score delta).

Save new baseline to `.context/smoke-{env}-baseline.json` at the end.

## Safety Rules

Credentials are test-mode — safe to finalize documents, generate PDFs, test payments.

**Only hard restriction:** never send email to any address other than the test email
from `qa-env`. This is the one rule QA must never break.

**Cleanup is mandatory.** Skipping or failing cleanup is itself a P0 finding.

## Output

### On success

```
Auto-QA-Web complete (staging).
- Score: 94 / 100 (green)
- Phases: 14 pass, 1 partial, 0 fail
- Findings: 2 low-severity (see report)
- Screenshots: /absolute/path/to/.context/screenshots/staging-route-pass.png, /absolute/path/to/.context/screenshots/staging-finding.png
- Baseline saved: .context/smoke-staging-baseline.json
```

### On failure (P0)

```
Auto-QA-Web FAIL (staging).
- Score: 62 / 100 (red)
- P0: FORM_INTERACTIVITY_BROKEN on /clients/new (field: name)
- Phase: 6.2
- Evidence: sentinel "QA_TYPE_1234" typed; DOM value read: ""
- Screenshot: /absolute/path/to/.context/screenshots/staging-clients-new-form-interactivity-broken.png

This blocks deploy. Investigate controlled-input state before merging.
```

### On skipped

```
Auto-QA-Web skipped — no .claude/skills/repo-plugin/SKILL.md in repo.
```

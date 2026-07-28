# Ticket Verify — Visible Surfaces

Load this reference only when acceptance includes a UI, rendered document, email preview, chart,
public page, or other browser-visible state.

## Environment boundary

Grade rendering on staging by default. The same frontend code normally reads the same table shapes
in both environments, so a production browser session usually adds attack surface without
improving the verdict.

- On staging, open the actual surface in a real browser and grade the visible behavior.
- On production, grade only deployed-code containment and the read-only production data
  precondition. Reuse the recorded staging visual PASS.
- A narrow production exception exists only when `bin/environment-capability` confirms exact
  topology with `staging_available: false`, the acceptance contract is genuinely
  production-only, the user explicitly authorized production browser verification, and the
  requested verifier mode matches the registry. Any missing gate stays staging-first.

For that exception, preflight and record every requirement before opening the page, pass the
corresponding flags to `bin/environment-capability`, and require
`production_visible_surface_allowed: true`:

1. the server enforces a short expiry and rejects expired/disabled/unconfigured access;
2. authorization is structurally read-only, denies every mutation route/method, and is scoped to
   the exact project/surface;
3. the token travels in a secret-safe transport and never appears in URLs, screenshots, logs, DOM,
   persisted browser state, or evidence text;
4. a real browser producer is available and can capture the rendered state; HTTP/API reads do not
   substitute; and
5. every non-browser producer required by the evidence contract is separately preflighted.

The backdoor is authentication only. It does not prove browser execution capability, deployed
frontend availability, data producers, or acceptance behavior. Failure of any preflight is
`BLOCKED`, not an authorization bypass or inferred PASS.

Before grading, confirm the change is on `origin/staging` and the staging surface serves it. If it
reached only `main`, return `BLOCKED` with: **needs to be deployed to staging as well, not only
main**. Waiting cannot fix a missing staging deployment.

## Screenshot evidence

On staging, authenticate through `.claude/environments/staging.md`. For the authorized
production-only exception, use only the registered short-lived read-only verifier transport.
Read credentials at runtime without printing or persisting them. Capture the actual surface in a
real browser and store screenshots only as temporary run-scoped scratch.

The durable evidence artifact records the target URL, browser actions, asserted visible state,
and a concise screenshot description or durable uploaded URL. Delete temporary screenshots after
persistence unless the user explicitly asked to retain them. If capture is impossible, record the
exact blocker and return `BLOCKED` or `FAIL` as appropriate.

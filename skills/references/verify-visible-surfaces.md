# Ticket Verify — Visible Surfaces

Load this reference only when acceptance includes a UI, rendered document, email preview, chart,
public page, or other browser-visible state.

## Environment boundary

Grade rendering on staging. The same frontend code normally reads the same table shapes in both
environments, so a production browser session adds write-capable attack surface without improving
the rendering verdict.

- On staging, open the actual surface in a real browser and grade the visible behavior.
- On production, grade only deployed-code containment and the read-only production data
  precondition. Reuse the recorded staging visual PASS.
- A genuine production-only flag or unreproducible data shape requires a human-in-the-loop spot
  check, never standing autonomous production browser tooling.

Before grading, confirm the change is on `origin/staging` and the staging surface serves it. If it
reached only `main`, return `BLOCKED` with: **needs to be deployed to staging as well, not only
main**. Waiting cannot fix a missing staging deployment.

## Screenshot evidence

Authenticate through `.claude/environments/staging.md`. Read credentials at runtime without
printing or persisting them. Capture the actual surface and store screenshots only as temporary
run-scoped scratch.

The durable evidence artifact records the target URL, browser actions, asserted visible state,
and a concise screenshot description or durable uploaded URL. Delete temporary screenshots after
persistence unless the user explicitly asked to retain them. If capture is impossible, record the
exact blocker and return `BLOCKED` or `FAIL` as appropriate.

# Ticket Verify — Failure Knowledge Capture

Load this reference only after a staging or production `FAIL` has been persisted and the ticket
status updated.

Search for duplicate knowledge first:

```text
mcp__autodev_memory__search(
  queries=[{"keywords": ["<feature area>"], "text": "<failure summary>"}],
  project=PROJECT, repo=REPO, detail="compact"
)
```

If no existing entry covers the lesson, create a gotcha containing the ticket/environment, failed
evidence row, expected versus observed output, known cause or evidence-artifact ID, and what
planning/build should do differently. Tag it with `verification` and the feature area, use source
`captured`, and set caller context to skill `ticket-verify` with trigger `verify FAIL <env>`.

If the memory tool is unavailable, skip silently; the ticket evidence remains authoritative.

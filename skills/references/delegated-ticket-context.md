# Delegated ticket-context hydration

Bulk autodev-memory reads belong in a fresh context-curator child, never in the ticket-flow parent.
The parent may resolve identity and lifecycle from one light manifest. Artifact bodies, relevant
memories, and similar-ticket evidence are read only by the curator. The parent receives one relevant,
phase-specific packet plus its receipt.

## Dispatch

Dispatch immediately after ticket resolution. For bugs without a confirmed investigation, run or
resume `/investigate` first, then dispatch the curator after the investigation artifact is
persisted.
If investigation changes later, discard the old packet and curate once from the new
`context_version`.

- Always use `fork_turns: "none"`. The ticket ID, project, repo, complete light manifest plus
  `context_version`, current phase, objective, target, risk boundaries, current changed paths/diff
  summary when available, and absolute packet directory are the complete task prompt. The curator
  must not repeat that manifest read.
- Claude: use the `context-curator` agent on `sonnet`. Escalate this retrieval-only child to `opus`
  only when current authoritative artifacts materially contradict each other or a safety-critical
  omission cannot be adjudicated mechanically.
- Codex: spawn a read-only context-curator child on `gpt-5.6-luna`. Prepare its self-contained
  prompt with `bin/managed-codex-delegation`; do not fork parent history. If Luna is unavailable,
  use the smallest available Codex model, not the parent model by default.
- Do not dispatch one curator per artifact. One curator owns the light manifest, every current
  artifact body, the consolidated memory search, similar-ticket evidence, selection, and receipt.
- Block once for its result. Do not poll it or stream its intermediate MCP output into the parent.

## Main-thread boundary

The parent reads only the curator's fixed return envelope and the resulting packet. The packet has no
fixed byte ceiling: it is as long as necessary to retain all decision-bearing context, while excluding
raw source prose, duplicates, unrelated history, generic memories, and other facts whose omission
cannot change the phase outcome. It must not replay `get_artifact`, memory search, entry expansion,
or similar-ticket calls to verify the curator. Validate the receipt instead:

```bash
bin/workflow-ticket-context-check receipt <absolute-context-receipt.json>
```

Downstream planner, build-planner, delivery, test, and review children receive the packet path and
hash. They may retrieve one specifically missing fact only when they name it and the curator omitted
it; route that request through one targeted curator refresh. Never fall back to loading every ticket
artifact in the parent.

Reuse requires an exact match on `context_version`, phase, and the curator's task fingerprint over
objective, risks, and diff inputs. A version match alone is insufficient. Never truncate the packet
to satisfy an arbitrary byte target. If the packet contains irrelevant material, refresh it with a
stricter relevance pass rather than moving raw hydration into the parent.

## Relevance and completeness

The curator reads all current artifact bodies before filtering, but returns only decision-bearing
facts for the named phase. Applicable memories are selected through consolidated semantic/tag
queries plus a repo/project-scoped inventory of relevant entry types, then expanded in the child.
The entire unrelated memory corpus is never dumped. The packet must retain:

- user requirements, acceptance criteria, approved plan decisions, and explicit exclusions;
- confirmed root cause and causal evidence for bugs;
- current deployment, schema, security, data-integrity, and cross-repo constraints;
- applicable gotchas, solutions, preferences, and lessons from completed or failed tickets;
- contradictions, stale assumptions, and missing evidence that could change the phase outcome;
- provenance IDs/hashes and a short list of reviewed material omitted as irrelevant.

A lifecycle-only refresh after the packet is built uses the light manifest with the cached
`context_version`. A new version requires one curator refresh only when an artifact or comment
needed by the current phase changed.

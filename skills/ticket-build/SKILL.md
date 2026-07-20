---
name: ticket-build
description: >-
  Implementation phase for one planned ticket: build todos, build, adaptive review, resolve
  findings, and the local health gate. Thin orchestrator over create-build-todos, build, review,
  and resolve-review; does not plan, land, deploy, or verify environments.
max_turns: 300
---

# Ticket Build

Implement one ticket that already has a `plan` artifact, through a locally verified tree with all
build/review artifacts persisted. This is an orchestrator over existing phase owners
(`/create-build-todos`, `/build`, `/review`, `/resolve-review`); it does not reimplement them and
does not land, merge, deploy, or run environment verification — those belong to `/ticket-deploy`.

## Usage

```text
/ticket-build F0123
```

## Prerequisites

- Ticket exists, non-terminal, with a `plan` artifact (run `/ticket-plan` first otherwise).
- Repo matches the ticket's `repo`; for epic steps, the caller (normally `/ticket-flow`) supplies
  the epic context extract.

## Process

Follow `../references/execution-phases.md` and `../references/execution-economy.md`.

1. **Load context once.** `get_ticket(detail="full", artifact_types=["source", "plan"],
   include_events=false)`; cache the response. Carry forward the planner's prior-knowledge blob
   into the build and review packets so builders and reviewers inherit the same knowledge without
   re-searching.
2. **Honor dashboard review comments.** Check `open_comment_count`; if the user left open review
   comments on the plan/source, resolve them (revise via `/ticket-plan` when the plan itself must
   change) before building. Do not build past unresolved feedback. There is no `approved` status;
   leaving `planned` means setting `in_progress`.
3. **Build todos.** Invoke `/create-build-todos` to derive MCP `build_todo` artifacts from the
   plan (it also finalizes the `deployment_guide`).
4. **Implement.** Invoke `/build`: one builder per todo in dependency order, focused tests, keep
   unrelated lint/type fixes in a separate commit.
5. **Review and resolve.** Invoke the `/review` skill (do not hand-roll it): it chooses the
   light/heavy native path, conditionally escalates peers, synthesizes once, and hands actionable
   findings to `/resolve-review`. Apply the conditional coverage gate in `execution-phases.md`
   only when peer escalation fired. Stop for unresolved design decisions.
6. **Persistence gate.** Confirm via `get_ticket(detail="light", artifact_types=["build_todo",
   "review_todo"], include_events=false)` that the ticket carries its `build_todo` artifacts and
   the `review_todo` artifacts the adaptive review wrote — building and reviewing in-session is
   not enough; those artifacts are the durable, auditable record. If a `create_artifact` call
   silently no-op'd (common on cross-provider/Codex MCP paths), re-issue it now. A ticket must
   not proceed to landing with only a `source` artifact.
7. **Local health gate.** Reuse `/build`'s full health-gate PASS when it is keyed to the current
   tree SHA and exact command; run only focused checks added after review resolution. If
   review/fixes changed the tree, run the full health gate once for that new final SHA. Do not
   query staging/prod as verification and do not trigger flows/processes.
8. **Push.** Ensure the feature branch is pushed to the remote (no PR — `/auto-deploy` creates
   the PR at deploy time).

### Phase checkpoints, rotation, and command output

- Build-todo creation, implementation, review, review resolution, and final health are durable
  phase boundaries. Persist the current MCP artifacts and tree SHA at each boundary, then start the
  next phase in a fresh `fork_turns: "none"` agent with only its bounded checkpoint/packet.
- Choose and record a fixed context/token budget for every phase owner. Force replacement after the
  first compaction or when the budget is reached, whichever happens first. A replacement receives
  only the persisted checkpoint and phase-specific packet; never continue an indefinitely growing
  agent merely because it still responds.
- Tests, builds, migrations, large diffs, and other noisy commands must use `bin/compact-exec` or an
  established equally compact stricter wrapper. Full output stays in the log; the model receives
  only the bounded summary/tail. On failure, report the absolute `output_file` and exact
  `rerun_command` before routing the fix.

## Output

```text
Ticket build complete: F0123
Branch: {branch} (pushed)
Build todos: {n} completed; review: {light|heavy}, {n} findings resolved
Local health gate: PASS ({command} @ {sha})
Artifacts: build_todo x{n}, review_todo x{n} persisted
Next: /ticket-deploy F0123 staging|prod|full
```

On failure, report the exact phase, evidence, and the unresolved decision or failing check.

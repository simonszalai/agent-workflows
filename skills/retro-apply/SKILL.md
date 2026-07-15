---
name: retro-apply
description: Apply accepted session-retro workflow recommendations through one fresh bounded maintainer context, preventing the original long session from being replayed during implementation.
---

# Retro Apply

Apply only the session-retro recommendations the user explicitly accepted. This is the execution
half of `session-retro`; it does not remeasure the session or reconsider rejected findings.

## Mandatory context boundary

The current parent is an orchestrator only. It must not read implementation targets, edit files,
inspect the resulting diff, run tests, create or merge the PR, or poll CI.

1. Write one compact packet to `.context/session-retro/<run-id>/accepted-change-packet.md`.
2. Spawn exactly one workflow-maintainer agent with `fork_turns: "none"`. Give it only the packet
   path, the exact repository/workspace path, and the instruction to follow `/workflow-authoring`.
3. Block once for its terminal result. Do not poll the child or wake the parent for intermediate
   approvals, CI states, or progress updates.

If the host cannot create a fresh child context, stop after writing the packet and return its path
with the instruction to invoke `/retro-apply --packet <path>` in a fresh session. Never silently
fall back to implementation in the large parent context.

```text
Agent(
  subagent_type="general-purpose",
  name="retro-apply-maintainer",
  fork_turns="none",
  prompt="Use /retro-apply in maintainer mode. Packet: <absolute packet path>. Workspace: <absolute linked agent-workflows workspace>. Follow /workflow-authoring, complete the PR lifecycle, and return only the compact terminal result."
)
```

## Change packet contract

Keep the packet self-contained and at most 12 KiB. It contains:

- source retro/session reference and accepted recommendation IDs;
- exact finding and measured evidence for each accepted ID;
- requested behavior, exact target paths/line anchors, and expected savings;
- quality/safety constraints and explicit non-goals;
- repository path, target branch, dirty-worktree constraints, and relevant project rules;
- known dependencies or tickets and whether they are implementation scope;
- required focused regression coverage;
- the final command `bin/check-agent-workflows` and required PR/propagation procedure.

Do not embed transcripts, whole skill files, broad command output, or recommendations the user did
not accept. References to files outside the packet are allowed only when the fresh maintainer can
read them from the stated workspace.

## Maintainer mode

When invoked by the fresh agent with `--packet` or an explicit packet path:

1. Validate that the packet names accepted IDs, an exact workspace, targets, constraints, tests,
   and the final gate. Reject an incomplete or oversized packet instead of rediscovering the parent
   session.
2. Work only in the linked/current clean `agent-workflows` workspace. Follow
   `/workflow-authoring` for bounded reads, implementation, one final health gate, PR handling, and
   truthful live-propagation verification.
3. Expand scope only for a concrete code reference or failing contract test; record that expansion
   in the PR summary. Never reread the original session transcript.
4. Return one compact terminal result: accepted IDs, changed paths, tests, PR and merge SHA,
   workspace cleanliness, local propagation status, and any genuinely blocked item.

## Stop rules

- One fresh implementation agent, not one agent per recommendation.
- Never inherit or replay the full parent conversation.
- No implementation before the packet exists.
- No second full health run on an unchanged final tree.
- Remote merge and local propagation remain separate facts.

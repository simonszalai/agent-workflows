# Memory delivery provider matrix

Memory delivery is classified by **provider** and **delegation mechanism**. A model name is not
a provider: Fable remains a Claude workflow/model variant.

| Runner | Parent session | Managed child | External CLI child | Duplicate prevention |
|---|---|---|---|---|
| Claude | `SessionStart` packet v2, <=9K final context | `PreToolUse(Agent)` rewrites `tool_input.prompt` with one <=3K task packet | `external-agent --provider claude --memory-context-file …` | adapters set `AUTODEV_MEMORY_EXPLICIT_PACKET=1` |
| Codex | `SessionStart` packet v2 when the host supports configured hooks | prepare the `spawn_agent` message with `managed-codex-delegation`; native child SessionStart is not assumed | `external-agent --provider codex --memory-context-file …` or `external-build --memory-context-file …` | explicit helper marker + adapter suppression |
| Grok | no supported ambient parent hook in this repository | no managed-child integration | `external-agent --provider grok --memory-context-file …` | adapter suppression environment |

## Contract

1. Parent clients request `context_version: "v2"` from `/session-init`.
2. The server selects and semantically budgets parent text to 8700 characters, reserving 300
   characters for the adapter's wrapper inside the 9000-character delivery budget. Clients validate declared
   character count and render hash, then add only a small wrapper. Clients never rebuild a full
   catalog, reconstruct topology, or slice a rendered rule.
3. A legacy response may contribute only its already bounded `digest.text`. Full legacy starred
   bodies and the title menu are not a fallback.
4. Session cache files are atomic mode 0600 and keyed by session, project, repo, packet version,
   corpus generation, and render hash. A different session cannot inherit a repo-wide cache.
5. Managed task packets combine the producer's <=1800 `child_base_text` with strict
   repo-scoped `/entries/by-skill` summaries and remain <=3000 characters. Search/expand handles
   retrieve full bodies only when needed.
6. Logs/telemetry record only event time, provider, mechanism, status, packet version, and
   character count. They never store packet bodies, prompts, queries, paths, entry IDs, tokens,
   or environment values.

## Managed Codex example

```bash
bin/autodev-memory-task-packet \
  --cwd "$PWD" --session-id "$SESSION_ID" --agent-type reviewer \
  --provider codex --mechanism managed_delegation > /tmp/memory-packet

bin/managed-codex-delegation \
  --cwd "$PWD" --session-id "$SESSION_ID" --agent-type reviewer \
  --message-file /tmp/child-message > /tmp/managed-child-message
```

Pass the contents of `/tmp/managed-child-message` as the managed `spawn_agent` message. The
helper prepares context only; the workflow still owns the spawn, result collection, and synthesis.

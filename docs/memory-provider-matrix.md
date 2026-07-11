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
5. Managed task packets combine the producer's <=1800 `child_base_text` with strict repo-scoped
   `/entries/by-skill` results and a compact semantic search over the actual task prompt. The prompt
   travels on stdin and in the authenticated request body, never argv or local logs. Selection keeps
   2–5 full IDs plus corpus generation internally. External agents that have no memory tool receive
   pre-expanded bodies only when whole bodies fit the <=3000 budget; otherwise the packet explicitly
   says expansion/body delivery was unavailable.
6. Local telemetry separates base delivery, selection attempt/result, expansion result, and final
   delivery. It stores counts/status and memory entry IDs but never packet bodies, prompts, queries,
   paths, tokens, or environment values. A keyed local-only session pseudonym joins the compliance
   audit; the default report never emits that pseudonym or prompt hashes.
7. The bounded v1 digest fallback sunsets on **2026-08-15** (earlier with
   `AUTODEV_MEMORY_DISABLE_V1=1`). Remove its code after seven consecutive production days with zero
   `parent_packet status=fallback` events. `AUTODEV_MEMORY_ALLOW_V1_UNTIL=YYYY-MM-DD` exists only for
   an explicitly approved, time-bounded rollback window.

## Managed Codex example

```bash
bin/autodev-memory-task-packet \
  --cwd "$PWD" --session-id "$SESSION_ID" --agent-type reviewer \
  --provider codex --mechanism managed_delegation --task-prompt-stdin \
  < /tmp/child-message > /tmp/memory-packet

bin/managed-codex-delegation \
  --cwd "$PWD" --session-id "$SESSION_ID" --agent-type reviewer \
  --message-file /tmp/child-message > /tmp/managed-child-message
```

Pass the contents of `/tmp/managed-child-message` as the managed `spawn_agent` message. The
helper prepares context only; the workflow still owns the spawn, result collection, and synthesis.

## Local compliance audit

```bash
python3 ~/.agents/skills/deep-dream/scripts/audit_memory_compliance.py --days 7
```

The default report contains only coarse classifications and counts. Use
`--restricted-diagnostics` only for a live local investigation; its prompt hashes are keyed with a
new random key per run and must not be persisted or uploaded.

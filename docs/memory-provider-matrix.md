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
6. Local telemetry separates base delivery, selection attempt/result, expansion result, packet
   preparation, and mechanism-owned confirmation. `parent_packet_prepared` and `packet_prepared`
   never prove delivery. A `parent_packet` confirmation is emitted only after the exact outer
   SessionStart JSON write succeeds (`session_start_output_emitted`). A
   `child_packet` confirmation is emitted only after Claude's PreToolUse JSON has been emitted
   (`pretool_output_emitted`) or an external provider returned a validated structured response
   (`validated_provider_response`); timeout/crash/invalid output remains unconfirmed. Telemetry
   stores counts/status and memory entry IDs but never packet bodies, prompts, queries,
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

The default report contains typed mechanism/status, packet version, corpus generation, and counts.
It omits entry IDs, delivery IDs, render hashes, prompts, bodies, and locators. Use
`--restricted-diagnostics` only for a live local investigation; its IDs and prompt/render hashes
must not be persisted or uploaded (prompt hashes use a new random key per run).

## Deployment-time evidence gate (not satisfied by this repository's unit tests)

Cloud installation and real-provider delivery are deployment evidence. Do not mark them PASS from
the synthetic fixtures. In each cloud image/session, pin the reviewed commit and use the same
transactional installer as local environments:

```bash
test "$AGENT_WORKFLOWS_COMMIT" = "$(git -C "$AGENT_WORKFLOWS_CLONE" rev-parse HEAD)"
"$AGENT_WORKFLOWS_CLONE/bin/install-agent-workflows" \
  --source "$AGENT_WORKFLOWS_CLONE" --home "$HOME" --version "$AGENT_WORKFLOWS_COMMIT"
python3 "$HOME/.agents/skills/deep-dream/scripts/audit_memory_compliance.py" \
  --days 1 > "$EVIDENCE_DIR/memory-delivery-audit.json"
```

The deployment runner must additionally execute one real canary for each supported mechanism:
Claude parent SessionStart and Agent child, Codex parent and managed collaboration child, and one
external adapter invocation (Fable is recorded under its actual Claude/Codex provider). Save a
metadata-only evidence document with this allowlisted shape:

```json
{
  "agent_workflows_commit": "<40-hex commit>",
  "environment": "staging|production",
  "installer": {"status": "observed_pass|observed_fail", "current_commit": "<40-hex>"},
  "mechanisms": [
    {"provider": "claude|codex|grok", "mechanism": "<stable slug>",
     "status": "delivered|partial|unavailable", "packet_version": "v2|v1|unknown",
     "corpus_generation": "<generation or unknown>", "selected_count": 0,
     "expanded_count": 0, "chars": 0}
  ]
}
```

The evidence must contain no packet/prompt body, path, token, environment value, entry ID, delivery
ID, or render hash. IDs and hashes are available only in a local `--restricted-diagnostics` run and
must not be copied into deployment evidence. Missing canaries remain `unavailable`/not run; they are
never inferred from installation success.

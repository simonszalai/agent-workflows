# Hermes activation provider

`bin/hermes-activation` is the reviewed E0006 M3 provider for creating the two Hermes
credentials, applying the restricted-memory policy to one Render key, recovering one exact
deploy, and running one bounded direct-memory canary. Its command and output contract is
`e0006-m3/v1`.

F0023 only builds and fake-tests the provider. It does not create a real 1Password item, call
Render or autodev-memory, edit or reload the MCP gateway, deploy code, or run a live canary.
F0033 owns the direct-memory activation and evidence. F0021 later consumes the closed handoff and
owns the gateway environment/reload.

## Sensitive invocation boundary

Every production invocation uses one command-local, operation-specific reason and the reviewed
1Password shim:

```bash
SENSITIVE_ACCESS_REASON='E0006/M3 F0033 Hermes activation' \
OP_BIN="$HOME/dev/agent-workflows/bin/op" \
bin/redacted-exec -- bin/hermes-activation items ensure
```

Use the same prefix for every command below. The provider's typed allowlist is the primary
disclosure boundary; `redacted-exec` is secondary defense in depth. Do not use direct `op`,
`OP_DESKTOP=1`, ambient secret exports, raw output logs, or `compact-exec`.

The provider accepts test endpoint overrides only when its explicit test mode is set, and then
only for loopback HTTP. Production hosts, refs, service IDs, key names, policy fields, polling
intervals, and deadlines cannot be supplied on the command line.

## Frozen identifiers

| Purpose | Identifier |
|---|---|
| Contract and stdout schema | `e0006-m3/v1` |
| Vault | `AUTODEV-sensitive` |
| Memory item | `HERMES_AUTODEV_MEMORY_TOKEN` |
| Memory ref | `op://AUTODEV-sensitive/HERMES_AUTODEV_MEMORY_TOKEN/password` |
| Gateway item | `HERMES_GATEWAY_TOKEN` |
| Gateway ref | `op://AUTODEV-sensitive/HERMES_GATEWAY_TOKEN/password` |
| Existing Render credential | `op://AUTODEV-sensitive/AUTODEV_RENDER_API_KEY/value` |
| Render service | `srv-d70oq214tr6s73ch3dbg` |
| Render key | `AUTODEV_MEMORY_RESTRICTED_TOKENS` |
| Direct memory base | `https://autodev-memory.onrender.com` |
| Memory transports | `/mcp`, `/tickets/workflow/batch` |

F0020's checked-in routes use `HERMES_AUTODEV_MEMORY_TOKEN` as the memory upstream ref and
`HERMES_GATEWAY_TOKEN` as the client ref. This provider consumes those names without changing
routes or expanding Hermes' Render tools.

## Public commands

There are five operations. No generic URL, ref, vault, item, service, key, body, header, policy,
tool, project, repo, title, or file-input flag exists.

### Ensure the two Password items

```bash
bin/hermes-activation items ensure [--receipt /absolute/path/to/SAFE_JSON]
```

The command lists the exact vault and Password category once. For each absent canonical title it
uses 1Password's built-in Password generator; it never sends a password assignment, template, or
value in argv or stdin. It reads each canonical ref once in process memory, requires two usable,
distinct values, and returns only this ordered result:

```json
{
  "schema": "e0006-m3/v1",
  "command": "items ensure",
  "status": "pass",
  "result": {
    "items": [
      {
        "name": "HERMES_AUTODEV_MEMORY_TOKEN",
        "ref": "op://AUTODEV-sensitive/HERMES_AUTODEV_MEMORY_TOKEN/password",
        "item_id": "opaque-id",
        "state": "created"
      },
      {
        "name": "HERMES_GATEWAY_TOKEN",
        "ref": "op://AUTODEV-sensitive/HERMES_GATEWAY_TOKEN/password",
        "item_id": "opaque-id",
        "state": "existing"
      }
    ]
  }
}
```

If either item was newly created and a later create/read fails, `partial_item_ensure` preserves
every safely validated receipt through the current item, including a newly created second item.
Do not delete those items; rerun the same command. Duplicate titles, IDs, values, a wrong
vault/category, blank or malformed data, or CLI drift fail closed.

### Apply active or inert memory configuration

```bash
bin/hermes-activation memory apply --mode active [--receipt /absolute/path/to/SAFE_JSON]
bin/hermes-activation memory apply --mode inert [--receipt /absolute/path/to/SAFE_JSON]
```

Active mode composes exactly one restricted-policy element in memory for project `autodev`,
origin `hermes`, knowledge read, tickets read/write, epics none, config read, and approvals none.
Inert mode uses literal `[]` and does not read the Hermes memory ref.

Both modes read the existing Render credential, issue one per-key `PUT` for the frozen
service/key, require the documented exact `key`/`value` response in memory, and then issue one
explicit same-service deploy trigger with `do_not_clear`. Deploy responses accept only documented
fields and require the exact deploy ID; response material is discarded after validation. The
provider never lists, reads, or replaces the whole environment. The result contains only `mode`,
`service`, `key`, and opaque `deploy_id`.

The official trigger contract has no idempotency key and can return an accepted response without
a deploy ID. A transport loss after acceptance is likewise ambiguous. Therefore any non-exact
trigger result after the key write returns `deploy_trigger_unknown_after_env_write`, state
`unknown`, and exit 5. **Do not retry either mode and do not start the opposite mutation.** Root
must reconcile the accepted action manually in Render and recover its exact deploy ID; this
provider intentionally does not invent a list/reconciliation endpoint.

### Wait for one exact deploy

```bash
bin/hermes-activation render wait \
  --deploy-id DEPLOY_ID \
  --timeout-receipt /absolute/path/to/PRIVATE_JSON
```

The command polls only the exact service/deploy pair at a fixed interval for at most 20 minutes.
The closed status inventory is:

- running: `created`, `queued`, `build_in_progress`, `pre_deploy_in_progress`,
  `update_in_progress`;
- success: `live`;
- terminal non-PASS: `deactivated`, `build_failed`, `pre_deploy_failed`, `update_failed`,
  `canceled`.

An unknown status is protocol drift. Timeout is state `unknown`, never PASS. The provider writes
a mode-0600 receipt with only schema, service, deploy ID, unknown state, and start/deadline
timestamps, then returns the exact safe same-ID wait command.

### Emergency exact-ID cancellation

```bash
bin/hermes-activation render cancel \
  --deploy-id DEPLOY_ID \
  --timeout-receipt /absolute/path/to/PRIVATE_TIMEOUT_JSON \
  --canceled-receipt /absolute/path/to/PRIVATE_CANCELED_JSON
```

Cancellation is an emergency recovery action requiring root/operator authorization outside the
provider. The command rejects symlinks, wrong ownership/mode, schema drift, or any receipt whose
service/deploy ID does not exactly match. It first proves the deploy remains in a documented
running state, atomically writes `cancel_requested`, cancels only that ID, validates documented
response fields, and waits until the exact ID reports `canceled`. A lost cancel response or poll
timeout returns `cancel_unknown` with the same-ID resume command. Resume recognizes
`cancel_requested` or an already-canceled deploy and never replays the POST.

Cancel does not apply inert. After cancellation is proven, the operator separately applies inert,
waits for the new ID, and proves the restricted configuration summary is false-zero.

### Run the phased direct-memory canary

```bash
bin/hermes-activation memory canary \
  --phase prepare \
  --state-receipt /absolute/path/to/PRIVATE_STATE_JSON \
  --preflight-receipt /absolute/path/to/FRESH_TRUE_ONE_JSON

bin/hermes-activation memory canary \
  --phase after-approval \
  --state-receipt /absolute/path/to/PRIVATE_STATE_JSON

bin/hermes-activation memory canary \
  --phase after-reapproval \
  --state-receipt /absolute/path/to/PRIVATE_STATE_JSON

bin/hermes-activation memory canary \
  --phase cleanup \
  --state-receipt /absolute/path/to/PRIVATE_STATE_JSON
```

`prepare` requires a fresh closed `e0006_m3_summary_preflight/v1` receipt with status PASS,
valid count one, invalid count zero, an evidence ID, and observation timestamp. It creates one
randomly suffixed synthetic repo and one feature ticket/source, then proves:

1. the current public `create_ticket` schema returns the exact ticket ID, readback matches the
   fixed repo/title/tag marker, origin is server-stamped `hermes`, the unsafe status is clamped,
   and exactly one source artifact exists;
2. MCP `update_ticket` and the REST workflow-batch schema produce their exact denial envelopes and
   leave the ticket unchanged;
3. a fixed `tags.canary_probe` write to human-origin F0033 is denied and the complete targeted
   `tags` field is unchanged;
4. restricted `update_ticket(..., approve_execution=true)` is denied;
5. one atomic batch creates the plan and moves the owned ticket to planned, then scoped pickup is
   empty.

The receipt then says `awaiting_admin_approval`. The connected admin MCP, never this provider,
approves that exact ticket. `after-approval` proves the approval, performs one Hermes metadata
edit, proves approval fields cleared, and proves pickup remains empty. The receipt then says
`awaiting_admin_reapproval`; the admin MCP reapproves the same ticket.

Both approval readbacks require the atomic pair: non-null timestamp plus
`execution_approved_by=admin`. The owner edit must clear both fields together.
`after-reapproval` proves the fresh pair and exact scoped pickup, then cleans up to abandoned,
null approval, and empty pickup. `cleanup` is idempotent, recognizes an already-abandoned ticket,
and is available after any partial failure or deadline. If create acceptance was ambiguous before
the ticket ID was returned, cleanup first reruns only the fixed random-repo selector, requires one
exact matching ticket, checkpoints its ID, and then abandons it; it never retries create. Cleanup
failure after identity recovery is terminal even if earlier checks passed. A selector with zero or
multiple matches remains state `unknown` for root/manual reconciliation rather than authorizing a
racing mutation. The abandoned ticket and its artifacts remain as audit history.

The mechanically enforced whole-chain caps are one synthetic repo, one ticket, one source, one
plan, zero entries/epics/schedules/fan-out, at most 24 provider HTTP requests, two external admin
actions, eight accepted ticket/artifact mutations, two embedding-producing writes, and five
minutes. The receipt is written before the first provider request and before every later request
reservation. Timestamps, phases, ordered check codes, and nonnegative integer counters are closed
and tamper-checked. Normal work is capped at 20 requests; four dedicated cleanup requests and one
cleanup mutation remain reserved inside the same 24/8 total ceilings. Cleanup uses the mutation
acknowledgment as its closed post-state proof, so the reserve also covers fixed-selector recovery
when an accepted create lost its ticket ID. No normal phase runs after the preserved deadline;
cleanup remains allowed. A nonterminal receipt is never overwritten: resume its recorded phase or
run `cleanup`.

## Exit codes and failures

| Code | Meaning |
|---:|---|
| 0 | Typed PASS |
| 2 | CLI usage |
| 3 | Local contract or preflight failure |
| 4 | External terminal/protocol failure |
| 5 | Unknown timeout/state requiring same-ID resume or cleanup |
| 6 | Canary cleanup failure |

Stdout is one closed object with only `schema`, `command`, `status`, and `result`. Failure results
contain a fixed code and only safe identifiers needed for recovery. Exception text, external
bodies, headers, argv, environment, C4 bytes, token values, value lengths, and digests never cross
the boundary. Optional output and state receipts are bounded, atomic, owned by the caller, and
mode 0600.

## Production activation order

Only after the reviewed F0023 merge is live:

1. F0033 proves the restricted summary is false-zero.
2. Run item ensure.
3. Apply active, wait on its exact ID, and prove true-one plus the admin smoke matrix.
4. Apply inert, wait on its exact ID, and prove false-zero plus admin smokes.
5. Reapply active using the same ref, wait on its exact ID, and prove true-one plus admin smokes.
6. Run the phased direct canary with two admin approvals and terminal cleanup.
7. F0033 emits one strict `e0006_m3_memory_handoff/v1` artifact.
8. F0021 validates the handoff, writes only the two ref names to its approved gateway destination,
   validates, reloads once, and runs its cross-layer matrix.

For every deploy timeout, rerun wait on the same ID first. After a second bounded timeout,
emergency cancellation is permitted only with root authorization and the matching safe timeout
receipt. Prove canceled before applying inert. Never start an opposite mutation while a prior
deploy is unknown.

## Closed F0033-to-F0021 handoff

`e0006_m3_memory_handoff/v1` is a closed PASS-only object:

- `schema`, `status`;
- `provider`: F0023, `bin/hermes-activation`, contract/output schema, reviewed merge and tree IDs;
- ordered `items`: the two canonical names/refs, distinct opaque IDs, and
  `created|existing`;
- ordered `deployments`: `initial_active`, `inert`, `final_active`, distinct deploy IDs, terminal
  `live`, and exact true-one/false-zero/true-one counts;
- `admin_matrix`: evidence ID and PASS;
- `direct_canary`: run, ticket, evidence IDs, PASS, and cleanup PASS;
- final F0033 evidence artifact ID.

Unknown or missing fields, duplicate labels/IDs, non-PASS state, failed cleanup, or a field named
for a bearer, secret, password, token, value, body, header, C4, digest, or length blocks F0021.
The handoff contains ref names, never resolved values or secret-derived material.

## Rollback

Before a consumer uses the provider, code rollback is an ordinary revert of the reviewed provider
merge. After any active application, runtime rollback comes first: apply inert through the same
reviewed provider, wait on that new exact deploy ID, prove false-zero, and retain the safe
receipts/evidence. Only then consider reverting provider code.

No rollback deletes the policy migration or the canary/audit rows. A key-write/deploy-trigger
unknown boundary requires root/manual Render reconciliation and exact-ID recovery before any
retry, opposite mutation, or rollback proceeds.

# Terminal Outcome and Closeout Contract

Use this contract at the end of every staging, production, deployment, promotion, or verification
run. It makes the terminal state unmistakable and prevents a successful command from being
mistaken for a ticket that is safe to forget.

## 1. Run the post-check before choosing the banner

After the operation reaches a terminal result, inspect the scope once more:

1. **Lifecycle truth:** re-read the canonical ticket/epic after the final mutation. Confirm the
   persisted status, blocker metadata, and expected next lifecycle owner. Never trust only the
   preceding update response or an in-memory status.
2. **Evidence and artifacts:** confirm required deployment/verification evidence artifact IDs
   exist and cover every acceptance/evidence row. Check for unresolved plan, build, review,
   deployment-guide, verification, or cleanup items that still belong to this scope.
3. **Repository and release state:** for every repository/worktree touched by this run, use
   narrow status/ref checks to confirm there are no unexpected uncommitted changes, unpushed
   commits, open/conflicted PR state, partially applied deploy steps, or temporary worktrees.
   Never sweep or alter unrelated work to make this check green.
4. **Cleanup:** confirm run-owned scratch files, temporary worktrees/deployments/schedules,
   canary data, and any required `deferred_cleanup` were removed or durably assigned. Do not
   treat pre-existing user/project scratch as run-owned cleanup.
5. **Ticket hygiene:** persist any status, blocker, evidence, notes, or affected-ticket updates
   discovered by the post-check. If work remains in this scope, keep it on the owning ticket with
   the exact next action; do not hide it only in the chat report.
6. **Closure decision:** a production/final run may say `COMPLETED — READY TO CLOSE` only when all
   required work and cleanup are done, the canonical item is actually `completed`, and no
   outstanding in-scope change or ticket update remains. Otherwise use a non-complete outcome and
   name the owner and next action.

Staging success is a successful stage, not final closure. Its notes must explicitly identify
production or any other later gate as not yet verified. A production deploy is likewise not final
closure until production behavior verification and required cleanup pass.

## 2. Put one colored outcome banner first

The final response starts with exactly one Markdown H2 banner (H2, not H1 — prominent but not
oversized). Emoji supply the color in clients that do not render ANSI terminal colors; do not
rely on raw ANSI escape sequences.

Use the most specific banner:

```text
## ✅ STAGING DEPLOYED
## ✅ STAGING VERIFIED
## ✅ PRODUCTION DEPLOYED
## ✅ PRODUCTION VERIFIED
## ✅ READINESS CHECK PASSED
## ✅ PROMOTION PRECHECK PASSED
## ✅ COMPLETED — READY TO CLOSE

## ❌ STAGING DEPLOY FAILED
## ❌ STAGING VERIFICATION FAILED
## ❌ PRODUCTION DEPLOY FAILED
## ❌ PRODUCTION VERIFICATION FAILED
## ❌ READINESS CHECK FAILED
## ❌ PROMOTION PRECHECK FAILED
## ❌ WORKFLOW FAILED

## ⛔ BLOCKED
## ⏳ NEEDS MORE TIME
## ⚠️ STOPPED — ACTION REQUIRED
```

Do not use a green check for a failed, blocked, partial, or uncertain outcome. Do not use
`COMPLETED — READY TO CLOSE` when a later environment, cleanup, ticket update, or other in-scope
action remains.

For batch/multi-scope runs, choose the worst terminal state for the one outer banner
(`FAILED` > `BLOCKED`/`STOPPED` > `NEEDS_MORE_TIME` > successful stage) and preserve each
scope's individual verdict in the table. When an orchestrator relays a child workflow result,
preserve the child's evidence but do not repeat the child's banner; the user-facing terminal
response still has exactly one outer banner. If the operation itself succeeded but the post-check
finds unresolved cleanup, repository state, or ticket hygiene, use
`## ⚠️ STOPPED — ACTION REQUIRED` rather than a green completion banner.

## 3. Put a structured details block directly under the banner

The old flat wall of `Key: value` lines is retired. Details are grouped so the reader can scan
them at a glance: a one-sentence outcome, one table for run facts, one table for the closeout
audit, then the mandatory Next section (§4).

Successful-stage and final-completion reports:

```text
<one plain-language sentence: what passed, for which item, with the verdict grade>

| Run | |
|---|---|
| Environment | <staging|production|local/read-only> |
| Lifecycle | <reread canonical status and owning item> |
| Evidence | <artifact IDs, PR/commit/deploy/run identifiers> |

| Closeout | |
|---|---|
| Closeout check | <READY|NOT READY — reason> |
| Outstanding changes | <none|exact items, owners, and next action> |
| Ticket hygiene | <updates confirmed|exact update still required> |
| Cleanup | <confirmed|not applicable|exact remainder> |
| Not verified | <none|later environment/behavior/items> |
```

`Closeout check: READY` is reserved for `COMPLETED — READY TO CLOSE`. Successful intermediate
stages use `NOT READY` and explain the intentionally remaining lifecycle gate.

Failure, blocked, stopped, and needs-more-time reports put the decisive details immediately below
the banner — the one-sentence outcome states the stage and the evidence-based reason, in prose,
before any table:

```text
<one sentence: what failed/stopped, at which environment and phase, and the specific cause>

| Run | |
|---|---|
| Stage | <exact environment and phase> |
| Partial changes | <what landed/ran/was mutated before the stop> |
| Lifecycle | <reread canonical status and blocker state> |
| Evidence | <logs/artifact/PR/deploy/run identifiers> |
| Outstanding changes | <required fixes or updates> |
| Cleanup | <confirmed|exact remainder and cleanup command> |
```

Preserve any workflow-specific table or evidence details after this block. Never replace concrete
evidence with the banner, and never bury the failure reason above or far below the banner. Table
cells stay short; anything needing explanation gets a sentence of prose below the table, not a
paragraph crammed into a cell.

## 4. Always end with the exact next command

Every terminal report — success, failure, blocked, stopped, or needs-more-time, in every workflow
that uses this contract — ends with a `### Next` section as the final content of the response.
It names what still needs to happen (or be checked by a human) in one sentence, then gives the
exact runnable command in a fenced block:

````text
### Next

<one sentence: what this command does and any precondition the user should confirm first>

```
/ticket-promote B0326
```
````

Rules:

- The command is a concrete, copy-pasteable invocation (slash command with its real ticket/epic
  ID and arguments, or a shell command) — never a vague "promote when ready".
- Success at an intermediate stage points at the next lifecycle owner (e.g. staging verified →
  the promote/production-verify command). Failure points at the single safest resume/fix command.
- If the next step is a human decision with no safe command, say exactly what must be decided and
  give the command to run after deciding.
- Only `COMPLETED — READY TO CLOSE` with nothing left in scope may end with
  `Next: none — ticket is closed.` instead of a command.
- This section is never omitted, even when a Next-like line already appears in a table or child
  workflow output.

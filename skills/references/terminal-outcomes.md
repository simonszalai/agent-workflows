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

## 2. Put one large, colored outcome banner first

The final response starts with exactly one Markdown H1 banner. Emoji supply the color in clients
that do not render ANSI terminal colors; do not rely on raw ANSI escape sequences.

Use the most specific banner:

```text
# ✅ STAGING DEPLOYED
# ✅ STAGING VERIFIED
# ✅ PRODUCTION DEPLOYED
# ✅ PRODUCTION VERIFIED
# ✅ READINESS CHECK PASSED
# ✅ PROMOTION PRECHECK PASSED
# ✅ COMPLETED — READY TO CLOSE

# ❌ STAGING DEPLOY FAILED
# ❌ STAGING VERIFICATION FAILED
# ❌ PRODUCTION DEPLOY FAILED
# ❌ PRODUCTION VERIFICATION FAILED
# ❌ READINESS CHECK FAILED
# ❌ PROMOTION PRECHECK FAILED
# ❌ WORKFLOW FAILED

# ⛔ BLOCKED
# ⏳ NEEDS MORE TIME
# ⚠️ STOPPED — ACTION REQUIRED
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
`# ⚠️ STOPPED — ACTION REQUIRED` rather than a green completion banner.

## 3. Put the details directly under the banner

Successful-stage and final-completion reports include a compact confirmation block:

```text
Outcome: <plain-language result>
Environment: <staging|production|local/read-only>
Lifecycle: <reread canonical status and owning item>
Evidence: <artifact IDs, PR/commit/deploy/run identifiers>
Closeout check: <READY|NOT READY — reason>
Outstanding changes: <none|exact items, owners, and next action>
Ticket hygiene: <updates confirmed|exact update still required>
Cleanup: <confirmed|not applicable|exact remainder>
Not verified: <none|later environment/behavior/items>
Next: <none — ticket can be closed|exact safest command/action>
```

`Closeout check: READY` is reserved for `COMPLETED — READY TO CLOSE`. Successful intermediate
stages use `NOT READY` and explain the intentionally remaining lifecycle gate.

Failure, blocked, stopped, and needs-more-time reports put the decisive details immediately below
the banner:

```text
Outcome: <FAILED|BLOCKED|NEEDS_MORE_TIME|STOPPED>
Stage: <exact environment and phase>
Reason: <specific evidence-based cause>
Partial changes: <what landed/ran/was mutated before the stop>
Lifecycle: <reread canonical status and blocker state>
Evidence: <logs/artifact/PR/deploy/run identifiers>
Outstanding changes: <required fixes or updates>
Cleanup: <confirmed|exact remainder and cleanup command>
Next: <single safest resume/fix command or named human decision>
```

Preserve any workflow-specific table or evidence details after this block. Never replace concrete
evidence with the banner, and never bury the failure reason above or far below the banner.

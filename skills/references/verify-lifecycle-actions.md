# Ticket Verify — Standalone Lifecycle Actions

Load this reference after computing a standalone ticket verdict. Apply only the current
environment's row.

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | Persist evidence; set `staging_verified`; apply the conditional promotion reference unless `--no-promote` or a batch/epic hold applies. |
| staging | PASS (contract-missing) | Persist the missing-contract evidence; set `staging_verified`; never auto-promote. |
| staging | FAIL | Persist evidence; set `verify_staging_failed`; load the failure-capture reference, then the failure-investigation reference (§9d). |
| staging | NEEDS_MORE_TIME | Leave status unchanged. |
| staging | BLOCKED | Persist blocker evidence; leave status unchanged; update/preserve blocker metadata. |
| production | PASS | Persist mandatory evidence; process deferred cleanup when present; otherwise set `completed`. |
| production | FAIL | Persist mandatory evidence; set `verify_prod_failed`; load the failure-capture reference, then the failure-investigation reference (§9d). |
| production | NEEDS_MORE_TIME | Leave status unchanged. |
| production | BLOCKED | Persist mandatory blocker evidence; leave status unchanged; update/preserve blocker metadata. |

`staging_verified` is the resting ready-for-production state even when a ticket is held from
individual promotion. When promotion runs, `/ticket-promote` owns landing, production deploy steps,
and the transition to `to_verify_prod`.

Epic and milestone gates do not use this table; use `verify-epic-gates.md` instead.

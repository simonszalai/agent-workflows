# Ticket Verify — Standalone Staging Auto-Promotion

Load this reference only for a standalone staging PASS when `--no-promote` and batch/epic holds do
not already prohibit promotion.

Auto-invoke `/ticket-promote <ID>` only when all three conditions hold:

1. **Finalized contract:** the deployment guide was `FINALIZED` and every staging row was graded;
   a derived `PASS (contract-missing)` cannot auto-promote.
2. **Fresh evidence:** every row passed on unambiguous post-activation data.
3. **Low-risk diff:** no schema/migration, deploy-config, auth/security, or payment path changed.
   Use the same path classification as `/ticket-promote` and `landing-policy.md`.

If any condition fails, leave the ticket at `staging_verified`, report the failed gate condition,
and name `/ticket-promote <ID>` as the explicit next command. Never amplify an uncertain staging
PASS into a production mutation.

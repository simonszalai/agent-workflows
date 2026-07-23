# Ticket Verify — Failure Root-Cause Investigation and Remediation Routing

Load this reference only after a staging or production `FAIL` has been persisted, the ticket
status updated, and the failure-capture reference applied. A FAIL report that stops at "evidence
row X failed" is incomplete: the run must also say **why** it failed and **what to do next**.

## 1. Bounded root-cause investigation (read-only)

Investigate every failed evidence row using the `investigate` skill methodology. Spawn one
read-only `investigator` agent per independent failure cluster (group rows that share one failing
surface — same flow, service, table, or UI — into one cluster; do not spawn per row). Cap at
3 investigator agents per scope; a broader failure than that is reported as systemic with the
top clusters investigated.

Each investigator receives a bounded packet — the failed evidence rows (command, expected,
observed, bad-output interpretation), the activation boundary, the ticket's diff/PR reference,
and relevant deployment-guide rows — and must return:

- a root-cause hypothesis with confidence (`confirmed`, `likely`, `unclear`), backed by
  reproducible read-only evidence (logs, queries, run states, code reading at the activated
  revision);
- the causal chain from the shipped change (or environment/deploy state) to the observed bad
  output — or an explicit statement that the failure predates the activation boundary;
- classification: `code_defect`, `deploy_or_config_gap`, `data_or_migration_gap`,
  `environment_or_dependency`, `contract_wrong` (the evidence row itself is incorrect), or
  `pre_existing`.

Investigation stays inside the verification boundaries: strictly read-only, no new flow triggers
beyond what §Boundaries already permitted for evidence collection, and bounded by the same
execution-economy rules. If ground truth needed to confirm a hypothesis is unreachable
(missing access, missing logs), record the hypothesis as `unclear` with the exact missing
evidence — never upgrade confidence by inference.

## 2. Persist the investigation artifact

Write one `investigation` artifact on the ticket (or the epic gate for epic/milestone mode):

- Title: `Verify FAIL root cause — <scope> (<env>)`.
- Content: per failed row — the root-cause hypothesis, confidence, classification, causal
  chain, and supporting evidence (commands/queries with observed output); plus the remediation
  decision from §3 and its reasoning.
- Link the `verification_evidence` artifact ID that recorded the FAIL.

The investigation artifact is created **in addition to** the FAIL evidence artifact, never as a
replacement, and never rewrites the FAIL verdict.

## 3. Remediation decision: direct fix or proposed routes

Choose exactly one path per scope and record it in the investigation artifact and final output.

### 3a. Direct-fix gate

Apply a fix in the same run **only when all of these hold**:

1. standalone ticket mode (never in `--epic`/`--milestone` mode — remediation there belongs to
   `/epic-flow`'s fix loop) and the environment is **staging**;
2. root cause is `confirmed` with reproducible evidence and classified `code_defect` or
   `contract_wrong`;
3. the fix is small and low-risk by the §9b risk vocabulary: no schema changes, no
   deploy-config/infra changes, no auth/security surface, no data backfill or migration;
4. the fix lands on the ticket's existing branch through the normal owners — a `builder` agent
   makes the code change (or, for `contract_wrong`, the deployment-guide evidence row is
   corrected), the branch is pushed, and redeploy + re-verification go through
   `/ticket-deploy staging` — `/ticket-verify` itself never edits environments or deploys.

Production FAILs are never direct-fixed from this skill: propose routes (§3b) and name
`/lfg`, a new bug ticket, or rollback via the deployment guide as the fix owner.

After a direct fix is dispatched, the current run's FAIL verdict and artifacts stand unchanged;
the re-run of `/ticket-verify staging <scope>` after redeploy produces the next verdict.

### 3b. Proposed routes (default)

When the direct-fix gate does not pass — or confidence is below `confirmed` — propose 2–4
ranked routes in the investigation artifact and final output. Each route names: the action, its
owner (`/lfg`, `/ticket-flow` on a new bug ticket, `/ticket-deploy`, `/milestone-flow`, a human
decision, or a specific missing-evidence check to run next), what it would prove or fix, and its
risk. The top route must be concrete enough to execute without re-deriving the investigation.

`pre_existing` failures additionally get a route to file a separate bug ticket via
`ticket-curator` so the regression-vs-baseline distinction stays tracked.

## 4. Output additions

The final report's FAIL rows must include the investigation artifact ID, the root-cause one-liner
with confidence, and either `direct fix dispatched -> /ticket-deploy staging` or the top proposed
route.

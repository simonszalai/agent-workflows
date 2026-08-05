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
- classification: `code_defect`, `verifier_defect`, `environment_capacity`,
  `external_observation`, `invalid_evidence`, or `unknown`.

`unknown` is the honest fail-closed default when the evidence cannot distinguish the classes.
Only `code_defect` may enter a product build/review loop. Route `verifier_defect` to the bounded
verifier owner, `environment_capacity` to the environment owner, `external_observation` to its
observation/provider owner, and `invalid_evidence` to the evidence-contract owner. Those routes do
not create a product-code revision.

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

## 3. Remediation decision and repair packet

Choose exactly one route per scope and record it in the investigation artifact and a
machine-readable repair packet for the deployment owner.

### 3a. Autonomous staging repair

For standalone staging under `/ticket-deploy`, every agent-resolvable failure enters that owner's
three-round repair/redeploy/reverify loop. This is not limited to tiny code fixes. Preserve the
normal safety machinery for the changed surface: delta/full review, specialists, health gates,
commit/push, deploy, and evidence collection.

The verifier itself does not edit code or environments. It returns the persisted failure class and
repair packet to `/ticket-deploy`, which dispatches exactly one fresh no-history repair subagent for
the round. The packet includes the activation/contract key, failed rows, supporting evidence,
classification, exact proposed change/owner, prior attempted fixes, and current persisted round.

An automatic product-code repair still requires all of these:

1. standalone ticket mode (never in `--epic`/`--milestone` mode — remediation there belongs to
   `/epic-flow`'s fix loop) and the environment is **staging**;
2. root cause is `confirmed`, or `likely` with reproducible evidence and a bounded reversible test
   of the hypothesis, and classified `code_defect`;
3. the remediation preserves the approved intent; a scope/design change or destructive choice
   requires the missing human decision;
4. the fix lands on the ticket's existing branch through the normal owners: a fresh `builder`
   agent makes the code change, then review, final health, push, redeploy, and re-verification run
   before the next verdict. `/ticket-verify` itself never edits environments or deploys.

Production FAILs are never direct-fixed from this skill. Code/config/auth remediation must use the
tracked lifecycle route in §3b; ticketless `/go-fable` and untracked auxiliary branches are prohibited
as the final route.

The current run's FAIL verdict and artifacts stand unchanged; the next `/ticket-verify staging
<scope>` after repair/redeploy creates the next verdict. Persist and increment the repair round when
the repair owner is dispatched. A no-op result still consumes that round but does not authorize a
duplicate verification of an unchanged source-of-truth surface.

### 3b. Proposed routes (default)

Outside an active standalone staging deployment loop, propose 2–4 ranked routes in the
investigation artifact and final output. Inside an active loop, `unclear`/`unknown` returns the top
specific missing-evidence check and owner for the next round; uncertainty alone never asks the user
to restart the workflow. Each route names: the action, its owner (`/ticket-flow` on a new bug
ticket, `/ticket-deploy`, `/milestone-flow`, a human decision, or a specific missing-evidence check
to run next), what it would prove or fix, and its risk. The top route must be concrete enough to
execute without re-deriving the investigation.

For every production or epic/milestone remediation that changes code, config, or authentication,
the top route must create a new fix ticket/epic step attached to the failed milestone. It names
separate owners for build, review, landing, secret/config application, deploy, and re-verification.
The failed milestone remains failed until all lifecycle stages complete. An auxiliary branch or
implemented commit is not a substitute for the attached step.

The verification report records each stage independently:

- `implemented`: fix exists on a reviewed worktree branch;
- `landed`: the reviewed fix commit is on the intended target branch;
- `configured`: required secret/config/auth state is applied by its named owner;
- `deployed`: runtime serves the landed/configured revision; and
- `producer available`: every browser/flow/job/data producer required for evidence is live.

Never report “unblocked” at an earlier stage. Re-verification starts only after all required stages
are true; missing stages are explicit blockers with their owner and resume command.

After two staging revisions for the same activation/contract, enter stabilization mode before any
further mutation: persist the latest failure class and the exact contract delta. A third mutation
without those fields is invalid. Stabilization does not turn `unknown` into a code defect and does
not waive deploy, review, or verification gates. The deployment owner caps the loop at three repair
rounds and persists the counter across agent rotations and user-invoked resumes.

## 4. Output additions

The final report's FAIL rows must include the investigation artifact ID, the root-cause one-liner
with confidence, repair packet reference, persisted repair round, and either `returned to active
/ticket-deploy staging repair loop` or the top proposed route. Production/epic rows also include
the five lifecycle stage fields above.

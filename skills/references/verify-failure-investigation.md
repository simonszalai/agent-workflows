# Ticket Verify — Failure Root-Cause Investigation and Remediation Routing

Load this reference only after a staging or production `FAIL` has been persisted, the ticket
status updated, and the failure-capture reference applied. A FAIL report that stops at "evidence
row X failed" is incomplete: the run must also say **why** it failed and **what to do next**.

## 1. Bounded root-cause investigation (read-only)

The verifier groups failed rows by shared surface (same flow, service, table, or UI) and performs
one bounded read-only root-cause pass inside its existing session. Do not spawn per row or per
cluster. Reuse a proven investigation artifact when its activation still matches. Only when the
root cause remains unproven **and** the ticket is already `heavy` may the dispatcher reserve and
spawn one separate read-only investigator with all clusters; `direct`/`standard` return `unknown`
fail-closed rather than adding a role outside their compact budget.

That single bounded pass receives the failed evidence rows (command, expected, observed,
bad-output interpretation), activation boundary, ticket diff/PR reference, and relevant
deployment-guide rows, and returns:

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

## 2a. Compound verifier-contract knowledge (`verifier_defect` / `invalid_evidence` only)

When any failed row is classified `verifier_defect` or `invalid_evidence`, the run has learned
something about how to write a verifier/evidence contract for this specific app — capture it so
the next contract author does not repeat it. After persisting the investigation artifact:

1. Search for an existing lesson first:

   ```text
   mcp__autodev-memory__search(project=PROJECT, repo=REPO, detail="compact",
     queries=[{"keywords": ["verifier-contract"], "text": "<contract defect summary>"}])
   ```

2. If an entry already covers the lesson, update it; otherwise create a gotcha stating the
   **generalized contract-authoring rule**, not just the incident: what structural property made
   the contract row defective (e.g. ancestry checks that break under squash promotion, shell
   quoting that fails controller decoding, timing math that cannot mature before the deadline)
   and the concrete rule a future contract for this app must follow. Include the ticket,
   environment, failed row, and investigation artifact ID as evidence.
3. Tag it `verifier-contract` plus `verification` and the feature area, use source `captured`,
   and set caller context to skill `ticket-verify` with trigger `verify FAIL <env>
   (<classification>)`. The `verifier-contract` tag is what `/create-deployment-guide` searches
   before authoring a contract; an untagged lesson is invisible to the next author.

If the memory tool is unavailable, skip silently; the investigation artifact remains authoritative.

## 3. Remediation decision and repair packet

Choose exactly one route per scope and record it in the investigation artifact and a
machine-readable repair packet for the deployment owner.

### 3a. Autonomous staging repair

For standalone staging under `/ticket-deploy`, every agent-resolvable failure enters that owner's
intensity-bounded repair/redeploy/reverify loop: one cycle for `direct`/`standard`, three for
explicit `heavy`. This is not limited to tiny code fixes. Preserve the normal safety machinery for
the changed surface: repair-owner-only same-risk deltas, full review on a new risk boundary,
specialists, health gates, commit/push, deploy, and evidence collection.

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
4. the fix lands on the ticket's existing branch through the single fresh `repair_owner`; it runs
   the required health/push/redeploy mechanics and returns before a fresh verifier produces the next
   verdict. `/ticket-verify` itself never edits environments or deploys.

Production FAILs are never direct-fixed from this skill. Product code/config/auth remediation must
use the tracked lifecycle route in §3b; ticketless `/go-fable` and untracked auxiliary branches are
prohibited as the final route.

**Exception — production verifier/contract repair (§3a-prod).** A production FAIL whose every
failed row is classified `verifier_defect` or `invalid_evidence` (`confirmed`, or `likely` with
reproducible evidence) **and** whose product-failure field is empty is not a product defect: the
shipped revision is already live and untouched, and the broken surface is the verifier or the
evidence contract itself. That repair may return to an active production `/ticket-deploy` loop the
same way as staging: the outer dispatcher sends one fresh repair subagent that changes only
the verifier/evidence-contract surface (re-finalizing the `deployment_guide` contract with the
recorded revision reason), then re-runs `/ticket-verify production <scope>` **without any product
redeploy or environment mutation**. The same persisted intensity cap applies: one repair cycle for
`direct`/`standard`, three for explicit `heavy`. Any row
classified `code_defect`, `environment_capacity`, `unknown`, or any non-empty product-failure
field disqualifies this path and falls through to §3b.

The current run's FAIL verdict and artifacts stand unchanged; the next `/ticket-verify staging
<scope>` after repair/redeploy creates the next verdict. Persist and increment the repair round when
the repair owner is dispatched. A no-op result still consumes that round but does not authorize a
duplicate verification of an unchanged source-of-truth surface.

### 3b. Proposed routes (default)

Outside an active standalone staging deployment loop, record one recommended route and at most one
materially different fallback. Inside an active loop, `unclear`/`unknown` returns the single top
missing-evidence check and owner for the next round; uncertainty alone never asks the user to restart
the workflow. A route names the action, owner (`/ticket-flow` on a new bug ticket,
`/ticket-deploy`, `/milestone-flow`, a human decision, or a specific evidence check), what it would
prove/fix, and its risk. It must be concrete enough to execute without re-deriving the investigation.

For every production or epic/milestone remediation that changes code, config, or authentication,
the top route must create a new fix ticket/epic step attached to the failed milestone. That ticket
uses its intensity-selected compact or heavy delivery ownership; separately name only the required
secret/config, deploy, and re-verification owners. The failed milestone remains failed until all
lifecycle stages complete. An auxiliary branch or implemented commit is not a substitute for the
attached step.

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
not waive deploy, review, or verification gates. The deployment owner applies the selected
intensity's repair/session caps and persists the chained receipt across agent rotations and
user-invoked resumes.

## 4. Output additions

The final report's FAIL rows must include the investigation artifact ID, the root-cause one-liner
with confidence, repair packet reference, persisted repair round, and either `returned to active
/ticket-deploy staging repair loop` or the top proposed route. Production/epic rows also include
the five lifecycle stage fields above.

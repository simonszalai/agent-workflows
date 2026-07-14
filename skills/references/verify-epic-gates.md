# Verify: Epic/milestone gate specifics

On-demand reference for `ticket-verify/SKILL.md`. Load this **only in `--epic`/`--milestone`
mode** (including epics auto-included by the default queue). Section numbers (§4, §6, §9) refer
to sections in `ticket-verify/SKILL.md`; standalone-ticket behavior lives there.

## 6 (epic/milestone). Persisting evidence across scopes

For explicit epic/milestone verification, evidence must be persisted in **all applicable scopes**:

1. **Canonical milestone/final gate artifact on the epic** — create/update a full
   `verification_evidence` epic artifact for the exact gate scope, for example
   `Staging milestone gate evidence — E0010/M2` or `Production final gate evidence — E0010`.
   This is the complete, self-contained proof package and is the source of truth for the
   milestone/final gate verdict. Metadata must include `scope`, `environment`, `verdict`,
   `activation_boundary`, `evidence_count`, `edge_case_count`, `screenshot_count`,
   `generated_by`, `step_ticket_ids`, and an `artifact_family` such as
   `epic-milestone-verification`. If this canonical artifact cannot be written, do not update
   milestone/step/epic statuses; production verdict is `BLOCKED`, and staging verdict must be
   reported without advancing statuses.
2. **Full ticket-level verification artifact on every included step ticket** — create/update a
   `verification_evidence` ticket artifact for each step ticket in the requested scope. This is
   more than a bare backlink: include the step's activation boundary, the evidence rows relevant
   to that step/contract edge, actual observed output summaries, verdict, status action, and a
   pointer to the canonical epic gate artifact. Shared cross-step evidence may be summarized instead
   of duplicated verbatim, but each step ticket page must be understandable without searching the
   epic first. Metadata must include `parent_scope`, `canonical_evidence_artifact_id`,
   `environment`, `verdict`, `step_ticket_id`, `repo`, `generated_by`, and
   `artifact_family=epic-step-verification`. If these ticket artifacts cannot be written, leave
   the corresponding step ticket statuses unchanged and report exactly which ticket artifact write
   failed.
3. **Compact epic-level verification summary** — create/update a separate concise epic artifact,
   for example `Epic verification summary — E0010`, after writing the gate and ticket artifacts.
   It should roll up all verified milestone/final gates, verdicts, canonical gate artifact ids,
   step ticket artifact ids, step statuses, remaining risks, and next action. This summary is not
   a substitute for the canonical gate artifact; it is the epic dashboard/readability index. Use
   `artifact_family=epic-verification-summary` in metadata and update the existing summary artifact
   if one exists.

## 7. Epic/milestone aggregation

In `--epic` mode, produce one gate verdict for the requested scope:

- include every evidence row from the milestone gate package or final epic deployment guide;
- for a non-first staging milestone, include an impact-based regression subset from earlier
  passed milestone gates so later work cannot silently break already-verified epic behavior;
- map each failed row to the most likely step ticket(s) and contract edge(s);
- prove every included step commit is present on the expected branch (`origin/staging` for
  staging, `origin/main` for production);
- do not pass the gate just because individual step tickets look healthy; the milestone's
  acceptance criteria and cross-step contracts must pass as a unit.

## 9 (epic/milestone). Status and promotion

Epic/milestone mode:

| Environment | Verdict | Action |
|---|---|---|
| staging | PASS | write canonical staging milestone gate `verification_evidence` on the epic; write full per-step ticket `verification_evidence` artifacts; update the compact epic verification summary; mark the milestone staging gate passed; set included step tickets to `staging_verified`/ready-for-parent-promotion when the lifecycle supports it; do **not** call `/ticket-promote` |
| staging | FAIL | write canonical staging gate `verification_evidence` plus per-step ticket artifacts for every included step, with failed evidence-to-step mapping on affected steps; update the epic summary; leave the milestone unpassed for `/epic-flow` fix loop |
| staging | NEEDS_MORE_TIME | write/update canonical staging gate `verification_evidence` plus per-step ticket artifacts for collected evidence; update the epic summary; leave milestone and step statuses unchanged |
| staging | BLOCKED | write/update canonical staging gate `verification_evidence` plus per-step ticket artifacts for every included step, with blocker ground-truth evidence on affected steps; update the epic summary; leave milestone and step statuses unchanged |
| production | PASS | write mandatory final production gate `verification_evidence` on the epic; write full per-step ticket `verification_evidence` artifacts; update the compact epic verification summary; if deferred cleanup remains, set the epic/affected owning item to `prod_verified_needs_cleanup`; otherwise mark included step tickets `completed` when their parent epic owns completion and mark epic complete only if all milestones are done |
| production | FAIL | write mandatory production gate `verification_evidence` plus per-step ticket artifacts for every included step; update the epic summary; mark epic/affected step production verification failed if supported, otherwise record blocker/failure metadata |
| production | NEEDS_MORE_TIME | write/update mandatory production gate `verification_evidence` plus per-step ticket artifacts for collected evidence; update the epic summary; leave statuses unchanged |
| production | BLOCKED | write/update mandatory production gate `verification_evidence` plus per-step ticket artifacts for every included step, with blocker ground-truth evidence on affected steps; update the epic summary; leave statuses unchanged; update/preserve blocker metadata |

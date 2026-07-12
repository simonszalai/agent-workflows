---
name: auto-plan
description: Autonomous planning for backlog tickets. Researches, investigates, creates plan artifact, sets status to planned. Re-run on a planned ticket to incorporate and resolve the user's dashboard review comments.
max_turns: 100
memory:
  tags:
    - architecture
    - tradeoff
    - constraint
    - $tech_tags
  types:
    - architecture
    - pattern
    - preference
---

# Auto-Plan Command

Follow `../references/execution-economy.md`; economy never permits unresolved material plan risk
to be hidden or a required critic/safety gate to be skipped.

Before any conditional external peer call, create its bounded memory packet (once per provider):

```bash
if ! cat .context/plan/question.txt .context/plan/source.md | \
  autodev-memory-task-packet --cwd "$PWD" --session-id "${SESSION_ID:-}" \
    --agent-type planner --provider "$provider" --mechanism external_peer \
    --task-prompt-stdin --allow-unavailable > "$MEMORY_PACKET"; then
  printf '%s\n' '<autodev-memory-task-context>Memory context is unavailable.</autodev-memory-task-context>' \
    > "$MEMORY_PACKET"
fi
```

Pass `--memory-context-file "$MEMORY_PACKET"` to `external-agent --task plan`.

The planning workflow. Picks up a `backlog` or `up_next` ticket (or creates one), researches the
codebase, selects a light or heavy native planning path, conditionally escalates peers for risk or
uncertainty, writes a plan artifact and a DRAFT deployment guide, and marks the ticket `planned`.

This is the **only** planning skill — there is no separate manual plan command. Methodology
standards (audits, checklists, synthesis guidelines) live in
`references/plan-methodology.md`; the plan output template is `templates/plan.md`.

## Usage

```
/auto-plan F0009                    # Plan existing backlog/up_next ticket
/auto-plan B0003                    # Plan bug ticket (includes investigation)
/auto-plan #123                     # Find or create ticket from GitHub issue
/auto-plan                          # Create ticket from conversation context
/auto-plan F0009 additional context # Ticket with extra context
/auto-plan F0009 --deep             # Force heavy path (plan-fanout workflow)
/auto-plan F0009 --light            # Force one-planner light path
/auto-plan F0009 --solo             # Disable conditional peer-provider escalation
/auto-plan F0009                    # Re-run on a planned ticket: revise the plan to address
                                    #   the user's open dashboard review comments, then resolve them
```

## When to Use

- Scheduled agent picks up `backlog`/`up_next` tickets automatically
- Manual trigger when you want planning for a specific ticket
- Starting planning from a GitHub issue or conversation (ticket created automatically)

## What the Plan Contains

**Architecture-focused, not implementation-focused:**

- What we're building (high-level description)
- What we're eliminating (old code/systems being replaced — see Elimination Audit in
  `references/plan-methodology.md`)
- How it works (architectural approach)
- Why this approach (reasoning, alternatives considered)
- Assumptions (every unverified claim about the codebase is an assumption)
- Tradeoffs made (what we're optimizing for vs sacrificing)
- Side effects (what else this affects)
- Risks and mitigations
- Verification strategy (how to know it works, per environment)
- For polling/observer/storage work: data-minimization, retention, and volume budget
- For external/provider-backed caches or ground-truth labels: a cache semantics contract
  (see `references/plan-methodology.md`)

**For features, also includes:**

- Codebase research (existing patterns, integration points)
- Requirements analysis

**Does NOT contain:**

- Specific files to modify or line-by-line implementation details (those come later via
  `/create-build-todos`)
- Invented implementation code. Plans contain **no invented code**; code snippets are allowed
  only as citations of existing canonical patterns with file:line references.

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
```

## Process Overview

```
1.  Resolve Ticket   -> Find existing ticket OR create one; record its starting status
2.  OUTPUT           -> Print ticket ID immediately (FIRST output line)
3.  Set Status       -> Update to "in_progress"
4.  Research         -> /research for features, /investigate for bugs
5.  Prior Knowledge  -> Memory + past-ticket search, rendered into a shared blob
6.  Complexity Gate  -> Choose light (inline) or heavy (plan-fanout) path
7.  Plan             -> Native planning; escalate peers for risk/uncertainty/disagreement
8.  Persist          -> Orchestrator writes plan artifact + DRAFT deployment_guide
9.  Set Status       -> Update to "planned" with summary_bullets
```

## Detailed Process

### Phase 1: Resolve Ticket

Determine whether the input is an existing ticket ID or something that needs a ticket.

**If input is a ticket ID (F/B prefix):**

```
ticket = mcp__autodev-memory__get_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  detail="full", artifact_types=["source", "investigation", "plan", "deployment_guide"],
  include_events=false
)
```

- If not found: STOP - "Ticket not found"
- If status is `backlog` OR `up_next`: proceed with a fresh plan (the normal path).
- If status is `planned` AND `ticket["open_comment_count"] > 0`: enter **revise mode** — the user
  has left review feedback on the plan/source in the dashboard. Skip Phase 2 (leave the status as
  `planned`) and use Phase 7's "Incorporating review feedback" path instead of writing a new plan.
- Any other status (or `planned` with no open comments): STOP - "Ticket status is {status},
  nothing to plan"

**Record `STARTING_STATUS`** (the status the ticket had when auto-plan began — `backlog`,
`up_next`, or `planned`). On any later failure, revert to this status, not unconditionally to
`backlog`.

**If input is a GitHub issue number or conversation context:**

First, search for an existing ticket that already tracks this work:

```
results = mcp__autodev-memory__search_tickets(
  project=PROJECT, query="<issue title or key terms from context>",
  detail="compact"
)
```

- If a matching ticket is found with status `backlog` or `up_next`: use that ticket
- If a matching ticket is found with another status: STOP - "Already tracked as {ID}
  (status: {status})"

If no existing ticket matches, create one:

```
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="<synthesized title>",
  type="bug" | "feature",
  description="<formatted description from issue or conversation>",
  status="backlog",
  tags={"github_issue": issue_number, "source": "conversation"},  # as applicable
  command="/auto-plan"
)
# ticket_id is auto-generated (e.g., F0043, B0012); STARTING_STATUS is "backlog"
```

### Phase 1b: Output Ticket ID

**CRITICAL — this must be the first user-visible output:**

```
{ticket_id}: {title}
```

This single line is emitted immediately so the user (or calling agent) can reference the
ticket while planning proceeds. All subsequent output follows after this line.

### Phase 2: Set Status to In Progress

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="in_progress",
  command="/auto-plan"
)
```

### Phase 3: Research / Investigate

**For features (F-prefix):**
- Spawn `researcher` agent to analyze codebase patterns, integration points
- Search for similar past tickets via `get_similar_tickets`

**For bugs (B-prefix):**
- Read the investigation artifact if one exists; otherwise run `/investigate` internally to find
  root causes (spawn `hypothesis-evaluator` if needed) and create the investigation artifact
- Use root causes from the investigation to inform solution design

### Phase 4: Gather Prior Knowledge

The heavy-path workflow spawns generic subagents — they receive NO knowledge-menu injection and
do NOT load the `autodev-search` skill, unlike the inline `planner` agent used on the light
path, which searches the memory system and past tickets itself. So gather prior knowledge here
in the skill and pass it into whichever path runs. For both paths, pass the same prior-knowledge
blob to the native planner and any conditionally escalated peers so they reason from the same
known gotchas and past decisions:

```
# Related memories (gotchas, patterns, architecture)
memories = mcp__autodev-memory__search(
  project=PROJECT,
  queries=[{ "keywords": [<feature/bug area>], "text": "<what is being planned>" },
           { "keywords": [<technology>],       "text": "<technology> gotchas pitfalls" }],
  limit=8
)

# Similar past work — proven approaches, tradeoffs, risks that materialized
similar = mcp__autodev-memory__get_similar_tickets(
  project=PROJECT, ticket_id=ID, repo=REPO, status="completed",
  detail="compact"
)
ticket_hits = mcp__autodev-memory__search_tickets(
  project=PROJECT, query="<keywords>",
  detail="compact"
)

# Similar past FAILURES — completed-only priors are survivorship-biased. Tickets that
# failed verification are exactly the ones where plan/build/review confidently produced
# something reality rejected; their verification_evidence artifacts carry the lesson.
failed_staging = mcp__autodev-memory__get_similar_tickets(
  project=PROJECT, ticket_id=ID, repo=REPO, status="verify_staging_failed",
  detail="compact"
)
failed_prod = mcp__autodev-memory__get_similar_tickets(
  project=PROJECT, ticket_id=ID, repo=REPO, status="verify_prod_failed",
  detail="compact"
)
```

Render the hits into a compact markdown blob (omit a section if it is empty), pass it to the
native planner and any conditionally escalated peer prompt, and pass it as
the shared prior-knowledge file on the heavy path. Every delegated planner reads that same file so
the plan reuses proven approaches and avoids documented gotchas. Omit the file when nothing
relevant turns up — never fabricate entries.

```markdown
## Related memories
- [<title>] (<type>): <one-line takeaway>

## Related past work
- <TICKET_ID> "<title>" (<status>): <approach / key learning>

## Related past failures — do not repeat
- <TICKET_ID> "<title>" (verify_staging_failed|verify_prod_failed): <what the
  verification evidence showed failed, and why — read the ticket's
  verification_evidence artifact for the failed rows, don't guess from the title>
```

### Phase 5: Complexity and peer-escalation gates

The light path is one native inline planner with no critic panel and no peer providers. The heavy
path adds multiple native framings and completeness/correctness/YAGNI critics. Peer providers are
an independent escalation used only for explicit high risk, material uncertainty, or disagreement.
Prompt length alone is never a complexity signal.

Use this path gate (top-to-bottom, first match wins):

| Condition | Path |
| --- | --- |
| User passed `--deep` | Heavy |
| User passed `--light` | Light |
| New system/app, multi-component/cross-repo work, schema/data migration, or epic step | Heavy |
| Shared infra, auth, billing, destructive data, or other high blast radius | Heavy |
| Conflicting requirements or no established implementation pattern | Heavy |
| Bounded change following an existing pattern or investigated bug fix | Light |
| Otherwise | Light |

Escalate peer providers only when at least one trigger is recorded:

1. the user explicitly requested cross-provider planning or independent opinions;
2. the work affects security, auth, billing, destructive/schema migration, or a cross-repo
   compatibility contract with material blast radius;
3. native research/critics leave a material factual or architectural uncertainty; or
4. two native framings/critics materially disagree and repository evidence does not settle it.

`--solo` disables peers, but not the heavy native critic panel or any project-required safety
review. Announce both decisions: `Plan path: light; peers: no trigger` or
`Plan path: heavy; peers: escalated for schema safety`.

### Phase 6: Plan, critique, and conditionally converge

All delegated planners/critics use `fork_turns: "none"` and bounded self-contained packets per
`../references/execution-economy.md`. Reuse the source, research, prior-knowledge, and diff files
from the run-local cache rather than embedding or rediscovering them for every call.

Before dispatch, write the stable inputs once under `.context/plan/<run-id>/`:

- `source.md` — selected `source` artifact body;
- `research.md` — codebase research or investigation findings;
- `prior-knowledge.md` — compact rendered memory and past-ticket shortlist, when non-empty.

Pass only `sourceArtifactFile`, `codebaseResearchFile`, and `priorKnowledgeFile` paths to
`plan-fanout`. Do not pass their contents in workflow arguments or repeat them in each agent prompt.

#### Light path

Spawn exactly ONE native/current-runner `planner`. Validate that its plan covers the
**routine tier** of the template (`title`, `the_ask`, `what`, `why`, `how`, `risks`,
`verification_strategy`, and `assumptions`); the deep sections (first-principles analysis,
`tradeoffs`, `alternatives_considered`, `side_effects`, `elimination`, `open_questions`,
feasibility/domain fit) are required only when the planner's judgment says the mechanism
or scope is genuinely uncertain — absence on a routine plan is not a validation failure.
Re-prompt once with the missing routine sections if validation fails.
There is no peer dispatch, fanout workflow, critic panel, or convergence round unless the planner
surfaces a peer-escalation trigger. Zero-fill heavy-only/provider-only stats.

#### Heavy path

Run `plan-fanout` with bounded native MVP-first and risk-first framings plus the three native critic
lenses. If Workflow is unavailable, execute the equivalent native loop inline. Stop when all
must-address findings are incorporated/rejected with evidence or a user decision is required.
Do not add peer providers merely because the path is heavy.

#### Conditional peer-provider convergence

Only when the peer-escalation gate fires and `--solo` is absent, run the two providers that are not
the current runner in parallel through `external-agent --task plan`. Provider subagents use
`fork_turns: "none"`; full logs/envelopes go under `.context/plan/<run-id>/`. One peer remains
research-blind so shared research errors can be detected. Preflight the adapter flags before
calling it; a mismatch is a loud failure, never an improvised re-pairing.

Merge usable peer envelopes with the native plan and audit material disagreements. Run at most one
convergence round for an escalated light plan and three for heavy. Resolve each disagreement by
code/artifact evidence, make it an explicit blocking `open_questions` item, or reject it as a
preference/YAGNI issue with rationale. Do not simulate failed peers. For safety-critical triggers,
peer unavailability is explicit residual risk and the plan may not claim independent agreement.

A routine non-escalated plan is valid with one native planner. An escalated plan reports per-provider
status and why escalation occurred. Empty envelopes count as failures, not contributions.

### Phase 6c: Result Shape (both paths produce this object)

```
{
  question: "...",
  plan: {
    title, what, why, how, tradeoffs,
    alternatives_considered: [{name, why_rejected}],
    risks: [{risk, mitigation}],
    verification_strategy, side_effects, elimination,
    assumptions: [...],
    open_questions: [...]
  },
  provider_contributions: [
    { planner_key, assumptions, disagreements, evidence, open_questions, notes }
  ],
  revision_log: {
    incorporated: [{finding_title, critic_lens, how_addressed}],
    rejected:     [{finding_title, critic_lens, why_rejected}],
    tension_resolutions: [{tension, resolution}]   // completeness vs YAGNI conflicts
  },
  drafts_considered: [{framing, framing_notes}],
  critic_findings: [{title, severity, area, issue, suggestion, critic_lens}],
  disagreement_log: [
    { round, title, area, providers, status, resolution, evidence }
  ],
  stats: {
    framings_attempted, drafts_succeeded, critics_succeeded,
    total_findings, must_address_findings,
    incorporated, rejected, tensions_resolved,
    provider_contributors, disagreement_rounds,
    disagreements_found, disagreements_resolved, unresolved_disagreements
  }
}
```

The light path must zero-fill the heavy-only fields. Downstream persist steps must not branch
on path.

### Phase 6d: Handle Additional Research Needs (both paths)

- If the returned plan has `open_questions` that need codebase patterns: spawn `researcher`
  (or invoke `/research`), update `research.md`, and re-run the path with the same file path.
- If the plan has `open_questions` requiring production state for a bug: spawn investigator
  agents and re-run.
- For the heavy path, prefer to satisfy open questions BEFORE re-running rather than running
  the workflow twice (it's not idempotent and not cheap).

### Phase 7: Persist the Plan Artifact (orchestrator writes it)

The **orchestrator** — not the planner agent — renders the converged plan as markdown per
`templates/plan.md` and persists it. The final plan artifact must be concise and answer three
questions clearly:

1. **What** will be done (high-level, 2-3 sentences)
2. **How** it will be done (approach, key decisions)
3. **Why** this approach (tradeoffs, alternatives considered)

Also include: assumptions, verification strategy (staging and prod), risks and mitigations,
side effects, and elimination scope.

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="plan",
  content="<rendered plan markdown>",
  command="/auto-plan"
)
```

**Incorporating review feedback (revise mode).** If you entered revise mode (an existing
`planned` ticket with open review comments), do **not** start a fresh plan — revise the
existing one:

1. Fetch the open threads (they sit on the `source` and/or `plan` artifact — `artifact_type`,
   `selected_text`, and `anchor` tell you which part each thread refers to):
   ```
   comments = mcp__autodev-memory__list_artifact_comments(
     project=PROJECT, ticket_id=ID, repo=REPO, status="open"
   )
   ```
2. Revise the existing plan to address every thread, then persist with `update_artifact` (this
   snapshots the prior version) — not `create_artifact`:
   ```
   mcp__autodev-memory__update_artifact(
     project=PROJECT, artifact_id=<plan artifact id>,
     content="<revised plan>",
     change_note="address review comments",
     command="/auto-plan"
   )
   ```
3. Close each addressed thread with a one-line note pointing at what changed:
   ```
   mcp__autodev-memory__resolve_artifact_comment(
     project=PROJECT, comment_id=<id>,
     resolution_note="<how the revised plan addresses this>",
     command="/auto-plan"
   )
   ```
   If a comment is out of scope or you disagree, use `reply_artifact_comment` and leave it open
   for the user rather than resolving it.

### Phase 8: Write a DRAFT Deployment Guide (conditional)

Write a DRAFT deployment guide as a separate `deployment_guide` artifact. The plan knows the
architecture, so it can already commit the *shape* of deploy and verification even though exact
commands/revisions come later at build time. This draft is the seed that `/create-build-todos`
finalizes and `/ticket-verify` grades against — do not skip it.

Capture, from the architecture:

- **Deploy shape:** which repos/components are touched and in what **order** (and why — which
  cross-repo contract or dependency forces it); whether there's a migration; whether a
  scheduler/worker/service deploy is needed; whether any secret/credential block or env var
  must be provisioned; whether code reaches runtime via git-pull or a service build. Name the
  project's *real* deploy primitives — discover them from the project `CLAUDE.md`/`AGENTS.md`
  and a memory search (`{"keywords": ["deploy", "migration"], "text": "deployment steps order"}`),
  never generic placeholders. Mark anything not yet known as `TBD — finalize at build`.
  If the work needs a database migration, also name the **migration lane**: schema-first
  backward-compatible PR off current `main` with immediate `main→staging` sync, full
  `staging→main` parity merge, or "no migration". Do not plan ordinary selective cherry-pick
  promotion for migration-bearing work; that is an emergency exception only.
- **Verification Evidence contract (per environment):** for **both staging and production**,
  what evidence proves this works — including the edge cases, not just a happy path — with
  each item a reproducible read-only query/command, an expected good output, and a bad-output
  interpretation. This is the precise form of the plan's `verification_strategy`: "what exactly
  proves the fix works", split by env. Plus the **activation boundary** (how to know the new
  code is live). For polling/observer/storage features, include explicit write-rate evidence:
  expected rows/day and bytes/day, dedupe/change-gating behavior on identical polls, and
  retention/TTL for raw snapshots or append-only observations.

```
mcp__autodev-memory__create_artifact(
  project=PROJECT, ticket_id=ID, repo=REPO,
  artifact_type="deployment_guide",
  content="<DRAFT filled from the template in the create-deployment-guide skill, Status: DRAFT>",
  command="/auto-plan"
)
```

Use the template in the `create-deployment-guide` skill. The draft is conditional:

- **Skip it** (state the skip + reason in the plan) when the change is docs/tests/local
  tooling only, or ships through an unchanged canonical deploy path with no migration,
  config, or infra impact — the plan's `verification_strategy` already says how to prove
  the fix.
- **Write it** whenever deployment has any shape of its own: migrations, deploy ordering,
  config/env changes, new services, or anything whose staging/prod evidence differs from
  the plan's verification strategy.

### Phase 9: Set Status to Planned

Also set `summary_bullets` — a compact 3–6 bullet summary (what / why / chosen approach) derived
from the plan you just wrote. The dashboard renders these as the ticket header summary; left
unset they default to `[]` and the header stays blank. `update_ticket` **replaces** the list, so
pass the full set each time (including in revise mode, where you refresh them to match the
revised plan).

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status="planned",
  summary_bullets=[
    "<what the work delivers>",
    "<why / the trigger>",
    "<the chosen approach>",
    "<key risk or dependency, if any>"
  ],
  command="/auto-plan"
)
```

In revise mode the status is already `planned`; this call just refreshes `summary_bullets` (and
confirms the resting status).

## Agent Selection

**For features:** Always spawn `researcher` to analyze codebase before planning.

**For bugs:** Use investigation artifact findings; spawn additional agents only if needed.

**For all:** The planner agent includes the `research` skill (references/past-work.md) and
searches past tickets automatically as part of its research phase.

| Need                     | Agent                | When Used                                        |
| ------------------------ | -------------------- | ------------------------------------------------ |
| Codebase patterns        | `researcher`         | Always for features                              |
| Past work learnings      | (built into planner) | Automatic via research (references/past-work.md) |
| Production state (bugs)  | Investigator agents  | If investigation incomplete                      |
| Additional code context  | `researcher`         | If planner requests                              |
| Peer provider planning   | `external-planner`   | Explicit risk/uncertainty/disagreement trigger   |

## Output

### On Success

```
{ticket_id}: {title}

Auto-plan complete for {ticket_id}: {title}

Plan path: {light|heavy} — {one-line reason}
Plan artifact created. Review and approve to proceed to build.

Status: planned (waiting for approval)

Next: Review the plan, then approve and run /ticket-flow {ticket_id}
```

### On Failure

```
{ticket_id}: {title}

Auto-plan failed for {ticket_id} at: {phase}

Reason: {error description}

Status reverted to: {STARTING_STATUS}
```

On failure, revert status to the status the ticket had when auto-plan started
(`STARTING_STATUS` from Phase 1 — `backlog`, `up_next`, or `planned`), **not** unconditionally
to `backlog`:

```
mcp__autodev-memory__update_ticket(
  project=PROJECT, ticket_id=ID, repo=REPO,
  status=STARTING_STATUS,
  command="/auto-plan"
)
```

## Error Handling

| Phase     | Error                          | Action                                   |
| --------- | ------------------------------ | ---------------------------------------- |
| Resolve   | Ticket not found               | STOP, report                             |
| Resolve   | Already tracked (not plannable) | STOP, report existing ID + status        |
| Validate  | Wrong status                   | STOP, report                             |
| Research  | Agent failure                  | Log, attempt plan with less context      |
| Plan      | Required peer escalation unavailable | Surface residual risk; safety-critical work cannot claim independent agreement |
| Plan      | Planner failure                | STOP, revert to STARTING_STATUS          |

## Relation to Other Commands

| Command              | Relationship                                         |
| -------------------- | ---------------------------------------------------- |
| `/create-build-todos`| Next step after user approves the plan               |
| `/ticket-flow`       | Calls auto-plan as part of end-to-end execution      |
| `/investigate`       | Called internally for bug tickets                    |
| `/research`          | Called internally for feature tickets                |
| `/epic-plan`         | Epic-level analogue; step tickets still use auto-plan |

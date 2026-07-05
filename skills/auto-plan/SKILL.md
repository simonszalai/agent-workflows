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

The planning workflow. Picks up a `backlog` or `up_next` ticket (or creates one), researches the
codebase, runs cross-provider planning with disagreement convergence, writes a plan artifact and
a DRAFT deployment guide, and marks the ticket `planned` for user approval.

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
/auto-plan F0009 --light            # Force light path (still cross-provider)
/auto-plan F0009 --solo             # Emergency opt-out: current provider only —
                                    #   skips peer providers AND cross-provider convergence.
                                    #   Use only when the external-agent adapter is broken.
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
7.  Plan             -> Cross-provider planning, converge disagreements
8.  Persist          -> Orchestrator writes plan artifact + DRAFT deployment_guide
9.  Set Status       -> Update to "planned" with summary_bullets
```

## Detailed Process

### Phase 1: Resolve Ticket

Determine whether the input is an existing ticket ID or something that needs a ticket.

**If input is a ticket ID (F/B prefix):**

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
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
  project=PROJECT, query="<issue title or key terms from context>"
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
blob to every peer provider planner so all three providers reason from the same known gotchas
and past decisions:

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
  project=PROJECT, ticket_id=ID, repo=REPO, status="completed"
)
ticket_hits = mcp__autodev-memory__search_tickets(
  project=PROJECT, query="<keywords>"
)

# Similar past FAILURES — completed-only priors are survivorship-biased. Tickets that
# failed verification are exactly the ones where plan/build/review confidently produced
# something reality rejected; their verification_evidence artifacts carry the lesson.
failed_staging = mcp__autodev-memory__get_similar_tickets(
  project=PROJECT, ticket_id=ID, repo=REPO, status="verify_staging_failed"
)
failed_prod = mcp__autodev-memory__get_similar_tickets(
  project=PROJECT, ticket_id=ID, repo=REPO, status="verify_prod_failed"
)
```

Render the hits into a compact markdown blob (omit a section if it is empty), pass it to every
peer planner prompt, and pass it as `args.priorKnowledge` on the heavy path, where it is
injected into the drafter, synthesizer, critic, reviser, and disagreement-convergence prompts so
the plan reuses proven approaches and avoids documented gotchas. Pass `null` if nothing relevant
turns up — never fabricate entries.

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

### Phase 5: Complexity Gate — Light vs Heavy

The heavy path runs the `plan-fanout` workflow: 2+ parallel plan drafts with different framings
(MVP-first, risk-first), peer-provider drafts merged in, synthesis, 3 parallel critics
(completeness, correctness, YAGNI — the YAGNI critic exists specifically to counter the natural
pressure of completeness critics), then bounded disagreement convergence. The light path runs
one inline planner plus the peer providers with a single convergence round.

**Complexity is about the work, not the words. Prompt/source LENGTH is not a signal** — "build
me an app that does X" is short but heavy; a 900-word bug report with a complete investigation
is long but light.

Use this gate (top-to-bottom, first match wins):

| Condition                                                              | Path  |
| ---------------------------------------------------------------------- | ----- |
| User passed `--deep`                                                    | Heavy |
| User passed `--light`                                                   | Light |
| New system/app built from scratch                                       | Heavy |
| Multi-component or cross-repo work                                      | Heavy |
| Schema change or data migration involved                                | Heavy |
| Research found no existing pattern to follow                            | Heavy |
| Ticket is an epic step                                                  | Heavy |
| High blast radius (touches shared infra, auth, billing, data pipelines) | Heavy |
| Requirements are conflicting or ambiguous                               | Heavy |
| Single component following an existing named pattern                    | Light |
| Clear bug fix with investigation artifact present                       | Light |
| Otherwise                                                               | Light |

Announce the chosen path:

```
Plan path: heavy (schema migration + cross-repo contract) — plan-fanout workflow
```

or:

```
Plan path: light (bug fix with investigation in place) — inline planner
```

### Phase 6: Cross-Provider Planning and Convergence (core, both paths)

A plan artifact is not valid until **all three providers** have contributed independent planning
judgment and material disagreements have been driven to evidence-backed convergence. The main
workflow runner is one provider (`claude`, `codex`, or `grok`); the other two providers are
peers. Unless the caller explicitly passed `--solo`, run the two peer providers with
`external-agent --task plan`, read their envelopes, and merge them into the same synthesis path
as the native/current-runner plan. Do not summarize what a provider "would" say; actually run
the providers and consume their JSON.

Provider roles are symmetric:

| Main workflow runner | Peer planners to run |
| -------------------- | -------------------- |
| `claude`             | `codex`, `grok`      |
| `codex`              | `claude`, `grok`     |
| `grok`               | `claude`, `codex`    |

Determine the current runner with `agent-workflow-provider`. Claude peers use
subscription-backed `claude -p`, never a direct Anthropic API call.

**Dispatch shape must match `/review`:**

- **Claude Code dispatch:** when Claude Code is the main runner, spawn two `external-planner`
  subagents in the same parallel `Agent` batch as the native/current planner. Each subagent
  calls `external-agent --task plan` for one peer provider (`codex` or `grok`) and returns the
  planner envelope JSON. This avoids foreground shell timeout caps and keeps provider dispatch
  as thin data collection, not hidden reasoning.
- **Codex/Grok dispatch:** when Codex or Grok is the main runner, call `external-agent` directly
  for the two peer providers (including `--provider claude` when Claude is a peer).
- **Synthesis/convergence:** always happens in the auto-plan orchestrator, not inside the
  provider dispatcher. External providers contribute envelopes; the deterministic skill logic
  validates, synthesizes, audits disagreements, and revises.

`external-planner` is the planning analogue of `/review`'s `external-reviewer` subagent.
It must not draft or critique the plan itself; it only runs the adapter and returns JSON.

**One peer runs research-blind.** The codebase-research blob is fresh, single-agent,
unverified output — feeding it to every planner with equal authority converts any research
error into a *shared unquestioned prior*: all providers agree because all were told the same
thing, and the disagreement audit only fires on disagreements. So the **second** peer in
`agent-workflow-provider --peers` order gets the source + prior knowledge but NOT the
research file — it must read the code itself. Where the blind peer's assumptions contradict
the research-informed plans, that divergence IS the signal: the convergence audit settles it
against the code. (The memory/past-ticket prior blob is verified, hard-won knowledge and is
still shared with everyone.)

```bash
mkdir -p .context/plan
printf '%s' "$QUESTION" > .context/plan/question.txt
printf '%s' "$SOURCE_ARTIFACT" > .context/plan/source.md
printf '%s' "$CODEBASE_RESEARCH" > .context/plan/codebase-research.md
printf '%s' "$PRIOR_KNOWLEDGE" > .context/plan/prior-knowledge.md
first=1
for provider in $(agent-workflow-provider --peers); do
  if [ "$first" = "1" ]; then
    research_args="--codebase-research-file .context/plan/codebase-research.md"
    first=0
  else
    research_args=""   # second peer is research-blind (see above)
  fi
  external-agent --task plan --provider "$provider" \
    --question "$(cat .context/plan/question.txt)" \
    --source-artifact-file .context/plan/source.md \
    $research_args \
    --prior-knowledge-file .context/plan/prior-knowledge.md \
    --out ".context/plan/${provider}.json" 2>".context/plan/${provider}.log" &
done
wait
```

Each peer returns:

```
{
  "planner_key": "claude|codex|grok",
  "plan": { title, what, why, how, tradeoffs, alternatives_considered,
            risks, verification_strategy, side_effects, elimination,
            open_questions },
  "assumptions": [...],
  "disagreements": [
    { area, claim, why_it_might_be_wrong, evidence_needed }
  ],
  "evidence": [...],
  "open_questions": [...],
  "notes": "..."
}
```

A provider failure contributes an empty envelope with a note; surface it but do not block if the
other two providers plus the current runner can still converge. If fewer than two providers
return usable plans, stop and report the provider failure instead of accepting a one-provider
plan. `.context/plan/*.json` is scratch only; the converged artifact is the persisted plan.

**Convergence rule:** Planning has subjective tradeoffs, but it also contains factual claims
about code, data, infra, sequencing, migrations, verification, and elimination. Iterate on
provider disagreements until every material factual/architectural disagreement is either:

1. resolved by evidence from code, existing artifacts, memory, or production/staging facts;
2. converted into an explicit `open_questions` item that blocks build planning; or
3. deliberately rejected as preference/YAGNI with a recorded reason.

**Round budget: light path runs exactly 1 convergence round; heavy path runs at most 3** (the
plan-fanout workflow owns the heavy loop). In each round:

```
synthesize current provider plans
identify disagreements across provider assumptions, risks, alternatives, and open questions
gather missing evidence with researcher/investigator only if evidence would settle the issue
revise the plan toward the evidence-backed answer
send the revised answer back through provider disagreement audit
```

Stop early only when there are no material unresolved disagreements. Do not let "convergence"
mean gold-plating: completeness claims must beat YAGNI only with concrete evidence. Do not bury
unresolved factual uncertainty in prose; if it matters, it must be an `open_questions` blocker.

### Phase 6a: Light Path (inline)

When the gate selects "Light", spawn ONE native/current-runner `planner` agent with all inputs
(source, codebase research findings if features, investigation findings if bugs, prior
knowledge) **and** run the two peer provider planners from Phase 6 unless `--solo` was passed.
The native planner returns the markdown plan (per `templates/plan.md`) as its final message;
peer planners return the envelope shown above. Validate the native plan covers the required
sections (`title`, `what`, `why`, `how`, `tradeoffs`, `alternatives_considered`, `risks`,
`verification_strategy`, `side_effects`, `elimination`, `open_questions`, `assumptions`). If
validation fails, re-prompt the planner with the template rather than accepting a partial plan.

Then synthesize the native plan + peer plans and run **one** disagreement-convergence round
inline. The light path skips the completeness/correctness/YAGNI critic panel, but it does
**not** skip cross-provider planning or convergence. Assemble the same result shape as the
heavy path with empty `critic_findings` and zero-filled critic-only stats
(`critics_succeeded: 0`, `total_findings: 0`, etc.). Populate provider/convergence stats.

Skip Phase 6b — that is the heavy path only.

### Phase 6b: Heavy Path (plan-fanout workflow)

When the gate selects "Heavy", invoke the workflow by name. The runtime resolves `name:`
against `~/.claude/workflows/`, where agent-workflows is symlinked in every environment.

If the current host tool does not expose Claude's `Workflow` tool (for example a
Codex/Grok-orchestrated run), execute the equivalent heavy-path planning loop inline: generate
multiple framings, run critics, revise until critical findings are resolved or a user decision
is needed, then assemble the same result shape. Do **not** silently skip the critic loop or
cross-provider convergence loop just because the Claude `Workflow` primitive is absent.

```
result = Workflow({
  name: "plan-fanout",
  args: {
    question: "<the planning question/spec from source artifact + user input>",
    sourceArtifact: "<source artifact content>",
    codebaseResearch: "<research artifact content if /research ran first; null otherwise>",
    priorKnowledge: "<rendered blob from Phase 4, or null>",
    providerDrafts: [
      // peer envelopes from .context/plan/*.json
    ],
    framings: [
      { key: "mvp-first", description: "..." },
      { key: "risk-first", description: "..." },
      // Optionally add { key: "integration-first", ... } for cross-system features.
      // Workflow defaults to mvp-first + risk-first if framings omitted.
    ],
    repoRoot: "<absolute path>",
    mode: "interactive" | "headless"
  }
})
```

**Pass `args` as an actual JSON object, never a stringified blob.** If `args` reaches the
`Workflow` tool as a JSON string, the script receives a string and every field
(`question`, `framings`, …) is `undefined`. (plan-fanout now parses a stringified blob
defensively and throws a clear error, but the caller must still pass an object.)

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
  (or invoke `/research`) and re-run the path with the new findings as `codebaseResearch`.
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

### Phase 8: Write a DRAFT Deployment Guide (MANDATORY)

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

Use the template in the `create-deployment-guide` skill. Bugs and trivial single-file changes
still get a draft — the Verification Evidence section is the whole point, and even a one-line
fix needs a stated way to prove it in staging and prod.

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
| Peer provider planning   | `external-planner`   | Always (unless `--solo`)                         |

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
| Plan      | <2 usable provider plans       | STOP, revert to STARTING_STATUS, report  |
| Plan      | Planner failure                | STOP, revert to STARTING_STATUS          |

## Relation to Other Commands

| Command              | Relationship                                         |
| -------------------- | ---------------------------------------------------- |
| `/create-build-todos`| Next step after user approves the plan               |
| `/ticket-flow`       | Calls auto-plan as part of end-to-end execution      |
| `/investigate`       | Called internally for bug tickets                    |
| `/research`          | Called internally for feature tickets                |
| `/epic-plan`         | Epic-level analogue; step tickets still use auto-plan |

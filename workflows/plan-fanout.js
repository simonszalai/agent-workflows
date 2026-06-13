// plan-fanout — heavyweight orchestrator for /plan when the feature is substantial.
//
// Plans are subjective artifacts (no right/wrong like a bug, no completeness metric like
// research). So the orchestration shape is panel-with-counterweight, NOT a convergence loop:
//
// Phase shape:
//   1. Draft (parallel): N diverse plan drafts from different framings (MVP-first,
//      risk-first, integration-first). Diversity beats sequential refinement here.
//   2. Synthesize: one opus agent picks the best base and grafts strong elements from
//      the others.
//   3. Critique (parallel): 3 critics with DIFFERENT (and partially-opposing) lenses:
//        - completeness — what's missing?
//        - correctness — what assumptions won't hold?
//        - YAGNI — what's over-engineered? (essential counterweight to completeness)
//   4. Revise: one opus agent incorporates must-address findings AND explicitly resolves
//      completeness-vs-YAGNI conflicts. Records what was rejected and why.
//
// NO open convergence loop. One bounded revision. Convergence loops on subjective output
// risk spiraling toward gold-plated plans because critics naturally find "missing things"
// faster than they validate "this is enough". The YAGNI critic is the only counterweight,
// and a single revision is enough to integrate it.
//
// Returns the synthesized plan object only. MCP persistence stays in the skill — the
// workflow never touches MCP. Related autodev memories + past tickets are gathered by the
// skill and passed in as args.priorKnowledge (a rendered markdown string); the workflow
// feeds it to the drafters, synthesizer, critics, and reviser so the plan reuses proven
// approaches and avoids documented gotchas.

export const meta = {
  name: 'plan-fanout',
  description: 'Diverse plan drafts in parallel, synthesize, critique through completeness/correctness/YAGNI lenses, revise once. No convergence loop — bounded by design to prevent over-engineering spiral.',
  phases: [
    { title: 'Draft', detail: 'N diverse plans in parallel (different framings)' },
    { title: 'Synthesize', detail: 'pick best base, graft strongest elements' },
    { title: 'Critique', detail: 'parallel critics: completeness, correctness, YAGNI' },
    { title: 'Revise', detail: 'incorporate must-address; resolve completeness vs YAGNI explicitly' },
  ],
}

// ---------- Inline schemas ----------

const planSchema = {
  type: 'object',
  required: [
    'title', 'what', 'why', 'how', 'tradeoffs', 'alternatives_considered',
    'risks', 'verification_strategy', 'side_effects', 'elimination', 'open_questions',
  ],
  properties: {
    title: { type: 'string', minLength: 4 },
    what: { type: 'string', minLength: 16, description: 'High-level description of what is being built.' },
    why: { type: 'string', minLength: 16, description: 'Reasoning — why this is worth building, what problem it solves.' },
    how: { type: 'string', minLength: 32, description: 'Architectural approach. No code-level detail.' },
    tradeoffs: { type: 'string', minLength: 16, description: 'What is being optimized for vs sacrificed.' },
    alternatives_considered: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'why_rejected'],
        properties: {
          name: { type: 'string', minLength: 2 },
          why_rejected: { type: 'string', minLength: 8 },
        },
      },
    },
    risks: {
      type: 'array',
      items: {
        type: 'object',
        required: ['risk', 'mitigation'],
        properties: {
          risk: { type: 'string', minLength: 8 },
          mitigation: { type: 'string', minLength: 8 },
        },
      },
    },
    verification_strategy: { type: 'string', minLength: 16, description: 'How we will know it works.' },
    side_effects: { type: 'string', minLength: 4, description: 'What else this affects, or "none".' },
    elimination: { type: 'string', minLength: 4, description: 'Old code/systems being replaced, or "none".' },
    open_questions: { type: 'array', items: { type: 'string' } },
  },
}

const draftOutputSchema = {
  type: 'object',
  required: ['framing', 'plan', 'framing_notes'],
  properties: {
    framing: { type: 'string' },
    plan: planSchema,
    framing_notes: { type: 'string', minLength: 16, description: 'Brief reflection on what this framing emphasized.' },
  },
}

const criticFindingSchema = {
  type: 'object',
  required: ['title', 'severity', 'area', 'issue', 'suggestion'],
  properties: {
    title: { type: 'string', minLength: 4 },
    severity: { type: 'string', enum: ['must-address', 'should-address', 'consider'] },
    area: { type: 'string', enum: ['what', 'why', 'how', 'tradeoffs', 'alternatives_considered', 'risks', 'verification_strategy', 'side_effects', 'elimination', 'scope'] },
    issue: { type: 'string', minLength: 16 },
    suggestion: { type: 'string', minLength: 8 },
  },
}

const criticOutputSchema = {
  type: 'object',
  required: ['lens', 'findings', 'overall_assessment'],
  properties: {
    lens: { type: 'string', enum: ['completeness', 'correctness', 'yagni'] },
    findings: { type: 'array', items: criticFindingSchema },
    overall_assessment: { type: 'string', minLength: 16 },
  },
}

const revisedOutputSchema = {
  type: 'object',
  required: ['plan', 'revision_log'],
  properties: {
    plan: planSchema,
    revision_log: {
      type: 'object',
      required: ['incorporated', 'rejected', 'tension_resolutions'],
      properties: {
        incorporated: {
          type: 'array',
          items: {
            type: 'object',
            required: ['finding_title', 'critic_lens', 'how_addressed'],
            properties: {
              finding_title: { type: 'string' },
              critic_lens: { type: 'string', enum: ['completeness', 'correctness', 'yagni'] },
              how_addressed: { type: 'string', minLength: 8 },
            },
          },
        },
        rejected: {
          type: 'array',
          items: {
            type: 'object',
            required: ['finding_title', 'critic_lens', 'why_rejected'],
            properties: {
              finding_title: { type: 'string' },
              critic_lens: { type: 'string', enum: ['completeness', 'correctness', 'yagni'] },
              why_rejected: { type: 'string', minLength: 8 },
            },
          },
        },
        tension_resolutions: {
          type: 'array',
          description: 'Where completeness/correctness and YAGNI critics gave conflicting advice, explain the choice.',
          items: {
            type: 'object',
            required: ['tension', 'resolution'],
            properties: {
              tension: { type: 'string', minLength: 16 },
              resolution: { type: 'string', minLength: 16 },
            },
          },
        },
      },
    },
  },
}

// ---------- Defaults ----------

const DEFAULT_FRAMINGS = [
  {
    key: 'mvp-first',
    description: 'The smallest, simplest thing that delivers the core value. Aggressively cut scope. Prefer reusing existing code over building new abstractions. Prefer one obvious path over flexibility.',
  },
  {
    key: 'risk-first',
    description: 'Identify what is most likely to go wrong — technical risks, integration risks, data risks, rollback risks — and design the plan around eliminating or containing them. Optimize for safety of the change, not minimal effort.',
  },
]

// ---------- Helpers ----------

function validFinding(f) {
  if (!f || typeof f !== 'object') return false
  return typeof f.title === 'string' && f.title.length > 0 &&
         typeof f.severity === 'string' && typeof f.area === 'string' &&
         typeof f.issue === 'string' && typeof f.suggestion === 'string'
}

// ---------- Prompts ----------

function draftPrompt(framing, question, sourceArtifact, codebaseResearch, repoRoot, priorKnowledge) {
  return [
    `You are drafting a high-level architecture plan using the "${framing.key}" framing.`,
    `Framing: ${framing.description}`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `What to plan:`,
    question,
    ``,
    sourceArtifact ? `Source artifact (ticket description):\n${sourceArtifact}\n` : '',
    codebaseResearch ? `Existing codebase research (use this, do not re-do it):\n${codebaseResearch}\n` : '',
    priorKnowledge ? `Prior knowledge from autodev (related memories + past tickets) — reuse proven\napproaches and avoid the documented gotchas:\n${priorKnowledge}\n` : '',
    ``,
    `Read the codebase as needed (Read, Bash, Grep) to understand existing patterns. Then`,
    `produce a plan that explicitly embodies your framing. Two planners using different`,
    `framings should produce visibly different plans — do not converge to the same plan.`,
    ``,
    `Return per the draft output schema:`,
    `- framing: "${framing.key}"`,
    `- plan: the structured plan object (what, why, how, tradeoffs, alternatives_considered,`,
    `  risks, verification_strategy, side_effects, elimination, open_questions)`,
    `- framing_notes: 1-3 sentences on what your framing emphasized in this plan`,
    ``,
    `Plan rules:`,
    `- Architecture-focused, not implementation. No file paths or code unless essential.`,
    `- "elimination": list old code/systems being replaced. "none" only if genuinely none.`,
    `- "side_effects": what else this change affects. "none" only if confidently isolated.`,
    `- "alternatives_considered": at least 1 alternative with a real "why_rejected" reason.`,
    `- "open_questions": things you genuinely don't know yet. Empty is OK.`,
    `- Embody your framing in the tradeoffs section explicitly.`,
  ].filter(Boolean).join('\n')
}

function synthesizePrompt(question, drafts, repoRoot, priorKnowledge) {
  return [
    `You are synthesizing ${drafts.length} parallel plan drafts into a single plan.`,
    ``,
    `Synthesis is NOT averaging. Pick the strongest base plan, then graft the best ideas`,
    `from the others. Acknowledge framing tradeoffs in the merged plan's "tradeoffs"`,
    `section. If two drafts conflict on a core decision, pick one and explain why in`,
    `"tradeoffs".`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `What to plan:`,
    question,
    ``,
    ...(priorKnowledge ? [
      `Prior knowledge from autodev (related memories + past tickets) — keep the merged plan`,
      `consistent with proven approaches and clear of documented gotchas:`,
      priorKnowledge,
      ``,
    ] : []),
    `Drafts:`,
    drafts.map((d, i) => d ? `\n--- DRAFT ${i + 1} (framing: ${d.framing}) ---\n${JSON.stringify(d.plan, null, 2)}\nFraming notes: ${d.framing_notes}\n` : `\n--- DRAFT ${i + 1}: FAILED ---\n`).join(''),
    ``,
    `Return per the draft output schema with framing: "synthesized". framing_notes should`,
    `summarize which base you chose and what you grafted from where.`,
  ].join('\n')
}

function criticPrompt(lens, plan, question, codebaseResearch, repoRoot, priorKnowledge) {
  const lensInstructions = {
    completeness: [
      `Your lens is COMPLETENESS. Identify what's missing.`,
      ``,
      `Specifically look for:`,
      `- Steps or workflows the plan doesn't address`,
      `- Dependencies not acknowledged`,
      `- Edge cases not considered (error paths, empty states, partial failures, concurrency)`,
      `- Affected systems not in side_effects`,
      `- Migrations / data backfill needs`,
      `- Permissions, auth, audit requirements`,
      `- Rollback strategy`,
      ``,
      `Be specific. Vague "the plan should handle errors" is weak. "The plan does not`,
      `address what happens when the migration partially succeeds" is strong.`,
    ].join('\n'),
    correctness: [
      `Your lens is CORRECTNESS. Identify what's wrong.`,
      ``,
      `Specifically look for:`,
      `- Assumptions that won't hold (about existing code, libraries, infra, scale)`,
      `- Approaches that look reasonable but won't actually work`,
      `- Misunderstanding of the existing codebase (read the code if needed to check)`,
      `- Risks marked as mitigated that aren't actually mitigated`,
      `- Verification strategy that won't actually verify what it claims`,
      `- Cross-cutting concerns the plan misreads`,
      ``,
      `Read the actual codebase to check claims. Do not just speculate.`,
    ].join('\n'),
    yagni: [
      `Your lens is YAGNI ("You Ain't Gonna Need It"). Identify what's over-engineered.`,
      ``,
      `You are the explicit counterweight to the completeness critic. Push back HARD on:`,
      `- Abstractions justified by hypothetical future requirements`,
      `- Flexibility added "in case" something changes that probably won't`,
      `- Configuration options no one will use`,
      `- Helper modules / shared utilities for things used in 1-2 places`,
      `- Migrations / refactors bundled in that aren't strictly needed`,
      `- Risk mitigations for risks that aren't real`,
      `- Verification strategies that test more than the actual change`,
      `- Plans designed for the third call site when there are 0`,
      ``,
      `Three similar lines are better than a premature abstraction. A bug fix doesn't`,
      `need surrounding cleanup. Default to "do less". If the plan has 5 components and`,
      `2 of them serve only hypothetical needs, flag both.`,
    ].join('\n'),
  }[lens]

  return [
    `You are a plan critic. Lens: ${lens}.`,
    lensInstructions,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `What was planned:`,
    question,
    ``,
    `Plan under review:`,
    JSON.stringify(plan, null, 2),
    ``,
    codebaseResearch ? `Existing codebase research (context):\n${codebaseResearch}\n` : '',
    priorKnowledge ? `Prior knowledge from autodev (related memories + past tickets) — flag where the\nplan contradicts a documented gotcha or ignores a proven past approach:\n${priorKnowledge}\n` : '',
    ``,
    `Return per criticOutputSchema:`,
    `- lens: "${lens}"`,
    `- findings: array of issues. Each with title, severity (must-address/should-address/consider),`,
    `  area (which plan section), issue (what's wrong), suggestion (what to change)`,
    `- overall_assessment: 2-4 sentences on the plan from your lens`,
    ``,
    `Severity guide:`,
    `- must-address: ignoring this would make the plan demonstrably wrong/incomplete/wasteful`,
    `- should-address: meaningful improvement, but plan could ship without it`,
    `- consider: minor refinement`,
    ``,
    `Honesty over thoroughness. If the plan is genuinely fine from your lens, return`,
    `findings: [] and say so in overall_assessment. Do NOT invent issues to appear thorough.`,
  ].filter(Boolean).join('\n')
}

function revisePrompt(plan, critiques, question, codebaseResearch, repoRoot, priorKnowledge) {
  return [
    `You are revising a plan based on critic findings. This is the SINGLE revision pass —`,
    `there is no second round, so make it count. Do NOT chase every finding; resolve`,
    `tensions explicitly.`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `What was planned:`,
    question,
    ``,
    `Current plan:`,
    JSON.stringify(plan, null, 2),
    ``,
    `Critic findings, by lens:`,
    critiques.map(c => c ? `\n--- ${c.lens.toUpperCase()} CRITIC ---\nOverall: ${c.overall_assessment}\nFindings:\n${JSON.stringify(c.findings, null, 2)}\n` : '\n--- CRITIC FAILED ---\n').join(''),
    ``,
    priorKnowledge ? `Prior knowledge to respect (autodev memories + related past tickets) — the revised\nplan must not reintroduce a documented gotcha:\n${priorKnowledge}\n` : '',
    `Revision rules:`,
    `1. Incorporate ALL must-address findings unless a YAGNI finding directly contradicts.`,
    `2. When completeness/correctness wants something added and YAGNI wants it cut,`,
    `   DEFAULT TO YAGNI's position unless the completeness/correctness finding identifies`,
    `   a concrete demonstrable problem (not a hypothetical). Record the tension explicitly.`,
    `3. Reject should-address and consider findings freely if the plan is fine without them.`,
    `   Justify rejections in revision_log.rejected.`,
    `4. Do NOT add scope. If a critic suggests a refactor or migration not in the original`,
    `   plan, reject it unless it's a must-address correctness issue.`,
    ``,
    `Return per revisedOutputSchema:`,
    `- plan: the revised plan (same schema as input)`,
    `- revision_log:`,
    `   - incorporated: list of findings you addressed, with how_addressed`,
    `   - rejected: list of findings you did not address, with why_rejected`,
    `   - tension_resolutions: where completeness vs YAGNI conflicted, the choice + reason`,
  ].filter(Boolean).join('\n')
}

// ---------- Script body ----------

const {
  question,
  sourceArtifact = null,
  codebaseResearch = null,
  priorKnowledge = null,
  framings = DEFAULT_FRAMINGS,
  repoRoot,
  mode = 'interactive',
} = args

if (!question || typeof question !== 'string') {
  throw new Error('plan-fanout: args.question is required')
}
if (!repoRoot || typeof repoRoot !== 'string') {
  throw new Error('plan-fanout: args.repoRoot is required')
}
if (!Array.isArray(framings) || framings.length < 2) {
  throw new Error('plan-fanout: args.framings must have at least 2 entries (diversity is the point)')
}

// Phase 1: parallel drafts
phase('Draft')
const draftResults = await parallel(
  framings.map(f => () => agent(
    draftPrompt(f, question, sourceArtifact, codebaseResearch, repoRoot, priorKnowledge),
    { label: `draft:${f.key}`, phase: 'Draft', schema: draftOutputSchema }
  ))
)
const validDrafts = draftResults.filter(d => d && d.plan)
log(`Drafts: ${validDrafts.length}/${framings.length} succeeded`)

if (validDrafts.length === 0) {
  throw new Error('plan-fanout: all drafts failed')
}

// Phase 2: synthesize
phase('Synthesize')
let synthesized = null
if (validDrafts.length === 1) {
  // Only one draft survived — skip synthesis, use it as-is.
  log('Only one draft survived; skipping synthesis')
  synthesized = validDrafts[0]
} else {
  synthesized = await agent(
    synthesizePrompt(question, validDrafts, repoRoot, priorKnowledge),
    // TODO: revert to model: 'fable' once available (effort xhigh not settable via agent())
    { label: 'synthesize', phase: 'Synthesize', model: 'opus', schema: draftOutputSchema }
  )
  if (!synthesized || !synthesized.plan) {
    log('Synthesis failed; falling back to first draft')
    synthesized = validDrafts[0]
  }
}

// Phase 3: parallel critics
phase('Critique')
const critiqueResults = await parallel(
  ['completeness', 'correctness', 'yagni'].map(lens => () => agent(
    criticPrompt(lens, synthesized.plan, question, codebaseResearch, repoRoot, priorKnowledge),
    { label: `critic:${lens}`, phase: 'Critique', schema: criticOutputSchema }
  ))
)
const validCritiques = critiqueResults.filter(c => c && Array.isArray(c.findings))
let totalFindings = 0, mustAddressCount = 0
for (const c of validCritiques) {
  const filtered = c.findings.filter(validFinding)
  totalFindings += filtered.length
  mustAddressCount += filtered.filter(f => f.severity === 'must-address').length
}
log(`Critique: ${validCritiques.length}/3 critics; ${totalFindings} findings (${mustAddressCount} must-address)`)

// Phase 4: revise (bounded, no loop)
phase('Revise')
let final = null
if (validCritiques.length === 0 || totalFindings === 0) {
  // Nothing to revise against — ship the synthesized plan as-is.
  log('No critique findings; skipping revision')
  final = {
    plan: synthesized.plan,
    revision_log: { incorporated: [], rejected: [], tension_resolutions: [] },
  }
} else {
  final = await agent(
    revisePrompt(synthesized.plan, validCritiques, question, codebaseResearch, repoRoot, priorKnowledge),
    // TODO: revert to model: 'fable' once available (effort xhigh not settable via agent())
    { label: 'revise', phase: 'Revise', model: 'opus', schema: revisedOutputSchema }
  )
  if (!final || !final.plan) {
    log('Revision failed; returning synthesized plan unrevised')
    final = {
      plan: synthesized.plan,
      revision_log: { incorporated: [], rejected: [], tension_resolutions: [] },
    }
  }
}

const incorporatedCount = final.revision_log?.incorporated?.length || 0
const rejectedCount = final.revision_log?.rejected?.length || 0
const tensionCount = final.revision_log?.tension_resolutions?.length || 0

return {
  question,
  plan: final.plan,
  revision_log: final.revision_log || { incorporated: [], rejected: [], tension_resolutions: [] },
  drafts_considered: validDrafts.map(d => ({ framing: d.framing, framing_notes: d.framing_notes })),
  critic_findings: validCritiques.flatMap(c =>
    (c.findings || []).filter(validFinding).map(f => ({ ...f, critic_lens: c.lens }))
  ),
  stats: {
    framings_attempted: framings.length,
    drafts_succeeded: validDrafts.length,
    critics_succeeded: validCritiques.length,
    total_findings: totalFindings,
    must_address_findings: mustAddressCount,
    incorporated: incorporatedCount,
    rejected: rejectedCount,
    tensions_resolved: tensionCount,
  },
}

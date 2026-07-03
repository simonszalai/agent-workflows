// plan-fanout — heavyweight orchestrator for /auto-plan when the work is substantial.
//
// Plans contain both subjective tradeoffs and factual/architectural claims. The tradeoffs
// need panel-with-counterweight; the factual claims need cross-provider disagreement
// convergence. The core invariant: all three providers contribute to planning, and material
// disagreements are iterated until evidence resolves them, they become explicit blockers, or
// they are deliberately rejected as preference/YAGNI.
//
// Phase shape:
//   1. Draft (parallel): N diverse plan drafts from different framings (MVP-first,
//      risk-first, integration-first). Diversity beats sequential refinement here.
//   2. Add peer-provider drafts gathered by the skill via external-agent --task plan.
//   3. Synthesize: one opus agent picks the best base and grafts strong elements from
//      the others.
//   4. Critique (parallel): 3 critics with DIFFERENT (and partially-opposing) lenses:
//        - completeness — what's missing?
//        - correctness — what assumptions won't hold?
//        - YAGNI — what's over-engineered? (essential counterweight to completeness)
//   5. Revise: one opus agent incorporates must-address findings AND explicitly resolves
//      completeness-vs-YAGNI conflicts. Records what was rejected and why.
//   6. Disagreement convergence: up to 3 bounded rounds. Audit provider assumptions,
//      disagreements, risks, and open questions against the current plan; revise only toward
//      evidence-backed truth, explicit blockers, or recorded YAGNI/preference rejections.
//
// Returns the synthesized plan object only. MCP persistence stays in the skill — the
// workflow never touches MCP. Related autodev memories + past tickets are gathered by the
// skill and passed in as args.priorKnowledge (a rendered markdown string); the workflow
// feeds it to the drafters, synthesizer, critics, and reviser so the plan reuses proven
// approaches and avoids documented gotchas.

export const meta = {
  name: 'plan-fanout',
  description: 'Cross-provider plan synthesis with diverse drafts, critics, and bounded disagreement convergence.',
  phases: [
    { title: 'Draft', detail: 'N diverse plans in parallel (different framings)' },
    { title: 'Synthesize', detail: 'pick best base, graft strongest elements' },
    { title: 'Critique', detail: 'parallel critics: completeness, correctness, YAGNI' },
    { title: 'Revise', detail: 'incorporate must-address; resolve completeness vs YAGNI explicitly' },
    { title: 'Converge', detail: 'iterate material disagreements until resolved or explicit blockers' },
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
    assumptions: {
      type: 'array',
      items: { type: 'string' },
      description: 'Unverified claims about the codebase/data/infra the plan relies on. Optional.',
    },
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

const disagreementAuditSchema = {
  type: 'object',
  required: ['round', 'disagreements', 'overall_assessment'],
  properties: {
    round: { type: 'integer' },
    disagreements: {
      type: 'array',
      items: {
        type: 'object',
        required: [
          'title', 'area', 'providers', 'status', 'severity',
          'issue', 'evidence_needed', 'suggested_resolution',
        ],
        properties: {
          title: { type: 'string', minLength: 4 },
          area: { type: 'string', enum: ['what', 'why', 'how', 'tradeoffs', 'alternatives_considered', 'risks', 'verification_strategy', 'side_effects', 'elimination', 'scope'] },
          providers: { type: 'array', items: { type: 'string' } },
          status: { type: 'string', enum: ['resolved_by_evidence', 'material_unresolved', 'open_question', 'preference_rejected'] },
          severity: { type: 'string', enum: ['must-resolve', 'should-resolve', 'preference'] },
          issue: { type: 'string', minLength: 16 },
          evidence_needed: { type: 'string', minLength: 4 },
          suggested_resolution: { type: 'string', minLength: 8 },
        },
      },
    },
    overall_assessment: { type: 'string', minLength: 16 },
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

function normalizeProviderDraft(env) {
  if (!env || typeof env !== 'object' || !env.plan) return null
  const key = env.planner_key || env.provider || env.key || 'provider'
  return {
    framing: `provider:${key}`,
    plan: env.plan,
    framing_notes: env.notes || `External provider contribution from ${key}`,
    provider_key: key,
    assumptions: Array.isArray(env.assumptions) ? env.assumptions : [],
    disagreements: Array.isArray(env.disagreements) ? env.disagreements : [],
    evidence: Array.isArray(env.evidence) ? env.evidence : [],
    open_questions: Array.isArray(env.open_questions) ? env.open_questions : [],
    notes: env.notes || '',
  }
}

function validDisagreement(d) {
  if (!d || typeof d !== 'object') return false
  return typeof d.title === 'string' && d.title.length > 0 &&
         typeof d.area === 'string' &&
         Array.isArray(d.providers) &&
         typeof d.status === 'string' &&
         typeof d.severity === 'string' &&
         typeof d.issue === 'string' &&
         typeof d.suggested_resolution === 'string'
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
    codebaseResearch ? `Existing codebase research (use as a starting point — do not re-do it wholesale,\nbut independently verify the 2-3 research claims your plan most depends on by reading\nthe code; record any claim you contradicted in "assumptions" or "open_questions"):\n${codebaseResearch}\n` : '',
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
    `- "assumptions": fill this. Every claim about the codebase, data, or infra you did NOT`,
    `  verify by reading code/artifacts is an assumption — list each one explicitly.`,
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
    `Quality rubric for the merged plan:`,
    `- verification_strategy names at least 1 reproducible observation per environment`,
    `  (staging AND production): a query/command plus the output that proves success.`,
    `- "how" names the components touched — not just an abstract description of the approach.`,
    `- No padding: every sentence carries information. Delete restatements and filler.`,
    `- Merge the drafts' assumptions: keep every assumption that still underpins the merged plan.`,
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
    `Quality rubric for the revised plan:`,
    `- verification_strategy names at least 1 reproducible observation per environment`,
    `  (staging AND production): a query/command plus the output that proves success.`,
    `- "how" names the components touched — not just an abstract description of the approach.`,
    `- No padding: every sentence carries information. Delete restatements and filler.`,
    ``,
    `Return per revisedOutputSchema:`,
    `- plan: the revised plan (same schema as input)`,
    `- revision_log:`,
    `   - incorporated: list of findings you addressed, with how_addressed`,
    `   - rejected: list of findings you did not address, with why_rejected`,
    `   - tension_resolutions: where completeness vs YAGNI conflicted, the choice + reason`,
  ].filter(Boolean).join('\n')
}

function disagreementAuditPrompt(round, plan, allDrafts, critiques, question, codebaseResearch, repoRoot, priorKnowledge, priorAudits, revisionLog) {
  const providerDrafts = allDrafts.filter(d => d.provider_key)
  // Payload trim: only round 1 sees the full draft plans. Later rounds audit the current plan
  // against provider assumptions/disagreements only — the drafts have already been synthesized.
  const includeFullDrafts = round === 1
  return [
    `You are auditing a synthesized plan for cross-provider disagreements. Round ${round}/3.`,
    ``,
    `Goal: converge on evidence-backed truth, not on bland compromise. Planning contains`,
    `subjective tradeoffs, but factual/architectural claims about code, data, infra,`,
    `migrations, sequencing, verification, and elimination must be settled or promoted to`,
    `explicit open questions.`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `Planning question:`,
    question,
    ``,
    `Current plan:`,
    JSON.stringify(plan, null, 2),
    ``,
    ...(includeFullDrafts ? [
      `All plan drafts considered:`,
      allDrafts.map((d, i) => `\n--- DRAFT ${i + 1} (${d.framing}) ---\n${JSON.stringify(d.plan, null, 2)}\nNotes: ${d.framing_notes || ''}\n`).join(''),
      ``,
    ] : []),
    `Provider assumptions / surfaced disagreements:`,
    providerDrafts.length
      ? providerDrafts.map(d => [
          `\n--- PROVIDER ${d.provider_key} ---`,
          `Assumptions: ${JSON.stringify(d.assumptions || [])}`,
          `Disagreements: ${JSON.stringify(d.disagreements || [])}`,
          `Evidence: ${JSON.stringify(d.evidence || [])}`,
          `Open questions: ${JSON.stringify(d.open_questions || [])}`,
        ].join('\n')).join('\n')
      : `No external provider drafts were supplied. Flag this if cross-provider mode was expected.`,
    ``,
    ...(includeFullDrafts ? [
      `Critic findings:`,
      JSON.stringify(critiques.flatMap(c => (c?.findings || []).map(f => ({ ...f, critic_lens: c.lens }))), null, 2),
      ``,
    ] : []),
    ...(priorAudits && priorAudits.length ? [
      `Earlier convergence rounds (audit results):`,
      JSON.stringify(priorAudits, null, 2),
      ``,
      `Revision log so far (what was incorporated / rejected / resolved):`,
      JSON.stringify(revisionLog || {}, null, 2),
      ``,
      `Do NOT re-raise items already classified resolved_by_evidence or preference_rejected in`,
      `earlier rounds unless NEW evidence contradicts the earlier resolution. Audit only what`,
      `remains unresolved or newly appeared in the current plan.`,
      ``,
    ] : []),
    codebaseResearch && includeFullDrafts ? `Existing codebase research:\n${codebaseResearch}\n` : '',
    priorKnowledge ? `Prior knowledge from autodev:\n${priorKnowledge}\n` : '',
    ``,
    `Evidence discipline (mandatory): for any factual claim about code, schema, data, or`,
    `infra, run the check YOURSELF (Read/Grep/Bash read-only query) and paste the observed`,
    `output into "evidence_needed" (command + result). Classifying a disagreement as`,
    `"resolved_by_evidence" is FORBIDDEN unless evidence_needed contains an actual`,
    `observation you (or an earlier round) made — a description of what someone should`,
    `check is not evidence, and adjudicating by plausibility is not convergence.`,
    ``,
    `Return disagreementAuditSchema. Classify each disagreement:`,
    `- resolved_by_evidence: current plan already chose the evidence-backed answer`,
    `- material_unresolved: build planning would be unsafe until this is settled`,
    `- open_question: cannot be settled from available context; must appear in plan.open_questions`,
    `- preference_rejected: subjective preference or YAGNI concern deliberately rejected/accepted`,
    ``,
    `Only "material_unresolved" and "open_question" with severity must-resolve should force`,
    `another revision round. Do not create fake disagreement just to be thorough.`,
  ].filter(Boolean).join('\n')
}

function convergenceRevisePrompt(plan, audit, question, repoRoot, priorKnowledge) {
  const actionable = (audit.disagreements || []).filter(d =>
    d.severity === 'must-resolve' &&
    (d.status === 'material_unresolved' || d.status === 'open_question')
  )
  return [
    `You are revising the plan to converge cross-provider disagreements. Revise only toward`,
    `evidence-backed truth, explicit build-blocking open questions, or recorded YAGNI/preference`,
    `rejections. Do not add scope merely to appease a critic.`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `Planning question:`,
    question,
    ``,
    `Current plan:`,
    JSON.stringify(plan, null, 2),
    ``,
    `Actionable disagreements from audit:`,
    JSON.stringify(actionable, null, 2),
    ``,
    priorKnowledge ? `Prior knowledge to respect:\n${priorKnowledge}\n` : '',
    `Revision rules:`,
    `1. If evidence settles a disagreement, update the plan to the settled answer. Evidence`,
    `   means an actual observation (command + output) — either pasted by the audit or made`,
    `   by you now (Read/Grep/read-only query). If the audit only asserted a resolution`,
    `   without observed output, verify it yourself before adopting it.`,
    `2. If the evidence is unavailable but required, add a concrete blocker to open_questions.`,
    `3. If the disagreement is only preference/YAGNI, keep the simpler plan and record why.`,
    `4. Preserve the plan schema exactly. Keep architecture-level, not file-by-file.`,
    ``,
    `Return revisedOutputSchema. Use revision_log.tension_resolutions for provider`,
    `disagreement resolutions as well as completeness-vs-YAGNI tensions.`,
  ].filter(Boolean).join('\n')
}

// ---------- Script body ----------

const {
  question,
  sourceArtifact = null,
  codebaseResearch = null,
  priorKnowledge = null,
  providerDrafts = [],
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
    // Drafting is mechanical divergence — sonnet at medium effort is enough; synthesis is
    // where the judgment happens.
    { label: `draft:${f.key}`, phase: 'Draft', schema: draftOutputSchema, model: 'sonnet', effort: 'medium' }
  ))
)
const validDrafts = draftResults.filter(d => d && d.plan)
const validProviderDrafts = (Array.isArray(providerDrafts) ? providerDrafts : [])
  .map(normalizeProviderDraft)
  .filter(Boolean)
log(`Drafts: ${validDrafts.length}/${framings.length} native succeeded; ${validProviderDrafts.length} provider drafts supplied`)

if (validDrafts.length === 0 && validProviderDrafts.length === 0) {
  throw new Error('plan-fanout: all drafts failed')
}
const allDrafts = [...validDrafts, ...validProviderDrafts]

// Phase 2: synthesize
phase('Synthesize')
let synthesized = null
if (allDrafts.length === 1) {
  // Only one draft survived — skip synthesis, use it as-is.
  log('Only one draft survived; skipping synthesis')
  synthesized = allDrafts[0]
} else {
  synthesized = await agent(
    synthesizePrompt(question, allDrafts, repoRoot, priorKnowledge),
    // stay on opus — fable is not available on the subscription plan after 2026-07-07
    { label: 'synthesize', phase: 'Synthesize', model: 'opus', schema: draftOutputSchema }
  )
  if (!synthesized || !synthesized.plan) {
    log('Synthesis failed; falling back to first draft')
    synthesized = allDrafts[0]
  }
}

// Phase 3: parallel critics
phase('Critique')
const critiqueResults = await parallel(
  ['completeness', 'correctness', 'yagni'].map(lens => () => agent(
    criticPrompt(lens, synthesized.plan, question, codebaseResearch, repoRoot, priorKnowledge),
    // Completeness and YAGNI are checklist-style lenses — sonnet at medium effort. The
    // correctness critic reads the codebase to verify claims, so it keeps the default model.
    {
      label: `critic:${lens}`, phase: 'Critique', schema: criticOutputSchema,
      ...(lens === 'correctness' ? {} : { model: 'sonnet', effort: 'medium' }),
    }
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
    // stay on opus — fable is not available on the subscription plan after 2026-07-07
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

// Phase 5: bounded cross-provider disagreement convergence
phase('Converge')
const disagreementLog = []
const auditHistory = []
let finalRoundDisagreements = []
let disagreementRounds = 0
for (let round = 1; round <= 3; round += 1) {
  const audit = await agent(
    disagreementAuditPrompt(round, final.plan, allDrafts, validCritiques, question, codebaseResearch, repoRoot, priorKnowledge, auditHistory, final.revision_log),
    // stay on opus — fable is not available on the subscription plan after 2026-07-07
    { label: `disagreement-audit:${round}`, phase: 'Converge', model: 'opus', schema: disagreementAuditSchema }
  )
  const disagreements = (audit?.disagreements || []).filter(validDisagreement)
  const actionable = disagreements.filter(d =>
    d.severity === 'must-resolve' &&
    (d.status === 'material_unresolved' || d.status === 'open_question')
  )
  auditHistory.push({
    round,
    overall_assessment: audit?.overall_assessment || '',
    disagreements: disagreements.map(d => ({
      title: d.title, area: d.area, status: d.status, severity: d.severity,
      resolution: d.suggested_resolution,
    })),
  })
  finalRoundDisagreements = disagreements
  disagreementLog.push(...disagreements.map(d => ({
    round,
    title: d.title,
    area: d.area,
    providers: d.providers,
    status: d.status,
    severity: d.severity,
    resolution: d.suggested_resolution,
    evidence: d.evidence_needed,
  })))
  disagreementRounds = round
  log(`Converge round ${round}: ${disagreements.length} disagreement(s), ${actionable.length} actionable`)
  if (actionable.length === 0) {
    break
  }
  const revised = await agent(
    convergenceRevisePrompt(final.plan, { ...audit, disagreements: actionable }, question, repoRoot, priorKnowledge),
    // stay on opus — fable is not available on the subscription plan after 2026-07-07
    { label: `convergence-revise:${round}`, phase: 'Converge', model: 'opus', schema: revisedOutputSchema }
  )
  if (!revised || !revised.plan) {
    log(`Convergence revision ${round} failed; keeping current plan and surfacing disagreements`)
    break
  }
  final = {
    plan: revised.plan,
    revision_log: {
      incorporated: [
        ...(final.revision_log?.incorporated || []),
        ...(revised.revision_log?.incorporated || []),
      ],
      rejected: [
        ...(final.revision_log?.rejected || []),
        ...(revised.revision_log?.rejected || []),
      ],
      tension_resolutions: [
        ...(final.revision_log?.tension_resolutions || []),
        ...(revised.revision_log?.tension_resolutions || []),
      ],
    },
  }
}

const incorporatedCount = final.revision_log?.incorporated?.length || 0
const rejectedCount = final.revision_log?.rejected?.length || 0
const tensionCount = final.revision_log?.tension_resolutions?.length || 0
// Dedupe re-raised disagreements: the same (title, area) audited across rounds counts once.
const disagreementsFound = new Set(disagreementLog.map(d => `${d.title}::${d.area}`)).size
// Unresolved is a final-state question — compute it from the FINAL round only, so items
// resolved in later rounds are not double-counted as unresolved.
const unresolvedDisagreements = finalRoundDisagreements.filter(d =>
  d.severity === 'must-resolve' &&
  (d.status === 'material_unresolved' || d.status === 'open_question')
).length
const disagreementsResolved = Math.max(0, disagreementsFound - unresolvedDisagreements)

return {
  question,
  plan: final.plan,
  revision_log: final.revision_log || { incorporated: [], rejected: [], tension_resolutions: [] },
  provider_contributions: validProviderDrafts.map(d => ({
    planner_key: d.provider_key,
    assumptions: d.assumptions,
    disagreements: d.disagreements,
    evidence: d.evidence,
    open_questions: d.open_questions,
    notes: d.notes,
  })),
  drafts_considered: allDrafts.map(d => ({ framing: d.framing, framing_notes: d.framing_notes })),
  critic_findings: validCritiques.flatMap(c =>
    (c.findings || []).filter(validFinding).map(f => ({ ...f, critic_lens: c.lens }))
  ),
  disagreement_log: disagreementLog,
  stats: {
    framings_attempted: framings.length,
    drafts_succeeded: allDrafts.length,
    critics_succeeded: validCritiques.length,
    total_findings: totalFindings,
    must_address_findings: mustAddressCount,
    incorporated: incorporatedCount,
    rejected: rejectedCount,
    tensions_resolved: tensionCount,
    provider_contributors: validProviderDrafts.length + (validDrafts.length > 0 ? 1 : 0),
    disagreement_rounds: disagreementRounds,
    disagreements_found: disagreementsFound,
    disagreements_resolved: disagreementsResolved,
    unresolved_disagreements: unresolvedDisagreements,
  },
}

// investigate-fanout — heavyweight orchestrator for /investigate when the bug is
// ambiguous, intermittent, or has multiple plausible root causes.
//
// Bug investigation maps to the scientific method: generate hypotheses → test each
// with evidence → try to falsify the survivors → converge on root cause (or honestly
// admit we don't have one).
//
// Phase shape:
//   1. Generate (parallel): N hypothesis generators with different angles
//      (stack-trace, recent-commits, code-pattern, data-state by default)
//   2. Dedup: synth agent groups near-duplicate hypotheses, applies cross-angle
//      confidence boost (multiple angles → same hypothesis = stronger signal)
//   3. Test (parallel): for each surviving hypothesis, an evidence-gatherer agent
//      runs the testable prediction and returns confirmed/refuted/inconclusive
//   4. Adversarial refute (parallel): for each CONFIRMED hypothesis, 2 skeptics
//      try to falsify. Same pattern as review-synthesize's verify.
//   5. Synthesize: opus agent picks the root cause (if any survives), builds the
//      causal chain, drafts short remediation. HONEST about partial findings —
//      "we ruled out X and Y, still don't know" is a valid output.
//
// Returns the synthesized object only. MCP persistence stays in the skill.
//
// WHY ADVERSARIAL ON HYPOTHESES (not just findings like review): premature
// convergence on the wrong root cause causes regressions and recurrence. A
// confirmed hypothesis is much more dangerous than an unconfirmed one if it's
// wrong, because someone will ship a fix based on it.

export const meta = {
  name: 'investigate-fanout',
  description: 'Hypothesis-elimination orchestrator for bug investigation. Multi-angle generation, evidence-gathering, adversarial refutation, honest synthesis (including "no root cause found" outcomes).',
  phases: [
    { title: 'Generate', detail: 'parallel hypothesis generators from different angles' },
    { title: 'Dedup', detail: 'group near-duplicate hypotheses, boost cross-angle agreement' },
    { title: 'Test', detail: 'evidence-gathering per hypothesis (parallel)' },
    { title: 'Refute', detail: 'adversarial skeptics on confirmed hypotheses' },
    { title: 'Synthesize', detail: 'pick root cause, build causal chain, short remediation' },
  ],
}

// ---------- Default angles ----------

const DEFAULT_ANGLES = [
  {
    key: 'stack-trace',
    description: 'Read the error message, stack trace, and immediate failure point. Propose hypotheses for what could directly produce this failure. Be specific — name the function or variable.',
  },
  {
    key: 'recent-commits',
    description: 'Run git log on files in the affected area (or the whole repo if scope is unclear). Look at commits in the last 7-30 days. Propose hypotheses based on what changed — new code is more suspect than old code.',
  },
  {
    key: 'code-pattern',
    description: 'Read the affected code paths. Identify common bug patterns in this style of code (race conditions, missing error handling, off-by-one, null/undefined misuse, etc.). Propose hypotheses anchored in the actual code structure.',
  },
  {
    key: 'data-state',
    description: 'Check the data state at the time of failure if possible (DB queries, log records, recent records that succeeded vs failed). Propose hypotheses about data shape, missing records, malformed values, or unexpected state.',
  },
]

// ---------- Inline schemas ----------

const hypothesisSchema = {
  type: 'object',
  required: ['statement', 'evidence', 'testable_prediction', 'category', 'initial_confidence'],
  properties: {
    statement: { type: 'string', minLength: 16, description: 'Specific claim about root cause. Name component/condition/behavior concretely.' },
    evidence: { type: 'array', minItems: 1, items: { type: 'string' }, description: 'Observations that support this hypothesis.' },
    testable_prediction: { type: 'string', minLength: 16, description: 'What we expect to see when we check Y, that confirms or refutes the hypothesis.' },
    category: { type: 'string', enum: ['code', 'data', 'infrastructure', 'config', 'dependency', 'concurrency', 'environment', 'other'] },
    initial_confidence: { type: 'number', minimum: 0, maximum: 1 },
  },
}

const generatorOutputSchema = {
  type: 'object',
  required: ['angle', 'hypotheses', 'notes'],
  properties: {
    angle: { type: 'string' },
    hypotheses: { type: 'array', items: hypothesisSchema },
    notes: { type: 'string', minLength: 8 },
  },
}

const dedupOutputSchema = {
  type: 'object',
  required: ['merged_hypotheses'],
  properties: {
    merged_hypotheses: {
      type: 'array',
      items: {
        type: 'object',
        required: ['hypothesis', 'source_angles'],
        properties: {
          hypothesis: hypothesisSchema,
          source_angles: { type: 'array', minItems: 1, items: { type: 'string' } },
        },
      },
    },
  },
}

const verdictSchema = {
  type: 'object',
  required: ['hypothesis_id', 'verdict', 'evidence_gathered', 'final_confidence', 'rationale'],
  properties: {
    hypothesis_id: { type: 'string' },
    verdict: { type: 'string', enum: ['confirmed', 'refuted', 'inconclusive'] },
    evidence_gathered: { type: 'array', items: { type: 'string' } },
    final_confidence: { type: 'number', minimum: 0, maximum: 1 },
    rationale: { type: 'string', minLength: 8 },
    counter_evidence: { type: 'array', items: { type: 'string' } },
  },
}

const refuteOutputSchema = {
  type: 'object',
  required: ['hypothesis_id', 'verdict', 'rationale'],
  properties: {
    hypothesis_id: { type: 'string' },
    verdict: { type: 'string', enum: ['survives', 'refuted', 'weakened'] },
    refutation_attempt: { type: 'string', minLength: 8 },
    rationale: { type: 'string', minLength: 8 },
    alternative_hypothesis: { type: ['string', 'null'] },
  },
}

const synthesisSchema = {
  type: 'object',
  required: ['root_cause', 'causal_chain', 'recommended_remediation', 'refuted_hypotheses', 'inconclusive_hypotheses', 'residual_unknowns'],
  properties: {
    root_cause: {
      anyOf: [
        { type: 'null' },
        {
          type: 'object',
          required: ['statement', 'confidence', 'evidence_summary', 'survived_skeptics'],
          properties: {
            statement: { type: 'string', minLength: 16 },
            confidence: { type: 'number', minimum: 0, maximum: 1 },
            evidence_summary: { type: 'string', minLength: 16 },
            survived_skeptics: { type: 'boolean' },
          },
        },
      ],
    },
    causal_chain: { type: 'array', minItems: 1, items: { type: 'string' }, description: 'Trigger → ... → symptom. One step per array entry.' },
    recommended_remediation: { type: 'string', minLength: 16, description: 'Short paragraph. This is /investigate, not /plan — do not design the full fix.' },
    refuted_hypotheses: {
      type: 'array',
      items: {
        type: 'object',
        required: ['statement', 'why_refuted'],
        properties: {
          statement: { type: 'string' },
          why_refuted: { type: 'string', minLength: 8 },
        },
      },
    },
    inconclusive_hypotheses: {
      type: 'array',
      items: {
        type: 'object',
        required: ['statement', 'what_still_needs_checking'],
        properties: {
          statement: { type: 'string' },
          what_still_needs_checking: { type: 'string', minLength: 8 },
        },
      },
    },
    residual_unknowns: { type: 'array', items: { type: 'string' } },
  },
}

// ---------- Pure helpers ----------

function validHypothesis(h) {
  if (!h || typeof h !== 'object') return false
  return typeof h.statement === 'string' && h.statement.length >= 8 &&
         Array.isArray(h.evidence) && h.evidence.length > 0 &&
         typeof h.testable_prediction === 'string' &&
         typeof h.category === 'string' &&
         Number.isFinite(+h.initial_confidence)
}

function applyCrossAngleBoost(item) {
  // +0.10 per additional source angle, capped at 1.0
  const angles = item.source_angles?.length || 1
  const extra = Math.max(0, angles - 1)
  return {
    ...item,
    hypothesis: {
      ...item.hypothesis,
      initial_confidence: Math.min(1.0, item.hypothesis.initial_confidence + 0.1 * extra),
    },
  }
}

// ---------- Prompts ----------

function generatePrompt(angle, bug, environment, errorEvidence, repoRoot) {
  return [
    `You are a hypothesis generator for a bug investigation. Your angle: "${angle.key}".`,
    `Approach: ${angle.description}`,
    ``,
    `Repository root: ${repoRoot}`,
    `Environment: ${environment}`,
    ``,
    `Bug description:`,
    bug,
    ``,
    errorEvidence ? `Error evidence already collected:\n${errorEvidence}\n` : '',
    `Generate 1-4 hypotheses from YOUR angle. Two generators using different angles should`,
    `produce different hypotheses — do not converge with other generators.`,
    ``,
    `Return per generatorOutputSchema:`,
    `- angle: "${angle.key}"`,
    `- hypotheses: array. For each:`,
    `   - statement: SPECIFIC claim. Name the component/function/condition. Not "something with the timeout".`,
    `   - evidence: at least 1 concrete observation that supports this hypothesis.`,
    `   - testable_prediction: "If this is the root cause, then when we check X we will see Y." Specific and falsifiable.`,
    `   - category: code / data / infrastructure / config / dependency / concurrency / environment / other`,
    `   - initial_confidence: 0.0-1.0 based on evidence strength. Be honest — 0.5 means "plausible but not strongly supported".`,
    `- notes: 1-3 sentences on what your angle surfaced`,
    ``,
    `Quality rules:`,
    `- Specific > thorough. 2 strong hypotheses beat 4 vague ones.`,
    `- Each hypothesis must be falsifiable. "It's a timing issue sometimes" is NOT a hypothesis.`,
    `- Hypothesis without a testable_prediction is useless to downstream — do not return it.`,
  ].filter(Boolean).join('\n')
}

function dedupPrompt(bug, hypothesesByAngle) {
  return [
    `You are deduplicating hypotheses from multiple parallel generators.`,
    ``,
    `Bug: ${bug}`,
    ``,
    `Hypotheses by generator angle:`,
    JSON.stringify(hypothesesByAngle, null, 2),
    ``,
    `Group semantically-equivalent hypotheses. Two hypotheses about "X is null because Y"`,
    `are the same even if worded differently. Two hypotheses about different X are different.`,
    ``,
    `Return per dedupOutputSchema:`,
    `- merged_hypotheses: one entry per unique hypothesis.`,
    `  - hypothesis: pick the strongest formulation (best statement, best testable_prediction,`,
    `    union evidence across sources, highest initial_confidence)`,
    `  - source_angles: the angle keys that produced this hypothesis`,
    ``,
    `Do NOT add new hypotheses. Do NOT drop hypotheses. Only merge near-duplicates.`,
    `Cap at 8 merged hypotheses — if more come in, drop the lowest-initial_confidence ones.`,
  ].join('\n')
}

function testPrompt(hypothesisId, hypothesis, bug, environment, repoRoot) {
  return [
    `You are gathering evidence to test a hypothesis. Hypothesis ID: ${hypothesisId}.`,
    ``,
    `Bug: ${bug}`,
    `Environment: ${environment}`,
    `Repository root: ${repoRoot}`,
    ``,
    `Hypothesis under test:`,
    JSON.stringify(hypothesis, null, 2),
    ``,
    `Your job: execute the testable_prediction. Gather CONCRETE evidence. Use Read, Bash,`,
    `Grep, MCP tools as needed to check the prediction.`,
    ``,
    `Return per verdictSchema:`,
    `- hypothesis_id: "${hypothesisId}"`,
    `- verdict: confirmed (evidence supports the hypothesis), refuted (evidence contradicts it), inconclusive (cannot determine from available evidence)`,
    `- evidence_gathered: array of concrete observations you collected (file:line, log entries, query results, command outputs)`,
    `- final_confidence: your post-evidence confidence in the hypothesis (0.0-1.0)`,
    `- rationale: 2-4 sentences on why your verdict, citing the evidence`,
    `- counter_evidence: anything that argues against, even if you concluded confirmed`,
    ``,
    `Default to inconclusive over confirmed when in doubt. False confirmations are more`,
    `dangerous than honest "we don't know yet" — someone will ship a fix based on a confirmed`,
    `hypothesis.`,
  ].join('\n')
}

function refutePrompt(hypothesisId, hypothesis, skepticIdx, bug, environment, evidenceGathered) {
  return [
    `You are skeptic #${skepticIdx} for a confirmed hypothesis. Your job is to REFUTE.`,
    `Default to "refuted" or "weakened" unless the evidence is irrefutable.`,
    ``,
    `Bug: ${bug}`,
    `Environment: ${environment}`,
    ``,
    `Hypothesis claimed as root cause:`,
    JSON.stringify(hypothesis, null, 2),
    ``,
    `Evidence gathered by tester:`,
    JSON.stringify(evidenceGathered, null, 2),
    ``,
    `Try to falsify. Specifically check:`,
    `- Does this hypothesis explain ALL observed symptoms, or only some?`,
    `- Is there a simpler alternative that would also explain the evidence?`,
    `- Is the evidence consistent with other plausible causes (correlation vs causation)?`,
    `- If we fixed exactly what this hypothesis says, would the bug stop? Or would it`,
    `  recur in a different form because the real cause is something else?`,
    `- Did the tester only check the things that would confirm? What did they not check`,
    `  that would refute?`,
    ``,
    `Return per refuteOutputSchema:`,
    `- hypothesis_id: "${hypothesisId}"`,
    `- refutation_attempt: 1-2 sentences on what you tried to find/check`,
    `- verdict: survives (cannot refute, evidence holds) / refuted (definite alternative explanation or counter-evidence) / weakened (evidence less strong than tester claimed but not refuted)`,
    `- rationale: 2-4 sentences with specific reasoning`,
    `- alternative_hypothesis: if you have a better explanation, state it (otherwise null)`,
  ].join('\n')
}

function synthesisPrompt(bug, environment, hypothesesWithVerdicts, refuteVerdictsByHypId, repoRoot) {
  return [
    `You are the investigation synthesizer. Produce the final root cause analysis.`,
    `Bug: ${bug}`,
    `Environment: ${environment}`,
    `Repository root: ${repoRoot}`,
    ``,
    `All hypotheses with verdicts:`,
    JSON.stringify(hypothesesWithVerdicts, null, 2),
    ``,
    `Skeptic refutation attempts by hypothesis ID:`,
    JSON.stringify(refuteVerdictsByHypId, null, 2),
    ``,
    `Return per synthesisSchema:`,
    `- root_cause: ONE hypothesis that survived both confirmation AND skeptics, OR null if none did.`,
    `  - statement: the surviving hypothesis claim`,
    `  - confidence: how sure are you (cap at 0.95 unless evidence is irrefutable)`,
    `  - evidence_summary: 2-4 sentences citing concrete evidence`,
    `  - survived_skeptics: true only if ALL skeptics returned "survives" (or weakened — that still survives, just less strongly)`,
    `- causal_chain: trigger → ... → symptom. One step per array entry. Must have NO gaps —`,
    `  "somehow X causes Y" is a gap. If you can't fill a gap, set root_cause to null.`,
    `- recommended_remediation: SHORT paragraph. This is /investigate, not /plan. Say what to`,
    `  change at a high level, not how to design the fix.`,
    `- refuted_hypotheses: hypotheses that were definitely ruled out (with why)`,
    `- inconclusive_hypotheses: hypotheses that couldn't be confirmed or refuted (with what's still needed)`,
    `- residual_unknowns: questions the investigation could not answer`,
    ``,
    `Honesty bar:`,
    `- If no hypothesis survived AND skeptics, set root_cause: null. Do not invent one.`,
    `- "We ruled out X, Y, Z; still don't know" is a VALID investigation outcome. The user`,
    `  has better information than before, even without a confirmed root cause.`,
    `- Premature confirmation causes regressions. Better to under-claim than over-claim.`,
  ].join('\n')
}

// ---------- Script body ----------

const {
  bug,
  environment = 'prod',
  errorEvidence = null,
  angles = DEFAULT_ANGLES,
  repoRoot,
  mode = 'interactive',
  testTopN = 6,
} = args

if (!bug || typeof bug !== 'string') {
  throw new Error('investigate-fanout: args.bug is required (the bug description)')
}
if (!repoRoot || typeof repoRoot !== 'string') {
  throw new Error('investigate-fanout: args.repoRoot is required')
}

// Phase 1: parallel hypothesis generation
phase('Generate')
const generatorResults = await parallel(
  angles.map(a => () => agent(
    generatePrompt(a, bug, environment, errorEvidence, repoRoot),
    { label: `generate:${a.key}`, phase: 'Generate', schema: generatorOutputSchema }
  ))
)

const hypothesesByAngle = []
let generatorErrors = 0
let invalidHypotheses = 0
for (const r of generatorResults) {
  if (!r || !Array.isArray(r.hypotheses)) { generatorErrors += 1; continue }
  const valid = r.hypotheses.filter(h => {
    if (!validHypothesis(h)) { invalidHypotheses += 1; return false }
    return true
  })
  hypothesesByAngle.push({ angle: r.angle, hypotheses: valid, notes: r.notes })
}
const rawHypothesisCount = hypothesesByAngle.reduce((n, a) => n + a.hypotheses.length, 0)
log(`Generate: ${generatorResults.length} angles, ${rawHypothesisCount} valid hypotheses (${invalidHypotheses} invalid, ${generatorErrors} errors)`)

if (rawHypothesisCount === 0) {
  return {
    bug,
    root_cause: null,
    causal_chain: ['investigation generated zero valid hypotheses — cannot proceed'],
    recommended_remediation: 'Provide more error evidence or context and re-run /investigate.',
    refuted_hypotheses: [],
    inconclusive_hypotheses: [],
    residual_unknowns: ['no hypotheses generated'],
    stats: { angles_attempted: angles.length, generator_errors: generatorErrors, invalid_hypotheses: invalidHypotheses, raw_hypotheses: 0 },
  }
}

// Phase 2: dedup + cross-angle boost
phase('Dedup')
const dedupResult = await agent(
  dedupPrompt(bug, hypothesesByAngle),
  { label: 'dedup', phase: 'Dedup', model: 'sonnet', effort: 'low', schema: dedupOutputSchema }
)
let mergedHypotheses = []
if (dedupResult && Array.isArray(dedupResult.merged_hypotheses)) {
  mergedHypotheses = dedupResult.merged_hypotheses
    .map(applyCrossAngleBoost)
    .sort((a, b) => (b.hypothesis.initial_confidence || 0) - (a.hypothesis.initial_confidence || 0))
    .slice(0, testTopN)
} else {
  // Fallback: skip dedup, just take all hypotheses
  log('Dedup failed; falling back to raw hypotheses')
  for (const angle of hypothesesByAngle) {
    for (const h of angle.hypotheses) {
      mergedHypotheses.push({ hypothesis: h, source_angles: [angle.angle] })
    }
  }
  mergedHypotheses = mergedHypotheses.slice(0, testTopN)
}
log(`Dedup: ${mergedHypotheses.length} unique hypotheses (testing top ${testTopN})`)

// Assign stable IDs for later cross-referencing
const idForHypothesis = (i) => `H${(i + 1).toString().padStart(2, '0')}`
const hypothesesWithIds = mergedHypotheses.map((m, i) => ({ ...m, id: idForHypothesis(i) }))

// Phase 3: parallel evidence gathering
phase('Test')
const testResults = await parallel(
  hypothesesWithIds.map(m => () => agent(
    testPrompt(m.id, m.hypothesis, bug, environment, repoRoot),
    { label: `test:${m.id}`, phase: 'Test', model: 'sonnet', effort: 'medium', schema: verdictSchema }
  ))
)

const verdictsById = new Map()
let testErrors = 0
for (const v of testResults) {
  if (!v || !v.hypothesis_id) { testErrors += 1; continue }
  verdictsById.set(v.hypothesis_id, v)
}
const confirmedIds = []
const refutedIds = []
const inconclusiveIds = []
for (const m of hypothesesWithIds) {
  const v = verdictsById.get(m.id)
  if (!v) continue
  if (v.verdict === 'confirmed') confirmedIds.push(m.id)
  else if (v.verdict === 'refuted') refutedIds.push(m.id)
  else inconclusiveIds.push(m.id)
}
log(`Test: ${confirmedIds.length} confirmed, ${refutedIds.length} refuted, ${inconclusiveIds.length} inconclusive (${testErrors} errors)`)

// Phase 4: adversarial refute on confirmed hypotheses
phase('Refute')
const skepticCalls = []
for (const id of confirmedIds) {
  const m = hypothesesWithIds.find(x => x.id === id)
  const v = verdictsById.get(id)
  for (let i = 1; i <= 2; i++) {
    skepticCalls.push(() => agent(
      refutePrompt(id, m.hypothesis, i, bug, environment, v.evidence_gathered),
      { label: `refute:${id}:${i}`, phase: 'Refute', schema: refuteOutputSchema }
    ))
  }
}
const refuteResults = skepticCalls.length ? await parallel(skepticCalls) : []

const refuteByHypId = new Map()
for (const r of refuteResults) {
  if (!r || !r.hypothesis_id) continue
  if (!refuteByHypId.has(r.hypothesis_id)) refuteByHypId.set(r.hypothesis_id, [])
  refuteByHypId.get(r.hypothesis_id).push(r)
}
log(`Refute: ${confirmedIds.length} confirmed hypotheses × 2 skeptics = ${skepticCalls.length} attempts`)

// Phase 5: synthesize
phase('Synthesize')
const hypothesesWithVerdicts = hypothesesWithIds.map(m => ({
  id: m.id,
  hypothesis: m.hypothesis,
  source_angles: m.source_angles,
  verdict: verdictsById.get(m.id) || null,
}))

const refuteVerdictsByHypId = {}
for (const [id, list] of refuteByHypId.entries()) {
  refuteVerdictsByHypId[id] = list
}

const synth = await agent(
  synthesisPrompt(bug, environment, hypothesesWithVerdicts, refuteVerdictsByHypId, repoRoot),
  { label: 'synthesize', phase: 'Synthesize', model: 'opus', schema: synthesisSchema }
) || {
  root_cause: null,
  causal_chain: ['synthesis failed'],
  recommended_remediation: 'synthesis agent returned no result; review the raw verdicts in stats',
  refuted_hypotheses: [],
  inconclusive_hypotheses: [],
  residual_unknowns: ['synthesis failed'],
}

return {
  bug,
  environment,
  root_cause: synth.root_cause,
  causal_chain: synth.causal_chain,
  recommended_remediation: synth.recommended_remediation,
  hypotheses: hypothesesWithVerdicts.map(h => ({
    id: h.id,
    statement: h.hypothesis.statement,
    category: h.hypothesis.category,
    source_angles: h.source_angles,
    initial_confidence: h.hypothesis.initial_confidence,
    verdict: h.verdict?.verdict || 'not_tested',
    final_confidence: h.verdict?.final_confidence ?? null,
    evidence_gathered: h.verdict?.evidence_gathered || [],
    skeptic_verdicts: (refuteByHypId.get(h.id) || []).map(r => ({
      verdict: r.verdict,
      rationale: r.rationale,
      alternative_hypothesis: r.alternative_hypothesis || null,
    })),
  })),
  refuted_hypotheses: synth.refuted_hypotheses || [],
  inconclusive_hypotheses: synth.inconclusive_hypotheses || [],
  residual_unknowns: synth.residual_unknowns || [],
  stats: {
    angles_attempted: angles.length,
    generator_errors: generatorErrors,
    invalid_hypotheses: invalidHypotheses,
    raw_hypotheses: rawHypothesisCount,
    after_dedup: mergedHypotheses.length,
    tested: hypothesesWithIds.length,
    confirmed: confirmedIds.length,
    refuted_in_test: refutedIds.length,
    inconclusive_in_test: inconclusiveIds.length,
    test_errors: testErrors,
    skeptic_attempts: skepticCalls.length,
    root_cause_found: !!synth.root_cause,
  },
}

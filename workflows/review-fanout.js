// review-fanout — heavyweight orchestrator for /review when the diff is non-trivial.
//
// Phase shape (mirrors skills/review/SKILL.md Synthesis Methodology 1-9):
//   1. BARRIER: parallel() all reviewers, wait for every one.
//   2. Validate + flatten + union coverage.
//   3. Dedup by fingerprint, then apply +0.10 cross-reviewer boost (capped at 1.0).
//   4. Confidence gate (<0.60 suppressed; p1 >=0.50 rescued).
//   5. Adversarial verify: ONLY borderline (0.55 <= c < 0.80). Consensus-boosted
//      findings already past 0.80 skip skeptics entirely. Skeptics run in parallel.
//   6. Apply skeptic verdicts (both-refute -> drop; both-uphold -> +0.10; attach counter-evidence).
//   7. Separate pre-existing.
//   8. Sort.
//   9. Partition into {inSkillFixer, residualActionable, reportOnly}.
//
// Returns the synthesized object only. MCP persistence, mode behavior, and
// presentation stay in the skill — the workflow never touches MCP.
//
// WHY A BARRIER (load-bearing): the +0.10 cross-reviewer boost can lift a 0.70 finding
// past the 0.80 verify-skip threshold. Pipeline-streaming would launch skeptics on
// findings that consensus would have skipped, wasting the most expensive tokens in
// the graph. The ~10-20% wall-clock cost saves ~30-50% of borderline skeptic spend.

export const meta = {
  name: 'review-fanout',
  description:
    'Fan out reviewers under a barrier, dedup with cross-reviewer boost, adversarially ' +
    'verify only borderline findings, partition results. Skill handles MCP and presentation.',
  phases: [
    { title: 'Fan out', detail: 'all reviewers in parallel (barrier)' },
    { title: 'Verify', detail: 'adversarial 2-skeptic verify on borderline findings only' },
  ],
}

// ---------- Inline schemas ----------

const findingSchema = {
  type: 'object',
  required: [
    'title', 'severity', 'file', 'line', 'confidence',
    'autofix_class', 'owner', 'requires_verification',
    'pre_existing', 'evidence', 'why_it_matters',
  ],
  properties: {
    title: { type: 'string', minLength: 4 },
    severity: { type: 'string', enum: ['p1', 'p2', 'p3'] },
    file: { type: 'string' },
    line: { type: 'integer', minimum: 0 },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
    autofix_class: { type: 'string', enum: ['safe_auto', 'gated_auto', 'manual', 'advisory'] },
    owner: { type: 'string', enum: ['review-fixer', 'downstream-resolver', 'human'] },
    requires_verification: { type: 'boolean' },
    pre_existing: { type: 'boolean' },
    evidence: { type: 'array', items: { type: 'string' }, minItems: 1 },
    why_it_matters: { type: 'string', minLength: 8 },
    suggested_fix: { type: ['string', 'null'] },
  },
}

const reviewerOutputSchema = {
  type: 'object',
  required: ['reviewer_key', 'findings', 'residual_risks', 'testing_gaps'],
  properties: {
    reviewer_key: { type: 'string' },
    findings: { type: 'array', items: findingSchema },
    residual_risks: { type: 'array', items: { type: 'string' } },
    testing_gaps: { type: 'array', items: { type: 'string' } },
  },
}

const verifyVerdictSchema = {
  type: 'object',
  required: ['fingerprint', 'verdict', 'rationale'],
  properties: {
    fingerprint: { type: 'string' },
    verdict: { type: 'string', enum: ['refute', 'uphold', 'unsure'] },
    rationale: { type: 'string', minLength: 8 },
    counter_evidence: { type: 'array', items: { type: 'string' } },
  },
}

// ---------- Pure helpers (deterministic) ----------

function normalizeTitle(t) {
  return String(t || '').toLowerCase().replace(/[`'".]/g, '').replace(/\s+/g, ' ').trim()
}
function normalizeFile(f) {
  return String(f || '').replace(/\\/g, '/').replace(/^\.\//, '').trim()
}
function lineBucket(line) {
  const n = Number.isFinite(+line) ? Math.max(0, +line | 0) : 0
  return Math.floor(n / 7)
}
function fingerprint(f) {
  return [normalizeFile(f.file), lineBucket(f.line), normalizeTitle(f.title)].join('|')
}
function severityRank(s) {
  return { p1: 0, p2: 1, p3: 2 }[s] ?? 3
}
function validFinding(f) {
  if (!f || typeof f !== 'object') return false
  const req = ['title', 'severity', 'file', 'line', 'confidence', 'autofix_class',
               'owner', 'requires_verification', 'pre_existing', 'evidence', 'why_it_matters']
  for (const k of req) if (!(k in f)) return false
  if (!Array.isArray(f.evidence) || f.evidence.length === 0) return false
  return true
}

function mergeFinding(a, b) {
  // Conservative narrowing per SKILL.md "Normalize routing": narrow allowed, widen not.
  const autofixOrder = ['manual', 'gated_auto', 'safe_auto', 'advisory']
  const autofix_class = autofixOrder.indexOf(a.autofix_class) <= autofixOrder.indexOf(b.autofix_class)
    ? a.autofix_class : b.autofix_class
  const ownerOrder = ['human', 'downstream-resolver', 'review-fixer']
  const owner = ownerOrder.indexOf(a.owner) <= ownerOrder.indexOf(b.owner) ? a.owner : b.owner
  const moreSevere = severityRank(a.severity) <= severityRank(b.severity) ? a : b
  return {
    ...moreSevere,
    confidence: Math.max(a.confidence, b.confidence),
    reviewers: Array.from(new Set([...(a.reviewers || []), ...(b.reviewers || [])])),
    evidence: Array.from(new Set([...(a.evidence || []), ...(b.evidence || [])])),
    suggested_fix: a.suggested_fix ?? b.suggested_fix ?? null,
    autofix_class,
    owner,
    pre_existing: a.pre_existing && b.pre_existing,
    requires_verification: a.requires_verification || b.requires_verification,
  }
}

function applyCrossReviewerBoost(f) {
  const extra = Math.max(0, (f.reviewers?.length || 1) - 1)
  return { ...f, confidence: Math.min(1.0, f.confidence + 0.1 * extra) }
}

function passesConfidenceGate(f) {
  if (f.severity === 'p1' && f.confidence >= 0.5) return true
  return f.confidence >= 0.6
}

function isBorderline(f) {
  return f.confidence >= 0.55 && f.confidence < 0.8
}

function sortFindings(arr) {
  return [...arr].sort((a, b) => {
    const s = severityRank(a.severity) - severityRank(b.severity); if (s) return s
    const c = (b.confidence || 0) - (a.confidence || 0); if (c) return c
    const f = normalizeFile(a.file).localeCompare(normalizeFile(b.file)); if (f) return f
    return (a.line || 0) - (b.line || 0)
  })
}

function partition(findings) {
  const inSkillFixer = [], residualActionable = [], reportOnly = []
  for (const f of findings) {
    if (f.autofix_class === 'safe_auto' && f.owner === 'review-fixer') inSkillFixer.push(f)
    else if ((f.autofix_class === 'gated_auto' || f.autofix_class === 'manual') &&
             f.owner === 'downstream-resolver') residualActionable.push(f)
    else reportOnly.push(f)
  }
  return { inSkillFixer, residualActionable, reportOnly }
}

function reviewerPrompt(reviewer, intent, files, diffSummary, mode) {
  const scope = reviewer.filesScope?.length ? reviewer.filesScope : files
  return [
    `You are reviewer "${reviewer.key}". Focus: ${reviewer.focus}. Mode: ${mode}.`,
    ``,
    `Intent:`,
    intent,
    ``,
    `Files in scope:`,
    scope.map(p => `  - ${p}`).join('\n'),
    ``,
    `Diff summary:`,
    diffSummary,
    ``,
    `References to load first:`,
    (reviewer.references || []).map(p => `  - ${p}`).join('\n') || '  (none)',
    ``,
    `Return per the reviewer output schema. Rules:`,
    `- One finding per real issue. Specific file:line. No vague nits.`,
    `- evidence: quote or paraphrase the code that proves the issue (>=1 required).`,
    `- confidence is code-grounded. >=0.80 requires direct evidence.`,
    `- pre_existing: true if the issue exists on main and the diff did not introduce it.`,
    `- autofix_class safe_auto only if the fix is mechanical and obviously correct.`,
    `- Set reviewer_key to "${reviewer.key}".`,
  ].join('\n')
}

function skepticPrompt(finding, idx, intent, diffSummary) {
  return [
    `You are an adversarial skeptic (#${idx}). Your job is to REFUTE this finding.`,
    `Default to "refute" unless the evidence is concrete and reproducible.`,
    ``,
    `Intent: ${intent}`,
    `Diff summary: ${diffSummary}`,
    ``,
    `Finding under review:`,
    `  file: ${finding.file}:${finding.line}`,
    `  title: ${finding.title}`,
    `  severity: ${finding.severity}`,
    `  confidence reported: ${finding.confidence}`,
    `  why_it_matters: ${finding.why_it_matters}`,
    `  evidence:`,
    (finding.evidence || []).map(e => `    - ${e}`).join('\n'),
    ``,
    `Open the file at the line. Read +/- 30 lines of context.`,
    `Return per verifyVerdictSchema. fingerprint must equal "${fingerprint(finding)}".`,
  ].join('\n')
}

// ---------- Script body ----------

const { reviewers, intent, files, diffSummary, mode } = args

// Phase 1: BARRIER fan-out
phase('Fan out')
const reviewerResults = await parallel(
  reviewers.map(r => () => agent(
    reviewerPrompt(r, intent, files, diffSummary, mode),
    { label: `reviewer:${r.key}`, phase: 'Fan out', model: r.model, schema: reviewerOutputSchema }
  ))
)

// Phase 2: validate + flatten + union coverage
const allFindings = []
const residualRisks = new Set()
const testingGaps = new Set()
let invalidDropped = 0
let reviewerErrors = 0

for (const result of reviewerResults) {
  if (!result || !Array.isArray(result.findings)) { reviewerErrors++; continue }
  for (const f of result.findings) {
    if (!validFinding(f)) { invalidDropped++; continue }
    allFindings.push({ ...f, reviewers: [result.reviewer_key], suggested_fix: f.suggested_fix ?? null })
  }
  for (const r of result.residual_risks || []) residualRisks.add(r)
  for (const g of result.testing_gaps || []) testingGaps.add(g)
}
log(`Fan-out: ${reviewerResults.length} reviewers, ${allFindings.length} valid findings (${invalidDropped} invalid, ${reviewerErrors} reviewer errors)`)

// Phase 3: dedup + cross-reviewer boost
const byFingerprint = new Map()
for (const f of allFindings) {
  const fp = fingerprint(f)
  byFingerprint.set(fp, byFingerprint.has(fp) ? mergeFinding(byFingerprint.get(fp), f) : f)
}
let merged = Array.from(byFingerprint.values()).map(applyCrossReviewerBoost)

// Phase 4: confidence gate
const beforeGate = merged.length
merged = merged.filter(passesConfidenceGate)
const suppressedByGate = beforeGate - merged.length

// Phase 5: adversarial verify on borderline only
phase('Verify')
const borderline = merged.filter(isBorderline)
const skipsVerify = merged.filter(f => !isBorderline(f))
log(`Verify: ${borderline.length} borderline -> 2 skeptics each; ${skipsVerify.length} skip verify`)

const skepticCalls = []
for (const f of borderline) {
  for (let i = 1; i <= 2; i++) {
    skepticCalls.push(() => agent(
      skepticPrompt(f, i, intent, diffSummary),
      { label: `skeptic:${fingerprint(f)}:${i}`, phase: 'Verify', model: 'sonnet', schema: verifyVerdictSchema }
    ))
  }
}
const verdicts = skepticCalls.length ? await parallel(skepticCalls) : []

const verdictsByFp = new Map()
for (const v of verdicts) {
  if (!v || !v.fingerprint) continue
  if (!verdictsByFp.has(v.fingerprint)) verdictsByFp.set(v.fingerprint, [])
  verdictsByFp.get(v.fingerprint).push(v)
}

// Phase 6: apply verdicts
const verifiedBorderline = []
let verifyDropped = 0
for (const f of borderline) {
  const vs = verdictsByFp.get(fingerprint(f)) || []
  const refutes = vs.filter(v => v.verdict === 'refute').length
  const upholds = vs.filter(v => v.verdict === 'uphold').length
  if (vs.length >= 2 && refutes === vs.length) { verifyDropped++; continue }
  let adj = f
  if (vs.length >= 2 && upholds === vs.length) {
    adj = { ...f, confidence: Math.min(1.0, f.confidence + 0.1) }
  }
  const counter = vs.flatMap(v => v.counter_evidence || [])
  if (counter.length) {
    adj = { ...adj, evidence: [...(adj.evidence || []), ...counter.map(c => `[skeptic] ${c}`)] }
  }
  adj = { ...adj, requires_verification: false }
  verifiedBorderline.push(adj)
}

// Phase 7-9: recombine, separate pre-existing, sort, partition
const finalFindings = [...skipsVerify, ...verifiedBorderline]
const preExisting = finalFindings.filter(f => f.pre_existing === true)
const currentDiffFindings = finalFindings.filter(f => f.pre_existing !== true)
const sortedCurrent = sortFindings(currentDiffFindings)
const sortedPreExisting = sortFindings(preExisting)
const partitions = partition(sortedCurrent)

return {
  findings: sortedCurrent,
  pre_existing: sortedPreExisting,
  partitions,
  suppressed: suppressedByGate + verifyDropped + invalidDropped,
  coverage: {
    residual_risks: Array.from(residualRisks),
    testing_gaps: Array.from(testingGaps),
  },
  stats: {
    reviewers: reviewers.length,
    reviewer_errors: reviewerErrors,
    raw_findings: allFindings.length,
    invalid_dropped: invalidDropped,
    after_dedup: byFingerprint.size,
    after_gate: beforeGate - suppressedByGate,
    borderline_verified: borderline.length,
    verify_dropped: verifyDropped,
    final: sortedCurrent.length,
  },
}

// review-fanout — heavyweight orchestrator for /review when the diff is non-trivial.
//
// Phase shape (mirrors skills/review/SKILL.md Synthesis Methodology 1-9):
//   1. BARRIER: parallel() all reviewers, wait for every one.
//   2. Validate + flatten + union coverage.
//   3. Dedup with true +/-3 line-window matching, then +0.10 cross-reviewer boost (cap 1.0).
//   4. Confidence gate (<0.60 suppressed; p1 >=0.50 rescued).
//   5. Adversarial verify: every surviving finding below the 0.80 skip-verify threshold
//      gets 2 independent skeptics in parallel. Consensus-boosted findings at >=0.80 skip.
//   6. Apply skeptic verdicts:
//        - <2 verdicts received: keep finding, requires_verification stays true (track in stats).
//        - 2 unanimous refute: drop.
//        - 2 unanimous uphold: +0.10 confidence, clear requires_verification.
//        - Mixed: keep, requires_verification = true.
//   7. Separate pre-existing.
//   8. Sort.
//   9. Normalize routing (coherence between autofix_class and owner) then partition.
//
// Returns the synthesized object only. MCP persistence, mode behavior, and presentation
// stay in the skill — the workflow never touches MCP.
//
// WHY A BARRIER (load-bearing): the +0.10 cross-reviewer boost can lift a 0.70 finding
// past the 0.80 verify-skip threshold. Pipeline-streaming would launch skeptics on
// findings that consensus would have skipped, wasting the most expensive tokens in
// the graph. The ~10-20% wall-clock cost saves ~30-50% of borderline skeptic spend.

export const meta = {
  name: 'review-fanout',
  description: 'Fan out reviewers under a barrier, dedup with cross-reviewer boost, adversarially verify only borderline findings, partition results. Skill handles MCP and presentation.',
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
  required: ['finding_key', 'verdict', 'rationale'],
  properties: {
    finding_key: { type: 'string' },
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
function lineNumber(f) {
  return Number.isFinite(+f?.line) ? Math.max(0, +f.line | 0) : 0
}
// Stable per-finding key for skeptic-verdict matching. Not fuzzy — each finding has
// exactly one key. Dedup uses a separate +/-3 window comparator (see dedupAndMerge).
function findingKey(f) {
  return [normalizeFile(f.file), lineNumber(f), normalizeTitle(f.title)].join('|')
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

// Dedup: true +/-3 line window. O(n^2) but n is small (<100 in practice).
// Two findings collapse iff: same normalized file, same normalized title, AND |line diff|
// <= 3 against ANY existing member of a group (not just the first). Anchoring on the first
// member only would break the +/-3 contract when a group spans more than 3 lines.
// Known limitation: semantically-identical findings with divergent titles will NOT merge.
// Fixing that requires embedding similarity; out of scope for the deterministic core.
function dedupAndMerge(findings) {
  const groups = []
  for (const f of findings) {
    const file = normalizeFile(f.file)
    const title = normalizeTitle(f.title)
    const line = lineNumber(f)
    const matchedGroup = groups.find(g => g.some(ref =>
      normalizeFile(ref.file) === file &&
      normalizeTitle(ref.title) === title &&
      Math.abs(lineNumber(ref) - line) <= 3
    ))
    if (matchedGroup) matchedGroup.push(f)
    else groups.push([f])
  }
  return groups.map(g => g.reduce((acc, x) => mergeFinding(acc, x)))
}

function mergeFinding(a, b) {
  // Autofix narrowing rule — disagreement-aware:
  //   both advisory      -> advisory
  //   one of each kind   -> gated_auto (disagreement deserves human-in-the-loop)
  //   both actionable    -> most cautious (manual > gated_auto > safe_auto)
  const isAdvisory = c => c === 'advisory'
  let autofix_class
  if (isAdvisory(a.autofix_class) && isAdvisory(b.autofix_class)) {
    autofix_class = 'advisory'
  } else if (isAdvisory(a.autofix_class) || isAdvisory(b.autofix_class)) {
    autofix_class = 'gated_auto'
  } else {
    const actionableOrder = ['manual', 'gated_auto', 'safe_auto']
    autofix_class = actionableOrder.indexOf(a.autofix_class) <= actionableOrder.indexOf(b.autofix_class)
      ? a.autofix_class
      : b.autofix_class
  }
  // owner is just a hint here; normalizeRouting() re-derives it from autofix_class
  // before partitioning so the (class, owner) pair is always coherent.
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

// Everything that survived the gate but isn't yet at the verify-skip threshold gets verified.
function isBorderline(f) {
  return f.confidence < 0.80
}

// Re-derive owner from autofix_class so (class, owner) is always coherent. Without this,
// a reviewer returning {gated_auto, review-fixer} would silently fall into reportOnly
// because partition() requires gated_auto + downstream-resolver.
function normalizeRouting(f) {
  let owner = f.owner
  if (f.autofix_class === 'safe_auto') owner = 'review-fixer'
  else if (f.autofix_class === 'gated_auto' || f.autofix_class === 'manual') owner = 'downstream-resolver'
  else if (f.autofix_class === 'advisory') owner = 'human'
  return { ...f, owner }
}

function sortFindings(arr) {
  return [...arr].sort((a, b) => {
    const s = severityRank(a.severity) - severityRank(b.severity); if (s) return s
    const c = (b.confidence || 0) - (a.confidence || 0); if (c) return c
    const f = normalizeFile(a.file).localeCompare(normalizeFile(b.file)); if (f) return f
    return lineNumber(a) - lineNumber(b)
  })
}

function partition(findings) {
  // Routing is normalized upstream; partition is just bucketing.
  const inSkillFixer = [], residualActionable = [], reportOnly = []
  for (const f of findings) {
    if (f.autofix_class === 'safe_auto') inSkillFixer.push(f)
    else if (f.autofix_class === 'gated_auto' || f.autofix_class === 'manual') residualActionable.push(f)
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
    `- owner: review-fixer for safe_auto fixes; downstream-resolver for gated_auto/manual; human for advisory.`,
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
    `Return per verifyVerdictSchema. finding_key must equal "${findingKey(finding)}".`,
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

// Phase 3: dedup (+/- 3 line window) + cross-reviewer boost
const beforeDedup = allFindings.length
const merged0 = dedupAndMerge(allFindings)
const dedupCollapsed = beforeDedup - merged0.length
const merged = merged0.map(applyCrossReviewerBoost)

// Phase 4: confidence gate
//
// Findings in [0.50, gate-threshold) are returned separately as `pre_gate_suppressed` so
// the skill can run a memory-assisted upgrade pass on them (the workflow has no MCP
// access). Without this the memory-upgrade step documented in the skill would be dead
// code on the heavy path.
const beforeGate = merged.length
const gated = merged.filter(passesConfidenceGate)
const preGateSuppressed = merged.filter(f => !passesConfidenceGate(f) && f.confidence >= 0.50)
const suppressedByGate = beforeGate - gated.length

// Phase 5: adversarial verify on borderline only
phase('Verify')
const borderline = gated.filter(isBorderline)
const skipsVerify = gated.filter(f => !isBorderline(f))
log(`Verify: ${borderline.length} borderline -> 2 skeptics each; ${skipsVerify.length} skip verify`)

const skepticCalls = []
for (const f of borderline) {
  for (let i = 1; i <= 2; i++) {
    skepticCalls.push(() => agent(
      skepticPrompt(f, i, intent, diffSummary),
      { label: `skeptic:${findingKey(f)}:${i}`, phase: 'Verify', model: 'sonnet', schema: verifyVerdictSchema }
    ))
  }
}
const verdicts = skepticCalls.length ? await parallel(skepticCalls) : []

const verdictsByKey = new Map()
for (const v of verdicts) {
  if (!v || !v.finding_key) continue
  if (!verdictsByKey.has(v.finding_key)) verdictsByKey.set(v.finding_key, [])
  verdictsByKey.get(v.finding_key).push(v)
}

// Phase 6: apply verdicts
const verifiedBorderline = []
let verifyDropped = 0
let skepticFailures = 0      // borderline findings that got <2 verdicts
let contestedKept = 0         // borderline findings with mixed verdicts

for (const f of borderline) {
  const vs = verdictsByKey.get(findingKey(f)) || []

  // Insufficient verdicts: keep finding, requires_verification stays true. Conservative.
  if (vs.length < 2) {
    skepticFailures += 1
    verifiedBorderline.push({ ...f, requires_verification: true })
    continue
  }

  // The prompt tells skeptics to default to "refute" when uncertain, so "unsure" is
  // treated as a non-uphold (counts toward dropping). This avoids the silent-survive
  // path where 1 refute + 1 unsure would otherwise keep a finding that no skeptic upheld.
  const upholds = vs.filter(v => v.verdict === 'uphold').length
  const nonUpholds = vs.length - upholds

  // No skeptic upheld: drop.
  if (nonUpholds === vs.length) {
    verifyDropped += 1
    continue
  }

  const counter = vs.flatMap(v => v.counter_evidence || [])
  const evidence = counter.length
    ? [...(f.evidence || []), ...counter.map(c => `[skeptic] ${c}`)]
    : f.evidence

  // Unanimous uphold: +0.10 confidence, requires_verification cleared.
  if (upholds === vs.length) {
    verifiedBorderline.push({
      ...f,
      confidence: Math.min(1.0, f.confidence + 0.1),
      requires_verification: false,
      evidence,
    })
    continue
  }

  // Mixed verdict (split refute/uphold/unsure): keep but flag for human review.
  contestedKept += 1
  verifiedBorderline.push({ ...f, requires_verification: true, evidence })
}

// Phase 7-9: recombine, separate pre-existing, sort, normalize routing, partition
const finalFindings = [...skipsVerify, ...verifiedBorderline]
const preExisting = finalFindings.filter(f => f.pre_existing === true)
const currentDiff = finalFindings.filter(f => f.pre_existing !== true)
const sortedCurrent = sortFindings(currentDiff).map(normalizeRouting)
const sortedPreExisting = sortFindings(preExisting).map(normalizeRouting)
const partitions = partition(sortedCurrent)

return {
  findings: sortedCurrent,
  pre_existing: sortedPreExisting,
  // Findings in [0.50, gate-threshold) that the skill can re-admit via memory upgrade.
  // These are NOT in `findings` or `partitions` — they're parked for skill-side rescue.
  pre_gate_suppressed: preGateSuppressed.map(normalizeRouting),
  partitions,
  // Total findings removed from the verdict for any reason. Each addend is also reported
  // separately in stats so callers can break down where the loss happened.
  suppressed: invalidDropped + dedupCollapsed + suppressedByGate + verifyDropped,
  coverage: {
    residual_risks: Array.from(residualRisks),
    testing_gaps: Array.from(testingGaps),
  },
  stats: {
    reviewers: reviewers.length,
    reviewer_errors: reviewerErrors,
    raw_findings: beforeDedup,
    invalid_dropped: invalidDropped,
    dedup_collapsed: dedupCollapsed,
    after_dedup: merged.length,
    after_gate: gated.length,
    suppressed_by_gate: suppressedByGate,
    borderline_verified: borderline.length,
    verify_dropped: verifyDropped,
    skeptic_failures: skepticFailures,   // <2 verdicts arrived
    contested_kept: contestedKept,        // mixed-verdict, requires_verification=true
    final: sortedCurrent.length,
  },
}

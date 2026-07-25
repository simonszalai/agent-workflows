// review-synthesize — one heavyweight synthesis/gating pass over raw findings from EVERY
// provider. Native collection and external peer dispatch finish before this workflow starts.
//
// Phase shape (mirrors skills/review/SKILL.md Synthesis Methodology):
//   1. Validate + flatten the already-collected reviewer envelopes + union coverage.
//   2. Dedup in two passes — exact (+/-3 line window, same normalized title), then a
//      SEMANTIC same-issue pass (one cheap judge call over same-file/±5-line pairs with
//      differing titles, and absence-finding pairs). Cross-provider agreement is the core
//      signal of this pipeline and providers never word titles identically, so exact
//      matching alone would silently discard consensus. Then +0.10 cross-reviewer boost
//      per extra reviewer (cap 1.0).
//   3. Label low-confidence findings (<0.60 -> low_confidence: true). Nothing is dropped
//      for confidence: the model reports, a later pass filters.
//   4. Absence confirmation: findings claiming something is MISSING get one search pass,
//      because reading an anchor line cannot establish an absence. A found artifact is
//      concrete external counter-evidence and drops the claim; anything else keeps it.
//   5. Separate pre-existing.
//   6. Sort.
//   7. Normalize routing (coherence between autofix_class and owner) then partition.
//
// WHY THERE IS NO SKEPTIC TIER: adversarial re-refutation of the model's own findings is
// self-verification. Current models self-correct, so a refute-biased second pass costs two
// agent calls per borderline finding and removes true positives. Precision belongs to the
// consumer of `findings`, not to a gate that deletes evidence before anyone reads it.
//
// Returns the synthesized object only. MCP persistence, mode behavior, and presentation
// stay in the skill — the workflow never touches MCP.
//
// WHY COLLECTION MUST FINISH FIRST (load-bearing): cross-provider agreement is the core
// signal, and it only exists once every envelope is present. Synthesizing native results
// before peer envelopes arrive loses the dedup match, so the +0.10 corroboration boost and
// the `reviewers` provenance list would both be wrong.

export const meta = {
  name: 'review-synthesize',
  description: 'Synthesize raw native and external review envelopes in one dedup, labelling, and routing pass.',
  phases: [
    { title: 'Synthesize', detail: 'validate all provider envelopes, dedup, boost, and label' },
    { title: 'Verify', detail: 'search-confirm absence claims only' },
  ],
}

// ---------- Inline schemas ----------

const sameIssueSchema = {
  type: 'object',
  required: ['decisions'],
  properties: {
    decisions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['pair', 'same_issue'],
        properties: {
          pair: { type: 'string' },
          same_issue: { type: 'boolean' },
        },
      },
    },
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
  return Number.isFinite(+f?.line) ? Math.max(1, +f.line | 0) : 1
}
// Stable per-finding key for absence-verdict matching. Not fuzzy — each finding has
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

// Exact dedup: true +/-3 line window. O(n^2) but n is small (<100 in practice).
// Two findings collapse iff: same normalized file, same normalized title, AND |line diff|
// <= 3 against ANY existing member of a group (not just the first). Anchoring on the first
// member only would break the +/-3 contract when a group spans more than 3 lines.
// Semantically-identical findings with divergent titles are handled by the semanticMerge
// pass that runs right after this one (see script body) — exact matching alone would
// discard cross-provider agreement, the signal the cross-reviewer boost exists to reward.
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

// Semantic same-issue merge (async — needs agent()). Exact-title dedup cannot see
// cross-provider agreement: the same defect gets different titles from different
// reviewers/providers. Candidate pairs — same file within a +/-5 line window with
// differing titles, or any two absence findings (absences may anchor to different
// files for the same missing artifact) — are judged in ONE cheap agent call; confirmed
// pairs merge via mergeFinding so the cross-reviewer boost sees the agreement.
async function semanticMerge(findings) {
  const pairs = []
  for (let i = 0; i < findings.length; i++) {
    for (let j = i + 1; j < findings.length; j++) {
      const a = findings[i], b = findings[j]
      if (normalizeTitle(a.title) === normalizeTitle(b.title)) continue // exact pass owns these
      const near = normalizeFile(a.file) === normalizeFile(b.file) &&
                   Math.abs(lineNumber(a) - lineNumber(b)) <= 5
      const bothAbsence = a.absence === true && b.absence === true
      if (near || bothAbsence) pairs.push({ id: `${i}-${j}`, i, j })
    }
  }
  if (pairs.length === 0) return findings

  const fmt = f => `[${f.severity}] ${f.file}:${f.line} "${f.title}" — ${f.why_it_matters} (evidence: ${(f.evidence || [])[0] || 'n/a'})`
  const judgePrompt = [
    `You are judging whether pairs of code-review findings describe the SAME underlying`,
    `defect (reported by different reviewers in different words) or genuinely different`,
    `issues. Judge by the underlying mechanism, not the wording. Same defect at the same`,
    `code site => same_issue: true. Different defects that happen to be near each other`,
    `=> same_issue: false. When genuinely unsure, answer false (a missed merge is safer`,
    `than collapsing two distinct signals).`,
    ``,
    ...pairs.map(p => `PAIR ${p.id}:\n  A: ${fmt(findings[p.i])}\n  B: ${fmt(findings[p.j])}\n`),
    `Return per schema: one decisions entry per pair id above.`,
  ].join('\n')

  const result = await agent(judgePrompt, {
    label: 'dedup:same-issue', phase: 'Synthesize', schema: sameIssueSchema,
    model: 'sonnet', effort: 'low',
  })
  const same = new Set()
  for (const d of result?.decisions || []) if (d.same_issue) same.add(String(d.pair))
  if (same.size === 0) return findings

  // Union-find over confirmed pairs, then reduce each cluster with mergeFinding.
  const parent = findings.map((_, idx) => idx)
  const find = x => (parent[x] === x ? x : (parent[x] = find(parent[x])))
  for (const p of pairs) if (same.has(p.id)) parent[find(p.i)] = find(p.j)
  const clusters = new Map()
  findings.forEach((f, idx) => {
    const root = find(idx)
    if (!clusters.has(root)) clusters.set(root, [])
    clusters.get(root).push(f)
  })
  return Array.from(clusters.values()).map(g => g.reduce((acc, x) => mergeFinding(acc, x)))
}

function applyCrossReviewerBoost(f) {
  const extra = Math.max(0, (f.reviewers?.length || 1) - 1)
  // Decimal boosts such as 0.70 + 0.10 can be represented as 0.799999..., which would
  // incorrectly route a consensus finding into the <0.80 skeptic tier. Confidence is
  // contractually two-decimal precision, so normalize before threshold comparisons.
  const boosted = Math.round((f.confidence + 0.1 * extra) * 100) / 100
  return { ...f, confidence: Math.min(1.0, boosted) }
}

// Confidence is a label, never a filter. Below this line a finding is marked
// `low_confidence` so a downstream pass can rank or triage it — it is still returned.
const LOW_CONFIDENCE = 0.60

function labelConfidence(f) {
  return { ...f, low_confidence: f.confidence < LOW_CONFIDENCE }
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

// Absence claims are the one case a second pass genuinely adds information: "X is
// missing" cannot be established by reading the anchor line, and the search that settles
// it is external evidence rather than the model second-guessing itself.
function absenceSearchPrompt(finding, intent, diffSummary, diffPath) {
  return [
    `Settle one absence claim by searching the working tree.`,
    `This finding claims something is MISSING (a migration, test, elimination step, scope`,
    `item, or deploy surface). Run the search commands listed in the evidence (grep/ls/Glob),`,
    `plus your own searches for plausible names and locations of the missing artifact.`,
    `UPHOLD if it is genuinely absent. REFUTE only if you actually find it — cite where it`,
    `exists (file:line) in counter_evidence. Do not refute on judgment; refute on a hit.`,
    ``,
    `Intent: ${intent}`,
    `Diff at: ${diffPath}`,
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
    `Return per verifyVerdictSchema. finding_key must equal "${findingKey(finding)}".`,
  ].join('\n')
}

// ---------- Script body ----------

// Normalize args. The Workflow tool delivers `args` verbatim, but an orchestrator
// that JSON-stringifies the object (a documented footgun) hands us a string. Parse a
// stringified blob back into an object, then validate.
let input = args
if (typeof input === 'string') {
  try {
    input = JSON.parse(input)
  } catch (e) {
    throw new Error(`review-synthesize: args was passed as a string that is not valid JSON (${e.message}). Pass args as a JSON object, not a stringified blob.`)
  }
}
if (!input || typeof input !== 'object') {
  throw new Error(`review-synthesize: expected args to be a JSON object, got ${typeof input}.`)
}
const { reviewerResults, intent, diffSummary, diffPath } = input
if (!Array.isArray(reviewerResults) || reviewerResults.length === 0) {
  throw new Error(`review-synthesize: args.reviewerResults must contain every raw native and peer envelope before synthesis starts.`)
}

// Phase 1: validate + flatten every provider envelope + union coverage
phase('Synthesize')
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
log(`Collected: ${reviewerResults.length} reviewer envelopes, ${allFindings.length} valid findings (${invalidDropped} invalid, ${reviewerErrors} reviewer errors)`)

// Phase 2: dedup — exact pass (+/- 3 line window, same title), then semantic same-issue
// pass (so cross-provider agreement is not lost to title wording) + cross-reviewer boost
const beforeDedup = allFindings.length
const exactMerged = dedupAndMerge(allFindings)
const exactCollapsed = beforeDedup - exactMerged.length
const merged0 = await semanticMerge(exactMerged)
const semanticCollapsed = exactMerged.length - merged0.length
const dedupCollapsed = exactCollapsed + semanticCollapsed
log(`Dedup: ${exactCollapsed} exact + ${semanticCollapsed} semantic collapsed (${merged0.length} remain)`)
const merged = merged0.map(applyCrossReviewerBoost)

// Phase 3: label confidence. No finding is dropped here — a numeric cutoff applied by the
// producer deletes true positives that the consumer never gets to see.
const labelled = merged.map(labelConfidence)
const lowConfidence = labelled.filter(f => f.low_confidence).length

// Phase 4: absence confirmation — one search pass per absence claim, nothing else.
phase('Verify')
const absenceClaims = labelled.filter(f => f.absence === true)
const settled = labelled.filter(f => f.absence !== true)
log(`Absence confirmation: ${absenceClaims.length} claim(s) searched; ${settled.length} finding(s) need none`)

const verdicts = absenceClaims.length
  ? await parallel(absenceClaims.map(f => () => agent(
      absenceSearchPrompt(f, intent, diffSummary, diffPath),
      { label: `absence:${findingKey(f)}`, phase: 'Verify', model: 'sonnet', schema: verifyVerdictSchema }
    )))
  : []

const verdictsByKey = new Map()
for (const v of verdicts) {
  if (!v || !v.finding_key) continue
  if (!verdictsByKey.has(v.finding_key)) verdictsByKey.set(v.finding_key, [])
  verdictsByKey.get(v.finding_key).push(v)
}

// Phase 5: apply absence verdicts. Only a located artifact removes the claim — that is
// evidence that the finding is factually wrong, not a second opinion about its severity.
const confirmedAbsences = []
let absenceRefuted = 0
let absenceUnsettled = 0

for (const f of absenceClaims) {
  const v = (verdictsByKey.get(findingKey(f)) || [])[0]

  // No verdict arrived: keep the claim, still flagged as needing verification.
  if (!v) {
    absenceUnsettled += 1
    confirmedAbsences.push({ ...f, requires_verification: true })
    continue
  }

  const counter = v.counter_evidence || []
  const evidence = counter.length
    ? [...(f.evidence || []), ...counter.map(c => `[absence-search] ${c}`)]
    : f.evidence

  // The artifact was found and cited: the absence claim is false.
  if (v.verdict === 'refute' && counter.length) {
    absenceRefuted += 1
    continue
  }

  if (v.verdict === 'uphold') {
    confirmedAbsences.push({ ...f, requires_verification: false, evidence })
    continue
  }

  absenceUnsettled += 1
  confirmedAbsences.push({ ...f, requires_verification: true, evidence })
}

// Phase 6-8: recombine, separate pre-existing, sort, normalize routing, partition
const finalFindings = [...settled, ...confirmedAbsences]
const preExisting = finalFindings.filter(f => f.pre_existing === true)
const currentDiff = finalFindings.filter(f => f.pre_existing !== true)
const sortedCurrent = sortFindings(currentDiff).map(normalizeRouting)
const sortedPreExisting = sortFindings(preExisting).map(normalizeRouting)
const partitions = partition(sortedCurrent)

return {
  findings: sortedCurrent,
  pre_existing: sortedPreExisting,
  partitions,
  // Total findings removed from the verdict for any reason. Each addend is also reported
  // separately in stats so callers can break down where the loss happened. Confidence is
  // never an addend here — low-confidence findings ship with `low_confidence: true`.
  suppressed: invalidDropped + dedupCollapsed + absenceRefuted,
  coverage: {
    residual_risks: Array.from(residualRisks),
    testing_gaps: Array.from(testingGaps),
  },
  stats: {
    reviewers: reviewerResults.length,
    reviewer_errors: reviewerErrors,
    raw_findings: beforeDedup,
    invalid_dropped: invalidDropped,
    dedup_collapsed: dedupCollapsed,
    dedup_collapsed_exact: exactCollapsed,
    dedup_collapsed_semantic: semanticCollapsed,
    after_dedup: merged.length,
    low_confidence: lowConfidence,        // labelled, still returned
    absence_claims: absenceClaims.length,
    absence_refuted: absenceRefuted,      // artifact located, claim removed
    absence_unsettled: absenceUnsettled,  // search inconclusive, requires_verification=true
    final: sortedCurrent.length,
  },
}

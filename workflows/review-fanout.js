// review-fanout — heavyweight orchestrator for /review when the diff is non-trivial.
//
// Phase shape (mirrors skills/review/SKILL.md Synthesis Methodology 1-9):
//   1. BARRIER: parallel() all reviewers, wait for every one.
//   2. Validate + flatten + union coverage.
//   3. Dedup in two passes — exact (+/-3 line window, same normalized title), then a
//      SEMANTIC same-issue pass (one cheap judge call over same-file/±5-line pairs with
//      differing titles, and absence-finding pairs). Cross-provider agreement is the core
//      signal of this pipeline and providers never word titles identically, so exact
//      matching alone would silently discard consensus. Then +0.10 cross-reviewer boost
//      per extra reviewer (cap 1.0).
//   4. Confidence gate (<0.60 suppressed; p1 >=0.50 rescued).
//   5. Adversarial verify, tiered by corroboration (confidence is self-reported and must
//      not buy an unconditional skip):
//        - <0.80: 2 independent skeptics in parallel.
//        - >=0.80 but p1, or single-reviewer: 1 spot-check skeptic.
//        - >=0.80 multi-reviewer consensus, p2/p3: skip verify.
//   6. Apply skeptic verdicts:
//        - fewer verdicts than expected: keep finding, requires_verification stays true.
//        - 2-skeptic: unanimous refute drops; unanimous uphold boosts +0.10 and clears
//          requires_verification; mixed keeps with requires_verification = true.
//        - 1-skeptic spot-check: uphold clears requires_verification; refute/unsure keeps
//          the finding contested (never a silent drop on one dissent vs a >=0.80 author).
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
    line: { type: 'integer', minimum: 1 },
    confidence: { type: 'number', minimum: 0, maximum: 1 },
    autofix_class: { type: 'string', enum: ['safe_auto', 'gated_auto', 'manual', 'advisory'] },
    owner: { type: 'string', enum: ['review-fixer', 'downstream-resolver', 'human'] },
    requires_verification: { type: 'boolean' },
    pre_existing: { type: 'boolean' },
    evidence: { type: 'array', items: { type: 'string' }, minItems: 1 },
    why_it_matters: { type: 'string', minLength: 8 },
    suggested_fix: { type: ['string', 'null'] },
    absence: { type: 'boolean' },
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
    label: 'dedup:same-issue', phase: 'Fan out', schema: sameIssueSchema,
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
  return { ...f, confidence: Math.min(1.0, f.confidence + 0.1 * extra) }
}

function passesConfidenceGate(f) {
  if (f.severity === 'p1' && f.confidence >= 0.5) return true
  return f.confidence >= 0.6
}

// Verify tiering: confidence alone cannot buy a skip — it is self-reported by the
// finding's author, and unpoliced inflation would bypass the only adversarial layer in
// the pipeline. Corroboration (multi-reviewer agreement after semanticMerge) is what
// earns the skip; p1 findings gate merges and always get at least a spot-check.
//   <0.80                                   -> 2 skeptics (full adversarial verify)
//   >=0.80, p1                              -> 1 skeptic spot-check
//   >=0.80, single reviewer, p2/p3          -> 1 skeptic spot-check (uncorroborated)
//   >=0.80, multi-reviewer, p2/p3           -> 0 (corroborated by independent agreement)
function skepticCount(f) {
  if (f.confidence < 0.80) return 2
  if (f.severity === 'p1') return 1
  if ((f.reviewers?.length || 1) < 2) return 1
  return 0
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

function reviewerPrompt(reviewer, intent, files, diffSummary, diffPath, mode, carried) {
  const scope = reviewer.filesScope?.length ? reviewer.filesScope : files
  return [
    `You are reviewer "${reviewer.key}". Focus: ${reviewer.focus}. Mode: ${mode}.`,
    ``,
    `Intent:`,
    intent,
    ``,
    ...(reviewer.extraContext ? [
      `Additional context for your focus area:`,
      reviewer.extraContext,
      ``,
    ] : []),
    `Diff at: ${diffPath}`,
    ``,
    `Files in scope:`,
    scope.map(p => `  - ${p}`).join('\n'),
    ``,
    `Diff summary:`,
    diffSummary,
    ``,
    ...(carried && carried.length ? [
      `Previously contested/advisory findings from earlier review rounds — re-examine`,
      `each; re-report ONLY with new evidence (do not repeat verbatim) and do not treat`,
      `this list as resolved:`,
      ...carried.map(c => `  - [${c.severity || '?'}] ${c.file || '?'}:${c.line || '?'} ${c.title || ''}${c.why_it_matters ? ' — ' + c.why_it_matters : ''}`),
      ``,
    ] : []),
    `References to load first:`,
    (reviewer.references || []).map(p => `  - ${p}`).join('\n') || '  (none)',
    ``,
    `Return per the reviewer output schema. Rules:`,
    `- One finding per real issue. Specific file:line. No vague nits.`,
    `- evidence: quote or paraphrase the code that proves the issue (>=1 required).`,
    `- confidence is code-grounded. Before assigning >=0.80 you MUST have read the`,
    `  surrounding function and at least one call site; cite both in evidence.`,
    `- If the issue is something MISSING (migration, test, elimination step, scope item,`,
    `  deploy surface): set absence: true, anchor file/line to the closest related`,
    `  artifact, and put the exact grep/ls commands that should find the missing thing`,
    `  in evidence — skeptics verify absences by searching, not by reading the anchor.`,
    `- pre_existing: true if the issue exists on main and the diff did not introduce it.`,
    `- autofix_class safe_auto only if the fix is mechanical and obviously correct.`,
    `- owner: review-fixer for safe_auto fixes; downstream-resolver for gated_auto/manual; human for advisory.`,
    `- Set reviewer_key to "${reviewer.key}".`,
  ].join('\n')
}

function skepticPrompt(finding, idx, intent, diffSummary, diffPath) {
  const protocol = finding.absence === true ? [
    `ABSENCE PROTOCOL: this finding claims something is MISSING (a migration, test,`,
    `elimination step, scope item, or deploy surface). Reading around the anchor line`,
    `cannot verify an absence. Instead: run the search commands listed in the evidence`,
    `(grep/ls/Glob), plus your own searches for plausible names and locations of the`,
    `missing artifact. UPHOLD if it is genuinely absent from the working tree; REFUTE`,
    `only if you find it — cite where it exists (file:line) in counter_evidence.`,
  ] : [
    `Open the file at the line. Read +/- 30 lines of context.`,
  ]
  return [
    `You are an adversarial skeptic (#${idx}). Your job is to REFUTE this finding.`,
    `Default to "refute" unless the evidence is concrete and reproducible.`,
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
    ...(finding.absence === true ? [`  absence claim: true (something is missing)`] : []),
    `  why_it_matters: ${finding.why_it_matters}`,
    `  evidence:`,
    (finding.evidence || []).map(e => `    - ${e}`).join('\n'),
    ``,
    ...protocol,
    `Return per verifyVerdictSchema. finding_key must equal "${findingKey(finding)}".`,
  ].join('\n')
}

// ---------- Script body ----------

const { reviewers, intent, files, diffSummary, diffPath, mode, carried = [] } = args

// Phase 1: BARRIER fan-out
phase('Fan out')
const reviewerResults = await parallel(
  reviewers.map(r => () => agent(
    reviewerPrompt(r, intent, files, diffSummary, diffPath, mode, carried),
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

// Phase 3: dedup — exact pass (+/- 3 line window, same title), then semantic same-issue
// pass (so cross-provider agreement is not lost to title wording) + cross-reviewer boost
const beforeDedup = allFindings.length
const exactMerged = dedupAndMerge(allFindings)
const exactCollapsed = beforeDedup - exactMerged.length
const merged0 = await semanticMerge(exactMerged)
const semanticCollapsed = exactMerged.length - merged0.length
const dedupCollapsed = exactCollapsed + semanticCollapsed
log(`Dedup: ${exactCollapsed} exact + ${semanticCollapsed} semantic collapsed (${merged0.length} remain)`)
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

// Phase 5: adversarial verify, tiered by corroboration (see skepticCount)
phase('Verify')
const borderline = gated.filter(f => skepticCount(f) > 0)
const skipsVerify = gated.filter(f => skepticCount(f) === 0)
const fullVerify = borderline.filter(f => skepticCount(f) === 2).length
const spotCheck = borderline.length - fullVerify
log(`Verify: ${fullVerify} full (2 skeptics) + ${spotCheck} spot-check (1 skeptic); ${skipsVerify.length} skip (>=0.80 multi-reviewer consensus)`)

const skepticCalls = []
for (const f of borderline) {
  const n = skepticCount(f)
  for (let i = 1; i <= n; i++) {
    skepticCalls.push(() => agent(
      skepticPrompt(f, i, intent, diffSummary, diffPath),
      // p1 findings get the strongest skeptic; everything else stays cheap.
      { label: `skeptic:${findingKey(f)}:${i}`, phase: 'Verify', model: f.severity === 'p1' ? 'opus' : 'sonnet', schema: verifyVerdictSchema }
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
  const expected = skepticCount(f)
  const vs = verdictsByKey.get(findingKey(f)) || []

  // Fewer verdicts than dispatched: keep finding, requires_verification stays true.
  if (vs.length < expected) {
    skepticFailures += 1
    verifiedBorderline.push({ ...f, requires_verification: true })
    continue
  }

  const upholds = vs.filter(v => v.verdict === 'uphold').length
  const counter = vs.flatMap(v => v.counter_evidence || [])
  const evidence = counter.length
    ? [...(f.evidence || []), ...counter.map(c => `[skeptic] ${c}`)]
    : f.evidence

  // Spot-check tier (1 skeptic on a >=0.80 self-confident finding): an uphold clears
  // requires_verification; a refute/unsure contests it — but never silently drops a
  // high-confidence finding on a single dissent.
  if (expected === 1) {
    if (upholds === 1) {
      verifiedBorderline.push({ ...f, requires_verification: false, evidence })
    } else {
      contestedKept += 1
      verifiedBorderline.push({ ...f, requires_verification: true, evidence })
    }
    continue
  }

  // Full tier (2 skeptics). The prompt tells skeptics to default to "refute" when
  // uncertain, so "unsure" is treated as a non-uphold (counts toward dropping). This
  // avoids the silent-survive path where 1 refute + 1 unsure would otherwise keep a
  // finding that no skeptic upheld.
  const nonUpholds = vs.length - upholds

  // No skeptic upheld: drop.
  if (nonUpholds === vs.length) {
    verifyDropped += 1
    continue
  }

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
    dedup_collapsed_exact: exactCollapsed,
    dedup_collapsed_semantic: semanticCollapsed,
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

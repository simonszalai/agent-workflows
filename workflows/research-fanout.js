// research-fanout — heavyweight orchestrator for /research when the question is broad.
//
// Research's failure mode is INCOMPLETENESS, not false positives. So unlike review-synthesize,
// the orchestration concentrates on coverage:
//   - Multi-modal sweep: parallel searchers using DIFFERENT angles, not just zones
//   - Loop-until-dry: completeness critic identifies gaps; gap-fillers run; repeat
//   - Synthesis is an LLM (judgment about patterns and inconsistencies), not pure code
//
// Phase shape:
//   1. Sweep (BARRIER): zone searchers + modality searchers in parallel
//   2. Dedup + merge (pure code, by file:line)
//   3. Loop: completeness critic -> gap-fillers -> dedup, until cap or dry
//   4. Synthesize: opus agent produces patterns, inconsistencies, recommendation
//
// Returns the synthesized object only. MCP persistence (storing the artifact) stays in
// the skill — the workflow never touches MCP. Related autodev memories + past tickets are
// likewise gathered by the skill and passed in as args.priorKnowledge (a rendered markdown
// string); the workflow only consumes it in the critic and synthesis prompts.

export const meta = {
  name: 'research-fanout',
  description: 'Multi-modal codebase research with loop-until-dry completeness checking. Parallel searchers across zones and modalities, dedup, gap-fill loop, judgment-based synthesis.',
  phases: [
    { title: 'Sweep', detail: 'parallel zone + modality searchers (barrier)' },
    { title: 'Gap-fill loop', detail: 'critic identifies gaps; targeted searchers fill until dry or cap' },
    { title: 'Synthesize', detail: 'opus agent produces patterns, inconsistencies, recommendation' },
  ],
}

// ---------- Default modalities (project-agnostic) ----------

const DEFAULT_MODALITIES = [
  {
    key: 'by-grep',
    description: 'Pull keywords from the research question and `git grep` them across tracked files. Cast a wide net.',
  },
  {
    key: 'by-symbol',
    description: 'Identify symbol/identifier names from the question (function names, class names, API endpoints). Search by exact identifier.',
  },
  {
    key: 'by-tests',
    description: 'Search test files (test_*, *_test, spec/, tests/) for the behavior being researched. Tests document expected usage.',
  },
  {
    key: 'by-config',
    description: 'Search config files (*.json, *.yaml, *.toml, *.env*, *.config.*) for related settings/declarations.',
  },
]

// ---------- Inline schemas ----------

const occurrenceSchema = {
  type: 'object',
  required: ['file', 'line', 'snippet', 'pattern_variant'],
  properties: {
    file: { type: 'string' },
    line: { type: 'integer', minimum: 0 },
    snippet: { type: 'string', minLength: 1 },
    pattern_variant: { type: 'string', minLength: 4 },
    notes: { type: ['string', 'null'] },
  },
}

const searcherOutputSchema = {
  type: 'object',
  required: ['key', 'files_searched', 'occurrences', 'summary'],
  properties: {
    key: { type: 'string' },
    files_searched: { type: 'integer', minimum: 0 },
    occurrences: { type: 'array', items: occurrenceSchema },
    summary: { type: 'string', minLength: 8 },
    questions_for_synthesis: { type: 'array', items: { type: 'string' } },
  },
}

const criticSchema = {
  type: 'object',
  required: ['coverage_assessment', 'gaps_identified'],
  properties: {
    coverage_assessment: { type: 'string', minLength: 8 },
    gaps_identified: {
      type: 'array',
      items: {
        type: 'object',
        required: ['gap_description', 'suggested_search', 'suggested_key'],
        properties: {
          gap_description: { type: 'string', minLength: 8 },
          suggested_search: { type: 'string', minLength: 8 },
          suggested_key: { type: 'string', minLength: 1 },
        },
      },
    },
  },
}

const synthesisSchema = {
  type: 'object',
  required: ['summary', 'patterns', 'inconsistencies', 'residual_gaps'],
  properties: {
    summary: { type: 'string', minLength: 32 },
    patterns: {
      type: 'array',
      items: {
        type: 'object',
        required: ['name', 'description', 'canonical_example', 'usage_example'],
        properties: {
          name: { type: 'string', minLength: 2 },
          description: { type: 'string', minLength: 8 },
          canonical_example: {
            type: 'object',
            required: ['file', 'line'],
            properties: { file: { type: 'string' }, line: { type: 'integer', minimum: 0 } },
          },
          usage_example: { type: 'string', minLength: 4 },
        },
      },
    },
    inconsistencies: {
      type: 'array',
      items: {
        type: 'object',
        required: ['description', 'locations', 'impact', 'severity', 'recommendation'],
        properties: {
          description: { type: 'string', minLength: 8 },
          locations: {
            type: 'array',
            minItems: 1,
            items: {
              type: 'object',
              required: ['file', 'line'],
              properties: { file: { type: 'string' }, line: { type: 'integer', minimum: 0 } },
            },
          },
          impact: { type: 'string', minLength: 8 },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          recommendation: { type: 'string', minLength: 8 },
        },
      },
    },
    residual_gaps: { type: 'array', items: { type: 'string' } },
  },
}

// ---------- Pure helpers ----------

function normalizeFile(f) {
  return String(f || '').replace(/\\/g, '/').replace(/^\.\//, '').trim()
}
function occurrenceKey(o) {
  return `${normalizeFile(o.file)}:${o.line || 0}`
}
function validOccurrence(o) {
  if (!o || typeof o !== 'object') return false
  return typeof o.file === 'string' && Number.isFinite(+o.line) &&
         typeof o.snippet === 'string' && o.snippet.length > 0 &&
         typeof o.pattern_variant === 'string'
}

function mergeOccurrence(existing, incoming, sourceKey) {
  // Same file:line found by multiple searchers. Merge: union sources, keep richer snippet.
  const sources = Array.from(new Set([...(existing.sources || []), sourceKey]))
  const snippet = (incoming.snippet?.length || 0) > (existing.snippet?.length || 0)
    ? incoming.snippet : existing.snippet
  const notes = [existing.notes, incoming.notes].filter(Boolean).join(' | ') || null
  return { ...existing, sources, snippet, notes }
}

// ---------- Prompt builders ----------

function zonePrompt(zone, question, repoRoot) {
  return [
    `You are a zone researcher for: "${zone.key}".`,
    `Zone description: ${zone.description}`,
    `Zone paths: ${(zone.paths || []).map(p => `  - ${p}`).join('\n') || '  (no path hints; use your judgment within the repo)'}`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `Research question:`,
    question,
    ``,
    `Search EVERY relevant file in your zone. Do not sample. Return per the searcher schema:`,
    `- key: "${zone.key}"`,
    `- files_searched: exact count of files you examined`,
    `- occurrences: one entry per relevant code location. file, line (1-indexed), snippet (1-5 lines), pattern_variant (short label describing what this instance demonstrates), notes (optional, anything unusual).`,
    `- summary: 1-3 sentence dominant-pattern observation for this zone`,
    `- questions_for_synthesis: list any cross-zone questions you cannot answer yourself`,
  ].join('\n')
}

function modalityPrompt(modality, question, repoRoot) {
  return [
    `You are a modality researcher using the "${modality.key}" approach.`,
    `Approach: ${modality.description}`,
    ``,
    `Repository root: ${repoRoot}`,
    ``,
    `Research question:`,
    question,
    ``,
    `Apply your specific search angle exhaustively. Return per the searcher schema:`,
    `- key: "${modality.key}"`,
    `- files_searched: count of files your search touched (e.g., for grep, files containing your terms)`,
    `- occurrences: one entry per match, with file, line (1-indexed), snippet (1-5 lines), pattern_variant, notes (optional)`,
    `- summary: 1-3 sentence observation of what this modality surfaced`,
    `- questions_for_synthesis: anything beyond your modality's reach`,
  ].join('\n')
}

function criticPrompt(question, occurrences, searcherSummaries, iter, repoRoot, priorKnowledge) {
  const occByFile = new Map()
  for (const o of occurrences) {
    const f = normalizeFile(o.file)
    occByFile.set(f, (occByFile.get(f) || 0) + 1)
  }
  return [
    `You are the completeness critic for a research sweep. Iteration ${iter}.`,
    ``,
    `Research question: ${question}`,
    `Repository root: ${repoRoot}`,
    ...(priorKnowledge ? [
      ``,
      `Prior knowledge from autodev (related memories + past tickets):`,
      priorKnowledge,
      `Use it to spot coverage gaps — subsystems, files, or concerns these reference that the`,
      `sweep may have under-covered. Treat it as a lead, not ground truth; the codebase is`,
      `authoritative.`,
    ] : []),
    ``,
    `Coverage so far — ${occurrences.length} occurrences across ${occByFile.size} files.`,
    `Searcher summaries:`,
    searcherSummaries.map(s => `  - [${s.key}] searched ${s.files_searched} files, found ${s.occurrences_found} occurrences. ${s.summary || ''}`).join('\n'),
    ``,
    `Top files by occurrence count:`,
    Array.from(occByFile.entries()).sort((a, b) => b[1] - a[1]).slice(0, 10).map(([f, n]) => `  - ${f}: ${n}`).join('\n'),
    ``,
    `Your job: identify GAPS in coverage. Specifically:`,
    `- Modalities not yet tried that could surface different occurrences (e.g., the search hit production code but not tests, or hit handlers but not config)`,
    `- Naming conventions/synonyms not explored (e.g., searched "authenticate" but not "login", "session", "credential")`,
    `- Indirect call paths not traced (e.g., found callers but not callees, or vice versa)`,
    `- File types not examined (e.g., docs, migrations, fixtures)`,
    `- Architectural layers under-covered`,
    ``,
    `Return per criticSchema:`,
    `- coverage_assessment: 2-4 sentences on what's well-covered and what's thin`,
    `- gaps_identified: list of concrete gaps. For each: gap_description (what's missing), suggested_search (the specific grep/glob/approach), suggested_key (a short label for the gap-filler agent).`,
    `- If coverage looks genuinely complete, return gaps_identified: []. Be honest — do not invent gaps to seem thorough.`,
  ].join('\n')
}

function gapFillerPrompt(gap, question, repoRoot) {
  return [
    `You are a targeted gap-filler. The completeness critic identified this gap in research coverage.`,
    ``,
    `Research question: ${question}`,
    `Repository root: ${repoRoot}`,
    ``,
    `Gap: ${gap.gap_description}`,
    `Suggested search: ${gap.suggested_search}`,
    ``,
    `Execute the suggested search (and your own judgment-expansion of it). Return per the searcher schema:`,
    `- key: "${gap.suggested_key}"`,
    `- files_searched: count touched`,
    `- occurrences: per-match entries with file, line (1-indexed), snippet, pattern_variant, notes`,
    `- summary: 1-3 sentences on what this gap-fill turned up`,
    `- questions_for_synthesis: anything beyond reach`,
    ``,
    `If the gap turns out to be empty (no new occurrences), return occurrences: [] and say so in summary.`,
  ].join('\n')
}

function synthesisPrompt(question, occurrences, searcherSummaries, residualQuestions, iterations, priorKnowledge) {
  return [
    `You are the research synthesizer. Produce the final research findings.`,
    ``,
    `Research question:`,
    question,
    ...(priorKnowledge ? [
      ``,
      `Prior knowledge from autodev (related memories + past tickets):`,
      priorKnowledge,
      `Cross-reference your findings against this: confirm where the codebase matches`,
      `documented patterns/gotchas, and FLAG (in inconsistencies or residual_gaps) where it`,
      `diverges or where documented knowledge now looks stale. Codebase evidence wins ties.`,
    ] : []),
    ``,
    `Total occurrences: ${occurrences.length} (after dedup and ${iterations} sweep iterations).`,
    `Searchers run: ${searcherSummaries.map(s => s.key).join(', ')}`,
    ``,
    `Occurrences (each with sources = which searchers found it):`,
    JSON.stringify(occurrences.slice(0, 200), null, 2), // cap to avoid prompt bloat
    occurrences.length > 200 ? `\n(... ${occurrences.length - 200} more occurrences truncated; you have enough signal)` : '',
    ``,
    `Cross-zone questions raised by searchers:`,
    residualQuestions.map(q => `  - ${q}`).join('\n') || '  (none)',
    ``,
    `Return per synthesisSchema:`,
    `- summary: 3-5 sentence overview answering the research question`,
    `- patterns: distinct architectural/coding patterns observed. For each: name, description, canonical_example {file, line}, usage_example (representative code snippet)`,
    `- inconsistencies: places where the codebase diverges in implementing the same concept. For each: description, locations [{file, line}], impact, severity (high/medium/low), recommendation`,
    `- residual_gaps: questions the sweep could not answer; topics worth follow-up research`,
    ``,
    `Quality bar:`,
    `- Patterns must be code-grounded — canonical_example must point to a real occurrence`,
    `- Inconsistencies must have ≥2 conflicting locations`,
    `- Do not invent patterns; if there is no dominant pattern, say so in residual_gaps`,
  ].join('\n')
}

// ---------- Script body ----------

const {
  question,
  zones = [],
  modalities = DEFAULT_MODALITIES,
  repoRoot,
  mode = 'interactive',
  loopCap = 2,
  priorKnowledge = null,
} = args

if (!question || typeof question !== 'string') {
  throw new Error('research-fanout: args.question is required')
}
if (!repoRoot || typeof repoRoot !== 'string') {
  throw new Error('research-fanout: args.repoRoot is required')
}

// Phase 1: BARRIER sweep — all zones + modalities in parallel
phase('Sweep')

const initialCalls = [
  ...zones.map(z => () => agent(
    zonePrompt(z, question, repoRoot),
    { label: `zone:${z.key}`, phase: 'Sweep', model: 'sonnet', effort: 'low', schema: searcherOutputSchema }
  )),
  ...modalities.map(m => () => agent(
    modalityPrompt(m, question, repoRoot),
    { label: `modality:${m.key}`, phase: 'Sweep', model: 'sonnet', effort: 'low', schema: searcherOutputSchema }
  )),
]

if (initialCalls.length === 0) {
  throw new Error('research-fanout: at least one zone or modality required')
}

const initialResults = await parallel(initialCalls)

// Phase 2: dedup + merge
const occurrenceByKey = new Map()
const searcherSummaries = []
const residualQuestions = new Set()
let searcherErrors = 0
let invalidOccurrences = 0

function ingestSearcherResult(r) {
  if (!r || typeof r !== 'object' || !Array.isArray(r.occurrences)) {
    searcherErrors += 1
    return 0
  }
  let newCount = 0
  for (const o of r.occurrences) {
    if (!validOccurrence(o)) { invalidOccurrences += 1; continue }
    const key = occurrenceKey(o)
    const enriched = { ...o, sources: [r.key] }
    if (occurrenceByKey.has(key)) {
      occurrenceByKey.set(key, mergeOccurrence(occurrenceByKey.get(key), enriched, r.key))
    } else {
      occurrenceByKey.set(key, enriched)
      newCount += 1
    }
  }
  searcherSummaries.push({
    key: r.key,
    files_searched: r.files_searched || 0,
    occurrences_found: r.occurrences.length,
    summary: r.summary || '',
  })
  for (const q of r.questions_for_synthesis || []) residualQuestions.add(q)
  return newCount
}

for (const r of initialResults) ingestSearcherResult(r)
log(`Sweep: ${initialResults.length} searchers, ${occurrenceByKey.size} unique occurrences (${invalidOccurrences} invalid, ${searcherErrors} errors)`)

// Phase 3: loop-until-dry — completeness critic + gap-fillers
phase('Gap-fill loop')
let iter = 0
let dryRounds = 0
let totalGapsIdentified = 0
let totalGapsFilled = 0
let residualGapsFromCritic = []

while (iter < loopCap && dryRounds < 1) {
  iter += 1
  const occurrencesArr = Array.from(occurrenceByKey.values())
  const critic = await agent(
    criticPrompt(question, occurrencesArr, searcherSummaries, iter, repoRoot, priorKnowledge),
    { label: `critic:r${iter}`, phase: 'Gap-fill loop', model: 'sonnet', schema: criticSchema }
  )

  if (!critic || !Array.isArray(critic.gaps_identified) || critic.gaps_identified.length === 0) {
    log(`Round ${iter}: critic reports complete coverage`)
    dryRounds += 1
    break
  }

  totalGapsIdentified += critic.gaps_identified.length
  log(`Round ${iter}: critic identified ${critic.gaps_identified.length} gaps`)

  const gapResults = await parallel(
    critic.gaps_identified.map((gap, i) => () => agent(
      gapFillerPrompt(gap, question, repoRoot),
      { label: `gap:r${iter}:${gap.suggested_key || i}`, phase: 'Gap-fill loop', model: 'sonnet', effort: 'low', schema: searcherOutputSchema }
    ))
  )

  let roundNewCount = 0
  for (const r of gapResults) roundNewCount += ingestSearcherResult(r)
  if (roundNewCount > 0) totalGapsFilled += critic.gaps_identified.length

  log(`Round ${iter}: gap-fillers added ${roundNewCount} new occurrences (total: ${occurrenceByKey.size})`)

  if (roundNewCount === 0) {
    dryRounds += 1
    // Critic identified gaps but gap-fillers found nothing — record as residual.
    residualGapsFromCritic = critic.gaps_identified.map(g => g.gap_description)
  }
}

// Phase 4: synthesis
phase('Synthesize')
const finalOccurrences = Array.from(occurrenceByKey.values())
  .sort((a, b) => {
    const f = normalizeFile(a.file).localeCompare(normalizeFile(b.file))
    if (f) return f
    return (a.line || 0) - (b.line || 0)
  })

const synth = await agent(
  synthesisPrompt(question, finalOccurrences, searcherSummaries, Array.from(residualQuestions), iter, priorKnowledge),
  { label: 'synthesize', phase: 'Synthesize', model: 'opus', schema: synthesisSchema }
) || { summary: '(synthesis failed)', patterns: [], inconsistencies: [], residual_gaps: [] }

return {
  question,
  summary: synth.summary,
  patterns: synth.patterns,
  inconsistencies: synth.inconsistencies,
  occurrences: finalOccurrences,
  zones_searched: zones.map(z => z.key),
  modalities_searched: modalities.map(m => m.key),
  searcher_summaries: searcherSummaries,
  loop_iterations: iter,
  residual_gaps: [
    ...(synth.residual_gaps || []),
    ...residualGapsFromCritic,
  ],
  stats: {
    searchers: initialCalls.length,
    searcher_errors: searcherErrors,
    invalid_occurrences: invalidOccurrences,
    unique_occurrences: finalOccurrences.length,
    multi_source_occurrences: finalOccurrences.filter(o => (o.sources || []).length > 1).length,
    gap_iterations: iter,
    gaps_identified: totalGapsIdentified,
    gaps_filled: totalGapsFilled,
  },
}

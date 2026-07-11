// review-collect — native reviewer collection for the heavyweight /review path.
//
// This workflow returns raw reviewer envelopes only. It MUST run concurrently with external
// provider dispatch. After every native and peer envelope has arrived, the orchestrator invokes
// review-synthesize exactly once with the combined array. No confidence gate, dedup, skeptic,
// persistence, or routing decision belongs here.

export const meta = {
  name: 'review-collect',
  description: 'Collect schema-validated raw native review envelopes without synthesizing them.',
  phases: [
    { title: 'Collect', detail: 'all native reviewers in parallel (barrier)' },
  ],
}

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

let input = args
if (typeof input === 'string') {
  try {
    input = JSON.parse(input)
  } catch (error) {
    throw new Error(`review-collect: args was passed as a string that is not valid JSON (${error.message}). Pass args as a JSON object.`)
  }
}
if (!input || typeof input !== 'object') {
  throw new Error(`review-collect: expected args to be a JSON object, got ${typeof input}.`)
}

const { reviewers, intent, files, diffSummary, diffPath, mode, carried = [] } = input
if (!Array.isArray(reviewers) || reviewers.length === 0) {
  throw new Error('review-collect: args.reviewers must be a non-empty native reviewer array.')
}
if (!Array.isArray(files)) {
  throw new Error('review-collect: args.files must be an array.')
}

phase('Collect')
const reviewerResults = await parallel(
  reviewers.map(reviewer => () => agent(
    reviewerPrompt(reviewer, intent, files, diffSummary, diffPath, mode, carried),
    {
      label: `reviewer:${reviewer.key}`,
      phase: 'Collect',
      model: reviewer.model,
      schema: reviewerOutputSchema,
    }
  ))
)

const succeeded = reviewerResults.filter(result => result && Array.isArray(result.findings)).length
log(`Collected ${succeeded}/${reviewers.length} native reviewer envelopes`)

return {
  reviewer_results: reviewerResults,
  stats: {
    attempted: reviewers.length,
    succeeded,
    failed: reviewers.length - succeeded,
  },
}

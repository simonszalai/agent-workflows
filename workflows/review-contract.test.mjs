import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

async function runWorkflow(file, args, agentImpl) {
  const source = await readFile(new URL(file, import.meta.url), 'utf8')
  const executable = source.replace('export const meta', 'const meta')
  const factory = new Function(
    'args',
    'agent',
    'parallel',
    'phase',
    'log',
    `return (async () => { ${executable} })()`,
  )
  return factory(
    args,
    agentImpl,
    calls => Promise.all(calls.map(call => call())),
    () => {},
    () => {},
  )
}

function finding(confidence = 0.70) {
  return {
    title: 'Missing authorization check',
    severity: 'p2',
    file: 'app/routes/admin.ts',
    line: 42,
    confidence,
    autofix_class: 'gated_auto',
    owner: 'downstream-resolver',
    requires_verification: false,
    pre_existing: false,
    evidence: ['route invokes destructive action without authorization'],
    why_it_matters: 'A non-admin can invoke the destructive action.',
    suggested_fix: 'Require the admin guard.',
  }
}

test('review-collect returns raw native envelopes without synthesis', async () => {
  const result = await runWorkflow(
    './review-collect.js',
    {
      reviewers: [
        { key: 'code-quality', model: 'sonnet', focus: 'correctness', references: [] },
        { key: 'security', model: 'opus', focus: 'authorization', references: [] },
      ],
      intent: 'Review the change.',
      files: ['app/routes/admin.ts'],
      diffSummary: '1 file changed',
      diffPath: '.context/review/diff.patch',
      mode: 'report-only',
    },
    async (_prompt, options) => ({
      reviewer_key: options.label.replace('reviewer:', ''),
      findings: [finding()],
      residual_risks: [],
      testing_gaps: [],
    }),
  )

  assert.equal(result.reviewer_results.length, 2)
  assert.equal(result.reviewer_results[0].findings[0].confidence, 0.70)
  assert.deepEqual(result.stats, { attempted: 2, succeeded: 2, failed: 0 })
})

test('review-synthesize boosts duplicate findings across native and peer envelopes', async () => {
  const result = await runWorkflow(
    './review-synthesize.js',
    {
      reviewerResults: [
        {
          reviewer_key: 'native-security',
          findings: [finding()],
          residual_risks: [],
          testing_gaps: [],
        },
        {
          reviewer_key: 'codex',
          findings: [finding()],
          residual_risks: [],
          testing_gaps: [],
        },
      ],
      intent: 'Review the change.',
      diffSummary: '1 file changed',
      diffPath: '.context/review/diff.patch',
    },
    async () => {
      throw new Error('a non-absence finding should never trigger an agent call after exact merge')
    },
  )

  assert.equal(result.findings.length, 1)
  assert.equal(result.findings[0].confidence, 0.80)
  assert.deepEqual(result.findings[0].reviewers, ['native-security', 'codex'])
  assert.equal(result.stats.reviewers, 2)
  assert.equal(result.stats.after_dedup, 1)
})

test('review-synthesize labels low confidence instead of dropping the finding', async () => {
  const result = await runWorkflow(
    './review-synthesize.js',
    {
      reviewerResults: [
        { reviewer_key: 'native-security', findings: [finding(0.35)], residual_risks: [], testing_gaps: [] },
      ],
      intent: 'Review the change.',
      diffSummary: '1 file changed',
      diffPath: '.context/review/diff.patch',
    },
    async () => {
      throw new Error('a low-confidence finding must not trigger a verification agent call')
    },
  )

  assert.equal(result.findings.length, 1, 'low-confidence findings are reported, never suppressed')
  assert.equal(result.findings[0].low_confidence, true)
  assert.equal(result.stats.low_confidence, 1)
  assert.equal(result.suppressed, 0)
  assert.equal(result.partitions.residualActionable.length, 1)
})

test('review-synthesize drops an absence claim only when the search locates the artifact', async () => {
  const absence = key => ({ ...finding(0.75), absence: true, title: `Missing ${key}` })
  const result = await runWorkflow(
    './review-synthesize.js',
    {
      reviewerResults: [
        {
          reviewer_key: 'native-plan-conformance',
          findings: [absence('migration'), { ...absence('test'), line: 90 }],
          residual_risks: [],
          testing_gaps: [],
        },
      ],
      intent: 'Review the change.',
      diffSummary: '1 file changed',
      diffPath: '.context/review/diff.patch',
    },
    async (prompt, options) => {
      // Two absence claims at different lines reach the semantic same-issue judge first.
      if (!options.label.startsWith('absence:')) return { decisions: [{ pair: '0-1', same_issue: false }] }
      const found = options.label.includes('|42|')
      return found
        ? { finding_key: options.label.replace('absence:', ''), verdict: 'refute', counter_evidence: ['migrations/0007_add_col.sql:1'] }
        : { finding_key: options.label.replace('absence:', ''), verdict: 'uphold', counter_evidence: [] }
    },
  )

  assert.equal(result.findings.length, 1, 'located artifact refutes its claim; the other survives')
  assert.equal(result.findings[0].title, 'Missing test')
  assert.equal(result.findings[0].requires_verification, false)
  assert.equal(result.stats.absence_claims, 2)
  assert.equal(result.stats.absence_refuted, 1)
  assert.equal(result.suppressed, 1)
})

test('review-synthesize refuses to run before raw envelopes arrive', async () => {
  await assert.rejects(
    runWorkflow(
      './review-synthesize.js',
      {
        reviewerResults: [],
        intent: 'Review the change.',
        diffSummary: '1 file changed',
        diffPath: '.context/review/diff.patch',
      },
      async () => ({}),
    ),
    /must contain every raw native and peer envelope/,
  )
})

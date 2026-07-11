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

test('review-synthesize boosts duplicate findings across native and peer envelopes before gate', async () => {
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
      throw new Error('corroborated p2 finding should not need an agent call after exact merge')
    },
  )

  assert.equal(result.findings.length, 1)
  assert.equal(result.findings[0].confidence, 0.80)
  assert.deepEqual(result.findings[0].reviewers, ['native-security', 'codex'])
  assert.equal(result.stats.reviewers, 2)
  assert.equal(result.stats.after_gate, 1)
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

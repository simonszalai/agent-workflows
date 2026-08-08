import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

async function runPlan(args, agentImpl = async () => ({})) {
  const source = await readFile(new URL('./plan-fanout.js', import.meta.url), 'utf8')
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

test('plan fanout requires one curated ticket-context file', async () => {
  await assert.rejects(
    runPlan({
      question: 'Plan the change',
      repoRoot: '/repo',
      sourceArtifactFile: '/tmp/source.md',
      priorKnowledgeFile: '/tmp/memory.md',
    }),
    /ticketContextFile is required/,
  )
})

test('plan fanout gives every native phase one curated context reference', async () => {
  const prompts = []
  const plan = {
    title: 'Bounded context',
    what: 'Use one curated packet for planning inputs.',
    why: 'Raw retrieval must stay outside the parent thread.',
    how: 'Pass one file path to every planning phase.',
    tradeoffs: 'Adds one cheap curator child to reduce parent context.',
    alternatives_considered: [{ name: 'Raw reads', why_rejected: 'Pollutes parent context.' }],
    risks: [{ risk: 'Relevant facts omitted', mitigation: 'Retain every decision-bearing fact.' }],
    verification_strategy: 'Assert every prompt references only the curated packet.',
    side_effects: 'none',
    elimination: 'Separate source and prior-knowledge prompt files.',
    open_questions: [],
  }
  const result = await runPlan(
    {
      question: 'Plan the change',
      repoRoot: '/repo',
      ticketContextFile: '/tmp/ticket-context.md',
      codebaseResearchFile: '/tmp/research.md',
      framings: [{ key: 'mvp-first', description: 'smallest useful change' }],
    },
    async (prompt, options) => {
      prompts.push(prompt)
      if (options.phase === 'Draft') {
        return { framing: 'mvp-first', plan, framing_notes: 'bounded' }
      }
      if (options.phase === 'Critique') {
        return { lens: options.label.replace('critic:', ''), findings: [], overall_assessment: 'ok' }
      }
      throw new Error(`unexpected phase ${options.phase}`)
    },
  )

  assert.equal(result.plan.title, 'Bounded context')
  assert.ok(prompts.length >= 4)
  for (const prompt of prompts) {
    assert.match(prompt, /Curated ticket-context file: \/tmp\/ticket-context\.md/)
    assert.doesNotMatch(prompt, /Source artifact file|Prior-knowledge file/)
  }
})

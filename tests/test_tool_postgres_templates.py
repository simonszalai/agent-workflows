from __future__ import annotations

import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = ROOT / "skills" / "tool-postgres"
RUNNER = SKILL_ROOT / "templates" / "readonly-query-bundle.mjs"


class ToolPostgresTemplateTests(unittest.TestCase):
    def run_node_contract(self, body: str) -> None:
        script = f"""
import assert from 'node:assert/strict'
import {{
  loadInvestigationParameters,
  loadInvestigationSql,
  runReadonlyInvestigation,
}} from {RUNNER.as_uri()!r}
{body}
"""
        completed = subprocess.run(
            ["node", "--input-type=module", "--eval", script],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_success_uses_one_read_only_transaction_and_always_closes(self) -> None:
        self.run_node_contract(
            """
const calls = []
const emitted = []
const client = {
  async connect() { calls.push('connect') },
  async query(sql) {
    calls.push(sql)
    if (typeof sql === 'object' && sql.text === 'SELECT bounded') return { rows: [{ fact: 1 }] }
    return { rows: [] }
  },
  async end() { calls.push('end') },
}
const rows = await runReadonlyInvestigation({
  client,
  sql: 'SELECT bounded',
  values: ['subject-id'],
  emit: (output) => emitted.push(output),
})
assert.deepEqual(calls, [
  'connect',
  'BEGIN READ ONLY',
  "SET LOCAL statement_timeout = '30000ms'",
  {
    name: 'readonly-investigation-bundle',
    text: 'SELECT bounded',
    values: ['subject-id'],
    queryMode: 'extended',
  },
  'ROLLBACK',
  'end',
])
assert.deepEqual(rows, [{ fact: 1 }])
assert.deepEqual(JSON.parse(emitted[0]), { investigation: [{ fact: 1 }] })
"""
        )

    def test_sql_loader_rejects_placeholders_and_accepts_customized_file(self) -> None:
        self.run_node_contract(
            """
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
const directory = await mkdtemp(join(tmpdir(), 'postgres-template-test-'))
try {
  const path = join(directory, 'investigation.sql')
  await writeFile(path, 'SELECT TODO_COLUMN FROM TODO_TABLE')
  await assert.rejects(loadInvestigationSql(path), (error) => error.code === 'SQL_NOT_CUSTOMIZED')
  await writeFile(path, 'SELECT 1 AS bounded')
  assert.equal(await loadInvestigationSql(path), 'SELECT 1 AS bounded')
} finally {
  await rm(directory, { recursive: true, force: true })
}
"""
        )

    def test_actual_sql_template_is_accepted_after_all_placeholders_are_customized(self) -> None:
        self.run_node_contract(
            f"""
import {{ mkdtemp, readFile, rm, writeFile }} from 'node:fs/promises'
import {{ join }} from 'node:path'
import {{ tmpdir }} from 'node:os'
const source = {str(SKILL_ROOT / 'templates' / 'investigation-bundle.sql')!r}
const replacements = new Map([
  ['TODO_SUBJECT_ID_TYPE', 'text'],
  ['TODO_SUBJECT_SCHEMA', 'app'],
  ['TODO_SUBJECT_TABLE', 'subject'],
  ['TODO_SUBJECT_PK_COLUMN', 'id'],
  ['TODO_SUBJECT_STATUS_COLUMN', 'status'],
  ['TODO_RELATED_SCHEMA', 'app'],
  ['TODO_RELATED_TABLE', 'related'],
  ['TODO_RELATED_SUBJECT_FK_COLUMN', 'subject_id'],
  ['TODO_RELATED_STATE_COLUMN', 'state'],
  ['TODO_RECENT_SCHEMA', 'app'],
  ['TODO_RECENT_TABLE', 'recent'],
  ['TODO_RECENT_PK_COLUMN', 'id'],
  ['TODO_RECENT_STATUS_COLUMN', 'status'],
  ['TODO_RECENT_CREATED_AT_COLUMN', 'created_at'],
  ['TODO_RECENT_SUBJECT_FK_COLUMN', 'subject_id'],
])
let sql = await readFile(source, 'utf8')
for (const [placeholder, value] of replacements) sql = sql.replaceAll(placeholder, value)
assert.equal(sql.includes('TODO_'), false)
const directory = await mkdtemp(join(tmpdir(), 'postgres-actual-template-test-'))
try {{
  const path = join(directory, 'investigation.sql')
  await writeFile(path, sql)
  assert.equal(await loadInvestigationSql(path), sql.trim())
}} finally {{
  await rm(directory, {{ recursive: true, force: true }})
}}
"""
        )

    def test_parameter_loader_requires_customized_bounded_scalars(self) -> None:
        self.run_node_contract(
            """
import { mkdtemp, rm, writeFile } from 'node:fs/promises'
import { join } from 'node:path'
import { tmpdir } from 'node:os'
const directory = await mkdtemp(join(tmpdir(), 'postgres-params-test-'))
try {
  const path = join(directory, 'params.json')
  await writeFile(path, '["TODO_SUBJECT"]')
  await assert.rejects(
    loadInvestigationParameters(path),
    (error) => error.code === 'PARAMS_NOT_CUSTOMIZED',
  )
  await writeFile(path, '["subject-id", "active", 20, true, null]')
  assert.deepEqual(
    await loadInvestigationParameters(path),
    ['subject-id', 'active', 20, true, null],
  )
  await writeFile(path, '{"subject":"not-an-array"}')
  await assert.rejects(
    loadInvestigationParameters(path),
    (error) => error.code === 'PARAMS_FILE_INVALID',
  )
} finally {
  await rm(directory, { recursive: true, force: true })
}
"""
        )

    def test_query_failure_rolls_back_and_closes_without_emitting(self) -> None:
        self.run_node_contract(
            """
const calls = []
const emitted = []
const failure = Object.assign(new Error('query failed'), { code: 'XX001' })
const client = {
  async connect() { calls.push('connect') },
  async query(sql) {
    calls.push(sql)
    if (typeof sql === 'object' && sql.text === 'SELECT broken') throw failure
    return { rows: [] }
  },
  async end() { calls.push('end') },
}
await assert.rejects(
  runReadonlyInvestigation({
    client,
    sql: 'SELECT broken',
    emit: (output) => emitted.push(output),
  }),
  (error) => error === failure,
)
assert.deepEqual(calls.slice(-2), ['ROLLBACK', 'end'])
assert.deepEqual(emitted, [])
"""
        )

    def test_connect_failure_still_closes_without_attempting_rollback(self) -> None:
        self.run_node_contract(
            """
const calls = []
const failure = Object.assign(new Error('connect failed'), { code: '08006' })
const client = {
  async connect() { calls.push('connect'); throw failure },
  async query(sql) { calls.push(sql); return { rows: [] } },
  async end() { calls.push('end') },
}
await assert.rejects(
  runReadonlyInvestigation({ client, sql: 'SELECT bounded', emit: () => {} }),
  (error) => error === failure,
)
assert.deepEqual(calls, ['connect', 'end'])
"""
        )

    def test_oversized_output_is_rejected_before_emit_and_still_cleans_up(self) -> None:
        self.run_node_contract(
            """
const calls = []
const emitted = []
const client = {
  async connect() { calls.push('connect') },
  async query(sql) {
    calls.push(sql)
    if (typeof sql === 'object' && sql.text === 'SELECT oversized') {
      return { rows: [{ value: 'x'.repeat(70_000) }] }
    }
    return { rows: [] }
  },
  async end() { calls.push('end') },
}
await assert.rejects(
  runReadonlyInvestigation({
    client,
    sql: 'SELECT oversized',
    emit: (output) => emitted.push(output),
  }),
  (error) => error.code === 'OUTPUT_TOO_LARGE',
)
assert.deepEqual(calls.slice(-2), ['ROLLBACK', 'end'])
assert.deepEqual(emitted, [])
"""
        )

    def test_skill_links_to_existing_references_and_templates(self) -> None:
        skill = (SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
        for relative in (
            "references/psql-cli-workflow.md",
            "references/application-shell-fallback.md",
            "templates/investigation-bundle.sql",
            "templates/investigation-params.json",
            "templates/readonly-query-bundle.mjs",
        ):
            self.assertIn(relative, skill)
            self.assertTrue((SKILL_ROOT / relative).is_file())

        sql = (SKILL_ROOT / "templates" / "investigation-bundle.sql").read_text(
            encoding="utf-8"
        )
        self.assertIn("$1::TODO_SUBJECT_ID_TYPE", sql)
        self.assertIn("= $2", sql)
        self.assertIn("TODO_SUBJECT_ID_TYPE", sql)
        self.assertIn('"TODO_SUBJECT_SCHEMA"."TODO_SUBJECT_TABLE"', sql)
        self.assertIn("TODO_RECENT_PK_COLUMN", sql)
        self.assertIn("LIMIT 20", sql)
        self.assertIn("jsonb_build_object", sql)


if __name__ == "__main__":
    unittest.main()

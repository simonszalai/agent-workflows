// Copy to run-local scratch and adapt only the connection variable name.
// Pass the customized SQL template path and execute below the verified application deploy directory
// so the `pg` dependency resolves.

import { readFile, stat } from 'node:fs/promises'

const CONNECTION_ENV_NAME = 'TODO_DATABASE_URL_ENV'
const MAX_OUTPUT_BYTES = 64 * 1024
const MAX_SQL_FILE_BYTES = 128 * 1024
const MAX_PARAMS_FILE_BYTES = 8 * 1024
const MAX_PARAMETERS = 20

function safeErrorCode(error) {
  if (typeof error !== 'object' || error === null || !('code' in error)) return 'UNKNOWN'
  return typeof error.code === 'string' ? error.code.slice(0, 40) : 'UNKNOWN'
}

function codedError(message, code) {
  const error = new Error(message)
  error.code = code
  return error
}

function boundedJson(value) {
  const encoded = JSON.stringify(value)
  const size = Buffer.byteLength(encoded, 'utf8')
  if (size > MAX_OUTPUT_BYTES) {
    const error = new Error(`structured output exceeds ${MAX_OUTPUT_BYTES} bytes`)
    error.code = 'OUTPUT_TOO_LARGE'
    throw error
  }
  return encoded
}

export async function loadInvestigationSql(path) {
  if (!path) throw codedError('pass the customized SQL file path', 'SQL_FILE_MISSING')
  const metadata = await stat(path)
  if (!metadata.isFile() || metadata.size > MAX_SQL_FILE_BYTES) {
    throw codedError('SQL file is missing or too large', 'SQL_FILE_INVALID')
  }
  const sql = (await readFile(path, 'utf8')).trim()
  if (!sql || sql.includes('TODO_')) {
    throw codedError('customize every SQL template placeholder', 'SQL_NOT_CUSTOMIZED')
  }
  return sql
}

export async function loadInvestigationParameters(path) {
  if (!path) throw codedError('pass the customized parameter file path', 'PARAMS_FILE_MISSING')
  const metadata = await stat(path)
  if (!metadata.isFile() || metadata.size > MAX_PARAMS_FILE_BYTES) {
    throw codedError('parameter file is missing or too large', 'PARAMS_FILE_INVALID')
  }
  let values
  try {
    values = JSON.parse(await readFile(path, 'utf8'))
  } catch {
    throw codedError('parameter file must be valid JSON', 'PARAMS_FILE_INVALID')
  }
  const scalar = (value) =>
    value === null || ['string', 'number', 'boolean'].includes(typeof value)
  if (!Array.isArray(values) || values.length > MAX_PARAMETERS || !values.every(scalar)) {
    throw codedError('parameters must be a bounded scalar array', 'PARAMS_FILE_INVALID')
  }
  if (values.some((value) => typeof value === 'string' && value.includes('TODO_'))) {
    throw codedError('customize every parameter placeholder', 'PARAMS_NOT_CUSTOMIZED')
  }
  return values
}

export async function runReadonlyInvestigation({ client, sql, values = [], emit }) {
  if (!sql) throw codedError('bounded SQL is required', 'SQL_MISSING')
  let transactionOpen = false
  let primaryError = null
  let result

  try {
    await client.connect()
    await client.query('BEGIN READ ONLY')
    transactionOpen = true
    await client.query("SET LOCAL statement_timeout = '30000ms'")
    result = await client.query({
      name: 'readonly-investigation-bundle',
      text: sql,
      values,
      queryMode: 'extended',
    })
    emit(boundedJson({ investigation: result.rows }))
  } catch (error) {
    primaryError = error
    throw error
  } finally {
    let cleanupError = null
    if (transactionOpen) {
      try {
        await client.query('ROLLBACK')
      } catch (error) {
        cleanupError = error
      }
    }
    try {
      await client.end()
    } catch (error) {
      cleanupError ??= error
    }
    if (primaryError === null && cleanupError !== null) throw cleanupError
  }

  return result.rows
}

async function main() {
  try {
    if (CONNECTION_ENV_NAME.startsWith('TODO_')) {
      throw codedError('customize the connection variable name', 'TEMPLATE_NOT_CUSTOMIZED')
    }
    const sql = await loadInvestigationSql(process.argv[2])
    const values = await loadInvestigationParameters(process.argv[3])
    const connectionUrl = process.env[CONNECTION_ENV_NAME]
    if (!connectionUrl) throw codedError(`${CONNECTION_ENV_NAME} is not set`, 'CONNECTION_ENV_MISSING')

    const { default: pg } = await import('pg')
    const client = new pg.Client({
      connectionString: connectionUrl,
      connectionTimeoutMillis: 10_000,
    })
    await runReadonlyInvestigation({
      client,
      sql,
      values,
      emit: (output) => console.log(output),
    })
  } catch (error) {
    console.error(JSON.stringify({ error: 'readonly_query_failed', code: safeErrorCode(error) }))
    process.exitCode = 1
  }
}

if (import.meta.main) await main()

-- Copy to run-local scratch. Replace every placeholder before use.
-- Keep this as one parameterized bounded statement for readonly-query-bundle.mjs.
-- The subject and recent primary-key column placeholders must resolve to unique columns.
-- Qualify every table as separate schema/table identifiers. Keep values in the JSON parameter file.
WITH params AS (
  SELECT $1::TODO_SUBJECT_ID_TYPE AS subject_id
)
SELECT jsonb_build_object(
  'subject', (
    SELECT jsonb_build_object(
      'id', subject."TODO_SUBJECT_PK_COLUMN",
      'status', subject."TODO_SUBJECT_STATUS_COLUMN"
    )
    FROM "TODO_SUBJECT_SCHEMA"."TODO_SUBJECT_TABLE" AS subject
    JOIN params ON params.subject_id = subject."TODO_SUBJECT_PK_COLUMN"
  ),
  'related_count', (
    SELECT COUNT(*)
    FROM "TODO_RELATED_SCHEMA"."TODO_RELATED_TABLE" AS related
    JOIN params ON params.subject_id = related."TODO_RELATED_SUBJECT_FK_COLUMN"
    WHERE related."TODO_RELATED_STATE_COLUMN" = $2
  ),
  'recent_items', (
    SELECT COALESCE(
      jsonb_agg(to_jsonb(recent) ORDER BY recent.created_at DESC, recent.id DESC),
      '[]'::jsonb
    )
    FROM (
      SELECT item."TODO_RECENT_PK_COLUMN" AS id,
             item."TODO_RECENT_STATUS_COLUMN" AS status,
             item."TODO_RECENT_CREATED_AT_COLUMN" AS created_at
      FROM "TODO_RECENT_SCHEMA"."TODO_RECENT_TABLE" AS item
      JOIN params ON params.subject_id = item."TODO_RECENT_SUBJECT_FK_COLUMN"
      WHERE item."TODO_RECENT_CREATED_AT_COLUMN" >= NOW() - INTERVAL '7 days'
      ORDER BY item."TODO_RECENT_CREATED_AT_COLUMN" DESC,
               item."TODO_RECENT_PK_COLUMN" DESC
      LIMIT 20
    ) AS recent
  )
) AS investigation;

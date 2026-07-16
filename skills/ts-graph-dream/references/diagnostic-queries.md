# Graph Dream diagnostic queries

Use these as templates. Replace filters with the user's scope. Run read-only versions first.

## Environment and table baseline

```sql
SELECT current_database() AS database, inet_server_addr() AS server_addr;

SELECT table_name, COUNT(*) AS columns
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name LIKE 'graph_%'
GROUP BY table_name
ORDER BY table_name;

-- Production schema evolves. Probe existence first and only query tables that exist:
SELECT t AS table_name, to_regclass(t) IS NOT NULL AS present
FROM unnest(ARRAY['graph_entity','graph_edge','graph_claim','graph_quant','graph_mention',
                  'graph_document','graph_source','graph_taxonomy','graph_note','graph_audit',
                  'graph_maintenance_run','graph_maintenance_change']) t;

SELECT 'graph_entity' AS table_name, COUNT(*) AS total, COUNT(*) FILTER (WHERE merged_into_id IS NULL) AS active FROM graph_entity
UNION ALL SELECT 'graph_edge', COUNT(*), COUNT(*) FILTER (WHERE superseded_at IS NULL) FROM graph_edge
UNION ALL SELECT 'graph_claim', COUNT(*), COUNT(*) FILTER (WHERE superseded_at IS NULL) FROM graph_claim
UNION ALL SELECT 'graph_source', COUNT(*), COUNT(*) FILTER (WHERE is_active) FROM graph_source
UNION ALL SELECT 'graph_taxonomy', COUNT(*), COUNT(*) FILTER (WHERE status = 'active') FROM graph_taxonomy
UNION ALL SELECT 'graph_note', COUNT(*), COUNT(*) FILTER (WHERE status = 'active') FROM graph_note;
-- add: SELECT 'graph_quant', COUNT(*), COUNT(*) FILTER (WHERE superseded_at IS NULL) FROM graph_quant
--      only when to_regclass('graph_quant') IS NOT NULL (legacy table).
```

## Exact active edge duplicates

```sql
WITH active_edges AS (
  SELECT ge.*, subj.name AS subject_name, subj.ticker AS subject_ticker,
         obj.name AS object_name, obj.ticker AS object_ticker
  FROM graph_edge ge
  JOIN graph_entity subj ON subj.id = ge.subject_entity_id
  JOIN graph_entity obj ON obj.id = ge.object_entity_id
  WHERE ge.superseded_at IS NULL
)
SELECT subject_entity_id, predicate, object_entity_id,
       COALESCE(subject_ticker, subject_name) AS subject_label,
       COALESCE(object_ticker, object_name) AS object_label,
       COUNT(*) AS active_edges,
       ARRAY_AGG(id ORDER BY support_count DESC, truth_probability DESC, learned_at DESC) AS edge_ids,
       MIN(learned_at) AS first_learned,
       MAX(learned_at) AS last_learned,
       ROUND(AVG(truth_probability)::numeric, 3) AS avg_truth
FROM active_edges
GROUP BY subject_entity_id, predicate, object_entity_id, subject_label, object_label
HAVING COUNT(*) > 1
ORDER BY active_edges DESC, subject_label, predicate
LIMIT 100;
```

## Entity-scoped duplicate edge view

```sql
WITH selected AS (
  SELECT id FROM graph_entity
  WHERE ticker = :ticker OR canonical_key = :key OR name = :name
  LIMIT 1
), incident AS (
  SELECT ge.*, subj.name AS subject_name, subj.ticker AS subject_ticker,
         obj.name AS object_name, obj.ticker AS object_ticker
  FROM graph_edge ge
  JOIN graph_entity subj ON subj.id = ge.subject_entity_id
  JOIN graph_entity obj ON obj.id = ge.object_entity_id
  WHERE ge.subject_entity_id = (SELECT id FROM selected)
     OR ge.object_entity_id = (SELECT id FROM selected)
)
SELECT COALESCE(subject_ticker, subject_name) AS subject_label,
       predicate,
       COALESCE(object_ticker, object_name) AS object_label,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE superseded_at IS NULL) AS active,
       ROUND(AVG(truth_probability)::numeric, 3) AS avg_truth,
       ARRAY_AGG(id ORDER BY superseded_at ASC NULLS FIRST, support_count DESC, truth_probability DESC) AS sample_ids
FROM incident
GROUP BY 1,2,3
HAVING COUNT(*) > 1
ORDER BY active DESC, total DESC, predicate
LIMIT 100;
```


## Predicate directionality classification

Before merging reverse edges, build or infer a predicate map. Keep this map in code/config if cleanup will recur.

Recommended classes:

- `symmetric`: direction does not change meaning. Current canonical allowlist: `competes_with`, `partners_with`, `mentioned_with`. Variants like `rivals`, `rival_of`, `competing_with`, `collaborates_with`, and `co_mentioned_with` must be canonicalized first, then handled through the allowlist.
- `directed`: subject/object roles matter (`supplies`, `owns`, `acquires`, `leads_over`, `outperforms`).
- `inverse_pair`: two predicates represent opposite directions (`supplies` / `purchases_from`, `owns` / `owned_by`).
- `temporal_event`: may look symmetric but encodes event order or scoped claim text; review manually.
- `unknown`: report only until classified.

For symmetric predicates, duplicate identity should be:

```sql
(predicate_canonical,
 LEAST(subject_entity_id, object_entity_id),
 GREATEST(subject_entity_id, object_entity_id),
 optional_scope_key)
```

Do not use raw `(subject_entity_id, predicate, object_entity_id)` for symmetric idempotency.

## Reverse/symmetric duplicates

Use this after predicate canonicalization to find `A -> B` and `B -> A` pairs for canonical symmetric predicates. Do not auto-merge directional predicates without review.

```sql
WITH symmetric_predicates(predicate) AS (
  VALUES ('competes_with'), ('partners_with'), ('mentioned_with')
), active AS (
  SELECT id, subject_entity_id, predicate, object_entity_id, truth_probability, learned_at
  FROM graph_edge
  WHERE superseded_at IS NULL
    AND predicate IN (SELECT predicate FROM symmetric_predicates)
), normalized AS (
  SELECT LEAST(subject_entity_id, object_entity_id) AS entity_a,
         GREATEST(subject_entity_id, object_entity_id) AS entity_b,
         predicate,
         COUNT(*) AS n,
         COUNT(*) FILTER (WHERE subject_entity_id < object_entity_id) AS forward_n,
         COUNT(*) FILTER (WHERE subject_entity_id > object_entity_id) AS reverse_n,
         ARRAY_AGG(id ORDER BY truth_probability DESC, learned_at DESC) AS edge_ids
  FROM active
  GROUP BY 1,2,3
)
SELECT n.*, ea.name AS entity_a_name, eb.name AS entity_b_name
FROM normalized n
JOIN graph_entity ea ON ea.id = n.entity_a
JOIN graph_entity eb ON eb.id = n.entity_b
WHERE n.forward_n > 0 AND n.reverse_n > 0
ORDER BY n.n DESC
LIMIT 100;
```

## Predicate drift

```sql
SELECT predicate,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE superseded_at IS NULL) AS active,
       ROUND(AVG(truth_probability)::numeric, 3) AS avg_truth,
       MIN(learned_at) AS first_seen,
       MAX(learned_at) AS last_seen
FROM graph_edge
GROUP BY predicate
ORDER BY active DESC, total DESC, predicate;

SELECT predicate, COUNT(*) AS active
FROM graph_edge
WHERE superseded_at IS NULL
GROUP BY predicate
HAVING COUNT(*) <= 2
ORDER BY active, predicate
LIMIT 200;
```

## Predicate synonym clusters

Surface candidate synonym/variant families by shared morphological stem (verb-tense and phrasing
variants collapse to the same key). Review by hand before mapping — this heuristic groups true
same-direction synonyms AND inverse pairs, which must be handled differently (see the SKILL's
**Predicate canonicalization pass**).

```sql
WITH active AS (
  SELECT predicate, COUNT(*) c FROM graph_edge WHERE superseded_at IS NULL GROUP BY 1
), stemmed AS (
  SELECT predicate, c,
         regexp_replace(
           regexp_replace(predicate, '_(with|to|from|by|in|of|for|on|at)$', ''),
           '(ed|ing|es|s)$', '') AS stem
  FROM active
)
SELECT stem, COUNT(*) AS variants, SUM(c) AS active_edges,
       ARRAY_AGG(predicate || ':' || c ORDER BY c DESC) AS members
FROM stemmed
GROUP BY stem
HAVING COUNT(*) > 1
ORDER BY active_edges DESC, variants DESC
LIMIT 100;
```

## Predicate canonicalize + re-collapse preview

Given an explicit, hand-approved `variant -> canonical` map of **same-direction** synonyms only
(exclude inverse pairs like `acquired_by`/`acquires` — those need a subject/object swap in a separate
reviewed script), preview how many rows each rewrite touches and how many duplicate edges it will
then create for the follow-up collapse to absorb.

```sql
WITH pmap(variant, canonical) AS (
  VALUES ('benefits','benefits_from'), ('drives','drives_demand_for'),
         ('partnered_with','partners_with'), ('developing','develops'),
         ('invested_in','invests_in'), ('collaborates','collaborates_with')
), rewrite AS (
  SELECT ge.id, ge.subject_entity_id, m.canonical AS new_predicate, ge.object_entity_id
  FROM graph_edge ge JOIN pmap m ON ge.predicate = m.variant
  WHERE ge.superseded_at IS NULL
)
SELECT
  (SELECT COUNT(*) FROM rewrite) AS rows_to_rewrite,
  (SELECT COUNT(*) FROM (
     SELECT subject_entity_id, new_predicate, object_entity_id FROM (
       SELECT subject_entity_id, new_predicate, object_entity_id FROM rewrite
       UNION ALL
       SELECT ge.subject_entity_id, ge.predicate, ge.object_entity_id
       FROM graph_edge ge JOIN pmap m ON ge.predicate = m.canonical
       WHERE ge.superseded_at IS NULL
     ) u
     GROUP BY 1,2,3 HAVING COUNT(*) > 1
   ) dup) AS new_duplicate_clusters;
```

Apply order: (1) `UPDATE graph_edge SET predicate = canonical` on the variant rows in a transaction
with `graph_audit` + `graph_maintenance_change` (`reason_code='predicate_canonicalize'`); (2) run the
**Safe supersede preview** collapse below to absorb the duplicates the rewrite created; (3) re-run the
**Predicate drift** / vocabulary query and confirm the singleton tail shrank; (4) persist the approved
map into `graph_taxonomy` (next section) so ingestion folds the variants going forward.

## Predicate vocabulary overrides (graph_taxonomy — write-time, durable)

Since F0216, the ts-prefect writer loads a `variant -> canonical` override map at write time from:

```sql
SELECT slug, metadata->>'canonical_slug' AS canonical
FROM graph_taxonomy
WHERE taxonomy_type IN ('edge_predicate', 'claim_predicate')
  AND status = 'active'
  AND metadata->>'canonical_slug' IS NOT NULL;
```

DB rows win over the in-code synonym map; rows whose canonical is missing/empty/equal to the slug are
ignored. So the durable output of a predicate pass is an upsert per approved variant
(`(taxonomy_type, slug)` is unique; the writer caches the map per instance, so rows apply on the next
writer start):

```sql
INSERT INTO graph_taxonomy (id, taxonomy_type, slug, label, description, status, metadata, created_at, updated_at)
VALUES (gen_random_uuid()::text, 'edge_predicate', :variant, :variant,
        'ts-graph-dream predicate fold', 'active',
        jsonb_build_object('canonical_slug', :canonical, 'source', 'ts-graph-dream'),
        now(), now())
ON CONFLICT (taxonomy_type, slug) DO UPDATE
SET metadata = graph_taxonomy.metadata || jsonb_build_object('canonical_slug', :canonical),
    status = 'active', updated_at = now();
```

Wrap in the usual `graph_audit` + `graph_maintenance_change` trail. Check the dashboard's
`graph-valence.ts` / `graph-predicate-class.ts` know each canonical target (unknown → neutral/blank
in the UI) and list any new canonicals for the dashboard maps (U-channel).

## Co-occurrence noise

Feeds the SKILL's **Co-occurrence & low-signal noise pass**. Since F0216, new co-occurrence edges
arrive tagged `additional_data.signal_class='co_occurrence'` — an untagged backlog implies pre-F0216
rows or an environment running old code. Adjust the `lowsig` predicate list per
graph. Step 1 — measure the noise footprint, support, and whether a `signal_class` tag already exists:

```sql
WITH lowsig(predicate) AS (VALUES ('mentioned_with'),('co_mentioned_with'),('related_to'),('interacts_with'))
SELECT
  count(*) AS lowsig_edges,
  count(*) FILTER (WHERE superseded_at IS NULL) AS active_lowsig,
  (SELECT count(*) FROM graph_edge WHERE superseded_at IS NULL) AS total_active,
  round(100.0 * count(*) FILTER (WHERE superseded_at IS NULL)
        / NULLIF((SELECT count(*) FROM graph_edge WHERE superseded_at IS NULL),0), 1) AS pct_of_active,
  round(avg(support_count) FILTER (WHERE superseded_at IS NULL)::numeric,2) AS avg_support,
  round(avg(truth_probability) FILTER (WHERE superseded_at IS NULL)::numeric,3) AS avg_truth,
  count(*) FILTER (WHERE superseded_at IS NULL AND additional_data ? 'signal_class') AS already_tagged
FROM graph_edge
WHERE predicate IN (SELECT predicate FROM lowsig);
```

Step 2 — redundancy ratio (decides prune vs tag). How many low-signal unordered pairs also have a
real causal edge (co-occurrence is redundant there) vs. are co-occurrence-**only** (pruning is lossy):

```sql
WITH lowsig(predicate) AS (VALUES ('mentioned_with'),('co_mentioned_with'),('related_to'),('interacts_with')),
mw AS (
  SELECT DISTINCT least(subject_entity_id,object_entity_id) a, greatest(subject_entity_id,object_entity_id) b
  FROM graph_edge WHERE superseded_at IS NULL AND predicate IN (SELECT predicate FROM lowsig)
),
causal AS (
  SELECT DISTINCT least(subject_entity_id,object_entity_id) a, greatest(subject_entity_id,object_entity_id) b
  FROM graph_edge WHERE superseded_at IS NULL AND predicate NOT IN (SELECT predicate FROM lowsig)
)
SELECT (SELECT count(*) FROM mw) AS lowsig_pairs,
       (SELECT count(*) FROM mw JOIN causal USING (a,b)) AS pairs_with_causal_backbone,
       (SELECT count(*) FROM mw) - (SELECT count(*) FROM mw JOIN causal USING (a,b)) AS cooccurrence_only_pairs;
```

Safe TAG_SIGNAL_CLASS apply (reversible, no topology change — audit before/after `additional_data`):

```sql
-- preview count, then wrap the UPDATE in BEGIN + graph_audit + graph_maintenance_change
UPDATE graph_edge
SET additional_data = COALESCE(additional_data,'{}'::jsonb) || jsonb_build_object('signal_class','co_occurrence'),
    updated_at = now()
WHERE superseded_at IS NULL
  AND predicate IN ('mentioned_with','co_mentioned_with','related_to','interacts_with')
  AND (additional_data->>'signal_class') IS DISTINCT FROM 'co_occurrence';
```

Gated PRUNE_REDUNDANT_COOCCURRENCE preview — only co-occurrence edges whose pair already has a causal
edge (never the co-occurrence-only tail). Review, then supersede with `reason_code='cooccurrence_redundant'`:

```sql
WITH lowsig(predicate) AS (VALUES ('mentioned_with'),('co_mentioned_with'),('related_to'),('interacts_with')),
causal AS (
  SELECT DISTINCT least(subject_entity_id,object_entity_id) a, greatest(subject_entity_id,object_entity_id) b
  FROM graph_edge WHERE superseded_at IS NULL AND predicate NOT IN (SELECT predicate FROM lowsig)
)
SELECT ge.id, ge.subject_entity_id, ge.predicate, ge.object_entity_id, ge.support_count, ge.truth_probability
FROM graph_edge ge
JOIN causal c ON c.a = least(ge.subject_entity_id,ge.object_entity_id)
             AND c.b = greatest(ge.subject_entity_id,ge.object_entity_id)
WHERE ge.superseded_at IS NULL AND ge.predicate IN (SELECT predicate FROM lowsig)
ORDER BY ge.support_count, ge.truth_probability
LIMIT 100;
```

## Alias contamination & false merges

`graph_entity.aliases` is `jsonb` — expand with `jsonb_array_elements_text`. Find alias strings
shared across more than one active entity. Then judge each: same real-world thing (→ merge) vs. one
entity carrying another's name by a bad auto-merge (→ REMOVE_ALIAS / UNMERGE).

```sql
WITH ex AS (
  SELECT e.id, e.node_type, e.canonical_key, e.ticker, e.name, TRIM(a) AS alias
  FROM graph_entity e, jsonb_array_elements_text(e.aliases) a
  WHERE e.merged_into_id IS NULL
)
SELECT alias,
       COUNT(DISTINCT id) AS on_n_entities,
       ARRAY_AGG(DISTINCT node_type) AS node_types,
       COUNT(*) FILTER (WHERE ticker IS NOT NULL) AS on_tickered_entities,
       (ARRAY_AGG(canonical_key || '::' || name ORDER BY canonical_key))[1:8] AS sample_entities
FROM ex
WHERE LENGTH(alias) >= 3
GROUP BY alias
HAVING COUNT(DISTINCT id) > 1
ORDER BY on_tickered_entities DESC, on_n_entities DESC
LIMIT 60;
```

High-precision contamination: an alias that is the *name/ticker of one ticker'd company* but sits on a
*different* ticker'd company. Also surface garbage aliases and cross-company false merges:

```sql
-- garbage aliases on active entities
SELECT id, name, aliases FROM graph_entity
WHERE merged_into_id IS NULL
  AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(aliases) a
              WHERE TRIM(a) IN ('N/A','n/a','','-') OR TRIM(a) ~ '^[0-9]+$')
LIMIT 100;

-- false merges: a merged row whose survivor has a different ticker (two distinct companies fused)
SELECT child.id AS merged_id, child.name AS merged_name, child.canonical_key AS merged_key,
       surv.id AS survivor_id, surv.name AS survivor_name, surv.ticker AS survivor_ticker
FROM graph_entity child
JOIN graph_entity surv ON surv.id = child.merged_into_id
WHERE child.node_type = 'company' AND surv.node_type = 'company'
  AND child.canonical_key IS DISTINCT FROM surv.canonical_key
ORDER BY surv.name
LIMIT 100;
```

Safe REMOVE_ALIAS apply (array edit, fully audited — does not touch edges/mentions):

```sql
-- preview: strip contaminating aliases from one entity
SELECT id, name, aliases,
       (SELECT jsonb_agg(a) FROM jsonb_array_elements_text(aliases) a
        WHERE TRIM(a) NOT IN ('Samsung','Samsung Electronics')) AS aliases_after
FROM graph_entity WHERE id = :entity_id;
```

UNMERGE is NOT a simple query — re-homing the merged entity's edges/mentions needs per-row provenance
that usually isn't recoverable; treat it as a reviewed, dry-run-first migration, not bulk cleanup.

Before ANY entity merge/quarantine, check for user-authored notes (they must be repointed to the
survivor, and a noted entity should not be silently quarantined):

```sql
SELECT gn.entity_id, ge.name, count(*) AS notes
FROM graph_note gn JOIN graph_entity ge ON ge.id = gn.entity_id
WHERE gn.status = 'active' AND gn.entity_id = ANY(:candidate_ids)
GROUP BY 1, 2;

-- on merge: UPDATE graph_note SET entity_id = :survivor_id, updated_at = now()
--           WHERE entity_id = :loser_id;  -- audited like every other repoint
```

## Entity name hygiene

Feeds the SKILL's **Entity name hygiene pass**. Two problems: opaque identifier-names and
ticker-as-name.

Opaque identifier-names (`PROD_MACRO_STORY:<UUID>`, bare UUIDs, `name = canonical_key` where the key
is an opaque `<key>:<uuid>`), joined to any readable twin sharing the same UUID:

```sql
WITH opaque AS (
  SELECT id, node_type, name, ticker, canonical_key, aliases
  FROM graph_entity
  WHERE merged_into_id IS NULL
    AND (
      name ~ '^[A-Za-z_]+:[0-9a-fA-F-]{36}$'                                  -- <KEY>:<uuid>
      OR name ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'  -- bare uuid
      OR name = canonical_key AND canonical_key ~ '^[A-Za-z_]+:[0-9a-fA-F-]{36}$'
    )
)
SELECT o.*,
       -- readable twin: another active entity whose canonical_key holds the same uuid
       (SELECT jsonb_agg(jsonb_build_object('id', t.id, 'node_type', t.node_type, 'name', t.name))
        FROM graph_entity t
        WHERE t.merged_into_id IS NULL AND t.id <> o.id
          AND lower(substring(t.canonical_key from '[0-9a-fA-F-]{36}'))
            = lower(substring(o.canonical_key from '[0-9a-fA-F-]{36}'))) AS readable_twins,
       (SELECT count(*) FROM graph_edge e
        WHERE e.superseded_at IS NULL
          AND (e.subject_entity_id = o.id OR e.object_entity_id = o.id)) AS active_edges
FROM opaque o
ORDER BY active_edges DESC
LIMIT 200;
```

Ticker-as-name companies (the `name` is an exchange symbol, not a real company name — common for
Asian listings `.KS .T .HK .SS .SZ .TW .KQ .SI`):

```sql
SELECT id, node_type, name, ticker, canonical_key, aliases,
       (SELECT count(*) FROM graph_edge e
        WHERE e.superseded_at IS NULL
          AND (e.subject_entity_id = graph_entity.id OR e.object_entity_id = graph_entity.id)) AS active_edges
FROM graph_entity
WHERE merged_into_id IS NULL
  AND node_type = 'company'
  AND (
    (ticker IS NOT NULL AND name = ticker)
    OR name ~ '^[0-9A-Z]{1,6}\.[A-Z]{1,4}$'   -- 005930.KS, 6758.T, 0700.HK, 600519.SS, 2330.TW
  )
ORDER BY active_edges DESC
LIMIT 200;
```

Safe RELABEL_ENTITY apply (edits only `name`/`aliases`/`ticker`; no edges/mentions move — audit
before/after). Preview one entity, then wrap the UPDATE in `BEGIN` + `graph_audit` +
`graph_maintenance_change` (`reason_code='entity_relabel'`):

```sql
-- :new_name and :new_ticker come from the reasoning model's verdict, never from a heuristic.
-- Old name is appended to aliases (deduped) so the ticker/opaque key still resolves in search.
SELECT id, name AS old_name, ticker AS old_ticker,
       :new_name AS new_name,
       (SELECT jsonb_agg(DISTINCT a)
        FROM jsonb_array_elements_text(COALESCE(aliases,'[]'::jsonb) || to_jsonb(name)) a) AS aliases_after
FROM graph_entity WHERE id = :entity_id;
```

## Non-entity & mistyped nodes

Feeds the SKILL's **Non-entity & mistyped node pass**. Non-entity literals (numbers/money/units
captured as entities) and their edge/quant/provenance footprint — decides salvage vs quarantine:

```sql
WITH junk AS (
  SELECT id, name, node_type FROM graph_entity
  WHERE merged_into_id IS NULL
    AND ( name ~ '^\$?[0-9][0-9.,]*\s*(bn|billion|m|million|k|B|M|K|T|%|x)?$'   -- 400, 1.3, 100B, 35%
          OR name ~ '^[^A-Za-z]+$' )                                             -- no letters at all
)
SELECT j.id, j.name, j.node_type,
  (SELECT count(*) FROM graph_edge e WHERE (e.subject_entity_id=j.id OR e.object_entity_id=j.id)) AS total_edges,
  (SELECT count(*) FROM graph_edge e WHERE e.superseded_at IS NULL AND (e.subject_entity_id=j.id OR e.object_entity_id=j.id)) AS active_edges,
  (SELECT count(*) FROM graph_quant q WHERE q.subject_entity_id=j.id AND q.superseded_at IS NULL) AS active_quants,
  (SELECT count(*) FROM graph_mention m
     WHERE m.source_record_id IS NOT NULL
       AND (m.assertion_id=j.id
            OR m.assertion_id IN (SELECT id FROM graph_edge e WHERE e.subject_entity_id=j.id OR e.object_entity_id=j.id)
            OR m.assertion_id IN (SELECT id FROM graph_quant q WHERE q.subject_entity_id=j.id))) AS provenance_records
FROM junk j
ORDER BY active_edges DESC, total_edges DESC
LIMIT 200;
```

Mistyped `company` nodes that read like a narrative/headline/theme (candidates for RETYPE — always
model-adjudicated, this is only a pre-filter):

```sql
SELECT id, name,
  (SELECT count(*) FROM graph_edge e WHERE e.superseded_at IS NULL AND (e.subject_entity_id=graph_entity.id OR e.object_entity_id=graph_entity.id)) AS active_edges
FROM graph_entity
WHERE merged_into_id IS NULL AND node_type='company'
  AND name ~ '\s'                                   -- multi-word
  AND ( length(name) > 35 OR name ~ '\y(and|of|the|for|ahead|amid|after|as)\y' )  -- sentence-like
  AND name !~ '(Inc|Corp|Ltd|LLC|Group|Holdings|Co|PLC|AG|SA|NV|Technologies|Systems|Motors?|Energy|Semiconductor)\.?$'
ORDER BY active_edges DESC
LIMIT 200;
```

Safe RETYPE_ENTITY apply (touches only `node_type`; edges/quants/mentions stay in place — audited):

```sql
-- :correct_type from the reasoning model (theme_situation|event|person|sector|macro_indicator|...)
UPDATE graph_entity SET node_type = :correct_type, updated_at = now() WHERE id = :entity_id;
-- wrap in BEGIN + graph_audit(before/after node_type, reason_code='entity_retype') + graph_maintenance_change
```

Safe QUARANTINE_ENTITY apply (no `is_active` column → flag in `additional_data`, and supersede the
node's noise assertions). Apply ONLY to nodes with zero active meaning-bearing edges, after salvage:

```sql
-- flag the entity (reversible)
UPDATE graph_entity
SET additional_data = COALESCE(additional_data,'{}'::jsonb)
      || jsonb_build_object('quarantined', true, 'quarantine_reason', :reason, 'quarantined_by','ts-graph-dream'),
    updated_at = now()
WHERE id = ANY(:junk_ids);

-- supersede its remaining (noise) edges + quants so they stop rendering / counting
UPDATE graph_edge  SET superseded_at = now(), updated_at = now()
WHERE superseded_at IS NULL AND (subject_entity_id = ANY(:junk_ids) OR object_entity_id = ANY(:junk_ids));
UPDATE graph_quant SET superseded_at = now(), updated_at = now()
WHERE superseded_at IS NULL AND subject_entity_id = ANY(:junk_ids);
-- all three wrapped in BEGIN + graph_audit + graph_maintenance_change (reason_code='non_entity_quarantine')
```

The dashboard graph query must then exclude quarantined entities
(`(additional_data->>'quarantined') IS DISTINCT FROM 'true'`) or the flag is inert.

## Geopolitical & location nodes

Feeds the SKILL's **Geopolitical vs location entity pass**. Match a curated GPE/location list across
ALL node types and group by concept to expose fragmentation. Extend `geo(name)` per graph.

```sql
WITH geo(name) AS (VALUES
  ('iran'),('china'),('united states'),('usa'),('us'),('u.s.'),('russia'),('israel'),('taiwan'),
  ('japan'),('south korea'),('north korea'),('india'),('germany'),('france'),('united kingdom'),('uk'),
  ('ukraine'),('saudi arabia'),('qatar'),('uae'),('canada'),('mexico'),('brazil'),('netherlands'),
  ('switzerland'),('italy'),('spain'),('poland'),('australia'),('indonesia'),('malaysia'),('thailand'),
  ('vietnam'),('singapore'),('hong kong'),('europe'),('asia'),('middle east'),('eu'),('gulf'),('opec')
)
SELECT lower(regexp_replace(ge.name,'[^a-zA-Z ]','','g')) AS concept,
       ge.id, ge.node_type, ge.name, ge.canonical_key,
  (SELECT count(*) FROM graph_edge e WHERE e.superseded_at IS NULL
     AND (e.subject_entity_id=ge.id OR e.object_entity_id=ge.id)) AS active_edges
FROM graph_entity ge
WHERE ge.merged_into_id IS NULL
  AND lower(ge.name) IN (SELECT name FROM geo)
ORDER BY concept, active_edges DESC;
```

Per-conflated-node edge dump (feed to the model to assign each edge a sense — geopolitical actor vs
place/market). `:node_id` is one candidate:

```sql
SELECT e.id AS edge_id, e.predicate,
  CASE WHEN e.subject_entity_id = :node_id THEN 'out' ELSE 'in' END AS dir,
  other.name AS counterpart, other.node_type AS counterpart_type,
  e.edge_text
FROM graph_edge e
JOIN graph_entity other ON other.id = CASE WHEN e.subject_entity_id = :node_id THEN e.object_entity_id ELSE e.subject_entity_id END
WHERE e.superseded_at IS NULL AND (e.subject_entity_id = :node_id OR e.object_entity_id = :node_id)
ORDER BY e.predicate;
```

Safe RETYPE to a geo type (single-sense). Beware `(node_type, canonical_key)` uniqueness — if the
target already exists, it's a MERGE, not a retype:

```sql
UPDATE graph_entity SET node_type = :geo_type, updated_at = now() WHERE id = :entity_id;  -- geopolitical | location
-- wrap in BEGIN + graph_audit(before/after node_type, reason_code='geo_retype') + graph_maintenance_change
```

SPLIT preview + apply (conflated node kept as dominant sense; minority-sense edges repointed to a new
sibling node). Create the sibling with a sense-suffixed canonical_key to dodge the unique index:

```sql
-- 1. create the minority-sense sibling (once), reusing the original's name/aliases
INSERT INTO graph_entity (id, node_type, canonical_key, name, aliases, scope, additional_data, created_at, updated_at)
SELECT gen_random_uuid()::text, :minority_type, canonical_key || ':' || :minority_type, name, aliases, scope,
       jsonb_build_object('split_from', id, 'sense', :minority_type), now(), now()
FROM graph_entity WHERE id = :orig_id
RETURNING id;   -- :sibling_id

-- 2. repoint the model-chosen minority-sense edges (by explicit edge id list), audited per row
UPDATE graph_edge SET subject_entity_id = :sibling_id, updated_at = now()
WHERE id = ANY(:minority_edge_ids) AND subject_entity_id = :orig_id;
UPDATE graph_edge SET object_entity_id  = :sibling_id, updated_at = now()
WHERE id = ANY(:minority_edge_ids) AND object_entity_id  = :orig_id;
-- repoint their mentions too if mentions are entity-keyed; write graph_audit(reason_code='geo_sense_split') + change rows
```

## Uninterpretable quants (legacy — only when graph_quant exists)

Feeds the SKILL's **Legacy quant pass**. Run `SELECT to_regclass('graph_quant')` first — the table
was decommissioned in 2026-07 (FMP is the financials source). If it
exists AND is still being written, the finding is environment drift (pre-decommission code), not row
hygiene. For in-place cleanup of legacy rows, measure the generic-fallback metrics and whether
any are salvageable (context / unit / period / provenance):

```sql
WITH generic(metric) AS (VALUES ('reported_numeric_value'),('value'),('numeric_value'),('reported_value'))
SELECT q.metric,
  count(*) FILTER (WHERE q.superseded_at IS NULL) AS active,
  count(*) FILTER (WHERE q.superseded_at IS NULL AND q.additional_data <> '{}'::jsonb) AS has_context,
  count(*) FILTER (WHERE q.superseded_at IS NULL AND q.unit IS NOT NULL) AS has_unit,
  count(*) FILTER (WHERE q.superseded_at IS NULL AND (q.period_start IS NOT NULL OR q.period_end IS NOT NULL)) AS has_period,
  count(*) FILTER (WHERE q.superseded_at IS NULL AND EXISTS (
     SELECT 1 FROM graph_mention m WHERE m.assertion_table='graph_quant' AND m.assertion_id=q.id AND m.source_record_id IS NOT NULL)) AS has_provenance,
  count(*) FILTER (WHERE q.superseded_at IS NULL AND q.value=round(q.value) AND q.value BETWEEN 1990 AND 2035) AS looks_like_year
FROM graph_quant q WHERE q.metric IN (SELECT metric FROM generic)
GROUP BY q.metric ORDER BY active DESC;
```

Safe DROP (supersede, audited) of the uninterpretable subset — no context, no unit, no provenance:

```sql
-- preview count, then wrap in BEGIN + graph_audit(before=metric/value/unit, reason_code='uninterpretable_quant') + graph_maintenance_change
UPDATE graph_quant SET superseded_at = now(), updated_at = now()
WHERE superseded_at IS NULL
  AND metric IN ('reported_numeric_value','value','numeric_value','reported_value')
  AND additional_data = '{}'::jsonb AND unit IS NULL
  AND NOT EXISTS (SELECT 1 FROM graph_mention m WHERE m.assertion_table='graph_quant' AND m.assertion_id=graph_quant.id AND m.source_record_id IS NOT NULL);
```

## Entity fragmentation

```sql
SELECT ticker, COUNT(*) AS entities, ARRAY_AGG(id || ':' || name ORDER BY created_at) AS ids
FROM graph_entity
WHERE ticker IS NOT NULL AND ticker <> ''
GROUP BY ticker
HAVING COUNT(*) > 1
ORDER BY entities DESC, ticker;

SELECT canonical_key, COUNT(*) AS entities, ARRAY_AGG(id || ':' || name ORDER BY created_at) AS ids
FROM graph_entity
GROUP BY canonical_key
HAVING COUNT(*) > 1
ORDER BY entities DESC, canonical_key
LIMIT 100;
```

## Ingestion temp entities (R0053 — resolve/merge forward, not contamination)

The new graph-ingestion writer marks unresolved model-proposed placeholder entities with
`additional_data->>'origin' = 'ingestion_temp_entity'` plus `additional_data->>'source_record_id'`.
These are expected-transient and should be prioritized for reconciliation/merge into their canonical
node — they are NOT contamination and NOT false-merge candidates.

```sql
SELECT
  e.id,
  e.name,
  e.ticker,
  e.additional_data->>'source_record_id' AS source_record_id,
  e.created_at,
  e.merged_into_id
FROM graph_entity e
WHERE e.additional_data->>'origin' = 'ingestion_temp_entity'
  AND e.merged_into_id IS NULL   -- still unresolved: candidates for merge-forward
ORDER BY e.created_at DESC
LIMIT 200;
```

## Provenance and import-family health

```sql
SELECT gd.metadata->>'capture_path' AS capture_path,
       COUNT(*) AS documents,
       COUNT(DISTINCT gd.source_record_id) AS source_records
FROM graph_document gd
GROUP BY 1
ORDER BY documents DESC NULLS LAST;

SELECT gm.assertion_table, gm.assertion_id, COUNT(*) AS mentions,
       COUNT(DISTINCT gm.source_document_id) AS docs,
       COUNT(DISTINCT gm.source_record_id) AS source_records
FROM graph_mention gm
GROUP BY 1,2
HAVING COUNT(*) > 10
ORDER BY mentions DESC
LIMIT 100;
```

## Safe supersede preview pattern

Preview first. Pick one canonical survivor per duplicate cluster using project-specific rules.

```sql
WITH duplicate_clusters AS (
  SELECT subject_entity_id, predicate, object_entity_id,
         ARRAY_AGG(id ORDER BY support_count DESC, truth_probability DESC, learned_at DESC, updated_at DESC) AS ordered_ids
  FROM graph_edge
  WHERE superseded_at IS NULL
  GROUP BY subject_entity_id, predicate, object_entity_id
  HAVING COUNT(*) > 1
), planned AS (
  SELECT ordered_ids[1] AS survivor_id, unnest(ordered_ids[2:]) AS supersede_id
  FROM duplicate_clusters
)
SELECT p.*, ge.edge_text, ge.truth_probability, ge.support_count
FROM planned p
JOIN graph_edge ge ON ge.id = p.supersede_id
ORDER BY p.survivor_id
LIMIT 100;
```

For an apply script, wrap in `BEGIN`, lock target rows with `FOR UPDATE`, update only `superseded_at IS NULL` rows, insert `graph_audit` and `graph_maintenance_change`, verify counts, then `COMMIT`. Do not paste credentials into logs.


## Symmetric-predicate durable fix outline

If the system should prevent recurrence, propose one of these code/schema fixes separately from cleanup:

1. In importer/write code, canonicalize symmetric predicates before hashing/upsert:
   - map predicate synonyms to a canonical predicate;
   - sort endpoint IDs for symmetric predicates;
   - compute content/upsert identity from normalized predicate + normalized endpoints + scope, not generated edge text.
2. Add a DB-supported guard, for example generated normalized endpoint columns or a functional unique index for active symmetric assertions. Validate with a read-only production plan, transaction rollback, and a narrowly scoped production canary before broad apply.
3. Keep source mentions as evidence rows and aggregate `support_count`; do not duplicate assertion rows for every source.
4. In the dashboard, display symmetric edges as `A ↔ B competes_with` or omit arrow semantics in the inspector.

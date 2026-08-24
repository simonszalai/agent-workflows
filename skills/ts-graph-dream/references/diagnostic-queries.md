# Graph Dream diagnostic queries (graph-v3)

Use these as templates. Replace filters with the user's scope. Run read-only versions first.

Graph-v3 canonical schema (E0026 flip complete — legacy `graph_entity` / `graph_edge` /
`graph_claim` / `graph_quant` / `graph_mention` / `graph_document` / `graph_audit` /
`graph_maintenance_*` are REMOVED from production):

- Nodes live in `graph_node` (`node_type`, `entity_subtype`, `canonical_key`, `name`, `aliases`
  jsonb, `ticker`, `merged_into_id`, `additional_data`). Event detail is in `graph_event`
  (1:1 on `node_id`).
- All assertions (former edges AND claims) live in `graph_assertion`:
  `assertion_kind='relation'` (former graph_edge; `object_node_id` NOT NULL) vs
  `assertion_kind='attribute'` (former graph_claim; `object_literal`). Columns:
  `subject_node_id`, `predicate`, `object_node_id`, `object_literal`, `assertion_text`,
  `fact_kind` ('semantic'|'source_material'|'system'), `truth_probability`, `support_count`,
  `contradiction_count`, `superseded_at`, `superseded_by_assertion_id`, `learned_at`,
  `identity_hash` (partial-unique while active), `additional_data`.
- Provenance: `graph_evidence` (per assertion×record: `assertion_id`, `record_id`, `quote`,
  `stance`, `origin_id`, `publisher_source_id`) + `graph_origin` + `graph_event_record`.
- Audit trail: `graph_request` (leased work/decision envelope) + `graph_mutation`
  (before/after per row, `reason_code`, `rationale`). There is no `graph_audit` /
  `graph_maintenance_change` anymore — every apply goes through the
  `record_decision` → `apply_decided_request` pattern in
  `src/graph/maintenance_v3.py` (proposals with exact `before` snapshots, stale-check
  `FOR UPDATE`, `graph_mutation` rows written by the framework). Prefer the
  `ts-graph-maintenance` skill for applies; raw UPDATEs bypass the mutation ledger.

## Environment and table baseline

```sql
SELECT current_database() AS database, inet_server_addr() AS server_addr;

SELECT table_name, COUNT(*) AS columns
FROM information_schema.columns
WHERE table_schema = 'public' AND table_name LIKE 'graph_%'
GROUP BY table_name
ORDER BY table_name;

-- Probe existence first and only query tables that exist. Any legacy table showing
-- present=true means you are NOT on canonical production — stop and re-check env.
SELECT t AS table_name, to_regclass(t) IS NOT NULL AS present
FROM unnest(ARRAY['graph_node','graph_assertion','graph_event','graph_evidence',
                  'graph_origin','graph_event_record','graph_request','graph_mutation',
                  'graph_source','graph_taxonomy','graph_note',
                  'graph_entity','graph_edge','graph_claim','graph_quant']) t;

SELECT 'graph_node' AS table_name, COUNT(*) AS total, COUNT(*) FILTER (WHERE merged_into_id IS NULL) AS active FROM graph_node
UNION ALL SELECT 'graph_assertion(relation)', COUNT(*), COUNT(*) FILTER (WHERE superseded_at IS NULL) FROM graph_assertion WHERE assertion_kind = 'relation'
UNION ALL SELECT 'graph_assertion(attribute)', COUNT(*), COUNT(*) FILTER (WHERE superseded_at IS NULL) FROM graph_assertion WHERE assertion_kind = 'attribute'
UNION ALL SELECT 'graph_source', COUNT(*), COUNT(*) FILTER (WHERE is_active) FROM graph_source
UNION ALL SELECT 'graph_taxonomy', COUNT(*), COUNT(*) FILTER (WHERE status = 'active') FROM graph_taxonomy
UNION ALL SELECT 'graph_note', COUNT(*), COUNT(*) FILTER (WHERE status = 'active') FROM graph_note;
```

## Exact active relation duplicates

Note: `uq_graph_assertion_active_identity_hash` (partial unique on `identity_hash` while
`superseded_at IS NULL`) already blocks identity-exact duplicates, so hits here mean the
identity hash inputs differ (scope/literal/text) while the triple is the same — still worth review.

```sql
WITH active_rel AS (
  SELECT ga.*, subj.name AS subject_name, subj.ticker AS subject_ticker,
         obj.name AS object_name, obj.ticker AS object_ticker
  FROM graph_assertion ga
  JOIN graph_node subj ON subj.id = ga.subject_node_id
  JOIN graph_node obj ON obj.id = ga.object_node_id
  WHERE ga.assertion_kind = 'relation' AND ga.superseded_at IS NULL
)
SELECT subject_node_id, predicate, object_node_id,
       COALESCE(subject_ticker, subject_name) AS subject_label,
       COALESCE(object_ticker, object_name) AS object_label,
       COUNT(*) AS active_assertions,
       ARRAY_AGG(id ORDER BY support_count DESC, truth_probability DESC, learned_at DESC) AS assertion_ids,
       MIN(learned_at) AS first_learned,
       MAX(learned_at) AS last_learned,
       ROUND(AVG(truth_probability)::numeric, 3) AS avg_truth
FROM active_rel
GROUP BY subject_node_id, predicate, object_node_id, subject_label, object_label
HAVING COUNT(*) > 1
ORDER BY active_assertions DESC, subject_label, predicate
LIMIT 100;
```

## Node-scoped duplicate relation view

```sql
WITH selected AS (
  SELECT id FROM graph_node
  WHERE ticker = :ticker OR canonical_key = :key OR name = :name
  LIMIT 1
), incident AS (
  SELECT ga.*, subj.name AS subject_name, subj.ticker AS subject_ticker,
         obj.name AS object_name, obj.ticker AS object_ticker
  FROM graph_assertion ga
  JOIN graph_node subj ON subj.id = ga.subject_node_id
  JOIN graph_node obj ON obj.id = ga.object_node_id
  WHERE ga.assertion_kind = 'relation'
    AND (ga.subject_node_id = (SELECT id FROM selected)
      OR ga.object_node_id = (SELECT id FROM selected))
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

Before merging reverse relations, build or infer a predicate map. In graph-v3,
`graph_taxonomy` rows of `taxonomy_type` in ('edge_predicate','claim_predicate') carry
`direction` and `inverse_of_id` columns — read those first instead of guessing:

```sql
SELECT slug, direction, status,
       (SELECT slug FROM graph_taxonomy inv WHERE inv.id = gt.inverse_of_id) AS inverse_slug,
       metadata->>'canonical_slug' AS canonical
FROM graph_taxonomy gt
WHERE taxonomy_type IN ('edge_predicate','claim_predicate')
ORDER BY status, slug
LIMIT 300;
```

Recommended classes:

- `symmetric`: direction does not change meaning. Current canonical allowlist: `competes_with`, `partners_with`, `mentioned_with`. Variants like `rivals`, `rival_of`, `competing_with`, `collaborates_with`, and `co_mentioned_with` must be canonicalized first, then handled through the allowlist.
- `directed`: subject/object roles matter (`supplies`, `owns`, `acquires`, `leads_over`, `outperforms`).
- `inverse_pair`: two predicates represent opposite directions (`supplies` / `purchases_from`, `owns` / `owned_by`) — modeled via `inverse_of_id`.
- `temporal_event`: may look symmetric but encodes event order or scoped claim text; review manually.
- `unknown`: report only until classified.

For symmetric predicates, duplicate identity should be:

```sql
(predicate_canonical,
 LEAST(subject_node_id, object_node_id),
 GREATEST(subject_node_id, object_node_id),
 optional_scope_key)
```

Do not use raw `(subject_node_id, predicate, object_node_id)` for symmetric idempotency.

## Reverse/symmetric duplicates

Use this after predicate canonicalization to find `A -> B` and `B -> A` pairs for canonical symmetric predicates. Do not auto-merge directional predicates without review.

```sql
WITH symmetric_predicates(predicate) AS (
  VALUES ('competes_with'), ('partners_with'), ('mentioned_with')
), active AS (
  SELECT id, subject_node_id, predicate, object_node_id, truth_probability, learned_at
  FROM graph_assertion
  WHERE assertion_kind = 'relation' AND superseded_at IS NULL
    AND predicate IN (SELECT predicate FROM symmetric_predicates)
), normalized AS (
  SELECT LEAST(subject_node_id, object_node_id) AS node_a,
         GREATEST(subject_node_id, object_node_id) AS node_b,
         predicate,
         COUNT(*) AS n,
         COUNT(*) FILTER (WHERE subject_node_id < object_node_id) AS forward_n,
         COUNT(*) FILTER (WHERE subject_node_id > object_node_id) AS reverse_n,
         ARRAY_AGG(id ORDER BY truth_probability DESC, learned_at DESC) AS assertion_ids
  FROM active
  GROUP BY 1,2,3
)
SELECT n.*, na.name AS node_a_name, nb.name AS node_b_name
FROM normalized n
JOIN graph_node na ON na.id = n.node_a
JOIN graph_node nb ON nb.id = n.node_b
WHERE n.forward_n > 0 AND n.reverse_n > 0
ORDER BY n.n DESC
LIMIT 100;
```

## Predicate drift

Scope to `assertion_kind='relation'` (attribute predicates form a separate vocabulary —
run the same query with `'attribute'` when auditing claims). `fact_kind` is a useful
extra split: `system`/`source_material` predicates are machine vocab, not drift.

```sql
SELECT predicate,
       COUNT(*) AS total,
       COUNT(*) FILTER (WHERE superseded_at IS NULL) AS active,
       ROUND(AVG(truth_probability)::numeric, 3) AS avg_truth,
       MIN(learned_at) AS first_seen,
       MAX(learned_at) AS last_seen
FROM graph_assertion
WHERE assertion_kind = 'relation'
GROUP BY predicate
ORDER BY active DESC, total DESC, predicate;

SELECT predicate, COUNT(*) AS active
FROM graph_assertion
WHERE assertion_kind = 'relation' AND superseded_at IS NULL
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
  SELECT predicate, COUNT(*) c FROM graph_assertion
  WHERE assertion_kind = 'relation' AND superseded_at IS NULL GROUP BY 1
), stemmed AS (
  SELECT predicate, c,
         regexp_replace(
           regexp_replace(predicate, '_(with|to|from|by|in|of|for|on|at)$', ''),
           '(ed|ing|es|s)$', '') AS stem
  FROM active
)
SELECT stem, COUNT(*) AS variants, SUM(c) AS active_assertions,
       ARRAY_AGG(predicate || ':' || c ORDER BY c DESC) AS members
FROM stemmed
GROUP BY stem
HAVING COUNT(*) > 1
ORDER BY active_assertions DESC, variants DESC
LIMIT 100;
```

## Predicate canonicalize + re-collapse preview

Given an explicit, hand-approved `variant -> canonical` map of **same-direction** synonyms only
(exclude inverse pairs like `acquired_by`/`acquires` — those need a subject/object swap in a separate
reviewed script), preview how many rows each rewrite touches and how many duplicate assertions it
will then create for the follow-up collapse to absorb. NOTE: in v3 a predicate rewrite changes the
row's `identity_hash` inputs — the rewrite must recompute `identity_hash` via the writer's hashing
code (or supersede+reinsert through the writer), never a bare `SET predicate = ...`, or the
active-identity unique index no longer guards the row.

```sql
WITH pmap(variant, canonical) AS (
  VALUES ('benefits','benefits_from'), ('drives','drives_demand_for'),
         ('partnered_with','partners_with'), ('developing','develops'),
         ('invested_in','invests_in'), ('collaborates','collaborates_with')
), rewrite AS (
  SELECT ga.id, ga.subject_node_id, m.canonical AS new_predicate, ga.object_node_id
  FROM graph_assertion ga JOIN pmap m ON ga.predicate = m.variant
  WHERE ga.assertion_kind = 'relation' AND ga.superseded_at IS NULL
)
SELECT
  (SELECT COUNT(*) FROM rewrite) AS rows_to_rewrite,
  (SELECT COUNT(*) FROM (
     SELECT subject_node_id, new_predicate, object_node_id FROM (
       SELECT subject_node_id, new_predicate, object_node_id FROM rewrite
       UNION ALL
       SELECT ga.subject_node_id, ga.predicate, ga.object_node_id
       FROM graph_assertion ga JOIN pmap m ON ga.predicate = m.canonical
       WHERE ga.assertion_kind = 'relation' AND ga.superseded_at IS NULL
     ) u
     GROUP BY 1,2,3 HAVING COUNT(*) > 1
   ) dup) AS new_duplicate_clusters;
```

Apply order: (1) rewrite variant rows via the maintenance framework (`graph_request` +
`graph_mutation`, `reason_code='predicate_canonicalize'`), recomputing `identity_hash`; (2) run the
**Safe supersede preview** collapse below to absorb the duplicates the rewrite created; (3) re-run
the **Predicate drift** / vocabulary query and confirm the singleton tail shrank; (4) persist the
approved map into `graph_taxonomy` (next section) so ingestion folds the variants going forward.

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

Wrap in a `graph_request` + `graph_mutation` trail. Check the dashboard's
`graph-valence.ts` / `graph-predicate-class.ts` know each canonical target (unknown → neutral/blank
in the UI) and list any new canonicals for the dashboard maps (U-channel).

## Co-occurrence noise

Feeds the SKILL's **Co-occurrence & low-signal noise pass**. Since F0216, new co-occurrence
relations arrive tagged `additional_data.signal_class='co_occurrence'` — an untagged backlog implies
pre-F0216 rows or an environment running old code. Adjust the `lowsig` predicate list per
graph. Step 1 — measure the noise footprint, support, and whether a `signal_class` tag already exists:

```sql
WITH lowsig(predicate) AS (VALUES ('mentioned_with'),('co_mentioned_with'),('related_to'),('interacts_with'))
SELECT
  count(*) AS lowsig_assertions,
  count(*) FILTER (WHERE superseded_at IS NULL) AS active_lowsig,
  (SELECT count(*) FROM graph_assertion WHERE assertion_kind = 'relation' AND superseded_at IS NULL) AS total_active,
  round(100.0 * count(*) FILTER (WHERE superseded_at IS NULL)
        / NULLIF((SELECT count(*) FROM graph_assertion WHERE assertion_kind = 'relation' AND superseded_at IS NULL),0), 1) AS pct_of_active,
  round(avg(support_count) FILTER (WHERE superseded_at IS NULL)::numeric,2) AS avg_support,
  round(avg(truth_probability) FILTER (WHERE superseded_at IS NULL)::numeric,3) AS avg_truth,
  count(*) FILTER (WHERE superseded_at IS NULL AND additional_data ? 'signal_class') AS already_tagged
FROM graph_assertion
WHERE assertion_kind = 'relation' AND predicate IN (SELECT predicate FROM lowsig);
```

Step 2 — redundancy ratio (decides prune vs tag). How many low-signal unordered pairs also have a
real causal relation (co-occurrence is redundant there) vs. are co-occurrence-**only** (pruning is lossy):

```sql
WITH lowsig(predicate) AS (VALUES ('mentioned_with'),('co_mentioned_with'),('related_to'),('interacts_with')),
mw AS (
  SELECT DISTINCT least(subject_node_id,object_node_id) a, greatest(subject_node_id,object_node_id) b
  FROM graph_assertion WHERE assertion_kind = 'relation' AND superseded_at IS NULL
    AND predicate IN (SELECT predicate FROM lowsig)
),
causal AS (
  SELECT DISTINCT least(subject_node_id,object_node_id) a, greatest(subject_node_id,object_node_id) b
  FROM graph_assertion WHERE assertion_kind = 'relation' AND superseded_at IS NULL
    AND predicate NOT IN (SELECT predicate FROM lowsig)
)
SELECT (SELECT count(*) FROM mw) AS lowsig_pairs,
       (SELECT count(*) FROM mw JOIN causal USING (a,b)) AS pairs_with_causal_backbone,
       (SELECT count(*) FROM mw) - (SELECT count(*) FROM mw JOIN causal USING (a,b)) AS cooccurrence_only_pairs;
```

Safe TAG_SIGNAL_CLASS apply (reversible, no topology change — mutation before/after covers `additional_data`):

```sql
-- preview count, then apply through the maintenance framework (graph_request + graph_mutation)
UPDATE graph_assertion
SET additional_data = COALESCE(additional_data,'{}'::jsonb) || jsonb_build_object('signal_class','co_occurrence'),
    updated_at = now()
WHERE assertion_kind = 'relation' AND superseded_at IS NULL
  AND predicate IN ('mentioned_with','co_mentioned_with','related_to','interacts_with')
  AND (additional_data->>'signal_class') IS DISTINCT FROM 'co_occurrence';
```

Gated PRUNE_REDUNDANT_COOCCURRENCE preview — only co-occurrence relations whose pair already has a
causal relation (never the co-occurrence-only tail). Review, then supersede with
`reason_code='cooccurrence_redundant'`:

```sql
WITH lowsig(predicate) AS (VALUES ('mentioned_with'),('co_mentioned_with'),('related_to'),('interacts_with')),
causal AS (
  SELECT DISTINCT least(subject_node_id,object_node_id) a, greatest(subject_node_id,object_node_id) b
  FROM graph_assertion WHERE assertion_kind = 'relation' AND superseded_at IS NULL
    AND predicate NOT IN (SELECT predicate FROM lowsig)
)
SELECT ga.id, ga.subject_node_id, ga.predicate, ga.object_node_id, ga.support_count, ga.truth_probability
FROM graph_assertion ga
JOIN causal c ON c.a = least(ga.subject_node_id,ga.object_node_id)
             AND c.b = greatest(ga.subject_node_id,ga.object_node_id)
WHERE ga.assertion_kind = 'relation' AND ga.superseded_at IS NULL
  AND ga.predicate IN (SELECT predicate FROM lowsig)
ORDER BY ga.support_count, ga.truth_probability
LIMIT 100;
```

## Alias contamination & false merges

`graph_node.aliases` is `jsonb` — expand with `jsonb_array_elements_text`. Find alias strings
shared across more than one active node. Then judge each: same real-world thing (→ merge) vs. one
node carrying another's name by a bad auto-merge (→ REMOVE_ALIAS / UNMERGE).

```sql
WITH ex AS (
  SELECT n.id, n.node_type, n.canonical_key, n.ticker, n.name, TRIM(a) AS alias
  FROM graph_node n, jsonb_array_elements_text(n.aliases) a
  WHERE n.merged_into_id IS NULL
)
SELECT alias,
       COUNT(DISTINCT id) AS on_n_nodes,
       ARRAY_AGG(DISTINCT node_type) AS node_types,
       COUNT(*) FILTER (WHERE ticker IS NOT NULL) AS on_tickered_nodes,
       (ARRAY_AGG(COALESCE(canonical_key,'∅') || '::' || name ORDER BY canonical_key))[1:8] AS sample_nodes
FROM ex
WHERE LENGTH(alias) >= 3
GROUP BY alias
HAVING COUNT(DISTINCT id) > 1
ORDER BY on_tickered_nodes DESC, on_n_nodes DESC
LIMIT 60;
```

High-precision contamination: an alias that is the *name/ticker of one ticker'd company* but sits on a
*different* ticker'd company. Also surface garbage aliases and cross-company false merges:

```sql
-- garbage aliases on active nodes
SELECT id, name, aliases FROM graph_node
WHERE merged_into_id IS NULL
  AND EXISTS (SELECT 1 FROM jsonb_array_elements_text(aliases) a
              WHERE TRIM(a) IN ('N/A','n/a','','-') OR TRIM(a) ~ '^[0-9]+$')
LIMIT 100;

-- false merges: a merged row whose survivor has a different canonical_key (two distinct companies fused)
SELECT child.id AS merged_id, child.name AS merged_name, child.canonical_key AS merged_key,
       surv.id AS survivor_id, surv.name AS survivor_name, surv.ticker AS survivor_ticker
FROM graph_node child
JOIN graph_node surv ON surv.id = child.merged_into_id
WHERE child.node_type = 'company' AND surv.node_type = 'company'
  AND child.canonical_key IS DISTINCT FROM surv.canonical_key
ORDER BY surv.name
LIMIT 100;
```

Safe REMOVE_ALIAS apply (array edit, fully audited — does not touch assertions/evidence):

```sql
-- preview: strip contaminating aliases from one node
SELECT id, name, aliases,
       (SELECT jsonb_agg(a) FROM jsonb_array_elements_text(aliases) a
        WHERE TRIM(a) NOT IN ('Samsung','Samsung Electronics')) AS aliases_after
FROM graph_node WHERE id = :node_id;
```

UNMERGE is NOT a simple query — re-homing the merged node's assertions/evidence needs per-row
provenance that usually isn't recoverable; treat it as a reviewed, dry-run-first migration, not bulk
cleanup.

Before ANY node merge/quarantine, check for user-authored notes (they must be repointed to the
survivor, and a noted node should not be silently quarantined). `graph_note` keys `node_id` in v3:

```sql
SELECT gn.node_id, n.name, count(*) AS notes
FROM graph_note gn JOIN graph_node n ON n.id = gn.node_id
WHERE gn.status = 'active' AND gn.node_id = ANY(:candidate_ids)
GROUP BY 1, 2;

-- on merge: UPDATE graph_note SET node_id = :survivor_id, updated_at = now()
--           WHERE node_id = :loser_id;  -- audited like every other repoint
```

## Node name hygiene

Feeds the SKILL's **Entity name hygiene pass**. Two problems: opaque identifier-names and
ticker-as-name.

Opaque identifier-names (`PROD_MACRO_STORY:<UUID>`, bare UUIDs, `name = canonical_key` where the key
is an opaque `<key>:<uuid>`), joined to any readable twin sharing the same UUID:

```sql
WITH opaque AS (
  SELECT id, node_type, name, ticker, canonical_key, aliases
  FROM graph_node
  WHERE merged_into_id IS NULL
    AND (
      name ~ '^[A-Za-z_]+:[0-9a-fA-F-]{36}$'                                  -- <KEY>:<uuid>
      OR name ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'  -- bare uuid
      OR name = canonical_key AND canonical_key ~ '^[A-Za-z_]+:[0-9a-fA-F-]{36}$'
    )
)
SELECT o.*,
       -- readable twin: another active node whose canonical_key holds the same uuid
       (SELECT jsonb_agg(jsonb_build_object('id', t.id, 'node_type', t.node_type, 'name', t.name))
        FROM graph_node t
        WHERE t.merged_into_id IS NULL AND t.id <> o.id
          AND lower(substring(t.canonical_key from '[0-9a-fA-F-]{36}'))
            = lower(substring(o.canonical_key from '[0-9a-fA-F-]{36}'))) AS readable_twins,
       (SELECT count(*) FROM graph_assertion a
        WHERE a.superseded_at IS NULL
          AND (a.subject_node_id = o.id OR a.object_node_id = o.id)) AS active_assertions
FROM opaque o
ORDER BY active_assertions DESC
LIMIT 200;
```

Ticker-as-name companies (the `name` is an exchange symbol, not a real company name — common for
Asian listings `.KS .T .HK .SS .SZ .TW .KQ .SI`):

```sql
SELECT id, node_type, name, ticker, canonical_key, aliases,
       (SELECT count(*) FROM graph_assertion a
        WHERE a.superseded_at IS NULL
          AND (a.subject_node_id = graph_node.id OR a.object_node_id = graph_node.id)) AS active_assertions
FROM graph_node
WHERE merged_into_id IS NULL
  AND node_type = 'company'
  AND (
    (ticker IS NOT NULL AND name = ticker)
    OR name ~ '^[0-9A-Z]{1,6}\.[A-Z]{1,4}$'   -- 005930.KS, 6758.T, 0700.HK, 600519.SS, 2330.TW
  )
ORDER BY active_assertions DESC
LIMIT 200;
```

Safe RELABEL_NODE apply (edits only `name`/`aliases`/`ticker`; no assertions/evidence move —
mutation before/after covers the change). Preview one node, then apply through the maintenance
framework (`reason_code='entity_relabel'`):

```sql
-- :new_name and :new_ticker come from the reasoning model's verdict, never from a heuristic.
-- Old name is appended to aliases (deduped) so the ticker/opaque key still resolves in search.
SELECT id, name AS old_name, ticker AS old_ticker,
       :new_name AS new_name,
       (SELECT jsonb_agg(DISTINCT a)
        FROM jsonb_array_elements_text(COALESCE(aliases,'[]'::jsonb) || to_jsonb(name)) a) AS aliases_after
FROM graph_node WHERE id = :node_id;
```

## Non-entity & mistyped nodes

Feeds the SKILL's **Non-entity & mistyped node pass**. Non-entity literals (numbers/money/units
captured as nodes) and their assertion/provenance footprint — decides salvage vs quarantine.
(No `graph_quant` in v3: numeric facts live as `assertion_kind='attribute'` rows with
`structured_fact` / `object_literal`.)

```sql
WITH junk AS (
  SELECT id, name, node_type FROM graph_node
  WHERE merged_into_id IS NULL
    AND ( name ~ '^\$?[0-9][0-9.,]*\s*(bn|billion|m|million|k|B|M|K|T|%|x)?$'   -- 400, 1.3, 100B, 35%
          OR name ~ '^[^A-Za-z]+$' )                                             -- no letters at all
)
SELECT j.id, j.name, j.node_type,
  (SELECT count(*) FROM graph_assertion a WHERE (a.subject_node_id=j.id OR a.object_node_id=j.id)) AS total_assertions,
  (SELECT count(*) FROM graph_assertion a WHERE a.superseded_at IS NULL AND (a.subject_node_id=j.id OR a.object_node_id=j.id)) AS active_assertions,
  (SELECT count(*) FROM graph_evidence ev
     WHERE ev.assertion_id IN (SELECT id FROM graph_assertion a
                               WHERE a.subject_node_id=j.id OR a.object_node_id=j.id)) AS provenance_records
FROM junk j
ORDER BY active_assertions DESC, total_assertions DESC
LIMIT 200;
```

Mistyped `company` nodes that read like a narrative/headline/theme (candidates for RETYPE — always
model-adjudicated, this is only a pre-filter):

```sql
SELECT id, name,
  (SELECT count(*) FROM graph_assertion a WHERE a.superseded_at IS NULL AND (a.subject_node_id=graph_node.id OR a.object_node_id=graph_node.id)) AS active_assertions
FROM graph_node
WHERE merged_into_id IS NULL AND node_type='company'
  AND name ~ '\s'                                   -- multi-word
  AND ( length(name) > 35 OR name ~ '\y(and|of|the|for|ahead|amid|after|as)\y' )  -- sentence-like
  AND name !~ '(Inc|Corp|Ltd|LLC|Group|Holdings|Co|PLC|AG|SA|NV|Technologies|Systems|Motors?|Energy|Semiconductor)\.?$'
ORDER BY active_assertions DESC
LIMIT 200;
```

Safe RETYPE_NODE apply. CAUTION: in v3 `node_type` participates in
`uq_graph_node_type_canonical_key` AND the composite FK from `graph_event(node_id, node_type)` —
retyping an `event` node (or retyping INTO `event`) is not a one-column edit; treat those as
migrations. For plain entity retypes:

```sql
-- :correct_type from the reasoning model (theme_situation|person|sector|macro_indicator|...)
UPDATE graph_node SET node_type = :correct_type, updated_at = now() WHERE id = :node_id;
-- apply through the maintenance framework (reason_code='entity_retype')
```

Safe QUARANTINE_NODE apply (no `is_active` column → flag in `additional_data`, and supersede the
node's noise assertions). Apply ONLY to nodes with zero active meaning-bearing assertions, after salvage:

```sql
-- flag the node (reversible)
UPDATE graph_node
SET additional_data = COALESCE(additional_data,'{}'::jsonb)
      || jsonb_build_object('quarantined', true, 'quarantine_reason', :reason, 'quarantined_by','ts-graph-dream'),
    updated_at = now()
WHERE id = ANY(:junk_ids);

-- supersede its remaining (noise) assertions so they stop rendering / counting
UPDATE graph_assertion SET superseded_at = now(), updated_at = now()
WHERE superseded_at IS NULL AND (subject_node_id = ANY(:junk_ids) OR object_node_id = ANY(:junk_ids));
-- both applied through the maintenance framework (reason_code='non_entity_quarantine')
```

The dashboard graph query must then exclude quarantined nodes
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
SELECT lower(regexp_replace(gn.name,'[^a-zA-Z ]','','g')) AS concept,
       gn.id, gn.node_type, gn.name, gn.canonical_key,
  (SELECT count(*) FROM graph_assertion a WHERE a.superseded_at IS NULL
     AND (a.subject_node_id=gn.id OR a.object_node_id=gn.id)) AS active_assertions
FROM graph_node gn
WHERE gn.merged_into_id IS NULL
  AND lower(gn.name) IN (SELECT name FROM geo)
ORDER BY concept, active_assertions DESC;
```

Per-conflated-node assertion dump (feed to the model to assign each assertion a sense —
geopolitical actor vs place/market). `:node_id` is one candidate:

```sql
SELECT a.id AS assertion_id, a.predicate,
  CASE WHEN a.subject_node_id = :node_id THEN 'out' ELSE 'in' END AS dir,
  other.name AS counterpart, other.node_type AS counterpart_type,
  a.assertion_text
FROM graph_assertion a
JOIN graph_node other ON other.id = CASE WHEN a.subject_node_id = :node_id THEN a.object_node_id ELSE a.subject_node_id END
WHERE a.assertion_kind = 'relation' AND a.superseded_at IS NULL
  AND (a.subject_node_id = :node_id OR a.object_node_id = :node_id)
ORDER BY a.predicate;
```

Safe RETYPE to a geo type (single-sense). Beware `(node_type, canonical_key)` uniqueness — if the
target already exists, it's a MERGE, not a retype:

```sql
UPDATE graph_node SET node_type = :geo_type, updated_at = now() WHERE id = :node_id;  -- geopolitical | location
-- apply through the maintenance framework (reason_code='geo_retype')
```

SPLIT preview + apply (conflated node kept as dominant sense; minority-sense assertions repointed to
a new sibling node). Create the sibling with a sense-suffixed canonical_key to dodge the unique
index. NOTE: repointing changes each assertion's `identity_hash` inputs — recompute the hash via the
writer's hashing code as part of the repoint, and repoint `graph_evidence` implicitly (it keys
`assertion_id`, so it follows the assertion):

```sql
-- 1. create the minority-sense sibling (once), reusing the original's name/aliases
INSERT INTO graph_node (id, node_type, canonical_key, name, aliases, scope, additional_data, created_at, updated_at)
SELECT gen_random_uuid()::text, :minority_type, canonical_key || ':' || :minority_type, name, aliases, scope,
       jsonb_build_object('split_from', id, 'sense', :minority_type), now(), now()
FROM graph_node WHERE id = :orig_id
RETURNING id;   -- :sibling_id

-- 2. repoint the model-chosen minority-sense assertions (by explicit id list), audited per row
UPDATE graph_assertion SET subject_node_id = :sibling_id, updated_at = now()
WHERE id = ANY(:minority_assertion_ids) AND subject_node_id = :orig_id;
UPDATE graph_assertion SET object_node_id  = :sibling_id, updated_at = now()
WHERE id = ANY(:minority_assertion_ids) AND object_node_id  = :orig_id;
-- apply through the maintenance framework (reason_code='geo_sense_split'); recompute identity_hash
```

## Uninterpretable quants — RETIRED

`graph_quant` was decommissioned in 2026-07 (FMP is the financials source) and the table does not
exist in graph-v3 production; numeric facts now live as `assertion_kind='attribute'` assertions with
`structured_fact`. There is no v3 equivalent of the generic-fallback-metric cleanup. If
`to_regclass('graph_quant')` is ever non-NULL, you are not on canonical production.

## Node fragmentation

```sql
SELECT ticker, COUNT(*) AS nodes, ARRAY_AGG(id || ':' || name ORDER BY created_at) AS ids
FROM graph_node
WHERE ticker IS NOT NULL AND ticker <> ''
GROUP BY ticker
HAVING COUNT(*) > 1
ORDER BY nodes DESC, ticker;

-- canonical_key is unique per node_type in v3, so exact-key duplicates can only exist
-- ACROSS node types (the interesting fragmentation case) or with NULL keys.
SELECT canonical_key, COUNT(*) AS nodes,
       ARRAY_AGG(node_type || '/' || id || ':' || name ORDER BY created_at) AS ids
FROM graph_node
WHERE canonical_key IS NOT NULL
GROUP BY canonical_key
HAVING COUNT(*) > 1
ORDER BY nodes DESC, canonical_key
LIMIT 100;
```

## Ingestion temp entities (R0053 — resolve/merge forward, not contamination)

The graph-ingestion writer marks unresolved model-proposed placeholder nodes with
`additional_data->>'origin' = 'ingestion_temp_entity'` plus `additional_data->>'source_record_id'`.
These are expected-transient and should be prioritized for reconciliation/merge into their canonical
node — they are NOT contamination and NOT false-merge candidates.

```sql
SELECT
  n.id,
  n.name,
  n.ticker,
  n.additional_data->>'source_record_id' AS source_record_id,
  n.created_at,
  n.merged_into_id
FROM graph_node n
WHERE n.additional_data->>'origin' = 'ingestion_temp_entity'
  AND n.merged_into_id IS NULL   -- still unresolved: candidates for merge-forward
ORDER BY n.created_at DESC
LIMIT 200;
```

## Provenance and import-family health

v3 provenance chain: `graph_evidence` (assertion×record) → `graph_origin` (derivation family) and
`graph_source` (publisher). `graph_event_record` links events to records by phase.

```sql
-- import/derivation family footprint (replaces the graph_document capture_path rollup)
SELECT go.derivation_kind,
       COUNT(*) AS origins,
       (SELECT count(*) FROM graph_evidence ev WHERE ev.origin_id IN
          (SELECT id FROM graph_origin g2 WHERE g2.derivation_kind = go.derivation_kind)) AS evidence_rows
FROM graph_origin go
GROUP BY 1
ORDER BY evidence_rows DESC;

-- assertions with outsized evidence fan-in (replaces the graph_mention rollup)
SELECT ev.assertion_id, COUNT(*) AS evidence_rows,
       COUNT(DISTINCT ev.origin_id) AS origins,
       COUNT(DISTINCT ev.record_id) AS source_records,
       COUNT(DISTINCT ev.publisher_source_id) AS publishers
FROM graph_evidence ev
GROUP BY 1
HAVING COUNT(*) > 10
ORDER BY evidence_rows DESC
LIMIT 100;
```

## Maintenance/audit trail health (graph_request + graph_mutation)

```sql
SELECT request_kind, status, COUNT(*) AS n, MAX(created_at) AS latest
FROM graph_request
GROUP BY 1,2
ORDER BY 1,2;

SELECT reason_code, target_table, operation, COUNT(*) AS mutations, MAX(created_at) AS latest
FROM graph_mutation
GROUP BY 1,2,3
ORDER BY mutations DESC
LIMIT 50;
```

## Safe supersede preview pattern

Preview first. Pick one canonical survivor per duplicate cluster using project-specific rules.

```sql
WITH duplicate_clusters AS (
  SELECT subject_node_id, predicate, object_node_id,
         ARRAY_AGG(id ORDER BY support_count DESC, truth_probability DESC, learned_at DESC, updated_at DESC) AS ordered_ids
  FROM graph_assertion
  WHERE assertion_kind = 'relation' AND superseded_at IS NULL
  GROUP BY subject_node_id, predicate, object_node_id
  HAVING COUNT(*) > 1
), planned AS (
  SELECT ordered_ids[1] AS survivor_id, unnest(ordered_ids[2:]) AS supersede_id
  FROM duplicate_clusters
)
SELECT p.*, ga.assertion_text, ga.truth_probability, ga.support_count
FROM planned p
JOIN graph_assertion ga ON ga.id = p.supersede_id
ORDER BY p.survivor_id
LIMIT 100;
```

For an apply, go through `src/graph/maintenance_v3.py` / the `ts-graph-maintenance` skill: proposals
with exact `before` snapshots, `record_decision` into `graph_request`, `FOR UPDATE` stale checks,
`superseded_at`/`superseded_by_assertion_id` updates, and `graph_mutation` rows. Set
`superseded_by_assertion_id` to the survivor so lineage is queryable. Do not paste credentials into
logs.


## Symmetric-predicate durable fix outline

If the system should prevent recurrence, propose one of these code/schema fixes separately from cleanup:

1. In importer/write code, canonicalize symmetric predicates before hashing/upsert:
   - map predicate synonyms to a canonical predicate (durably via `graph_taxonomy` canonical_slug rows);
   - sort endpoint node IDs for symmetric predicates;
   - compute `identity_hash` from normalized predicate + normalized endpoints + scope, not generated assertion text.
2. Lean on the existing DB guard: `uq_graph_assertion_active_identity_hash` already enforces one
   active row per identity — the fix is making symmetric/synonym variants hash to the same identity.
   Validate with a read-only production plan, transaction rollback, and a narrowly scoped production
   canary before broad apply.
3. Keep `graph_evidence` rows as per-source evidence and aggregate `support_count`; do not duplicate
   assertion rows for every source.
4. In the dashboard, display symmetric relations as `A ↔ B competes_with` or omit arrow semantics in
   the inspector.

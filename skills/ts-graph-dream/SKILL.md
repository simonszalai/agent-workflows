---
name: ts-graph-dream
description: Whole-system knowledge graph consolidation for ts-graph style databases. Use when asked to audit, clean, deduplicate, canonicalize, or "dream" over graph data; investigate duplicate graph_edge rows, predicate explosion, co-occurrence / mentioned_with noise edges dominating the graph or viz layout, low-signal predicate pruning, entity aliases/merges, stale/superseded graph assertions, graph maintenance runs, Grok/import backfill contamination, or graph dashboard inspector noise. Produces evidence-bound cleanup plans and can apply safe audited graph_* mutations only when explicitly approved.
---

# TS Graph Dream

`ts-graph-dream` is the graph-data analogue of `deep-dream`: it audits a knowledge graph for duplicate assertions, predicate drift, entity fragmentation, stale rows, and bad importer patterns, then proposes safe consolidation actions.

Default stance: **read-only report first**. Mutate only after explicit user approval or an explicit apply request.

## Safety rules

1. **Never hard-delete graph rows.** Use `superseded_at`, `merged_into_id`, `is_active=false`, `status=inactive`, and `graph_audit` / `graph_maintenance_*` records.
2. **Preserve provenance and user annotations.** Do not orphan `graph_mention`, `graph_document`, `llm_stat_id`, source rows, quotes, or source_record links. Duplicates may be real independent evidence. `graph_note` rows are **user-authored** notes keyed to `graph_entity.id`: an entity MERGE must repoint its notes to the survivor, and never quarantine an entity that carries active notes without surfacing them to the user first.
3. **Separate duplicate assertion from duplicate evidence.** Collapse repeated claims/edges only when they assert the same semantic fact. Keep or aggregate multiple source mentions.
4. **Production mutation needs an explicit go-ahead.** If the DB looks production-like, stop after the plan unless the user clearly asked to apply there.
5. **Dry-run all SQL first.** Every mutation plan must show expected row counts and sample IDs before changing data.
6. **Use transactions and audit rows.** Mutations must be reversible by evidence, with `graph_audit.before/after` and a `graph_maintenance_run` / `graph_maintenance_change` trail when available.
7. **No schema changes unless requested.** If a durable fix needs constraints, generated columns, or importer code changes, propose it separately from data cleanup.
8. **Respect predicate directionality.** Treat every predicate as directed unless it is explicitly classified as symmetric in the ts-graph contract (`competes_with`, `partners_with`, `mentioned_with`) or has a declared inverse. Canonicalize variants (`rivals` -> `competes_with`, `collaborates_with` -> `partners_with`, `co_mentioned_with` -> `mentioned_with`) before duplicate checks. Symmetric predicates should use an unordered entity pair for duplicate detection and ingestion idempotency.
9. **A shared alias is ambiguous — never treat it as an automatic merge signal.** Two entities sharing an alias means EITHER they are the same thing fragmented (→ merge) OR one entity has absorbed another's name as a bad alias / bad auto-merge (→ remove alias / unmerge). Distinguish before acting. High-precision contamination rule: a ticker'd company must NOT carry a *different* ticker'd company's name or ticker as an alias, and a single entity must NOT fuse two distinct tickers. Removing a contaminating alias (editing the `aliases` array with a before/after audit) is low-risk. **Unmerging** a bad `merged_into_id` is high-risk — it requires re-homing edges/mentions to the correct entity and usually cannot be done from provenance alone; propose it, dry-run it, and get explicit approval, never bulk-apply.
10. **Co-occurrence noise is low-signal, not wrong — down-weight/tag before you prune.** Pure co-occurrence predicates (`mentioned_with`, `co_mentioned_with`, and often `related_to`, `interacts_with`) assert only "these two were named in the same document" — no causal/semantic direction — yet they routinely outnumber every real predicate and dominate the force-layout hairball and node `degree`. They are still weak evidence, and in practice most co-occurrence pairs are the *only* edge between those two entities (measure it — see the co-occurrence pass), so hard-pruning them silently deletes the sole link for a pair and loses information. Default to the reversible, non-destructive lever: **tag** each as `additional_data.signal_class='co_occurrence'` and/or **down-weight** it (so it no longer drives degree/layout), letting the dashboard cheaply filter it out. Only **supersede** (prune) the redundant subset — a co-occurrence edge between a pair that *already* has a real causal edge — and only **collapse** (merge to one weighted survivor, `support_count = Σ`) genuine duplicate co-occurrence edges for the same unordered pair. Never bulk-delete the co-occurrence-only tail without explicit approval.

## System contract — how the graph is populated and consumed (read first)

Every dream run must reason against the *current* producer and consumer, not the historical ones.
Verify the following before proposing anything (they were true as of 2026-07-03; re-check quickly):

**Population (ts-prefect `src/graph/`).** Edges/claims come only from the two-pass LLM assimilator
(`assimilate_record` → entities → assertions → `write_assimilation`). Since **F0216** (PR #526/#527,
merged to ts-prefect `main` **and** `staging` 2026-07-02), ingestion is hardened at write time:

- **Predicate canonicalization at write:** `canonicalize_predicate()` folds synonym variants using an
  in-code map PLUS a **DB-backed override map from `graph_taxonomy`** (`taxonomy_type IN
  ('edge_predicate','claim_predicate')`, `status='active'`, `slug`=variant,
  `metadata->>'canonical_slug'`=canonical). Extending the vocabulary is therefore **data work this
  skill can do** (insert taxonomy rows), not a code proposal.
- **Edge identity no longer includes edge_text:** edge `content_hash = hash(subject, canonical
  predicate, object)`; symmetric predicates get unordered endpoints
  (`additional_data.endpoints_were_reordered`), and every edge stores
  `additional_data.predicate_direction`. Rephrased triples no longer mint duplicate edges — duplicate
  collapse is now a *legacy backlog* problem, not a recurring one.
- **Co-occurrence tagged at write:** `mentioned_with`-family edges get
  `additional_data.signal_class='co_occurrence'`, and the extraction prompt injects the canonical
  vocabulary and forbids co-occurrence edges between entities with a real relationship. A hardcoded
  fallback still seeds one `mentioned_with` edge when the LLM yields none (it arrives tagged).
- **Entity guards:** numeric/low-information names are quarantined at insert
  (`should_quarantine_entity_name`), garbage aliases (`N/A`, empty, none/null) are sanitized, and a
  cross-ticker conflict guard blocks auto-merging two distinct ticker'd companies.

Consequence: **before proposing any I-channel (importer) fix, check whether F0216 already implements
it and whether the code is deployed to the environment you're cleaning.** Findings in old rows may
predate the guard — then the action is a one-time historical cleanup, with no recurrence work needed.
Still open upstream (verify before re-proposing): company `name` populated from the security master
(ticker-as-name keeps re-accumulating), and geo `geopolitical`/`location` typing at extraction.

**Node-type taxonomy (R0042 final, 9 types — 2026-07).** `company, person, organization, event,
topic, geopolitical, government, facility, location`. Legacy `theme_situation`/`macro_indicator`/
`sector` are being backfilled away and must never be re-proposed as retype targets. The governing
rule is **type by identity, never by narrative role**: `node_type` says what the thing IS; what it
is doing in a story lives in claims/edges; hierarchy lives in `entity_subtype` + edges (`unit_of`,
`owned_by`), never in the type. Key conventions: named built installations (fabs, plants, data
centers, pipelines, refineries) → `facility` (vs natural/geographic → `location`); a jurisdiction
name denotes TWO entities — the territory (`location`, plain key) and the polity (`government` for
sub-nationals with keys like `texas state government`, `geopolitical` for sovereigns/blocs); named
state machinery (regulators, ministries, courts, administrations) → `government`, only the
sovereign/bloc actor itself → `geopolitical`; corporate divisions/research arms resolve to the
PARENT company as aliases (only quasi-independent units get their own `company` node with a
`unit_of` edge); exchanges-as-institutions, SWFs, parties, and non-state armed groups →
`organization` with a descriptive subtype. Canonical statement of these rules:
`GRAPH_ENTITY_EXTRACTION_RULES` in ts-prefect `src/graph/assimilate.py`; the maintenance engine's
set is `GRAPH_NODE_TYPES` in `src/graph/maintenance.py`.

**Consumption (ts-dashboard `app/models/graph.server.ts`, `app/routes/(dashboard)/graph.tsx`).**
The /graph map renders **`graph_edge` only** (claims/documents/notes never draw as edges):

- Active view filters `superseded_at IS NULL`; superseding an edge removes it from the default map.
- The query **excludes quarantined endpoints** (`additional_data->>'quarantined' IS DISTINCT FROM
  'true'` on subject and object) — quarantine flags are honoured, but only via this filter.
- **`merged_into_id` is NOT filtered.** A merged loser still renders if it retains active edges — an
  entity MERGE must repoint or supersede *every* loser edge or the ghost node stays on the map.
- **Degree, node size, force layout, and Louvain clustering count every rendered edge** (no
  predicate/signal_class exception unless the dashboard filter is on). Superseding or repointing
  edges reshuffles clusters; that is expected, not a bug.
- Edge coloring/classification is keyed on the **normalized predicate string**: `graph-valence.ts`
  (beneficial/adversarial/neutral; unknown → neutral) and `graph-predicate-class.ts` (supply/
  competition/ownership/regulation/driver/partnership glyphs). **Canonicalizing a predicate changes
  its UI valence/class — prefer canonical targets that already exist in those maps, and flag ones
  that don't.**
- Search ILIKEs `name`, `ticker`, `canonical_key`, `predicate`, `edge_text` — **not `aliases`**. A
  RELABEL that moves the old searchable name into `aliases` makes it invisible to map search; note
  this when relabeling high-traffic entities.
- Node colors/legend include `geopolitical` (red) and `location` (indigo); unknown node_types render
  gray but do display — RETYPE targets should stay within the dashboard's known set. As of the R0042
  9-type taxonomy the dashboard color/legend maps still lack `government` and `facility` (they render
  gray) and still list the legacy `theme_situation`/`macro_indicator`/`sector` entries — update
  `GRAPH_NODE_COLORS` + `NODE_TYPE_LEGEND_ORDER` in `app/routes/(dashboard)/graph.tsx` after the
  backfill applies.
- Cluster labels pick the highest-priority member's `name` (opaque names skipped) — name hygiene
  directly drives label quality.

## Quick workflow

### Phase 0 - Scope and baselines

1. Identify the graph DB and environment:
   - Prefer the current repo `.env` `DATABASE_URL` when the user points at a local/staging dashboard.
   - If linked `ts-prefect` is relevant, inspect importer/backfill code there too.
   - Print only database host/db name, never credentials.
   - **Environments diverge — check both.** Staging (`ts_duoh`) holds the large graph (~9k entities);
     production has had live `graph_*` tables and a running assimilator since the 2026-07 promotion,
     and its schema can differ from staging (e.g. `graph_quant` exists in prod but was dropped from
     staging). Never assume the graph is staging-only, and never assume table parity.
2. Probe which graph tables exist (`to_regclass`), rather than asserting a fixed list: `graph_entity`,
   `graph_edge`, `graph_claim`, `graph_mention`, `graph_document`, `graph_source`, `graph_taxonomy`,
   `graph_note`, `graph_audit`, `graph_maintenance_run`, `graph_maintenance_change`, and (legacy,
   possibly dropped) `graph_quant`. Skip passes whose tables are absent instead of erroring.
3. Record baseline counts: total vs active rows, superseded counts, recent maintenance runs, and imported source families.
4. Check write-time guard deployment for this environment (see the System contract above): does the
   assimilator here canonicalize predicates / tag co-occurrence / quarantine junk names? This decides
   whether each finding is a recurring problem or a one-time historical backlog.
5. If the user named an entity/ticker, scope diagnostics to that node first, then decide whether global cleanup is needed.

### Phase 1 - Evidence gathering

Load `references/diagnostic-queries.md` when writing SQL. Gather compact evidence for:

- **Edge duplicates:** repeated `(subject, predicate, object)` active edges; reverse/symmetric duplicates; same content hashes. Since F0216 the edge `content_hash` is `(subject, canonical predicate, object)` with symmetric endpoints normalized — new writes cannot duplicate, so any nonzero count is either pre-F0216 backlog (one-time collapse) or a writer regression (investigate, don't just clean).
- **Predicate drift (mandatory):** always enumerate the full set of distinct predicate values and their active counts, then cluster them into synonym/variant families (see the **Predicate canonicalization pass** below). Free-text LLM predicates fragment into a long tail of one-off strings (`benefits` vs `benefits_from`, `drives` vs `drives_demand_for`, `partnered_with` vs `partners_with`) that must be collapsed to a canonical predicate.
- **Co-occurrence noise (mandatory to measure, often already resolved):** measure the share of pure co-occurrence predicates (`mentioned_with` and siblings) among active edges, their average `support_count`/`truth_probability`, and — critically — how many of their unordered entity pairs *also* have a real causal edge vs. are co-occurrence-only. This ratio decides the action mix (see the **Co-occurrence & low-signal noise pass**). Check whether edges already carry `additional_data.signal_class` (F0216 writes it) — on staging the historical co-occurrence backlog was bulk-removed in 2026-07 (`reason_code='cooccurrence_removed'`), so a near-zero count means "verify the write-time guard, then move on", not "invent work".
- **Predicate directionality:** classify predicates as directed, symmetric, inverse-paired, temporal/event-scoped, or unknown before consolidation. Inverse pairs (`supplies`/`purchases_from`, `sells_to`/`buys_from`, `owns`/`owned_by`, plus hand-reviewed pairs like `acquires`/`acquired_by`) must never be flat-merged — canonicalizing one onto the other requires swapping subject/object.
- **Entity fragmentation:** same ticker/canonical key/name across several entities; alias overlap; merged_into chains; orphan nodes.
- **Display-name hygiene (mandatory):** entities whose `name` is not a human-readable label — opaque internal identifiers (`PROD_MACRO_STORY:<UUID>`, bare UUIDs, `<KEY>:<uuid>` importer keys) and companies whose `name` is just a **ticker symbol** rather than the real company name (especially Asian listings: `005930.KS`, `6758.T`, `0700.HK`, `600519.SS`, `2330.TW`). These read as garbage in the map, inspector, and cluster labels. See the **Entity name hygiene pass**.
- **Non-entity & mistyped nodes (mandatory):** `company` (or other typed) nodes that are not entities at all — a bare number/money/unit literal (`400`, `1.3`, `100B`, `2.2`) that the extractor captured as an "entity", or nodes typed `company` whose `name` is clearly a **narrative/headline/theme** ("Shutdown Pressure Ahead of Senate Recess"), a person, a sector, or an event. See the **Non-entity & mistyped node pass**.
- **Geopolitical / location nodes (when present):** countries, regions, blocs, and cities (`Iran`, `China`, `United States`, `Middle East`, `Hong Kong`) mis-filed under `company`/`organization`/`sector`/`macro_indicator`, usually **fragmented** across those types and name-variants (`US`/`USA`/`U.S.`/`United States`), and often **conflating two senses** — the state/government actor vs. the country as a place/market. See the **Geopolitical vs location entity pass**.
- **Uninterpretable quants (conditional — only if `graph_quant` exists):** the quant layer was deleted from staging + the dashboard in 2026-07 (~86% garbage; FMP is the financials source). If the environment still has the table and live writers, see the **Legacy quant pass** — the headline finding there is code/schema drift, not row hygiene.
- **Alias contamination & false merges (mandatory):** enumerate alias strings that appear on more than one active entity. For each, decide whether the entities are the same real-world thing (fragmentation → merge) or different things (→ one alias is wrong). Flag as contamination any case where a ticker'd company carries another ticker'd company's name/ticker as an alias, an entity fuses two distinct tickers, or an alias is garbage (`N/A`, empty, a bare number). Also inspect `merged_into_id` targets: a merge whose survivor is a *different* real company than the merged row (e.g. "SK Hynix" merged into "Huawei") is a false merge to unwind. Cite the entity ids and the offending alias/merge.
- **Assertion staleness:** low-confidence rows, contradictions, outdated valid windows, superseded rows still shown as active.
- **Provenance health:** mentions per assertion, duplicate source refs, Grok/import capture paths, source trust tiers.
- **Importer causes:** code paths that inserted edge text/predicates without canonicalization or idempotent upsert.

Every finding must cite SQL counts plus sample IDs or code locators.

### Phase 2 - Candidate actions

Group findings into candidates with stable IDs:

| Code | Channel | Action vocabulary |
|---|---|---|
| E | Edge | SUPERSEDE_DUPLICATES / CANONICALIZE_PREDICATE / MERGE_SYMMETRIC / NORMALIZE_SYMMETRIC_ENDPOINTS / SPLIT_OVERBROAD |
| X | Co-occurrence | TAG_SIGNAL_CLASS / DOWNWEIGHT_COOCCURRENCE / COLLAPSE_COOCCURRENCE / PRUNE_REDUNDANT_COOCCURRENCE |
| N | Entity | MERGE_ENTITY / RESCOPE_ENTITY / ADD_ALIAS / REMOVE_ALIAS / UNMERGE_ENTITY / RETYPE_ENTITY / RELABEL_ENTITY / SPLIT_ENTITY / QUARANTINE_ENTITY |
| C | Claim/Quant | SUPERSEDE_DUPLICATES / UPDATE_VALIDITY / LOWER_CONFIDENCE / FLAG_CONTRADICTION |
| P | Provenance | REPOINT_MENTION / AGGREGATE_SUPPORT / DEACTIVATE_SOURCE / FIX_SOURCE_REF |
| T | Taxonomy/vocab | EXTEND_PREDICATE_VOCAB (insert `graph_taxonomy` variant→canonical rows honoured at write time) / DEPRECATE_PREDICATE |
| I | Importer | ADD_IDEMPOTENCY / ADD_PREDICATE_MAP / ADD_ENTITY_RESOLUTION / STOP_BAD_BACKFILL — **check F0216 first; most of these already exist at write time** |
| U | UI | GROUP_DUPLICATES / HIDE_SUPERSEDED_BY_DEFAULT / SHOW_SOURCE_COUNT |

For each candidate include:

- exact target rows or target pattern;
- before/after semantics;
- expected count changed;
- why provenance is preserved;
- SQL/code diff outline;
- risk and rollback story.

### Phase 3 - Adversarial review

Before applying anything, challenge each candidate:

- Could these rows represent independent corroborating evidence rather than duplicates?
- Is the predicate actually directional, temporal, scoped differently, or only symmetric after canonical predicate mapping?
- Would merging entities combine distinct companies/products/events? Is the shared alias evidence of sameness, or evidence that one entity absorbed the other's name by a bad auto-merge?
- For a REMOVE_ALIAS / UNMERGE: am I sure the alias/merge is wrong and not a legitimate parent/brand relationship (e.g. `AWS` under `AMZN`)? Removing an alias only edits the `aliases` array; unmerging must correctly re-home the merged entity's edges/mentions or it strands them.
- For a co-occurrence prune: is this edge really redundant (the pair has a causal edge), or is it the *only* link for that pair — in which case tag/down-weight, don't delete? Am I destroying topology to fix a *rendering* problem the dashboard should solve by filtering the `signal_class` tag?
- Would superseding hide a useful contradiction?
- Does the importer fix prevent recurrence, or only clean symptoms? Does F0216 already prevent it —
  i.e. is this finding purely pre-F0216 backlog, making the I-channel proposal redundant?
- Is there a DB constraint/index that would be safer than repeated cleanup?
- Does the action's downstream effect match the consumption contract (map ghosting after a partial
  merge, valence/class loss after canonicalizing to an unknown predicate, search loss after a
  relabel)?

Drop or amend any candidate that fails. Bias toward report-only when uncertain.

### Phase 4 - Apply, only when approved

If applying data changes:

1. Create a `graph_maintenance_run` with `dry_run=false`, `run_type='graph_dream'`, `command` containing the user request, and counts initialized.
2. For each action, lock target rows (`FOR UPDATE`) inside a transaction.
3. Update rows by superseding/deactivating/repointing, never deleting.
4. Insert `graph_audit` rows with `actor_type='agent'`, `actor_id='ts-graph-dream'`, and a clear `reason_code`.
5. Insert `graph_maintenance_change` rows linked to the run and audit rows.
6. Re-run the diagnostic queries and compare before/after counts.
7. If changing importer/dashboard code, run the project tests that cover graph server/UI/importer behavior.

If applying code changes only, keep the DB read-only and state that no graph data changed.

### Phase 5 - Report

Final report format:

- Environment and scope.
- Baseline counts.
- Findings by channel with evidence.
- Candidate actions: survived / amended / killed.
- Applied mutations or explicit "no mutations applied".
- Verification queries and results.
- Recurrence prevention: importer fixes, constraints, dashboard grouping, or scheduled maintenance suggestions.

## Predicate canonicalization pass (mandatory)

Every ts-graph-dream run MUST include an explicit predicate-canonicalization pass. Historically the
LLM wrote free-text predicates verbatim, so the vocabulary exploded (staging 2026-07-03: **4,054
distinct predicates over ~10.4k active edges**, a huge singleton tail) — this backlog is the largest
remaining consolidation opportunity. Since F0216, *new* writes are canonicalized through the in-code
synonym map plus `graph_taxonomy` overrides, so the pass has two jobs: (a) rewrite the historical
tail, and (b) **grow the write-time vocabulary** (T-channel `EXTEND_PREDICATE_VOCAB`) so the same
variants never come back. The extraction prompt also now advertises the canonical vocabulary, so a
richer taxonomy directly improves extraction, not just cleanup.

**Step 1 — Enumerate.** List every distinct predicate with its active/total counts and first/last
seen. Report the vocabulary size, the singleton count (predicates used exactly once), and the head
(predicates used ≥20×). A large singleton tail is the signal.

**Step 2 — Cluster synonyms.** Group predicates that assert the same relation. Detect:
  - verb-tense / morphology variants: `partnered_with` → `partners_with`, `developing` → `develops`,
    `acquired` → `acquires`, `invested_in` → `invests_in`;
  - phrasing variants: `benefits` vs `benefits_from`, `drives` vs `drives_demand_for`,
    `collaborates` vs `collaborates_with`, `supplies_to` vs `supplies`, `manufactures` vs `produces`;
  - separators/casing already handled by ingestion, but re-check anyway.
  Pick the highest-count, clearest member of each cluster as the **canonical predicate**. Build an
  explicit map `variant -> canonical` and show it to the user before applying.

**Step 3 — Split by directionality (safety gate).**
  - **Same-direction synonyms** (both members read subject→object the same way): safe to rewrite the
    variant's `predicate` to the canonical value in place.
  - **Inverse pairs** (`acquired_by` is the reverse of `acquires`, `used_by` of `uses`, `led_by` of
    `leads`, `supplied_by` of `supplies`): canonicalizing requires **swapping subject_entity_id and
    object_entity_id** as you rewrite the predicate. Do this only on a hand-reviewed allowlist; never
    bulk-flip. If unsure whether a pair is a true inverse, leave it and report it.
  - **Symmetric predicates** (`competes_with`, `partners_with`, `mentioned_with`): use an unordered
    entity pair for duplicate detection (per safety rule 8); do not treat A→B and B→A as distinct.

**Step 4 — Rewrite (audited).** For each approved same-direction mapping, `UPDATE graph_edge SET
predicate = :canonical` (and `graph_claim` where applicable) on the variant rows, inside a
transaction, writing `graph_audit` (before/after predicate) and `graph_maintenance_change` rows with
`reason_code='predicate_canonicalize'`. Never delete rows.

**Step 5 — Re-collapse.** Canonicalizing predicates CREATES new same-(subject, predicate, object)
duplicates (e.g. an `A benefits B` and an `A benefits_from B` edge become two identical triples).
Immediately re-run the edge duplicate-collapse pass (SUPERSEDE_DUPLICATES: keep one survivor,
repoint mentions, `support_count = Σ`, supersede the rest) so the canonicalization does not leave
redundant edges behind. Re-run Step 1 and confirm the vocabulary shrank and no new duplicate
clusters remain.

**Step 6 — Extend the write-time vocabulary (T-channel, this is data work — do it, don't propose
code).** For every approved `variant -> canonical` mapping, insert a `graph_taxonomy` row that the
F0216 writer loads as an override (`SELECT slug, metadata->>'canonical_slug' FROM graph_taxonomy
WHERE taxonomy_type IN ('edge_predicate','claim_predicate') AND status='active'`):
`taxonomy_type='edge_predicate'`, `slug=<variant>`, `label`, `status='active'`,
`metadata = {"canonical_slug": "<canonical>", "source": "ts-graph-dream", ...}`. Respect the
`(taxonomy_type, slug)` unique constraint (upsert). DB overrides win over the in-code map, and the
writer caches the map per instance — new rows apply on the next writer start. Also mind the UI
contract: a canonical predicate outside the dashboard's valence/class maps renders neutral/blank —
prefer canonical targets already known to `graph-valence.ts` / `graph-predicate-class.ts`, and list
any new canonicals so the dashboard maps can be extended (U-channel).

**Recurrence prevention (already largely done).** Write-time canonicalization + the prompt-injected
vocabulary shipped in F0216 (ts-prefect main + staging, 2026-07-02). Verify it is deployed to the
environment being cleaned; the remaining durable lever is exactly Step 6 (taxonomy data). Only if the
environment runs pre-F0216 code is a code-side proposal warranted — and then it is "promote F0216",
not "build canonicalization".

## Co-occurrence & low-signal noise pass (mandatory to measure — often already clean)

Every ts-graph-dream run MUST measure co-occurrence, but the historical crisis is largely resolved:
the staging backlog (`mentioned_with` was once ~2.2k edges, the largest predicate ~7×) was
bulk-removed in the 2026-07 dream runs, and F0216 now (a) tags any new co-occurrence edge
`additional_data.signal_class='co_occurrence'` at write, and (b) instructs the extractor never to
emit `mentioned_with` between entities with a real relationship (only a fallback seed edge remains,
and it arrives tagged). So the pass is now: **measure → if near zero, verify the write-time guard is
deployed here and stop; if a backlog exists (e.g. an environment running pre-F0216 code), apply the
ladder below.** The original hazard still holds where a backlog exists: undirected co-mention volume
collapses the force layout into a hairball and inflates `degree`, drowning the causal backbone. Make
co-occurrence cheaply separable **without losing evidence**.

**Step 1 — Enumerate & measure (SQL).** Identify the co-occurrence / low-signal predicate set for
this graph — always `mentioned_with`/`co_mentioned_with`, and evaluate `related_to`,
`interacts_with`, and any near-empty relational predicate (`comments_on`, `reports_on`) as
candidates. For that set report: active count and share of all active edges; avg `support_count`
and `truth_probability`; and the **redundancy ratio** — of the distinct unordered entity pairs they
connect, how many *also* have a non-co-occurrence (causal) edge vs. are co-occurrence-**only**. Also
check whether `additional_data.signal_class` is already set. See `references/diagnostic-queries.md`
("Co-occurrence noise").

**Step 2 — Choose the action mix from the redundancy ratio (do not default to prune).** The measured
reality is that the vast majority of co-occurrence pairs are the *only* link between those two
entities (~95% co-occurrence-only in the staging sample), so pruning them outright deletes the sole
edge for a pair and loses information. Pick per subset:
  - **TAG_SIGNAL_CLASS (safe default, always do this):** set `additional_data.signal_class =
    'co_occurrence'` on every edge in the set. Reversible, touches no topology, and gives the
    dashboard a cheap `WHERE additional_data->>'signal_class' <> 'co_occurrence'` filter and a
    degree/layout exclusion. This alone satisfies "cheaply separable downstream."
  - **DOWNWEIGHT_COOCCURRENCE:** in the viz/degree computation, exclude or weight-down tagged
    co-occurrence so hub sizing and layout reflect causal structure. Prefer doing this in the
    dashboard/query layer (a rendering concern) over mutating `truth_probability`/`spread_score`;
    only mutate assertion scores if the graph contract says those columns should encode signal
    class, and audit it if so.
  - **COLLAPSE_COOCCURRENCE:** for the small set of unordered pairs with duplicate co-occurrence
    edges (A→B and B→A, or repeated same-pair rows), collapse to one survivor with `support_count =
    Σ`, repoint mentions, supersede the rest — the symmetric case of the edge duplicate-collapse
    pass. Note this typically removes few rows (co-occurrence is ~1 edge/pair), so it is not the
    volume lever.
  - **PRUNE_REDUNDANT_COOCCURRENCE (gated):** supersede *only* co-occurrence edges whose unordered
    pair already has a real causal edge — the co-occurrence is then genuinely redundant. Use
    `reason_code='cooccurrence_redundant'`. Never bulk-supersede the co-occurrence-**only** tail
    without explicit user approval; that is a lossy topology change, not cleanup.

**Step 3 — Apply the safe tier (audited).** `TAG_SIGNAL_CLASS` and `COLLAPSE_COOCCURRENCE` are safe
once approved: update inside a transaction, write `graph_audit` (before/after `additional_data` or
the supersede) with `reason_code='cooccurrence_tag'` / `'cooccurrence_collapse'`, and
`graph_maintenance_change` rows. Re-run Step 1 and confirm the causal backbone's share of untagged
active edges rose.

**Recurrence prevention (mostly shipped — verify, don't re-propose).** F0216 already tags
co-occurrence `signal_class='co_occurrence'` at write time and suppresses it in the extraction
prompt. Verify deployment to this environment; the still-open items are (a) the dashboard actually
*filtering/down-weighting* tagged edges in degree/layout (U-channel — as of 2026-07 the map counts
every rendered edge), and (b) whether the hardcoded fallback that seeds one `mentioned_with` edge
when extraction yields none should be dropped entirely (I-channel, small).

## Entity & alias resolution pass (mandatory)

Every ts-graph-dream run MUST include an entity/alias hygiene pass. Ingestion (`assimilate_record`)
resolves entities with fuzzy alias auto-merge and free-text surface forms, which both **over-merges**
distinct co-occurring entities (e.g. `SK Hynix` fused into `Huawei`; `Samsung` appended to the SK Hynix
ticker) and **under-merges** true duplicates (ticker-keyed vs name-keyed nodes kept apart by the
`(node_type, canonical_key)` unique index). Nothing downstream repairs this unless this pass does.

**Step 1 — Enumerate signals (SQL).** From `references/diagnostic-queries.md`: shared-alias clusters
(one alias on >1 active entity), garbage aliases (`N/A`, empty, bare numbers), and cross-company false
merges (`merged_into_id` survivor is a different ticker/company than the merged row). Also gather
ticker/canonical_key/name fragmentation. Output a compact candidate set with entity ids, names,
tickers, node_types, aliases, and edge/mention counts.

**Step 2 — Adjudicate with a capable model (REQUIRED — do not decide from SQL heuristics).** Deciding
whether two nodes are the *same real-world entity* is world-knowledge reasoning, not string matching
(`China` sector vs `China` macro = same; `SK Hynix` vs `Huawei` = different; `AWS` vs `AMZN` = brand
under parent, not an alias to strip). SQL can only *surface* candidates. For the judgment, spawn a
subagent (Agent tool) running a strong model and feed it the candidate batch:
  - use `model: "sonnet"` for routine batches, `model: "opus"` for the hard/ambiguous ones;
  - prefer a **1M-context** model and send the whole candidate set at once when it's large, so the
    model sees every fragment of an entity together rather than in blind sub-batches;
  - ask it to label each candidate: `MERGE` (same thing → which survivor), `REMOVE_ALIAS` (which alias
    strings are contamination), `UNMERGE` (bad `merged_into_id` to unwind), `RETYPE`, or `LEAVE`, each
    with a one-line rationale and a confidence. Require it to treat different tickers as different
    companies and to flag garbage aliases.
  Keep the model's verdicts as structured rows; never auto-apply a low-confidence verdict.

**Step 3 — Apply the safe tier (audited).**
  - **REMOVE_ALIAS / garbage strip:** edit the `graph_entity.aliases` jsonb array only, with a
    `graph_audit` before/after (`reason_code='alias_contamination_remove'`) and a
    `graph_maintenance_change` row. This touches no edges/mentions and is fully reversible — safe to
    apply once the model + user approve.

**Step 4 — Propose the risky tier (gated, never bulk-auto).**
  - **MERGE_ENTITY:** set the losers' `merged_into_id` to the survivor, then repoint their active
    edges/claims/quant and mentions to the survivor and re-run the edge duplicate-collapse pass
    (merging creates new same-(s,p,o) duplicates). Preview counts first.
  - **UNMERGE_ENTITY:** high-risk. The merged node's edges/mentions are commingled with the survivor's
    with no per-row provenance of origin, so a clean split usually isn't possible by SQL — prefer
    re-extracting the affected source records (the `ts-graph-reextract` path) over hand-splitting.
    Always dry-run and get explicit approval; never bulk-apply.

**Recurrence prevention (partly shipped).** F0216 added the cross-ticker conflict guard (no
auto-merge fusing two distinct ticker'd companies) and alias sanitization (garbage aliases rejected
at write) — verify deployment rather than re-proposing. Still open as `I`-channel work: resolving
ticker-keyed and name-keyed candidates for the same company to one node (the under-merge caused by
the `(node_type, canonical_key)` unique index), and shared *concept* aliases (`HBM`, `NAND`, `AI`)
landing on many unrelated entities — the alias-adder should reject aliases that are generic terms
rather than names of the entity.

## Entity name hygiene pass (mandatory)

Every ts-graph-dream run MUST include an entity-name hygiene pass. `graph_entity.name` is meant to
be the human-readable label shown everywhere downstream — the map nodes, the inspector, and the
Louvain **cluster labels** (which pick the highest-priority member's `name`). Ingestion sometimes
stores a non-human string there, which then surfaces as garbage. Two failure modes:

1. **Opaque identifier-names (contamination).** Placeholder/duplicate nodes whose `name` is a raw
   importer key or UUID — observed: `company` nodes named `PROD_MACRO_STORY:<UUID>` (grok backfill
   contamination; the real story exists separately as a `theme_situation` with the same UUID
   lowercased in `canonical_key`), plus bare UUIDs and other `<KEY>:<uuid>` forms. These have no
   meaning to a reader and produce useless cluster labels.
2. **Ticker-as-name.** `company` nodes whose `name` is just the exchange ticker instead of the
   company's real name — most common for non-US listings where the ticker is opaque:
   `005930.KS` (should be *Samsung Electronics*), `6758.T` (*Sony*), `0700.HK` (*Tencent*),
   `600519.SS` (*Kweichow Moutai*), `2330.TW` (*TSMC*). The ticker belongs in the `ticker` column,
   not as the display name.

**Step 1 — Enumerate (SQL).** From `references/diagnostic-queries.md` ("Entity name hygiene"),
surface: (a) active entities whose `name` matches an opaque pattern (`^[A-Z_]+:[0-9a-f-]{36}$`, bare
UUID, or `name = canonical_key` where the key is an opaque `<key>:<uuid>`), joined to any
readable **twin** entity that shares the same UUID; and (b) `company` entities whose `name` looks
like a ticker (`name = ticker`, or `name ~ '^[0-9A-Z]{1,6}\.[A-Z]{1,4}$'`, or `name` equals a bare
exchange symbol). Report each with id, node_type, name, ticker, canonical_key, aliases, and
edge/mention counts.

**Step 2 — Decide the real name (REQUIRED — reasoning model, per "Model selection").** Mapping a
ticker to a company name (`005930.KS` → *Samsung Electronics*) or judging whether an opaque node is
a duplicate of a readable twin is world-knowledge, not string work. Batch the candidates to an
Agent-tool subagent (`fork_turns: "none"`; `model: "sonnet"` routine, `model: "opus"` ambiguous;
prefer 1M-context so the
whole batch fits) and have it return, per entity: a verdict `RELABEL` (with the exact `new_name`) /
`MERGE` (opaque node is a duplicate of a named twin → which survivor) / `QUARANTINE` (pure noise,
no real edges) / `LEAVE`, plus the correct `ticker` when it recognises one, a confidence, and a
one-line rationale. Never invent a company name — if the model is not confident which real company a
ticker maps to, it must return `LEAVE`, not a guess. Keep verdicts as structured rows.

**Step 3 — Apply the safe tier (audited).**
  - **RELABEL_ENTITY:** update `graph_entity.name` to the model's `new_name`; **append the old name
    to `aliases`** (dedup) so ticker/opaque-key lookups still resolve; set `ticker` if it was null
    and the model supplied one and `name` was the ticker. This touches only `name`/`aliases`/`ticker`
    — no edges or mentions move — so it is fully reversible. Write `graph_audit` (before/after `name`
    + `aliases`) with `reason_code='entity_relabel'` and a `graph_maintenance_change` row. Only apply
    verdicts above the confidence bar; hold the rest for report.

**Step 4 — Propose the risky tier (gated).** `MERGE` (opaque duplicate into its readable twin) and
`QUARANTINE` follow the **Entity & alias resolution pass** rules — preview counts, re-home
edges/mentions, re-collapse duplicates, get explicit approval; never bulk-auto. Prefer RELABEL when a
merge isn't clearly safe: a readable-but-still-separate node beats a UUID on the map even if the
underlying duplication is deferred.

**Recurrence prevention (STILL OPEN — this one recurs).** F0216 does **not** fix ticker-as-name:
staging re-accumulated 273 ticker-named companies after the 2026-07 run relabeled 259, so every dream
run will find fresh ones until ingestion changes. The durable I-channel fix remains unshipped:
(a) reject an opaque `<KEY>:<uuid>` or bare-UUID string as a `name` at write time (fall back to a
resolved label or the readable twin); and (b) in entity resolution, populate `company.name` from the
security master's long name and keep the ticker only in `ticker`, so `005930.KS`-style symbols never
land in `name`. Prioritize filing/deploying this over repeated relabel sweeps.

## Non-entity & mistyped node pass (mandatory)

Every ts-graph-dream run MUST include a non-entity / mistyped-node pass. Free-text extraction
sometimes mints a graph_entity for something that is not an entity, or files a real entity under the
wrong `node_type`. Both surface as garbage nodes on the map. **Salvage intel first, then clean up —
never blind-delete.**

Two failure modes:

1. **Non-entity literals.** A bare number, money, or unit fragment captured as a `company`: `400`,
   `1.3`, `100B`, `2.2`, `$40`, `35%`. These are extraction slips where a numeric *value* was
   mistaken for a subject. They typically have **no active edges** and their incident edges are
   `related_to`/`mentioned_with` noise between numbers (`"100B related to 100"`).
2. **Mistyped node_type.** A real, meaningful node filed under the wrong type — most often a
   narrative/headline/theme stored as `company` ("Shutdown Pressure Ahead of Senate Recess",
   "AI Infrastructure Supply Chain Bottlenecks"), but also a person, sector, or event mis-typed.

**Step 1 — Enumerate (SQL).** From `references/diagnostic-queries.md` ("Non-entity & mistyped
nodes"): (a) typed-entity nodes whose `name` matches a numeric/money/unit-only pattern or has no
letters; (b) `company` nodes whose `name` reads like a sentence/headline/theme (long, multi-word,
sentence-cased). For each, report active/total edge counts, quant counts, and whether provenance
(`graph_mention.source_record_id`) exists.

**Step 2 — SALVAGE FIRST (required before any cleanup).** For every candidate, check what real intel
it holds and relocate it to the correct place *before* quarantining:
  - **Mistyped node_type → RETYPE_ENTITY** (the salvage IS the relocation): flip `node_type` to the
    correct value and keep the node, its edges, quants, and mentions in place. Reasoning-model
    adjudicated (company→theme_situation/event/person/sector). This preserves 100% of the intel.
  - **A numeric literal that is really a metric value** (`"NVIDIA … $40 billion …"` captured as a
    `40` node): the *value* survived but its **subject (which company) and metric are lost** once the
    only links are `related_to` number-to-number noise. You cannot re-attribute "revenue = 99"
    without knowing whose. Two honest outcomes: **(i)** if the node still has an *active, directional*
    edge that names the real subject and metric, record the fact as a `graph_claim` on that real
    entity (the quant layer is decommissioned — numbers live in claims or in FMP, not `graph_quant`),
    then quarantine the literal; **(ii)** if the subject identity is gone
    (the usual case — noise edges only, and often **no `source_record_id`** so re-extraction isn't
    even possible), there is nothing to salvage in place — say so plainly and quarantine. Never
    fabricate an attribution to satisfy "salvage".
  - **A numeric node with recoverable provenance** (`graph_mention.source_record_id` present): don't
    hand-repair — route the source records through the `ts-graph-reextract` path so the real
    `(company, metric, value)` triples are re-derived. Report the record ids.

**Step 3 — Clean up the salvaged husks (audited).**
  - **RETYPE_ENTITY** (safe tier): `UPDATE graph_entity SET node_type=:correct` with a `graph_audit`
    before/after (`reason_code='entity_retype'`) and a `graph_maintenance_change` row. Touches no
    edges/mentions.
  - **QUARANTINE_ENTITY** for non-entity literals with no salvageable intel: there is no `is_active`
    column, so mark `additional_data = additional_data || '{"quarantined":true,"quarantine_reason":
    "non_entity_numeric_literal"}'` and **supersede** the node's noise edges/quants
    (`superseded_at=now()`, `reason_code='non_entity_quarantine'`). Fully audited and reversible.
    Only quarantine nodes confirmed to have **no active, meaning-bearing edges** — a numeric name
    alone is not sufficient if the node carries a real active relationship.

**Recurrence prevention & UI (partly shipped).** (a) **UI/query:** the dashboard graph query already
excludes quarantined endpoints (`buildGraphVisualizationWhere`) — verify, don't re-propose; any new
entity-hiding must go through that same filter. (b) **I-channel:** F0216 quarantines numeric /
low-information names at insert (`should_quarantine_entity_name`, ticker'd companies exempt) —
verify deployment. Still open: validating `node_type` against the surface form so headlines/themes
aren't filed as `company`.

## Geopolitical vs location entity pass (run when the graph has geo entities)

Countries, regions, blocs, and cities are first-class actors in a macro/markets graph, but
extraction files them wherever it guessed — `Iran` as `company`, `China` as `organization`/`sector`/
`macro_indicator` — fragmented across types and name-variants (`US` / `USA` / `U.S.` /
`United States`). Worse, one node **conflates two fundamentally different senses**:

- **`geopolitical`** — the state / government / political actor: *"US conducts strikes in Iran"*,
  *"US considers export cap on China"*, *"Iran closes Strait of Hormuz"*, *"US coordinates with
  Israel"*. This drives company exposure like a macro driver (sanctions, tariffs, conflict).
- **`location`** — the country/region/city as a **place or market**: *"US copper stockpile"*,
  *"US IT employment"*, *"exports to the US"*, *"production in the US"*, *"listed in Hong Kong"*.

These are two node types (both must exist in the dashboard's color/legend map). The same real-world
"United States" legitimately appears in both senses in different edges, so cleanup is not a simple
retype — conflated nodes must be **split**, with each edge reassigned to the sense it actually asserts.

**Step 1 — Discover (SQL).** From `references/diagnostic-queries.md` ("Geopolitical & location
nodes"): match a curated GPE/location list (countries + regions/blocs + major cities) against `name`
across **all** node types, with active-edge counts. Group by concept to expose the fragmentation
(all `US`-family rows together).

**Step 2 — Classify each entity (REQUIRED reasoning model).** World knowledge, not string matching —
homonyms abound (`Georgia` country vs US state vs a company; `Jordan` country vs person; `Turkey`
country vs the bird; `Chad`, `Georgia`, `Jordan` as people). For every candidate the model returns:
  - `NOT_GEO` — a real company/person/etc. that merely shares a country name → LEAVE.
  - `LOCATION` — used purely as a place/market → RETYPE to `location`.
  - `GEOPOLITICAL` — used purely as a state actor → RETYPE to `geopolitical`.
  - `CONFLATED` — edges span both senses → SPLIT (Step 4). Give the model the node's active edges
    (predicate + counterpart + edge_text) so it judges from real usage, and let it name the
    **dominant sense** (which the retained node keeps) vs the minority sense (peeled off).
  Also emit a **survivor map** for name-variants (`US`/`USA`/`U.S.`/`United States` → one survivor
  per (sense, concept)).

**Step 3 — Apply the safe tier (audited).** RETYPE single-sense entities to `geopolitical` /
`location` (`reason_code='geo_retype'`). Watch the `(node_type, canonical_key)` unique constraint —
two variants retyped to the same (type, key) collide; that pair is a MERGE, not two retypes.

**Step 4 — Dedup + split (gated, dry-run first).**
  - **MERGE name-variants** into the survivor (re-home edges/quants/mentions, then re-collapse
    duplicate edges) — the standard entity-merge tier; preview counts, get approval.
  - **SPLIT_ENTITY (conflated):** keep the node as its **dominant** sense (retype it), create a
    sibling node for the minority sense (same name, `node_type` = the other geo type, distinct
    `canonical_key` e.g. `<key>:<sense>`), then **repoint each minority-sense edge** (and its
    mentions) from the original to the sibling. Reassignment is **per-edge, model-adjudicated** from
    predicate + edge_text; default an edge to the dominant sense when unsure (fewer moves, lower
    risk). Audit every repoint (`reason_code='geo_sense_split'`, before/after subject/object id) and
    write `graph_maintenance_change` rows. Dry-run the counts (edges to move, edges retained) and get
    approval before applying; never bulk-split without review.

**Recurrence prevention (I-channel, ts-prefect).** Entity resolution should (a) assign `geopolitical`
vs `location` from edge context rather than a single default type, (b) canonicalize country
name-variants to one key per sense, and (c) not fuse a country's government-actor and market-place
senses into one node. File this against the assimilate/entity-resolution code (see memory
`ts-graph-extraction-and-grok-backfill`).

## Legacy quant pass (conditional — only when `graph_quant` exists)

**The quant layer was decommissioned in 2026-07**: ~86% of rows were garbage (5,028 metric names for
~9.7k rows, generic fallbacks, mis-attributed values), FMP already provides trustworthy financials by
ticker, so the decision was: *the graph is for relationships, not a second-rate metrics store*. The
table was dropped from staging and all quant UI/extraction code removed from the dashboard and the
current ts-prefect graph code. Check `to_regclass('graph_quant')` first — if absent, skip this pass.

If the table still exists **and is still being written** (production was in this state as of
2026-07-03: 21 rows, `reported_numeric_value` fallbacks arriving from a live assimilator), the
headline finding is **environment drift** — that environment runs pre-decommission code — and the
right action is promoting the decommission (code + table drop; note ts-prefect's Atlas policy is
additive-only, so the DROP is manual), not metric-by-metric row hygiene. Only when the user wants the
legacy rows cleaned in place does the original procedure below apply, targeting **generic-fallback
metric names** (`reported_numeric_value`, `value`, `numeric_value`, `reported_value`) — bare numbers
with no metric semantics, often stray years captured as a "value".

**Step 1 — Measure & attempt salvage (SQL).** From `references/diagnostic-queries.md`
("Uninterpretable quants"): count active generic-metric quants and, crucially, whether ANY are
recoverable — do they carry `additional_data` context, a meaningful `unit`, `period_start/end`, or
**provenance** (`graph_mention.source_record_id`)? `graph_quant` has no statement/text column, so
absent all of those there is literally nothing to infer the real metric from.

**Step 2 — Salvage what's recoverable, drop the rest.**
  - If a subset carries `additional_data` naming the real metric, or a `unit` + provenance that makes
    the measure obvious, **relabel** those (`UPDATE metric`) — that's the salvage.
  - If provenance exists but the metric still isn't inferable, route the source records through
    `ts-graph-reextract` rather than guess.
  - **Otherwise DROP them** (the common case): no context, no unit-meaning, no provenance →
    uninterpretable and unrecoverable. **Supersede** (never hard-delete): `superseded_at = now()`,
    `reason_code='uninterpretable_quant'`, with `graph_audit` (before = metric/value/unit) and
    `graph_maintenance_change` rows. Superseding (not deleting) keeps the row auditable and lets the
    dashboard hide it (quant surfaces already filter `superseded_at IS NULL`).

**Recurrence prevention.** Already decided and implemented on the current code line: quant
extraction was deleted outright. If an environment still emits quants, the fix is promoting the
decommission, not patching the fallback.

## Model selection for semantic judgments

SQL finds candidates; **it cannot decide meaning.** Any step that asks "are these the same real-world
thing?", "is this predicate a true synonym/inverse?", or "is this alias contamination?" must be
delegated to a reasoning model, not answered from string heuristics. Spawn an Agent-tool subagent with
`fork_turns: "none"`, `model: "sonnet"` (routine) or `model: "opus"` (hard/ambiguous), and prefer a **1M-context** model so
the whole candidate set for one entity/predicate family fits in a single prompt. Return structured
verdicts with confidence; apply only the safe tier automatically, and only above a confidence bar.

## ts-graph table reminders

Current known graph tables use these conventions:

- Assertions: `graph_edge`, `graph_claim` (and legacy `graph_quant` where it still exists) have `truth_probability`, `confidence`, `support_count`, `contradiction_count`, `spread_score`, `learned_at`, `superseded_at`, `content_hash`, `additional_data`.
- Well-known `additional_data` keys written by ingestion/maintenance: `signal_class` (`'co_occurrence'`), `predicate_direction`, `endpoints_were_reordered` (edges); `quarantined` / `quarantine_reason` (entities).
- Entities: `graph_entity` has `node_type`, `canonical_key`, `name`, `aliases`, `scope`, `ticker`, `merged_into_id` — **no `is_active`**; soft-delete is the `additional_data.quarantined` flag. `(node_type, canonical_key)` is unique; `ticker` has an FK to the companies table (don't backfill arbitrary symbols — keep them in `aliases`).
- Provenance: `graph_mention` links assertions to `graph_document`/source records and must survive cleanup.
- User annotations: `graph_note` (`entity_id` FK → `graph_entity`, `note_text`, `status`) — user-authored; repoint on entity merge, never orphan or supersede as "noise".
- Vocabulary: `graph_taxonomy` (`taxonomy_type`, `slug` unique per type, `metadata.canonical_slug`) drives write-time predicate canonicalization — the dream's durable output channel.
- Auditing: `graph_audit` records before/after changes; `graph_maintenance_run` and `graph_maintenance_change` summarize batch maintenance.

## References

- `references/diagnostic-queries.md`: SQL templates for finding duplicates, predicate drift, entity fragmentation, provenance issues, and safe dry-run mutation previews.

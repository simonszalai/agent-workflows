---
name: ts-graph-dream
description: Whole-system knowledge graph consolidation for ts-graph style databases. Use when asked to audit, clean, deduplicate, canonicalize, or "dream" over graph data; investigate duplicate graph_edge rows, predicate explosion, co-occurrence / mentioned_with noise edges dominating the graph or viz layout, low-signal predicate pruning, entity aliases/merges, stale/superseded graph assertions, graph maintenance runs, Grok/import backfill contamination, or graph dashboard inspector noise. Produces evidence-bound cleanup plans and can apply safe audited graph_* mutations only when explicitly approved.
---

# TS Graph Dream

`ts-graph-dream` is the graph-data analogue of `deep-dream`: it audits a knowledge graph for duplicate assertions, predicate drift, entity fragmentation, stale rows, and bad importer patterns, then proposes safe consolidation actions.

Default stance: **read-only report first**. Mutate only after explicit user approval or an explicit apply request.

## Safety rules

1. **Never hard-delete graph rows.** Use `superseded_at`, `merged_into_id`, `is_active=false`, `status=inactive`, and `graph_audit` / `graph_maintenance_*` records.
2. **Preserve provenance.** Do not orphan `graph_mention`, `graph_document`, `llm_stat_id`, source rows, quotes, or source_record links. Duplicates may be real independent evidence.
3. **Separate duplicate assertion from duplicate evidence.** Collapse repeated claims/edges only when they assert the same semantic fact. Keep or aggregate multiple source mentions.
4. **Production mutation needs an explicit go-ahead.** If the DB looks production-like, stop after the plan unless the user clearly asked to apply there.
5. **Dry-run all SQL first.** Every mutation plan must show expected row counts and sample IDs before changing data.
6. **Use transactions and audit rows.** Mutations must be reversible by evidence, with `graph_audit.before/after` and a `graph_maintenance_run` / `graph_maintenance_change` trail when available.
7. **No schema changes unless requested.** If a durable fix needs constraints, generated columns, or importer code changes, propose it separately from data cleanup.
8. **Respect predicate directionality.** Treat every predicate as directed unless it is explicitly classified as symmetric in the ts-graph contract (`competes_with`, `partners_with`, `mentioned_with`) or has a declared inverse. Canonicalize variants (`rivals` -> `competes_with`, `collaborates_with` -> `partners_with`, `co_mentioned_with` -> `mentioned_with`) before duplicate checks. Symmetric predicates should use an unordered entity pair for duplicate detection and ingestion idempotency.
9. **A shared alias is ambiguous — never treat it as an automatic merge signal.** Two entities sharing an alias means EITHER they are the same thing fragmented (→ merge) OR one entity has absorbed another's name as a bad alias / bad auto-merge (→ remove alias / unmerge). Distinguish before acting. High-precision contamination rule: a ticker'd company must NOT carry a *different* ticker'd company's name or ticker as an alias, and a single entity must NOT fuse two distinct tickers. Removing a contaminating alias (editing the `aliases` array with a before/after audit) is low-risk. **Unmerging** a bad `merged_into_id` is high-risk — it requires re-homing edges/mentions to the correct entity and usually cannot be done from provenance alone; propose it, dry-run it, and get explicit approval, never bulk-apply.
10. **Co-occurrence noise is low-signal, not wrong — down-weight/tag before you prune.** Pure co-occurrence predicates (`mentioned_with`, `co_mentioned_with`, and often `related_to`, `interacts_with`) assert only "these two were named in the same document" — no causal/semantic direction — yet they routinely outnumber every real predicate and dominate the force-layout hairball and node `degree`. They are still weak evidence, and in practice most co-occurrence pairs are the *only* edge between those two entities (measure it — see the co-occurrence pass), so hard-pruning them silently deletes the sole link for a pair and loses information. Default to the reversible, non-destructive lever: **tag** each as `additional_data.signal_class='co_occurrence'` and/or **down-weight** it (so it no longer drives degree/layout), letting the dashboard cheaply filter it out. Only **supersede** (prune) the redundant subset — a co-occurrence edge between a pair that *already* has a real causal edge — and only **collapse** (merge to one weighted survivor, `support_count = Σ`) genuine duplicate co-occurrence edges for the same unordered pair. Never bulk-delete the co-occurrence-only tail without explicit approval.

## Quick workflow

### Phase 0 - Scope and baselines

1. Identify the graph DB and environment:
   - Prefer the current repo `.env` `DATABASE_URL` when the user points at a local/staging dashboard.
   - If linked `ts-prefect` is relevant, inspect importer/backfill code there too.
   - Print only database host/db name, never credentials.
2. Confirm graph tables exist: `graph_entity`, `graph_edge`, `graph_claim`, `graph_quant`, `graph_mention`, `graph_document`, `graph_source`, `graph_taxonomy`, `graph_audit`, `graph_maintenance_run`, `graph_maintenance_change`.
3. Record baseline counts: total vs active rows, superseded counts, recent maintenance runs, and imported source families.
4. If the user named an entity/ticker, scope diagnostics to that node first, then decide whether global cleanup is needed.

### Phase 1 - Evidence gathering

Load `references/diagnostic-queries.md` when writing SQL. Gather compact evidence for:

- **Edge duplicates:** repeated `(subject, predicate, object)` active edges; reverse/symmetric duplicates; same content hashes.
- **Predicate drift (mandatory):** always enumerate the full set of distinct predicate values and their active counts, then cluster them into synonym/variant families (see the **Predicate canonicalization pass** below). Free-text LLM predicates fragment into a long tail of one-off strings (`benefits` vs `benefits_from`, `drives` vs `drives_demand_for`, `partnered_with` vs `partners_with`) that must be collapsed to a canonical predicate.
- **Co-occurrence noise (mandatory):** measure the share of pure co-occurrence predicates (`mentioned_with` and siblings) among active edges, their average `support_count`/`truth_probability`, and — critically — how many of their unordered entity pairs *also* have a real causal edge vs. are co-occurrence-only. This ratio decides the action mix (see the **Co-occurrence & low-signal noise pass**). Also check whether the edges already carry a `signal_class` tag in `additional_data`.
- **Predicate directionality:** classify predicates as directed, symmetric, inverse-paired, temporal/event-scoped, or unknown before consolidation. Inverse pairs (`supplies`/`purchases_from`, `sells_to`/`buys_from`, `owns`/`owned_by`, plus hand-reviewed pairs like `acquires`/`acquired_by`) must never be flat-merged — canonicalizing one onto the other requires swapping subject/object.
- **Entity fragmentation:** same ticker/canonical key/name across several entities; alias overlap; merged_into chains; orphan nodes.
- **Display-name hygiene (mandatory):** entities whose `name` is not a human-readable label — opaque internal identifiers (`PROD_MACRO_STORY:<UUID>`, bare UUIDs, `<KEY>:<uuid>` importer keys) and companies whose `name` is just a **ticker symbol** rather than the real company name (especially Asian listings: `005930.KS`, `6758.T`, `0700.HK`, `600519.SS`, `2330.TW`). These read as garbage in the map, inspector, and cluster labels. See the **Entity name hygiene pass**.
- **Non-entity & mistyped nodes (mandatory):** `company` (or other typed) nodes that are not entities at all — a bare number/money/unit literal (`400`, `1.3`, `100B`, `2.2`) that the extractor captured as an "entity", or nodes typed `company` whose `name` is clearly a **narrative/headline/theme** ("Shutdown Pressure Ahead of Senate Recess"), a person, a sector, or an event. See the **Non-entity & mistyped node pass**.
- **Geopolitical / location nodes (when present):** countries, regions, blocs, and cities (`Iran`, `China`, `United States`, `Middle East`, `Hong Kong`) mis-filed under `company`/`organization`/`sector`/`macro_indicator`, usually **fragmented** across those types and name-variants (`US`/`USA`/`U.S.`/`United States`), and often **conflating two senses** — the state/government actor vs. the country as a place/market. See the **Geopolitical vs location entity pass**.
- **Uninterpretable quants (mandatory):** `graph_quant` rows whose `metric` is a generic extractor fallback (`reported_numeric_value`, `value`, `numeric_value`) — a bare number with no idea what it measures (often a stray year like `2024`). See the **Uninterpretable quant pass**.
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
| I | Importer | ADD_IDEMPOTENCY / ADD_PREDICATE_MAP / ADD_ENTITY_RESOLUTION / STOP_BAD_BACKFILL |
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
- Does the importer fix prevent recurrence, or only clean symptoms?
- Is there a DB constraint/index that would be safer than repeated cleanup?

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

Every ts-graph-dream run MUST include an explicit predicate-canonicalization pass. Free-text LLM
predicates are written verbatim (normalized only for case/spacing), so the vocabulary explodes into
thousands of near-duplicate strings. Finding and collapsing these is a first-class channel, not an
afterthought.

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

**Recurrence prevention.** Predicate cleanup is symptomatic unless ingestion stops emitting free-text
predicates. Propose (separately, as code work) a controlled predicate vocabulary + `variant->canonical`
map applied at write time, and/or a `graph_taxonomy`-backed canonicalization step in the cloud graph
maintenance skill so this pass runs on a schedule instead of by hand.

## Co-occurrence & low-signal noise pass (mandatory)

Every ts-graph-dream run MUST include a co-occurrence pass. Free-text extraction mints a
`mentioned_with` edge for entity pairs that merely appear in the same document, so co-occurrence
becomes the single largest predicate by a wide margin (measured on staging: `mentioned_with` ≈ 2.2k
of ~12.8k active edges — ~7× the next predicate). Because it is undirected, low-support co-mention
volume rather than meaning, it collapses the force layout into a central hairball and inflates node
`degree` (which drives node size), drowning the tradeable causal backbone (company→company causal,
company→theme). This pass makes co-occurrence cheaply separable **without losing evidence**.

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

**Recurrence prevention (I-channel, propose separately).** Tagging is symptomatic unless extraction
stops minting co-occurrence as first-class edges. The volume originates in the assimilate two-pass
extraction (see memory `ts-graph-extraction-and-grok-backfill`). Propose as code work: (a) tag
co-occurrence with `signal_class='co_occurrence'` at write time so no dashboard/dream backfill is
needed; and/or (b) stop emitting `mentioned_with` as a graph_edge at all and route co-occurrence to a
separate lightweight signal, keeping `graph_edge` for asserted relations. File a source-side ticket
if the fix is non-trivial.

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

**Recurrence prevention.** Data cleanup won't stop ingestion re-introducing it. Propose (separately, as
`I`-channel code work) an entity-resolver guard: block an auto-merge/alias-add when the alias equals a
*different* ticker'd company's name/ticker, reject garbage aliases, and resolve ticker-keyed and
name-keyed candidates for the same name to one node.

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
Agent-tool subagent (`model: "sonnet"` routine, `model: "opus"` ambiguous; prefer 1M-context so the
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

**Recurrence prevention (I-channel, propose separately).** Names are symptomatic unless ingestion
stops writing identifiers/tickers into `name`. Propose as code work: (a) reject an opaque
`<KEY>:<uuid>` or bare-UUID string as a `name` at write time (fall back to a resolved label or the
readable twin); and (b) in entity resolution, populate `company.name` from the security master's
long name and keep the ticker only in `ticker`, so `005930.KS`-style symbols never land in `name`.

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
    edge/quant that names the real subject and metric, record it as a `graph_quant` on that real
    entity (P/C-channel), then quarantine the literal; **(ii)** if the subject identity is gone
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

**Recurrence prevention & UI (propose separately).** (a) **UI/query:** the dashboard graph query
must exclude quarantined entities (`additional_data->>'quarantined' <> 'true'`) so flagged garbage
stops rendering — quarantine flags are inert until the reader honours them; the same is true of nodes
kept alive only by superseded edges (the map should default to active edges or drop quarantined
nodes). (b) **I-channel:** at extraction/resolution time, reject a bare numeric/money/unit string as
an entity `name` (route the number to a `graph_quant` value on the real subject instead), and
validate `node_type` against the surface form so headlines/themes aren't filed as `company`.

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

## Uninterpretable quant pass (mandatory)

Every ts-graph-dream run MUST check `graph_quant` for **generic-fallback metric names** — the
extractor's dumping ground for a number it saw but couldn't classify. The dominant one is
`metric = 'reported_numeric_value'` (also `value`, `numeric_value`, `reported_value`): a bare `value`
with no metric semantics — you cannot tell whether `Boeing = 99694` is revenue, headcount, or an
order number, and many are stray **years** (`2024`, `2028`) captured as a "value". They inflate quant
counts and the node data-richness badge with noise.

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

**Recurrence prevention (I-channel).** The real fix is upstream: the quant extractor should not emit a
`reported_numeric_value` fallback — a number with no classifiable metric should not become a
`graph_quant` at all (drop it, or attach it to the sentence as text, not as a metric). File against
the assimilate/quant-extraction code.

## Model selection for semantic judgments

SQL finds candidates; **it cannot decide meaning.** Any step that asks "are these the same real-world
thing?", "is this predicate a true synonym/inverse?", or "is this alias contamination?" must be
delegated to a reasoning model, not answered from string heuristics. Spawn an Agent-tool subagent with
`model: "sonnet"` (routine) or `model: "opus"` (hard/ambiguous), and prefer a **1M-context** model so
the whole candidate set for one entity/predicate family fits in a single prompt. Return structured
verdicts with confidence; apply only the safe tier automatically, and only above a confidence bar.

## ts-graph table reminders

Current known graph tables use these conventions:

- Assertions: `graph_edge`, `graph_claim`, `graph_quant` have `truth_probability`, `confidence`, `support_count`, `contradiction_count`, `spread_score`, `learned_at`, `superseded_at`, `content_hash`, `additional_data`.
- Entities: `graph_entity` has `node_type`, `canonical_key`, `name`, `aliases`, `scope`, `ticker`, `merged_into_id`.
- Provenance: `graph_mention` links assertions to `graph_document`/source records and must survive cleanup.
- Auditing: `graph_audit` records before/after changes; `graph_maintenance_run` and `graph_maintenance_change` summarize batch maintenance.

## References

- `references/diagnostic-queries.md`: SQL templates for finding duplicates, predicate drift, entity fragmentation, provenance issues, and safe dry-run mutation previews.

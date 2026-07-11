# Audit Checklist — Detailed Dimensions

Authority for the memory channel: per-entry and cross-entry audit dimensions, plus the MCP
tool mapping for executing surviving memory actions.

## Per-Entry Audit

### A. Validity — Is the information still correct?

- Cross-reference claims about code behavior with the actual codebase. If an entry says
  "function X does Y", grep for function X and verify.
- Check if referenced files, functions, classes, or config keys still exist.
- Check if referenced tools, libraries, or APIs are still in use (check package.json,
  pyproject.toml, requirements.txt).
- Flag entries that reference things that no longer exist or work differently.

### B. Currency — Is this still relevant?

- Entries older than 6 months without updates deserve extra scrutiny.
- Check if the problem an entry describes has been fixed (e.g., a gotcha about a bug that
  was patched).
- Check if a workaround entry is still needed or if the proper fix landed.
- Check if architectural decisions described still reflect the current architecture.

### C. Accuracy — Does this match how the code actually works?

- For pattern entries: does the codebase still follow this pattern?
- For architecture entries: does the described architecture still hold?
- For gotcha entries: is the gotcha still a real trap?
- For solution entries: does the solution still work?
- For preference entries: is the preference still being followed?

### D. Scope — Is the entry scoped correctly?

- Is a project-scoped entry actually project-specific, or is it general enough to be global?
- Is a global entry actually universal, or is it only relevant to one project?
- Is the `repos` filter correct? (Should it be broader or narrower?)

### E. Size & Quality — Is the entry well-structured?

- Entries under 50 tokens may be too terse to be useful.
- Entries over 1,500 tokens may need splitting.
- Is the summary search-friendly? Does it use vocabulary people naturally use?
- Is the content self-contained and actionable?
- Does the entry include WHY, not just WHAT?

### F. Utility & Recall — does the entry earn its place?

Borrowed from offline "memory consolidation" / agent "dreaming" research (Auto-Dreamer,
Active Dreaming Memory). Dimensions A–C ask "is it true?"; this asks "would a future task fail
or regress if it were gone?" An accurate but never-load-bearing entry is still token cost.

The store exposes retrieval counters/timestamps, but they are **delivery signals, not utility
signals**. A hit means the entry occupied a returned result slot; it does not mean an agent read,
cited, or applied it. Search also updates `last_searched_at` and currently trips the generic
`updated_at` trigger, so `updated_at` cannot be trusted as content freshness. Audit searches
contaminate both fields. Judge utility structurally and counterfactually unless normalized
retrieval-feedback events prove actual use:

- **Counterfactual test:** Imagine the entry deleted. Does any realistic future task get worse
  — a bug reintroduced, a settled decision relitigated, time wasted rediscovering it? If
  nothing breaks, it does not earn its place.
- **Discoverability:** Would the search pipeline ever surface it? An entry whose summary/tags
  don't match the vocabulary of the tasks it should inform is effectively invisible — flag for
  IMPROVE SUMMARY / RETAG. Lack of observed returns alone is never enough to retire it.
- **Redundant with always-loaded context:** If the fact is already obvious from CLAUDE.md, a
  starred entry, or the code itself, it is dead weight.
- **One-off trivia:** A detail that mattered for exactly one closed ticket and has no recurring
  relevance rarely earns its place.

Low apparent utility is a review flag, not a standalone quarantine reason. A retirement
candidate needs additional evidence that the entry is obsolete, harmful, redundant with a
durable canonical source, or has no plausible audience after scope/discoverability repair.

## Cross-Entry Analysis

### G. Duplicates & Overlaps

- Entries with similar titles covering the same topic.
- Entries where one is a subset of another (the smaller one can be deleted).
- Entries that say the same thing with different wording.

### H. Merge Candidates

- Multiple small entries on closely related topics that would be clearer as one entry.
- Entries that form a natural group (e.g., 3 separate gotchas about the same library
  could become one "Library X Gotchas" entry).
- Entries where merging would stay under ~1,500 tokens.

### I. Split Candidates

- Entries over ~1,500 tokens that cover multiple distinct topics.
- Entries where different sections have different scopes (part is global, part is
  project-specific).

### J. Contradiction Detection

- Entries that give conflicting advice on the same topic.
- A newer entry that implicitly contradicts an older one without superseding it.
- Preferences that conflict with patterns or architecture entries.

### K. Tag & Type Consistency

- Entries with missing or inconsistent tags.
- Entries whose `entry_type` doesn't match their content (e.g., a "gotcha" that reads
  like a "reference").
- Extremely broad or fragmented tag sets are review signals, not automatic defects. Preserve
  exact identifiers and symbols; do not force every entry into an arbitrary tag-count range.

### L. Tag Vocabulary Audit

Fetch the complete tag vocabulary for both scopes:

```
mcp__autodev-memory__get_all_tags(project: "global")
mcp__autodev-memory__get_all_tags(project: <project>)
```

Analyze the full tag list for:

- **Synonyms that should be merged:** Different words for the same thing. Examples:
  `pg` / `postgres` / `postgresql`, `js` / `javascript`, `ts` / `typescript`,
  `k8s` / `kubernetes`, `env` / `environment`, `config` / `configuration`.
  Pick the canonical form (usually the most commonly used or most recognizable)
  and propose retagging all entries using the non-canonical variant.

- **Abbreviation vs full name:** When both exist (e.g., `sqlalchemy` and `sa`,
  `react-router` and `rr`), merge to the full name — it's more searchable.

- **Casing inconsistencies:** Tags should be lowercase kebab-case per the autodev-tags
  skill conventions. Flag any tags with uppercase, underscores, or camelCase
  (e.g., `React_Router`, `reactRouter`, `React-Router` should all be `react-router`).

- **Overly broad tags:** Tags like `code`, `dev`, `fix`, `bug`, `misc`, `other` are too
  generic to aid search. Propose replacing with more specific alternatives.

- **Singleton tags:** inspect whether they are valuable exact identifiers, error codes, or symbols
  before merging. Singleton frequency alone does not prove noise. Keep exact-search terms
  separate from semantic concepts when the schema supports it.

- **Near-duplicates with different separators:** e.g., `error-handling` vs `errorhandling`
  vs `error_handling`.

- **Plural vs singular:** e.g., `migration` vs `migrations`, `index` vs `indexes`.
  Prefer singular.

For each tag merge, identify all affected entries so the user knows the blast radius.

### M. Abstraction Candidates

Borrowed from "dreaming" consolidators that rewrite task-specific instances into general
rules. Distinct from MERGE (combine two related entries into one) and SIMPLIFY (trim a single
entry): abstraction **raises the altitude** of the knowledge so it covers cases that haven't
happened yet.

Look for:

- **Instances of one rule.** Several narrow entries that are each a case of the same
  underlying principle — e.g. "set `server_default` on table A's timestamp", "…on table B's
  timestamp", "…on table C's" → one rule: "all timestamp columns need
  `server_default CURRENT_TIMESTAMP`". Propose ABSTRACT into a single rule entry.
- **An over-specific lone entry** whose lesson plainly generalizes beyond the one case it
  documents. Propose rewriting it as the general rule, keeping the original case as a worked
  example inside the entry.

When proposing ABSTRACT:

- Name every instance being subsumed so the user sees the blast radius.
- Confirm the general rule loses **no** case-specific caveat that still matters. Abstraction is
  forgetting-by-omission — it is only safe when the omitted specifics are genuinely redundant.
  If an instance has a real exception, preserve it; do not flatten it into the rule.
- Ground the rewrite in provenance: check what created each instance (ticket, commit, session)
  before assuming they're interchangeable.

## Executing Surviving Memory Actions (MCP tool mapping)

After the adversarial loop converges **and the memory gate is approved** (or
`--apply-memory` was explicit), apply surviving actions via these tools:

- **QUARANTINE** -> for an approved starred entry, unstar first; then call
  `mcp__autodev-memory__delete_entry(entry_id, project)`. This is a recoverable soft-delete that
  excludes the entry from search; call it quarantine, never permanent deletion.
- **SUPERSEDE** -> `mcp__autodev-memory__supersede_entry(...)`. Prefer this over quarantine when
  corrected guidance can replace the stale entry and preserve an explicit chain.
- **UPDATE** -> `mcp__autodev-memory__update_entry(entry_id, project, content, summary, ...)`
- **MERGE** -> Create new entry with merged content via `mcp__autodev-memory__create_entry()`,
  then quarantine the source entries after verifying the destination is durable
- **ABSTRACT** -> Create new general-rule entry via `mcp__autodev-memory__create_entry()`
  (carry over any exception that still applies), then quarantine the subsumed instances
- **RESCOPE** -> Create new entry in the target scope, verify it, then quarantine the original
  (scope is immutable per entry, so rescoping requires recreate + quarantine)
- **SPLIT** -> Create and verify the replacement entries, then quarantine the original
- **SIMPLIFY** -> `mcp__autodev-memory__update_entry()` with trimmed content
- **RETYPE/RETAG** -> `mcp__autodev-memory__update_entry()` with corrected type/tags
- **IMPROVE SUMMARY** -> `mcp__autodev-memory__update_entry()` with better summary
- **MERGE TAGS** / **FIX TAG CASING** -> For each affected entry,
  `mcp__autodev-memory__update_entry()` replacing the non-canonical tag with the canonical one
- **DROP TAG** -> `mcp__autodev-memory__update_entry()` removing the tag, optionally adding
  a replacement
- **RESOLVE contradiction** -> With no human to arbitrate, the codebase decides: verify both
  entries against the current code and propose keeping/repairing the one the code supports,
  superseding or quarantining the other. If the code is genuinely ambiguous, take **no action**
  and report the contradiction for a human. Preferences and architecture decisions cannot be
  arbitrated from code alone.

Any action that touches a starred entry always stops for explicit human approval, even under
`--apply-memory`.

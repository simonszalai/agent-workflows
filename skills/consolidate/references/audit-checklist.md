# Audit Checklist — Detailed Dimensions

## Per-Entry Audit (Step 4)

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

## Cross-Entry Analysis (Step 5)

### F. Duplicates & Overlaps

- Entries with similar titles covering the same topic.
- Entries where one is a subset of another (the smaller one can be deleted).
- Entries that say the same thing with different wording.

### G. Merge Candidates

- Multiple small entries on closely related topics that would be clearer as one entry.
- Entries that form a natural group (e.g., 3 separate gotchas about the same library
  could become one "Library X Gotchas" entry).
- Entries where merging would stay under ~1,500 tokens.

### H. Split Candidates

- Entries over ~1,500 tokens that cover multiple distinct topics.
- Entries where different sections have different scopes (part is global, part is
  project-specific).

### I. Contradiction Detection

- Entries that give conflicting advice on the same topic.
- A newer entry that implicitly contradicts an older one without superseding it.
- Preferences that conflict with patterns or architecture entries.

### J. Tag & Type Consistency

- Entries with missing or inconsistent tags.
- Entries whose `entry_type` doesn't match their content (e.g., a "gotcha" that reads
  like a "reference").
- Entries with fewer than 2 or more than 5 tags (outside the recommended range).

### K. Tag Vocabulary Audit

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

- **Overly narrow tags:** Tags used by only 1 entry that could be generalized. Example:
  `alembic-batch-mode` used once -> should probably just be `alembic` (the entry title
  and content already provide specificity).

- **Near-duplicates with different separators:** e.g., `error-handling` vs `errorhandling`
  vs `error_handling`.

- **Plural vs singular:** e.g., `migration` vs `migrations`, `index` vs `indexes`.
  Prefer singular.

For each tag merge, identify all affected entries so the user knows the blast radius.

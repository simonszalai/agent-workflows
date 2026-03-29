---
name: autodev-consolidate
description: >-
  Audit all memories applicable to the current repo (global + project-scoped).
  Checks validity, accuracy, redundancy, and structure. Read-only investigation
  that presents a numbered action list for user selection. Never modifies memories.
user_invocable: false
---

# Autodev Consolidate — Memory Audit & Consolidation Planner

Comprehensive audit of all memory entries that apply to the current working context. Reads
every applicable entry, cross-references with the actual codebase, identifies issues, and
presents a numbered list of proposed actions. The user picks which actions to execute.

**Critical rule: NEVER modify any memories. NEVER change any code. Investigation only.**

## When to Load

Loaded by the `/consolidate` command. Use when the memory system has accumulated entries over
time and needs a health check — stale entries, duplicates, entries that no longer match how the
code actually works, entries that could be merged or simplified.

## Procedure

### Step 1: Identify Scope

Determine the current project from the `<!-- mem:project=X -->` stub in CLAUDE.md. If not
found, ask the user.

Fetch the project topology:

```
mcp__autodev-memory__list_projects()
mcp__autodev-memory__list_repos(project_name: <project>)
```

The audit covers TWO scopes:
1. **Global entries** — apply to all projects
2. **Project-scoped entries** — specific to the current project (including repo-tagged ones)

### Step 2: Fetch All Applicable Entries

Fetch the complete entry index for both scopes:

```
mcp__autodev-memory__list_entries(project: "global")
mcp__autodev-memory__list_entries(project: <project>)
```

Also fetch superseded entries to check for orphaned chains:

```
mcp__autodev-memory__list_entries(project: "global", include_superseded: true)
mcp__autodev-memory__list_entries(project: <project>, include_superseded: true)
```

Record the total count. Report to user: "Found N global + M project-scoped entries. Reading
all of them..."

### Step 3: Read Every Entry

Fetch the full content of every active entry:

```
mcp__autodev-memory__get_entry(entry_id: <id>, project: <project>)
```

Batch these calls — run up to 5 in parallel to avoid overwhelming the API. For each entry,
record:

| Field | What to Note |
|---|---|
| `id` | Entry UUID |
| `title` | Entry title |
| `entry_type` | gotcha, pattern, preference, correction, solution, reference, architecture, glossary |
| `summary` | One-line summary |
| `content` | Full content text |
| `tags` | Tag list |
| `repos` | Repo filter (null = project-wide) |
| `scope` | "global" or project name |
| `created_at` | When created |
| `updated_at` | When last modified |
| `token_estimate` | Rough token count (~4 chars per token) |

### Step 4: Audit Each Entry

For every entry, evaluate these dimensions:

#### A. Validity — Is the information still correct?

- Cross-reference claims about code behavior with the actual codebase. If an entry says
  "function X does Y", grep for function X and verify.
- Check if referenced files, functions, classes, or config keys still exist.
- Check if referenced tools, libraries, or APIs are still in use (check package.json,
  pyproject.toml, requirements.txt).
- Flag entries that reference things that no longer exist or work differently.

#### B. Currency — Is this still relevant?

- Entries older than 6 months without updates deserve extra scrutiny.
- Check if the problem an entry describes has been fixed (e.g., a gotcha about a bug that
  was patched).
- Check if a workaround entry is still needed or if the proper fix landed.
- Check if architectural decisions described still reflect the current architecture.

#### C. Accuracy — Does this match how the code actually works?

- For pattern entries: does the codebase still follow this pattern?
- For architecture entries: does the described architecture still hold?
- For gotcha entries: is the gotcha still a real trap?
- For solution entries: does the solution still work?
- For preference entries: is the preference still being followed?

#### D. Scope — Is the entry scoped correctly?

- Is a project-scoped entry actually project-specific, or is it general enough to be global?
- Is a global entry actually universal, or is it only relevant to one project?
- Is the `repos` filter correct? (Should it be broader or narrower?)

#### E. Size & Quality — Is the entry well-structured?

- Entries under 50 tokens may be too terse to be useful.
- Entries over 1,500 tokens may need splitting.
- Is the summary search-friendly? Does it use vocabulary people naturally use?
- Is the content self-contained and actionable?
- Does the entry include WHY, not just WHAT?

### Step 5: Cross-Entry Analysis

After auditing individual entries, look across the full set for:

#### F. Duplicates & Overlaps

- Entries with similar titles covering the same topic.
- Entries where one is a subset of another (the smaller one can be deleted).
- Entries that say the same thing with different wording.

#### G. Merge Candidates

- Multiple small entries on closely related topics that would be clearer as one entry.
- Entries that form a natural group (e.g., 3 separate gotchas about the same library
  could become one "Library X Gotchas" entry).
- Entries where merging would stay under ~1,500 tokens.

#### H. Split Candidates

- Entries over ~1,500 tokens that cover multiple distinct topics.
- Entries where different sections have different scopes (part is global, part is
  project-specific).

#### I. Contradiction Detection

- Entries that give conflicting advice on the same topic.
- A newer entry that implicitly contradicts an older one without superseding it.
- Preferences that conflict with patterns or architecture entries.

#### J. Tag & Type Consistency

- Entries with missing or inconsistent tags.
- Entries whose `entry_type` doesn't match their content (e.g., a "gotcha" that reads
  like a "reference").
- Entries with fewer than 2 or more than 5 tags (outside the recommended range).

#### K. Tag Vocabulary Audit

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
  `alembic-batch-mode` used once → should probably just be `alembic` (the entry title
  and content already provide specificity).

- **Near-duplicates with different separators:** e.g., `error-handling` vs `errorhandling`
  vs `error_handling`.

- **Plural vs singular:** e.g., `migration` vs `migrations`, `index` vs `indexes`.
  Prefer singular.

For each tag merge, identify all affected entries so the user knows the blast radius.

### Step 6: Compile Findings

Organize all findings into a structured report. Group by action type and sort by impact
(highest impact first within each group).

### Step 7: Present Numbered Action List

Present findings as a numbered list of proposed actions. Each action should be self-contained
— the user should understand what will happen without reading the full audit.

## Output Format

```markdown
## Memory Consolidation Audit

**Date:** YYYY-MM-DD
**Project:** <project-name>
**Scope:** N global entries + M project-scoped entries (T total)

### Summary

<2-3 sentences on overall health and the most impactful findings>

### Proposed Actions

Pick the actions you want me to execute (e.g., "do 1, 3, 5-7, skip the rest").

#### Stale / Invalid

1. **DELETE** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ References `function_x()` which was removed in commit <hash>.
   No replacement needed — the function and its gotcha are gone.

2. **UPDATE** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ Says the API returns XML but it was switched to JSON 3 months ago.
   _Change:_ Update content to reflect JSON response format.

#### Duplicates & Merges

3. **MERGE** entries "<title A>" + "<title B>" → new entry "<merged title>"
   _Reason:_ Both cover Postgres connection pooling. A has the config details,
   B has the gotchas. Combined they'd be ~600 tokens — well within limits.

4. **DELETE** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ Subset of entry "<other title>" which already covers everything
   this one says plus more.

#### Scope Corrections

5. **RESCOPE** entry "<title>" from project to global
   _Reason:_ Describes a general SQLAlchemy pattern, not specific to this project.
   Other projects would benefit from finding this.

6. **RESCOPE** entry "<title>" from global to project "<name>"
   _Reason:_ References project-specific table names and business logic.
   Not useful to other projects.

#### Content Improvements

7. **SIMPLIFY** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ 1,800 tokens with redundant explanations. Can be cut to ~700
   without losing information.

8. **SPLIT** entry "<title>" into 2 entries
   _Reason:_ Covers both deployment gotchas and local dev setup. These are
   different topics with different audiences.

9. **IMPROVE SUMMARY** entry "<title>" (id: <short-id>, <scope>)
   _Reason:_ Summary says "database stuff" — not search-friendly.
   _Change:_ "Postgres JSONB column indexing patterns for partial key lookups"

#### Tag & Type Fixes

10. **RETYPE** entry "<title>" from "pattern" to "gotcha"
    _Reason:_ Content describes a trap and its workaround, not a pattern.

11. **RETAG** entry "<title>" — add tags: ["postgres", "indexing"]
    _Reason:_ Currently untagged. These tags match the content and improve
    search discoverability.

#### Tag Merges

12. **MERGE TAGS** `pg` + `postgres` + `postgresql` → `postgres` (N entries affected)
    _Entries:_ "<title A>" (pg), "<title B>" (postgresql), "<title C>" (postgres)
    _Reason:_ Three synonyms for the same technology. `postgres` is the most
    commonly used form. Will retag entries using non-canonical variants.

13. **MERGE TAGS** `js` → `javascript` (N entries affected)
    _Entries:_ "<title A>" (js)
    _Reason:_ Abbreviation. Full name is more searchable.

14. **FIX TAG CASING** `React-Router` → `react-router` (N entries affected)
    _Reason:_ Tags must be lowercase kebab-case per convention.

15. **DROP TAG** `misc` from entries "<title A>", "<title B>"
    _Reason:_ Too generic to aid search. Replacing with more specific tags.

#### Contradictions

12. **RESOLVE** contradiction between "<title A>" and "<title B>"
    _Reason:_ A says "always use TEXT columns", B says "use VARCHAR(255)
    for indexed columns". Need user decision on which is correct.

#### No Issues Found

- "<title>" — current, accurate, well-scoped
- "<title>" — current, accurate, well-scoped
- ...
```

## Key Principles

1. **Never execute without user selection.** Present the list, wait for the user to pick
   numbers. Only then execute the chosen actions.
2. **Verify against code, not just memory.** The codebase is the source of truth. If an entry
   says X but the code does Y, the entry is wrong (or outdated).
3. **Be specific in proposals.** Don't say "this entry could be improved" — say exactly what's
   wrong and what the fix looks like.
4. **Preserve information.** When proposing merges, note that all unique content from both
   sources will be preserved. When proposing deletions, explain why no information is lost.
5. **Bias toward fewer, better entries.** Three focused entries beat seven scattered ones.
   Merging is almost always better than keeping near-duplicates.
6. **Short IDs for readability.** Show first 8 chars of UUIDs in the action list.
7. **Group "no issues" entries.** Don't waste space on healthy entries — list them briefly
   at the bottom so the user knows they were reviewed.

## Executing Selected Actions

When the user selects actions (e.g., "do 1, 3, 5-7"), execute them using the autodev-save
skill's MCP patterns:

- **DELETE** → `mcp__autodev-memory__delete_entry(entry_id, project)`
- **UPDATE** → `mcp__autodev-memory__update_entry(entry_id, project, content, summary, ...)`
- **MERGE** → Create new entry with merged content via `mcp__autodev-memory__create_entry()`,
  then delete the source entries
- **RESCOPE** → Create new entry in the target scope, then delete the original (scope is
  immutable per entry, so rescoping requires recreate + delete)
- **SPLIT** → Create 2 new entries, delete the original
- **SIMPLIFY** → `mcp__autodev-memory__update_entry()` with trimmed content
- **RETYPE/RETAG** → `mcp__autodev-memory__update_entry()` with corrected type/tags
- **IMPROVE SUMMARY** → `mcp__autodev-memory__update_entry()` with better summary
- **MERGE TAGS** → For each affected entry, `mcp__autodev-memory__update_entry()` replacing
  the non-canonical tag with the canonical one in the tags array
- **FIX TAG CASING** → Same as MERGE TAGS — update each affected entry's tags
- **DROP TAG** → `mcp__autodev-memory__update_entry()` removing the tag, optionally adding
  a replacement
- **RESOLVE contradiction** → Ask user which is correct, then update or delete as directed

After executing, report what was done:

```
Executed 5 of 12 proposed actions:
- Deleted 2 stale entries
- Merged 1 pair → new entry "Postgres Connection Pooling" (id: abc12345)
- Rescoped 1 entry to global
- Simplified 1 entry (1,800 → 680 tokens)
```

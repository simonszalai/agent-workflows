---
name: consolidate
description: Audit all memories for the current repo. Checks validity, duplicates, scope, and structure. Proposes actions — never auto-modifies.
max_turns: 200
---

# Consolidate

Audit every memory entry applicable to the current repository — both global and project-scoped.
Cross-references entries against the actual codebase to find stale, duplicate, contradictory,
or poorly structured entries. Presents a numbered action list for user selection.

**Critical rule: NEVER modify any memories during audit. NEVER change any code. Investigation only
until the user selects actions.**

## Usage

```
/consolidate              # Full audit of all applicable entries
```

## When to Use

| Situation | Use This? |
|---|---|
| Memory system has grown organically, feels bloated | Yes |
| Suspect stale entries that reference deleted code | Yes |
| Multiple entries seem to cover the same topic | Yes |
| Entries feel too long, too short, or badly scoped | Yes |
| Want to add new knowledge | No — use /compound |
| Want to fix a memory search failure | No — use /wtf |

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

Evaluate every entry against the audit dimensions in `references/audit-checklist.md`
(dimensions A-E: Validity, Currency, Accuracy, Scope, Size & Quality).

### Step 5: Cross-Entry Analysis

After auditing individual entries, analyze across the full set using the cross-entry
dimensions in `references/audit-checklist.md` (dimensions F-K: Duplicates & Overlaps,
Merge Candidates, Split Candidates, Contradiction Detection, Tag & Type Consistency,
Tag Vocabulary Audit).

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

3. **MERGE** entries "<title A>" + "<title B>" -> new entry "<merged title>"
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

12. **MERGE TAGS** `pg` + `postgres` + `postgresql` -> `postgres` (N entries affected)
    _Entries:_ "<title A>" (pg), "<title B>" (postgresql), "<title C>" (postgres)
    _Reason:_ Three synonyms for the same technology. `postgres` is the most
    commonly used form. Will retag entries using non-canonical variants.

#### Contradictions

13. **RESOLVE** contradiction between "<title A>" and "<title B>"
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

When the user selects actions (e.g., "do 1, 3, 5-7"), execute them using MCP tools:

- **DELETE** -> `mcp__autodev-memory__delete_entry(entry_id, project)`
- **UPDATE** -> `mcp__autodev-memory__update_entry(entry_id, project, content, summary, ...)`
- **MERGE** -> Create new entry with merged content via `mcp__autodev-memory__create_entry()`,
  then delete the source entries
- **RESCOPE** -> Create new entry in the target scope, then delete the original (scope is
  immutable per entry, so rescoping requires recreate + delete)
- **SPLIT** -> Create 2 new entries, delete the original
- **SIMPLIFY** -> `mcp__autodev-memory__update_entry()` with trimmed content
- **RETYPE/RETAG** -> `mcp__autodev-memory__update_entry()` with corrected type/tags
- **IMPROVE SUMMARY** -> `mcp__autodev-memory__update_entry()` with better summary
- **MERGE TAGS** -> For each affected entry, `mcp__autodev-memory__update_entry()` replacing
  the non-canonical tag with the canonical one in the tags array
- **FIX TAG CASING** -> Same as MERGE TAGS — update each affected entry's tags
- **DROP TAG** -> `mcp__autodev-memory__update_entry()` removing the tag, optionally adding
  a replacement
- **RESOLVE contradiction** -> Ask user which is correct, then update or delete as directed

After executing, report what was done:

```
Executed 5 of 12 proposed actions:
- Deleted 2 stale entries
- Merged 1 pair -> new entry "Postgres Connection Pooling" (id: abc12345)
- Rescoped 1 entry to global
- Simplified 1 entry (1,800 -> 680 tokens)
```

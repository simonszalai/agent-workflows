---
name: autodev-ingest-knowledge
description: Ingest .claude/knowledge/ files and CLAUDE.md from project repos into autodev-memory
user_invocable: true
---

# Autodev Ingest Knowledge

Ingest `.claude/knowledge/` markdown files and `CLAUDE.md` from any repo into the
autodev-memory database via MCP tools. This is the structured knowledge that developers have
explicitly written down — gotchas, references, solutions, and patterns.

**Key principle:** One markdown file does NOT necessarily become one memory entry. The AI
reads all files, understands the knowledge holistically, then decides the optimal memory
entries — merging related files, splitting multi-topic files, rewriting for clarity, or
dropping redundant content. Each piece of knowledge gets the treatment it needs.

## When to Use

- After adding new gotchas, references, or solutions to `.claude/knowledge/`
- After updating a repo's `CLAUDE.md` with new rules or conventions
- Periodic bulk sync to keep memory up-to-date with all repos

## Usage

```
/autodev-ingest-knowledge                    # Ingest all repos in all known projects
/autodev-ingest-knowledge ts-prefect         # Ingest one specific repo
/autodev-ingest-knowledge --project ts       # Ingest all repos in a project
/autodev-ingest-knowledge --dry-run          # Preview what would be ingested without storing
```

## Step 1: Discover Topology

Resolve the project/repo mapping from the memory database:

```
mcp__autodev-memory__list_projects()     # Get all projects
mcp__autodev-memory__list_repos(project) # Get repos per project
```

**Repo path resolution:** repos live at `~/dev/{repo_name}`. Verify the path exists before
scanning. If a repo path doesn't exist, skip it and warn.

## Step 2: Collect and Read All Files

For each repo, collect files from two sources and **read their full contents**.

### Source A: Knowledge Directory (Primary)

Some projects (e.g., amaru-web) store knowledge at `knowledge/` instead of
`.claude/knowledge/`. Check both paths, preferring `.claude/knowledge/` if both exist.

```bash
# Check both paths (some projects use knowledge/ at root instead of .claude/knowledge/)
for knowledge_dir in "{repo_path}/.claude/knowledge" "{repo_path}/knowledge"; do
  if [[ -d "$knowledge_dir" ]]; then
    find "$knowledge_dir" -name "*.md" -not -name "README.md"
    break
  fi
done
```

**Directory-to-type hints:**

| Subdirectory  | default entry_type |
| ------------- | ------------------ |
| `gotchas/`    | gotcha             |
| `references/` | reference          |
| `solutions/`  | solution           |
| `patterns/`   | pattern            |
| `domain/`     | reference          |
| *(other)*     | reference          |

The directory is a hint, not a hard rule — the curation step may override it.

### Source B: `CLAUDE.md` (Repo Root)

If `{repo_path}/CLAUDE.md` exists, read it as input for curation.

### Parse Each File

For each collected file:

1. **Parse frontmatter** — extract YAML between `---` delimiters
2. **Extract title** — from frontmatter `title` field, or fall back to filename stem with
   dashes replaced by spaces and title-cased
3. **Extract body** — everything after the frontmatter block, stripped
4. **Record provenance** — file path relative to repo root, subdirectory under knowledge/,
   canonical_key (filename stem with trailing date pattern `-\d{8}$` removed)

If frontmatter parsing fails, use filename as title and full content as body.

## Step 3: Curate — Plan Optimal Memory Entries

This is the critical step. Do NOT blindly map files 1:1 to memory entries. The plan must
account for **both** the source files being ingested **and** what already exists in the
database. An ingestion that creates a new entry when it should have appended to an existing
one is a bug.

### 3a: Fetch Existing Entries for the Repo

Before planning, load what's already in the database for this repo:

```
mcp__autodev-memory__list_entries(project: <project>, repo: <repo_name>)
```

Also search for broader matches (an entry might be global or tagged to a different repo):

```
mcp__autodev-memory__search(
  queries: [{ "text": "<repo_name> conventions rules gotchas patterns" }],
  project: <project>,
  limit: 20
)
```

For every existing entry returned, **fetch its full content** with `get_entry()`. You cannot
decide whether to merge or skip based on titles and summaries alone — you need the full text
to know what's already covered.

### 3b: Evaluate Each Piece of Source Content

For every source file, ask:

1. **Does an existing entry already cover this topic?** This is the FIRST question, not an
   afterthought. If an existing entry covers the same domain (e.g., both are about alembic
   migrations, both are about proxy configuration, both are about auth cookies), the default
   action is **append** or **supersede** — not create new. Only create a separate entry if
   the topics are genuinely distinct and independently searchable.

2. **Is this one topic or several?** A file covering "auth cookies, session management, AND
   rate limiting gotchas" should be split into separate entries — each topic should be
   independently searchable.

3. **Does this overlap with another source file?** Two files about the same topic (e.g.,
   `proxy-rotation.md` and `proxy-fallback-patterns.md`) may be better as one merged entry
   than two near-duplicate memories.

4. **Is the content well-written for retrieval?** Knowledge entries are found via semantic
   search. Rewrite if the content is:
   - **Too bloated** — verbose explanations, excessive examples, filler text. Cut to the
     essential knowledge. A memory entry should be dense and scannable.
   - **Too sparse** — one-liners that lack context. Add enough detail that the entry is
     useful without its source file. Include the "why", not just the "what".
   - **Poorly structured** — wall of text that should be bullet points, or scattered points
     that need a coherent narrative.
   - **Missing search surface** — the title or content lacks the keywords someone would
     actually search for. Ensure the entry is findable.

5. **Is this still relevant?** Skip content that is clearly outdated, obsolete, or
   superseded by other files in the same batch.

6. **What's the right entry_type?** The directory hint may be wrong. A file in `references/`
   that describes a pitfall is really a `gotcha`. Use judgment.

### CLAUDE.md Special Handling

`CLAUDE.md` files are typically long and multi-topic. **Always split** them into logical
sections. Each major rule, convention, or architectural decision should become its own entry.
Do not ingest a full CLAUDE.md as a single entry — it will be too large and unfocused for
search.

### 3c: Fetch Existing Tags

Before producing the plan, fetch the existing tag vocabulary so planned entries reuse existing
tags. Follow the **autodev-tags** skill procedure (Step 1 only — get existing tags for the
target project + global). Keep the merged tag list available for Step 3d.

### 3d: Produce the Ingestion Plan

Each planned entry must specify an **action** — the plan encodes merge decisions, not just
content:

| Field | Description |
| --- | --- |
| `action` | **new**, **append**, **supersede**, or **skip** |
| `target_entry_id` | For append/supersede: the existing entry ID to modify |
| `title` | Clear, searchable title (for append/supersede: updated title if scope shifted) |
| `content` | The curated content (for append: **merged** content combining existing + new) |
| `entry_type` | gotcha, reference, solution, pattern, architecture, diagnosis |
| `tags` | 2-5 tags per entry, following autodev-tags skill rules (reuse existing, kebab-case, technology not concept) |
| `source_files` | List of source file paths this entry draws from |
| `rationale` | Why this action was chosen — must reference existing entry if append/supersede |

**Append vs supersede vs new — decision guide:**

- **Append**: Existing entry is good but the source file adds complementary information
  (e.g., existing entry covers "always create migrations" and source file adds "how to name
  and resolve multi-head conflicts"). Merge into one coherent entry. Update the title and
  summary if the combined scope has shifted.
- **Supersede**: Existing entry is outdated or the source file is a better/more complete
  version of the same knowledge. Replace entirely.
- **New**: No existing entry covers this topic. Genuinely distinct knowledge.
- **Skip**: Source file content is already fully covered by an existing entry.

**In `--dry-run` mode**, output the plan and stop. Do not proceed to ingestion.

## Step 4: Execute the Ingestion Plan

Process each planned entry sequentially. The plan already encodes the action (from Step 3),
so execute it directly — do NOT re-search or re-decide.

**Common fields for all actions:**

- `source`: `"ingested"`
- `project`: from the topology mapping (Step 1)
- `repos`: always `["{repo_name}"]`
- `tags`: from the plan (Step 3d), following autodev-tags skill rules
- `summary`: concise 1-sentence summary written for search relevance
- `caller_context.skill`: `"autodev-ingest-knowledge"`
- `caller_context.trigger`: `"user invoked /autodev-ingest-knowledge"`

**`source_metadata` fields:**

| Field | Required | Description |
| --- | --- | --- |
| `source_files` | Yes | Relative paths from repo root that contributed to this entry |
| `repo` | Yes | Repo name the files came from |
| `curation_rationale` | Yes | Why this entry was shaped this way |

**Execute by action type:**

- **new** → `mcp__autodev-memory__create_entry(...)` with all fields
- **append** → `mcp__autodev-memory__update_entry(entry_id: <target_entry_id>, ...)`
  with merged content, updated title/summary if scope shifted
- **supersede** → `mcp__autodev-memory__supersede_entry(old_entry_id: <target_entry_id>,
  ...)` with full new entry details
- **skip** → Log the decision, no MCP call

## Step 5: Report Results

```
Knowledge ingestion complete for project: ts

  ts-prefect:
    Source files:    89 knowledge/ + 1 CLAUDE.md
    Existing in DB:  42 entries fetched (full text read)
    Plan:            67 actions (31 new, 12 append, 3 supersede, 21 skip)
    Executed:        31 created, 12 appended, 3 superseded, 21 skipped, 0 errors

  ts-dashboard:
    Source files:    34 knowledge/ + 1 CLAUDE.md
    Existing in DB:  18 entries fetched (full text read)
    Plan:            41 actions (28 new, 5 append, 1 supersede, 7 skip)
    Executed:        28 created, 5 appended, 1 superseded, 7 skipped, 0 errors
```

## Handling Errors

- If ingestion returns an error for one entry, log it and continue with the next
- If a repo path doesn't exist, skip and warn
- If `.claude/knowledge/` doesn't exist for a repo, skip silently (not all repos have it)

## Adding a New Project

If ingesting for a project that doesn't exist yet in the memory database:

1. Create the project: `mcp__autodev-memory__create_project(project_name, description)`
2. Create each repo: `mcp__autodev-memory__create_repo(project_name, repo_name, description)`
3. Then proceed with ingestion as normal

## Parallelism

Process repos sequentially within a project. The curation step (Step 3) must see all files
for a repo at once to make good merge/split decisions. Ingestion within a repo is sequential
as required by the autodev-add-memory skill (each decision is informed by prior ones).

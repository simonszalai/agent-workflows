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

This is the critical step. Do NOT blindly map files 1:1 to memory entries. Instead, review
all collected content for the repo and produce an **ingestion plan** — a list of memory
entries to create, where each entry may draw from one or more source files, or a source file
may produce multiple entries.

### What to Evaluate for Each Piece of Content

For every source file, ask:

1. **Is this one topic or several?** A file covering "auth cookies, session management, AND
   rate limiting gotchas" should be split into separate entries — each topic should be
   independently searchable.

2. **Does this overlap with another file?** Two files about the same topic (e.g.,
   `proxy-rotation.md` and `proxy-fallback-patterns.md`) may be better as one merged entry
   than two near-duplicate memories.

3. **Is the content well-written for retrieval?** Knowledge entries are found via semantic
   search. Rewrite if the content is:
   - **Too bloated** — verbose explanations, excessive examples, filler text. Cut to the
     essential knowledge. A memory entry should be dense and scannable.
   - **Too sparse** — one-liners that lack context. Add enough detail that the entry is
     useful without its source file. Include the "why", not just the "what".
   - **Poorly structured** — wall of text that should be bullet points, or scattered points
     that need a coherent narrative.
   - **Missing search surface** — the title or content lacks the keywords someone would
     actually search for. Ensure the entry is findable.

4. **Is this still relevant?** Skip content that is clearly outdated, obsolete, or
   superseded by other files in the same batch.

5. **What's the right entry_type?** The directory hint may be wrong. A file in `references/`
   that describes a pitfall is really a `gotcha`. Use judgment.

### CLAUDE.md Special Handling

`CLAUDE.md` files are typically long and multi-topic. **Always split** them into logical
sections. Each major rule, convention, or architectural decision should become its own entry.
Do not ingest a full CLAUDE.md as a single entry — it will be too large and unfocused for
search.

### Produce the Ingestion Plan

For each planned memory entry, define:

| Field | Description |
| --- | --- |
| `title` | Clear, searchable title |
| `content` | The curated content (rewritten as needed) |
| `entry_type` | gotcha, reference, solution, pattern, architecture, diagnosis |
| `source_files` | List of source file paths this entry draws from |
| `rationale` | Brief note on why this structure was chosen (merge/split/rewrite/as-is) |

**In `--dry-run` mode**, output the plan and stop. Do not proceed to ingestion.

## Step 4: Ingest via autodev-add-memory

For each planned entry from the ingestion plan, use the **autodev-add-memory** skill to
ingest. Load that skill and follow its search -> decide -> act procedure sequentially,
passing:

- `source`: `"ingested"`
- `source_metadata`: provenance about the source file(s)
- `caller_context.skill`: `"autodev-ingest-knowledge"`
- `caller_context.trigger`: `"user invoked /autodev-ingest-knowledge"`

**Key field rules:**

- `project`: from the topology mapping (Step 1)
- `repos`: always `["{repo_name}"]` — single repo tag for the source repo
- `source`: always `"ingested"`
- `summary`: concise 1-sentence summary written for search relevance

**`source_metadata` fields:**

| Field | Required | Description |
| --- | --- | --- |
| `source_files` | Yes | List of relative paths from repo root that contributed to this entry |
| `repo` | Yes | Repo name the files came from |
| `curation_rationale` | Yes | Why this entry was shaped this way (merged/split/rewritten/as-is) |

**Note:** A planned entry may still be skipped by autodev-add-memory if it duplicates an
existing memory. That's expected — the curation step handles file-level dedup, and
autodev-add-memory handles memory-level dedup.

## Step 5: Report Results

```
Knowledge ingestion complete for project: ts

  ts-prefect:
    Source files:  89 knowledge/ + 1 CLAUDE.md
    Curated into:  67 planned entries (14 merged, 8 split, 23 rewritten, 22 as-is)
    Ingested:      42 new, 16 skipped (existing), 9 appended, 0 errors

  ts-dashboard:
    Source files:  34 knowledge/ + 1 CLAUDE.md
    Curated into:  41 planned entries (2 merged, 9 split, 12 rewritten, 18 as-is)
    Ingested:      38 new, 3 skipped (existing), 0 appended, 0 errors

  Total: 125 source files -> 108 planned entries -> 80 new, 19 skipped, 9 appended, 0 errors
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

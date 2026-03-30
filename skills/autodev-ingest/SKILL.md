---
name: autodev-ingest
description: Ingest structured knowledge from project repos into the autodev-memory database
user_invocable: true
---

# Autodev Ingest

Ingest `.claude/knowledge/` files, `CLAUDE.md`, and work item artifacts from any repo into the
autodev-memory database via MCP tools.

## When to Use

- After adding new gotchas, references, or solutions to `.claude/knowledge/`
- After resolving flow failures with investigation/conclusion docs
- After completing features with retrospectives or architectural decisions
- Periodic bulk sync to keep memory up-to-date with all repos

## Usage

```
/autodev-ingest                          # Ingest all repos in all known projects
/autodev-ingest ts-prefect               # Ingest one specific repo
/autodev-ingest --project ts             # Ingest all repos in a project
/autodev-ingest --dry-run                # Preview what would be ingested without storing
```

## Step 1: Discover Topology

Before ingesting, resolve the project/repo mapping from the memory database:

```
mcp__autodev-memory__list_projects()     # Get all projects
mcp__autodev-memory__list_repos(project) # Get repos per project
```

This returns the canonical mapping. Example:

| Project  | Repo                 | Local Path                    |
| -------- | -------------------- | ----------------------------- |
| ts       | ts-prefect           | ~/dev/ts-prefect              |
| ts       | ts-dashboard         | ~/dev/ts-dashboard            |
| ts       | ts-scraper           | ~/dev/ts-scraper              |
| ts       | ts-decrypt-chrome-ext| ~/dev/ts-decrypt-chrome-ext   |
| ts       | ts-decrypt-proxy     | ~/dev/ts-decrypt-proxy        |
| global   | agent-workflows      | ~/dev/agent-workflows         |

**Repo path resolution:** repos live at `~/dev/{repo_name}`. Verify the path exists before
scanning. If a repo path doesn't exist, skip it and warn.

## Step 2: Collect Files

For each repo, collect files from these sources in order:

### Source A: `.claude/knowledge/` (Primary)

```bash
find {repo_path}/.claude/knowledge -name "*.md" -not -name "README.md"
```

**Directory-to-type mapping:**

| Subdirectory  | entry_type  |
| ------------- | ----------- |
| `gotchas/`    | gotcha      |
| `references/` | reference   |
| `solutions/`  | solution    |
| `patterns/`   | pattern     |
| `domain/`     | reference   |
| *(other)*     | reference   |

The **top-level** directory under `knowledge/` determines the type. Nested subdirectories
inherit from their parent (e.g., `solutions/database/fix.md` is still `solution`).

### Source B: `CLAUDE.md` (Repo Root)

If `{repo_path}/CLAUDE.md` exists, ingest it as a single `reference` entry.

### Source C: Resolved Flow Failures (Optional)

```bash
find {repo_path}/work_items/flow_failures/resolved -name "conclusion.md"
find {repo_path}/work_items/flow_failures/resolved -name "investigation.md"
```

- `conclusion.md` files → `solution` type
- `investigation.md` files → `reference` type
- Title: derived from parent directory name (e.g., `B007-supervisor-prefect-server-520`)

### Source D: Feature Retrospectives (Optional)

```bash
find {repo_path}/work_items/completed -name "retrospective.md"
```

- `retrospective.md` files → `reference` type
- Title: derived from parent directory name

## Step 3: Parse Each File

For each collected file:

1. **Parse frontmatter** — extract YAML between `---` delimiters
2. **Extract title** — from frontmatter `title` field, or fall back to filename stem with
   dashes replaced by spaces and title-cased
3. **Extract body** — everything after the frontmatter block, stripped
4. **Generate canonical_key** — filename stem with trailing date pattern removed
   (`-\d{8}$` or `-YYYYMMDD`). Example: `auth-cookie-vicious-cycle-20260324.md` becomes
   `auth-cookie-vicious-cycle`
5. **Determine entry_type** — from directory mapping (Step 2)

## Step 4: Ingest via MCP

For each parsed file, call `mcp__autodev-memory__add_entry`:

```
mcp__autodev-memory__add_entry(
  title: "Auth Cookie Vicious Cycle",
  content: "<body without frontmatter>",
  entry_type: "gotcha",
  project: "ts",
  summary: "<first sentence or frontmatter summary>",
  canonical_key: "auth-cookie-vicious-cycle",
  repos: ["ts-prefect"],
  source: "ingested",
  caller_context: {
    "skill": "autodev-ingest",
    "reason": "Bulk knowledge ingestion from .claude/knowledge/gotchas/",
    "action_rationale": "New ingestion — add_entry handles dedup via content hash",
    "trigger": "user invoked /autodev-ingest"
  }
)
```

**Key field rules:**

- `project`: from the topology mapping (Step 1)
- `repos`: always `["{repo_name}"]` — single repo tag for the source repo
- `source`: always `"ingested"`
- `canonical_key`: generated from filename (Step 3)
- `summary`: first sentence of the body, or frontmatter `summary` if present

**CLAUDE.md special case:** When ingesting `CLAUDE.md`, use:
- `canonical_key`: `"{repo_name}-claude-md"`
- `title`: `"{repo_name} CLAUDE.md"`
- `repos`: `["{repo_name}"]`

**Work item special case:** When ingesting from `work_items/`, use:
- `canonical_key`: work item ID from directory name (e.g., `b007-supervisor-prefect-server-520`)
- `repos`: `["{repo_name}"]`

## Step 5: Report Results

After processing all files, print a summary:

```
Ingestion complete for project: ts

  ts-prefect:
    knowledge/:    89 files → 42 new, 47 duplicates, 0 errors
    CLAUDE.md:     1 file  → 0 new, 1 duplicate
    flow_failures: 12 files → 8 new, 4 duplicates
    retrospectives: 2 files → 2 new

  ts-dashboard:
    knowledge/:    34 files → 34 new, 0 duplicates, 0 errors
    CLAUDE.md:     1 file  → 1 new

  Total: 139 files processed, 127 new entries, 52 duplicates, 0 errors
```

## Deduplication

The memory system deduplicates via SHA-256 content hash per project. Re-running ingestion
on unchanged files is safe — they will be reported as duplicates and skipped. Modified files
get a new hash and create a new entry (the old entry remains; use `merge_entries` or
`update_entry` to consolidate if needed).

## Handling Errors

- If `add_entry` returns an error, log it and continue with the next file
- If a repo path doesn't exist, skip and warn
- If `.claude/knowledge/` doesn't exist for a repo, skip silently (not all repos have it)
- If frontmatter parsing fails, use filename as title and full content as body

## Adding a New Project

If ingesting for a project that doesn't exist yet in the memory database:

1. Create the project: `mcp__autodev-memory__create_project(project_name, description)`
2. Create each repo: `mcp__autodev-memory__create_repo(project_name, repo_name, description)`
3. Then proceed with ingestion as normal

## Parallelism

Process repos sequentially within a project to avoid overwhelming the embedding API. Files
within a repo can be processed in batches of 5-10 parallel `add_entry` calls since each
call is independent.

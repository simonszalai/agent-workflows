---
name: autodev-ingest-work-items
description: Ingest work item artifacts (flow failures, retrospectives, plans) into autodev-memory
user_invocable: true
---

# Autodev Ingest Work Items

Ingest knowledge from work item artifacts — resolved flow failures, feature retrospectives,
investigation reports, and plans — into the autodev-memory database via MCP tools. These are
operational learnings that emerge from building and debugging.

## When to Use

- After resolving flow failures with investigation/conclusion docs
- After completing features with retrospectives or architectural decisions
- After closing work items that contain valuable investigation reports
- Periodic sweep to capture work item knowledge that was never ingested

## Usage

```
/autodev-ingest-work-items                   # Ingest all repos in all known projects
/autodev-ingest-work-items ts-prefect        # Ingest one specific repo
/autodev-ingest-work-items --project ts      # Ingest all repos in a project
/autodev-ingest-work-items --dry-run         # Preview what would be ingested without storing
```

## Step 1: Discover Topology

Resolve the project/repo mapping from the memory database:

```
mcp__autodev-memory__list_projects()     # Get all projects
mcp__autodev-memory__list_repos(project) # Get repos per project
```

**Repo path resolution:** repos live at `~/dev/{repo_name}`. Verify the path exists before
scanning. If a repo path doesn't exist, skip it and warn.

## Step 2: Collect Files

For each repo, scan these work item locations:

### Source A: Resolved Flow Failures

```bash
find {repo_path}/work_items/flow_failures/resolved -name "conclusion.md"
find {repo_path}/work_items/flow_failures/resolved -name "investigation.md"
```

- `conclusion.md` files -> `solution` type (the fix/resolution)
- `investigation.md` files -> Skip by default. Only ingest if the investigation reveals a
  reusable anti-pattern (not just project-specific operational details).
- Title: derived from parent directory name (e.g., `B007-supervisor-prefect-server-520`)

### Source B: Feature Retrospectives

```bash
find {repo_path}/work_items/completed -name "retrospective.md"
find {repo_path}/work_items/closed -name "retrospective.md"
```

- `retrospective.md` files -> `reference` type
- Title: derived from parent directory name (e.g., `F003-add-user-dashboard`)

### Source C: Investigation Reports

```bash
find {repo_path}/work_items/closed -name "investigation.md"
find {repo_path}/work_items/completed -name "investigation.md"
```

- `investigation.md` files -> `reference` type
- Title: derived from parent directory name

### Source D: Plans with Architectural Decisions

- `plan.md`: Skip entirely. Plans are forward-looking design documents, not lessons about
  what went wrong. They contain zero signal for the memory system.

### Source E: Review findings with AI-introduced bugs

```bash
find {repo_path}/work_items -path "*/review_todos/*.md" -not -name "README.md"
```

- Only ingest review findings where **the AI introduced a real bug or anti-pattern**
- Skip generic code quality advice the AI already knows (magic numbers, stale comments,
  unused variables, "use Pydantic not dataclass" — these are coding standards, not memory)
- **Signal**: The finding describes something the AI built incorrectly that caused a real
  issue (security gap, data loss, race condition, deployment failure, framework misuse)
- **Noise**: The finding describes general best practices the AI conceptually knows but
  happened to miss in this instance
- Map to appropriate type based on essence: gotcha, pattern, solution, etc.
- Title: Prefix with work item ID for traceability

**Do NOT ingest from active/ or backlog/** — those work items are still in progress and
their artifacts may change.

## Step 3: Parse Each File

For each collected file:

1. **Parse frontmatter** — extract YAML between `---` delimiters (if present)
2. **Extract title** — from frontmatter `title` field, or derive from the work item
   directory name: strip the ID prefix, replace dashes with spaces, title-case.
   Example: `B007-supervisor-prefect-server-520` -> `Supervisor Prefect Server 520`
3. **Prefix the title with the work item ID** for traceability.
   Example: `B007: Supervisor Prefect Server 520`
4. **Extract body** — everything after the frontmatter block, stripped
5. **Generate canonical_key** — the full work item directory name in lowercase.
   Example: `b007-supervisor-prefect-server-520`
6. **Determine entry_type** — from the file type mapping (Step 2)

## Step 4: Ingest via autodev-add-memory

For each parsed file, use the **autodev-add-memory** skill to ingest. Load that skill and
follow its search -> decide -> act procedure for each file sequentially, passing:

- `source`: `"ingested"`
- `source_metadata`: provenance about the work item
- `caller_context.skill`: `"autodev-ingest-work-items"`
- `caller_context.trigger`: `"user invoked /autodev-ingest-work-items"`

**Key field rules:**

- `project`: from the topology mapping (Step 1)
- `repos`: always `["{repo_name}"]` — single repo tag for the source repo
- `source`: always `"ingested"`
- `summary`: first paragraph of the body that describes the problem or resolution

**`source_metadata` fields:**

| Field | Required | Description |
| --- | --- | --- |
| `file_path` | Yes | Relative path from repo root (e.g., `work_items/flow_failures/resolved/B007-.../conclusion.md`) |
| `repo` | Yes | Repo name the file came from |
| `canonical_key` | Yes | Work item directory name in lowercase |
| `work_item_id` | Yes | The ID portion (e.g., `B007`, `F003`) |
| `work_item_type` | Yes | One of: `flow_failure`, `feature`, `bug`, `optimization` |
| `artifact_type` | Yes | One of: `conclusion`, `investigation`, `retrospective`, `plan`, `review_todo` |

## Step 5: Report Results

```
Work item ingestion complete for project: ts

  ts-prefect:
    flow_failures:   12 items -> 16 files -> 8 new, 6 skipped, 2 appended
    retrospectives:   3 items ->  3 files -> 3 new
    investigations:   2 items ->  2 files -> 1 new, 1 skipped
    plans:            5 items ->  2 files -> 2 new (3 skipped as trivial)

  ts-scraper:
    flow_failures:    4 items ->  6 files -> 6 new
    retrospectives:   0 items

  Total: 29 files processed, 20 new, 7 skipped, 2 appended, 0 errors
```

## Handling Errors

- If ingestion returns an error, log it and continue with the next file
- If a repo path doesn't exist, skip and warn
- If `work_items/` doesn't exist for a repo, skip silently
- If frontmatter parsing fails, derive title from directory name and use full content as body

## Parallelism

Process repos sequentially within a project. Files within a repo are processed sequentially
as required by the autodev-add-memory skill (each ingestion decision is informed by what
happened to previous files).

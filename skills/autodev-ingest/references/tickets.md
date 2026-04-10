# Autodev Ingest Tickets

Migrate the filesystem-based `work_items/` directories into the database ticket system.
Tickets are **repo-scoped** — each repo maintains its own numbering (F001 in ts-scraper is
independent of F001 in ts-prefect). Original IDs are preserved.

## When to Use

- One-time migration of existing work items into the ticket system
- After new work items are created outside the ticket system

## Usage

```
/autodev-ingest-tickets                     # All repos in all projects
/autodev-ingest-tickets ts-prefect          # One specific repo
/autodev-ingest-tickets --project ts        # All repos in a project
/autodev-ingest-tickets --dry-run           # Preview without creating tickets
```

## Step 1: Discover Topology

Query the memory database for the project/repo mapping:

```
mcp__autodev-memory__list_projects()
mcp__autodev-memory__list_repos(project_name=...)
```

**Repo path resolution:** repos live at `~/dev/{repo_name}`. Verify each path exists. Skip
and warn if missing.

Build a reverse lookup: repo_name → project_name (e.g., "ts-prefect" → "ts").

## Step 2: Load Existing Tickets for Deduplication

For each project, list all existing tickets:

```
mcp__autodev-memory__list_tickets(project=..., limit=500)
```

Build a set of `(repo, ticket_id)` pairs to skip duplicates. The ticket_id here is the
display_id like "F0004" and repo is the repo column.

## Step 3: Scan Work Item Directories

For each repo, scan all work item locations. List directory contents with Glob or ls:

```
{repo_path}/work_items/active/
{repo_path}/work_items/backlog/
{repo_path}/work_items/to_verify/
{repo_path}/work_items/closed/
{repo_path}/work_items/completed/
{repo_path}/work_items/flow_failures/ongoing/
{repo_path}/work_items/flow_failures/resolved/
```

Each subdirectory matching a naming pattern is a work item:

| Pattern | Type | Prefix |
|---|---|---|
| `F###-slug` | feature | F |
| `B###-slug` | bug | B |
| `O###-slug` | refactor | R |
| `R###-slug` | refactor | R |
| `###-slug` (no letter prefix) | bug | B |

**Extract the original seq_num** from the directory name (e.g., `F045` → seq_num=45).

## Step 4: Handle Duplicates Within a Repo

Some repos have duplicate IDs (e.g., two `F052-*` directories in ts-prefect). Before
ingesting, detect duplicates by grouping work items by their (type_prefix, seq_num).

For each duplicate group:
1. Read the `source.md` of each duplicate
2. Compare: which is more meaningful? Consider:
   - Does it have a plan.md or build_todos? (more complete = keep)
   - Is the content longer and more detailed?
   - Is the status further along (completed > active > backlog)?
3. **Keep the more meaningful one, skip the other**
4. Log which was skipped and why

## Step 5: Parse Each Work Item

### 5a. Parse source.md

Read `source.md` (or first `.md` file if source.md missing).

1. **Parse YAML frontmatter** between `---` delimiters
2. **Extract fields:**

**Type mapping:**

| Frontmatter `type` / folder prefix | Ticket `type` |
|---|---|
| `feature`, `F` prefix | `feature` |
| `bug`, `B` prefix, plain number | `bug` |
| `refactor`, `R` prefix | `refactor` |
| `optimization`, `O` prefix | `refactor` |
| `investigation` | `bug` |

**Status mapping (from folder location):**

| Folder | Ticket `status` |
|---|---|
| `active/` | `active` |
| `backlog/` | `backlog` |
| `to_verify/` | `to_verify` |
| `closed/` | `completed` |
| `completed/` | `completed` |
| `flow_failures/ongoing/` | `active` |
| `flow_failures/resolved/` | `completed` |

**Priority mapping:**

| Source | Ticket `priority` |
|---|---|
| `p0`, `1`, `high` | `p0` |
| `p1`, `2`, `medium` | `p1` |
| `p2`, `3`, `low` | `p2` |
| missing / other | `null` |

3. **Extract title** from frontmatter `title`, or derive from directory name
4. **Extract description** — full markdown body after frontmatter

### 5b. Collect Artifacts

Scan for additional files:

| File | Artifact Type | Notes |
|---|---|---|
| `plan.md` | `plan` | Single artifact |
| `investigation.md` | `investigation` | Single artifact |
| `retrospective.md` | `retrospective` | Single artifact |
| `build_todos/NN-name.md` | `build_todo` | One per file, `sequence` = NN |
| `review_todos/NN-name.md` | `review_todo` | One per file, `sequence` = NN |
| `learning-report.md` | `learning_report` | Single artifact |
| `deployment-guide.md` | `deployment_guide` | Single artifact |

For each artifact file:
1. Parse frontmatter if present
2. Extract title from frontmatter or filename
3. Extract content (body after frontmatter)
4. For todos: extract `sequence` from `NN-` prefix
5. For review_todos: put `status`, `priority`, `source` into `metadata`

### 5c. Build Tags

```json
{
  "original_folder": "active",
  "estimated_hours": 8,
  "severity": "high",
  "source": "conversation",
  "flow_failure": true
}
```

Include any non-standard frontmatter fields as tags. Set `flow_failure: true` for items from
`flow_failures/`.

### 5d. Build Related References

Map frontmatter `related` field to ticket format. Use the repo→project lookup:

| Source format | Ticket `related` format |
|---|---|
| `ts-scraper/F042` | `[{"project": "ts", "repo": "ts-scraper", "ticket": "F0042"}]` |

Pad numbers to 4 digits.

## Step 6: Create Tickets

For each parsed work item:

### 6a. Create the Ticket with Explicit seq_num

```
mcp__autodev-memory__create_ticket(
  project=...,
  repo=...,
  title=...,
  type=...,
  description=<source.md content>,
  status=...,
  priority=...,
  quarter=...,
  related=...,
  depends_on=[],
  tags=...,
  seq_num=<original seq_num from directory name>,
  command="/autodev-ingest-tickets",
  agent="ingest"
)
```

**Key:** `seq_num` preserves the original ID. F045 in ts-scraper stays F0045 in the ticket
system because tickets are repo-scoped.

### 6b. Create Additional Artifacts

For each non-source artifact:

```
mcp__autodev-memory__create_artifact(
  project=...,
  ticket_id=<display_id from 6a>,
  repo=...,
  artifact_type=...,
  content=<artifact body>,
  title=<artifact title>,
  sequence=<for todos>,
  status=<for todos>,
  metadata=<for review_todos>,
  command="/autodev-ingest-tickets",
  agent="ingest"
)
```

## Step 7: Report Results

```
Ticket ingestion complete for project: ts

  ts-prefect:
    Scanned: 92 directories
    Duplicates resolved: 8 (skipped less meaningful duplicate)
    Created: 73 tickets (52 features, 13 bugs, 8 refactors)
    Skipped: 7 (already exist in DB)
    Artifacts: 210 total
    Errors: 0

  ts-scraper:
    Scanned: 8 directories
    Created: 8 tickets (8 features)
    Artifacts: 24

  Total: 100 directories -> 81 tickets, 234 artifacts, 8 duplicates resolved, 0 errors
```

## Processing Order

1. Process repos **sequentially** within a project
2. Within a repo, process work items in **directory name order** (sorted alphabetically
   so F001 comes before F002)
3. Within a work item: ticket first, then artifacts in order:
   source (auto) → plan → investigation → build_todos → review_todos →
   retrospective → learning_report → deployment_guide

## Error Handling

| Error | Action |
|---|---|
| Repo path doesn't exist | Skip repo, warn |
| No `work_items/` directory | Skip silently |
| No `source.md` in work item | Try first `.md`; if none, skip and warn |
| Frontmatter parse failure | Derive from dir name, use full content |
| `create_ticket` error | Log, skip work item, continue |
| `create_artifact` error | Log, continue with next artifact |
| Duplicate in DB | Skip (already ingested) |

## Idempotency

Safe to run multiple times. Checks existing tickets by `(repo, display_id)` before creating.
Already-ingested tickets are skipped entirely.

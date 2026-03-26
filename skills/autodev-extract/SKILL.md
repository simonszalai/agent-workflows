---
name: autodev-extract
description: Extract knowledge from Claude Code session logs and Conductor conversations
user_invocable: true
---

# Autodev Extract

Mine Claude Code session transcripts and Conductor data for knowledge that was never formally
captured. Identifies corrections, debugging resolutions, repeated patterns, and architectural
decisions embedded in conversation history.

## When to Use

- Periodic knowledge harvesting (weekly/monthly)
- After a burst of debugging sessions
- When you suspect useful learnings exist in session history but weren't captured as gotchas
- To find patterns across many sessions (e.g., "what mistakes keep recurring?")

## Usage

```
/autodev-extract                         # Process unprocessed sessions across all projects
/autodev-extract ts-prefect              # Process sessions for one repo only
/autodev-extract --since 7d              # Only sessions from the last 7 days
/autodev-extract --topic "migration"     # Focus extraction on a specific topic
/autodev-extract --review-only           # Show candidates without ingesting
```

## Data Sources

### Claude Code Session Transcripts (Primary)

**Location:** `~/.claude/projects/`

Each project directory contains:
- `sessions-index.json` — manifest with session metadata
- `{sessionId}.jsonl` — full conversation transcript (one JSON object per line)
- `{sessionId}/subagents/` — subagent conversation transcripts

**Session index structure:**
```json
{
  "entries": [{
    "sessionId": "uuid",
    "projectPath": "/Users/simon/dev/ts-prefect",
    "gitBranch": "branch-name",
    "messageCount": 14,
    "created": "ISO-8601",
    "modified": "ISO-8601",
    "summary": "short description",
    "isSidechain": false
  }]
}
```

**JSONL message structure:**
```json
{
  "type": "user|assistant|progress",
  "message": {
    "role": "user|assistant",
    "content": "string | [{type: 'text', text: '...'}, {type: 'tool_use', name: '...'}]"
  },
  "sessionId": "uuid",
  "timestamp": "ISO-8601",
  "cwd": "/path/to/project"
}
```

### Conductor Database (Secondary)

**Location:** `~/Library/Application Support/com.conductor.app/conductor.db` (SQLite)

Key tables:
- `session_messages` — 330K+ messages with full text (role, content, session_id)
- `diff_comments` — code review comments with file/line context
- `workspaces` — branch names, PR titles/descriptions, notes

## Progress Tracking

Session volume is too large for single-batch processing. Track progress in a persistent
state file:

**State file:** `~/.local/share/autodev-extract/progress.json`

```json
{
  "version": 1,
  "last_run": "2026-03-25T12:00:00Z",
  "processed_sessions": {
    "a820f041-19a9-4136-96ca-0fe6bcaf9a4c": {
      "processed_at": "2026-03-25T12:00:00Z",
      "message_count": 14,
      "candidates_found": 2,
      "project_path": "/Users/simon/dev/ts-prefect"
    }
  },
  "stats": {
    "total_sessions_processed": 142,
    "total_candidates_found": 38,
    "total_entries_created": 22,
    "last_full_scan": "2026-03-20T00:00:00Z"
  }
}
```

**On each run:**
1. Load progress.json (create if missing)
2. Scan all session indexes for sessions not in `processed_sessions`
3. Process only unprocessed sessions (or those matching `--since` filter)
4. Update progress.json after each session completes

**Create the state directory on first run:**
```bash
mkdir -p ~/.local/share/autodev-extract
```

## Project/Repo Resolution

Map session `projectPath` to project + repo for correct entry tagging:

**Resolution rules (checked in order):**

1. **Direct repo match:** `~/dev/{name}` — repo_name = `{name}`
2. **Conductor workspace:** `~/conductor/workspaces/{repo}/{workspace}` — repo_name = `{repo}`
3. **Branch worktree:** `~/dev/{repo}.{branch}` — repo_name = `{repo}`

**Then resolve project from repo:**
```
mcp__autodev-memory__list_projects() → for each project:
  mcp__autodev-memory__list_repos(project) → check if repo_name is in the list
```

**Fallback:** If a repo isn't registered in any project, use `project: "global"` and
`repos: null`. Log a warning so the user can register it.

**Cache the topology** at the start of each run to avoid repeated MCP calls.

## Extraction Patterns

For each unprocessed session, read the JSONL and scan for these knowledge signals:

### Pattern 1: User Corrections

**Signal:** User says something like "no", "that's wrong", "actually", "don't do that",
"you should have", "the correct way is", "stop doing X"

**Extraction logic:**
1. Find user messages containing correction language
2. Capture the assistant's prior message (what was wrong)
3. Capture the user's correction (what's right)
4. Generate a `correction` entry

**Example:**
```
User: "No, never suppress flow failures. They are intentional observability."
→ correction entry: "Flow failures are intentional — never suppress"
```

### Pattern 2: Debugging Resolutions

**Signal:** Multi-turn investigation that ends with a fix or root cause identification.
Look for patterns like:
- Session starts with error/bug description
- Multiple tool_use calls (Read, Grep, Bash) investigating
- Ends with an Edit/Write that fixes the issue
- Or ends with the user confirming the root cause

**Extraction logic:**
1. Identify sessions where early messages contain error text or "failing", "broken", etc.
2. Find the resolution — the last substantive assistant message or the fix applied
3. Generate a `solution` or `gotcha` entry with the problem + resolution

### Pattern 3: Repeated Questions

**Signal:** Same concept asked about across multiple sessions (same or different repos).

**Extraction logic:**
1. Collect user prompts from all sessions being processed
2. Group semantically similar questions (use the session summary as a proxy)
3. If a question appears 3+ times, it should be a `reference` entry

### Pattern 4: Architectural Decisions

**Signal:** Sessions where the user discusses design, architecture, or "should we" choices
and arrives at a decision.

**Extraction logic:**
1. Find sessions with planning/architecture language in user prompts
2. Look for definitive statements: "let's go with", "the approach is", "we decided"
3. Generate an `architecture` or `reference` entry

### Pattern 5: Diff Comments (Conductor)

**Signal:** Code review comments in the Conductor database.

**Extraction logic:**
1. Query `diff_comments` table for unprocessed comments
2. Group by workspace (which maps to a repo/branch)
3. Extract review findings that identify patterns or gotchas
4. Generate `gotcha` or `pattern` entries

## Processing a Single Session

```
1. Read {sessionId}.jsonl line by line
2. Build a message timeline: [(role, content_text, timestamp)]
   - For assistant messages with content blocks, extract text blocks only
   - Skip tool_use and tool_result blocks (they're noise for knowledge extraction)
   - Skip progress messages
3. Scan the timeline for extraction patterns (above)
4. For each candidate found, create a KnowledgeCandidate:
   {
     "title": "descriptive title",
     "content": "full knowledge content with context",
     "entry_type": "gotcha|correction|solution|reference|architecture",
     "project": "ts",
     "repos": ["ts-prefect"],
     "canonical_key": "kebab-case-key",
     "source_session": "sessionId",
     "source_timestamp": "ISO-8601",
     "confidence": "high|medium|low",
     "evidence": "the specific messages that support this"
   }
5. Filter: only keep candidates with medium or high confidence
6. Check for duplicates: search existing entries via
   mcp__autodev-memory__search(queries=[candidate.title], project=project)
   If similarity > 0.85, skip (already known)
7. Present candidates to user for review (unless --auto flag)
```

## Review Before Ingestion

By default, show candidates grouped by project/repo and let the user approve:

```
Found 5 knowledge candidates from 23 sessions:

[1] GOTCHA (high confidence) — ts-prefect
    Title: pgvector HNSW index limit on local dev
    Source: session abc123 (2026-03-15)
    Evidence: "Local pgvector 0.8.1 has a 2000-dim HNSW index limit..."
    → Ingest? [y/n/edit]

[2] CORRECTION (medium confidence) — ts-scraper
    Title: Scrapling response body is always string not bytes
    Source: session def456 (2026-03-18)
    Evidence: User corrected: "response.text not response.content..."
    → Ingest? [y/n/edit]

...
```

When the user approves, ingest via:

```
mcp__autodev-memory__add_entry(
  title: candidate.title,
  content: candidate.content,
  entry_type: candidate.entry_type,
  project: candidate.project,
  repos: candidate.repos,
  source: "captured",
  canonical_key: candidate.canonical_key,
  caller_context: {
    "skill": "autodev-extract",
    "reason": "Extracted from session log — <pattern type>",
    "action_rationale": "No existing entry found above 0.85 similarity",
    "trigger": "session log analysis of {sessionId}"
  }
)
```

Note: `source` is `"captured"` (not `"ingested"`) because these entries are derived from
conversations, not directly copied from files.

## Batch Processing Strategy

Given ~5,280 sessions totaling ~2.1 GB:

1. **First run:** Process by recency — start with the last 30 days of sessions
2. **Subsequent runs:** Only process new sessions (tracked via progress.json)
3. **Backfill:** Use `--since 90d` or `--since 180d` to gradually process older sessions
4. **Per-session budget:** Read at most 500 messages per session. For larger sessions,
   focus on user messages and the final assistant response (where resolutions live).
5. **Rate limiting:** Process 10-20 sessions per run to keep context manageable

## Session Filtering

Skip sessions that are unlikely to contain extractable knowledge:

- Sessions with `messageCount < 4` (too short for meaningful knowledge)
- Sessions where `isSidechain: true` (subagent work, already captured by parent)
- Sessions older than 6 months (diminishing relevance)
- Sessions from repos not registered in any project (unless `--include-unregistered`)

## Output

After each run, print:

```
Extraction complete (23 sessions processed, 142 remaining)

  Candidates found: 5
    - 2 gotchas (ts-prefect)
    - 1 correction (ts-scraper)
    - 1 solution (ts-prefect)
    - 1 reference (ts-dashboard)

  Ingested: 4 (1 skipped by user)
  Duplicates: 0

  Progress: 165/5280 sessions processed (3.1%)
  State saved to ~/.local/share/autodev-extract/progress.json
```

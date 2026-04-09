---
name: autodev-extract
description: Extract knowledge from Claude session logs and Conductor conversations
user_invocable: true
---

# Autodev Extract

Mine Claude session logs and Conductor data for knowledge that was never formally
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

### Claude Session Logs (Primary)

**Location:** `~/.claude/projects/`

Each project directory contains:
- `sessions-index.json` — manifest with session metadata
- `{sessionId}.jsonl` — Claude session log (one JSON object per line)
- `{sessionId}/subagents/` — subagent Claude session logs

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

**Signal:** The user corrects the assistant's approach, assumption, or output. This is NOT
limited to explicit phrases — use judgment to detect corrective intent broadly, including:

- Explicit corrections: "no", "that's wrong", "actually", "don't do that"
- Implicit corrections: user redoes what the assistant just did (differently), user provides
  context that contradicts what the assistant assumed, user answers a question in a way that
  reveals the assistant was on the wrong track
- Behavioral corrections: "we don't do it that way", "that's not how it works here"
- Preference signals: user consistently rejects a certain approach across the conversation
- Redirections: user ignores the assistant's suggestion and asks for something different

**Extraction logic:**
1. Read the full conversation flow — don't grep for keywords
2. When the user's message changes the direction of what the assistant was doing, that's a
   correction even if the user is polite or indirect about it
3. Capture the assistant's prior approach (what was wrong/rejected)
4. Capture what the user wanted instead (what's right)
5. Generate a `diagnosis` entry

**Example:**
```
User: "No, never suppress flow failures. They are intentional observability."
→ diagnosis entry: "Flow failures are intentional — never suppress"

Assistant asks: "Should I add error handling around this?"
User: "it already has error handling, the issue is the selector changed"
→ diagnosis entry: "Investigate actual root cause before adding error handling"
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
     "entry_type": "gotcha|diagnosis|solution|reference|architecture",
     "project": "ts",
     "repos": ["ts-prefect"],
     "source_session": "sessionId",
     "source_timestamp": "ISO-8601",
     "extraction_pattern": "user_correction|debugging_resolution|repeated_question|
                            architectural_decision|diff_comment",
     "project_path": "/Users/simon/dev/ts-prefect",
     "git_branch": "fix/auth-retry",
     "confidence": "high|medium|low",
     "evidence": "the specific messages that support this"
   }
5. Filter: only keep candidates with medium or high confidence
6. Present candidates to user for review (unless --auto flag)
7. Ingest approved candidates sequentially (see Ingestion Loop below)
```

## Review Before Ingestion

Show candidates grouped by project/repo and let the user approve:

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
```

## Ingestion

Ingest approved candidates using the **autodev-add-memory** skill. Load that skill and
follow its procedure for each candidate sequentially, passing:

- `source`: `"captured"` (not `"ingested"` — these are derived from conversations)
- `source_metadata`: rich provenance about where this was extracted from (see table below)
- `caller_context.skill`: `"autodev-extract"`
- `caller_context.trigger`: `"session {sessionId}"`

**`source_metadata` fields for captured entries:**

| Field | Required | Description |
| --- | --- | --- |
| `session_id` | Yes | Claude Code session UUID or Conductor conversation ID |
| `extraction_pattern` | Yes | Which pattern matched (`user_correction`, `debugging_resolution`, `repeated_question`, `architectural_decision`, `diff_comment`) |
| `confidence` | Yes | Extraction confidence (`high`, `medium`, `low`) |
| `source_timestamp` | Yes | ISO-8601 timestamp of the source message(s) |
| `project_path` | No | Original project path from the session |
| `git_branch` | No | Git branch active during the session |
| `conductor_workspace` | No | Conductor workspace name (for Conductor-sourced entries) |
| `message_range` | No | Approximate message indices containing the knowledge (e.g., `"42-58"`) |

The autodev-add-memory skill handles searching for related entries, deciding whether to
create new / append / supersede / skip, and executing the action.

## Batch Processing Strategy

Given ~5,280 sessions totaling ~2.1 GB:

1. **First run:** Process by recency — start with the last 30 days of sessions
2. **Subsequent runs:** Only process new sessions (tracked via progress.json)
3. **Backfill:** Use `--since 90d` or `--since 180d` to gradually process older sessions
4. **Per-session budget:** Read at most 500 messages per session. For larger sessions,
   focus on user messages and the final assistant response (where resolutions live).
5. **Rate limiting:** 50 sessions per run for backfill (`--since 90d+`), 10-20 for
   incremental runs

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
    - 1 diagnosis (ts-scraper)
    - 1 solution (ts-prefect)
    - 1 reference (ts-dashboard)

  Ingestion results:
    - 2 new entries created
    - 1 appended to existing entry "DataDome blocking patterns" (entry abc123)
    - 1 superseded "old pgvector config" (entry def456)
    - 1 skipped (already covered by "Scrapling response types")

  Progress: 165/5280 sessions processed (3.1%)
  State saved to ~/.local/share/autodev-extract/progress.json
```

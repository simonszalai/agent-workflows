---
name: autodev-improve
description: >-
  Audit the autodev-memory system against real session evidence. Parses Claude
  session JSONL logs to verify memories surface when needed, MCP tools are called
  appropriately, bloat is minimized, and the knowledge pipeline is functioning
  end-to-end. Propose-only, never auto-implements.
user_invocable: true
argument-hint: "[project] [focus-area]"
---

# Autodev Improve

Evidence-based audit of the autodev-memory system. Every finding must be backed by
data from session logs, operation logs, or the knowledge base — not speculation.

Use this for:

- **Surfacing verification** — are the right memories reaching the right agent at the
  right time? Cross-reference session JSONL against the knowledge base.
- **MCP tool call verification** — is Claude calling `mcp__autodev-memory__search`,
  `create_entry`, etc. when it should? Are there missed opportunities?
- **Bloat detection** — entries that are never retrieved, duplicate CLAUDE.md content,
  overlapping entries, stale knowledge
- **Hook effectiveness** — are hooks firing, returning results, and are those results
  being consumed by Claude?
- **Design evaluation** — switching embedding models, changing chunking, adding new
  entry types, restructuring schema
- **Pipeline completeness** — are corrections being captured? Are zero-result searches
  signaling gaps?

When invoked with a specific question or idea, skip the full audit and focus the
analysis on that topic. When invoked without context, run a broad audit.

**Rule: Propose only. Never auto-implement changes.**

## Data Sources — In Priority Order

### 0. Session JSONL Logs (Primary Evidence)

The JSONL session logs are the ground truth for what actually happened in each session.

**User-level session index:**
```
~/.claude/history.jsonl
```
Each line: `{"display": "<user prompt>", "project": "<cwd>", "sessionId": "<uuid>", "timestamp": <epoch_ms>}`

This file indexes ALL sessions across all projects. Use it to find session IDs for
a specific project or time range, then read the corresponding project-level JSONL.

**Project-level session logs:**
```
~/.claude/projects/<path-encoded-cwd>/<session-id>.jsonl
```
Path encoding: replace `/` with `-`, prefix with `-`.
Example: `/Users/simon/conductor/workspaces/ts-prefect/oslo` → `-Users-simon-conductor-workspaces-ts-prefect-oslo`

Each JSONL line is one conversation event (user message, assistant response, tool
result, progress event, etc.).

**Subagent logs:**
```
~/.claude/projects/<path-encoded-cwd>/<session-id>/subagents/agent-<id>.jsonl
```
Subagents are spawned by the `Agent` tool. They have their own JSONL logs with the same
format. These are important — subagents often do the bulk of the work and need memory
surfacing too.

**Finding recent sessions for a project:**
```bash
# All ts-prefect workspace sessions, newest first (excluding subagents)
find ~/.claude/projects -path "*ts-prefect*" -name "*.jsonl" -not -path "*/subagents/*" \
  -exec ls -lt {} + | head -20

# Including subagent logs
find ~/.claude/projects -path "*ts-prefect*" -name "*.jsonl" \
  -exec ls -lt {} + | head -30

# Sessions from the last 48 hours
find ~/.claude/projects -path "*ts-prefect*" -name "*.jsonl" -mtime -2 \
  -exec ls -lt {} +
```

**JSONL entry structure:**

| Entry type | How to identify | What it tells you |
|---|---|---|
| User message | `"type": "user"`, `message.content[].type == "text"` | What the user asked — topic for memory matching |
| Assistant with tools | `"type": "assistant"`, `message.content[].type == "tool_use"` | Which tools Claude called (check `.name` and `.input`) |
| Tool result | `"type": "user"`, `content[].type == "tool_result"` | What tools returned to Claude |
| Hook injection | `"type": "user"`, content contains `<system-reminder>` with `autodev-memory-hook-result` | What the memory system injected |
| Assistant text | `"type": "assistant"`, `message.content[].type == "text"` | What Claude said — did it USE the memories? |

**Parsing session JSONL — essential scripts:**

```bash
SESSION="<path-to-session>.jsonl"

# 1. All MCP autodev-memory tool calls
python3 -c "
import json, sys
for line in open('$SESSION'):
    obj = json.loads(line)
    if obj.get('type') == 'assistant':
        for c in obj.get('message', {}).get('content', []):
            if isinstance(c, dict) and c.get('type') == 'tool_use' and 'autodev' in c.get('name', ''):
                print(f\"{c['name']}: {json.dumps(c.get('input', {}))[:200]}\")
"

# 2. Tool call frequency summary
python3 -c "
import json, sys, collections
counts = collections.Counter()
for line in open('$SESSION'):
    obj = json.loads(line)
    if obj.get('type') == 'assistant':
        for c in obj.get('message', {}).get('content', []):
            if isinstance(c, dict) and c.get('type') == 'tool_use':
                counts[c['name']] += 1
for name, count in counts.most_common():
    print(f'{count:3d}  {name}')
"

# 3. Hook injections — what the memory system delivered to Claude
python3 -c "
import json, sys
for i, line in enumerate(open('$SESSION')):
    obj = json.loads(line)
    content = json.dumps(obj)
    if 'autodev-memory-hook-result' in content:
        source = 'unknown'
        for s in ['session-start', 'pre-agent', 'pre-tool', 'prompt-submit']:
            if s in content: source = s; break
        entry_count = content.count('### [')
        print(f'Line {i}: HOOK={source}, ~{entry_count} entries injected')
"

# 4. User messages (topics for memory matching)
python3 -c "
import json, sys
for line in open('$SESSION'):
    obj = json.loads(line)
    if obj.get('type') == 'user':
        msg = obj.get('message', {})
        if isinstance(msg, dict):
            for c in msg.get('content', []):
                if isinstance(c, dict) and c.get('type') == 'text':
                    text = c['text'][:200].replace('\n', ' ')
                    if '<system-reminder>' not in text and len(text.strip()) > 10:
                        print(f'USER: {text}')
"

# 5. Full session timeline (messages + tools + hooks)
python3 -c "
import json, sys
for i, line in enumerate(open('$SESSION')):
    obj = json.loads(line)
    t = obj.get('type', '?')
    content = json.dumps(obj)
    if t == 'user':
        msg = obj.get('message', {})
        if isinstance(msg, dict):
            for c in msg.get('content', []):
                if isinstance(c, dict) and c.get('type') == 'text':
                    text = c['text'][:100].replace('\n', ' ')
                    if '<system-reminder>' not in text and len(text.strip()) > 5:
                        print(f'{i:4d} USER: {text}')
        if 'autodev-memory-hook-result' in content:
            print(f'{i:4d} HOOK: memory injected')
    elif t == 'assistant':
        tools = [c['name'] for c in obj.get('message', {}).get('content', [])
                 if isinstance(c, dict) and c.get('type') == 'tool_use']
        if tools:
            print(f'{i:4d} TOOL: {\", \".join(tools)}')
        else:
            texts = [c.get('text', '')[:80] for c in obj.get('message', {}).get('content', [])
                     if isinstance(c, dict) and c.get('type') == 'text']
            if texts and any(t.strip() for t in texts):
                print(f'{i:4d} ASST: {texts[0][:80]}')
"
```

### 1. Hook Log File (Quick Debug)

All hooks write structured logs to `~/.config/autodev-memory/hooks.log`.

```bash
tail -50 ~/.config/autodev-memory/hooks.log
grep ERROR ~/.config/autodev-memory/hooks.log
grep "output ->" ~/.config/autodev-memory/hooks.log | tail -5
```

Log format: `YYYY-MM-DD HH:MM:SS [hook-name     ] LEVEL message`

### 2. Operation Logs (MCP Debug)

Query via autodev-memory MCP `debug_logs` tool:

```
debug_logs(project="<project>", operation="mcp_search", hours=48, limit=100)
debug_logs(project="<project>", operation="mcp_create_entry", hours=48, limit=50)
```

Key fields: `request.queries`, `response.results`, `response.count`,
`response.search_time_ms`, `hook_source`, `error`

NOTE: `result_count` is always null — use `response.count` instead.

### 3. Knowledge Base Content

Query via MCP `list_entries` and `get_entry` tools to audit entry quality,
duplicates, gaps, and staleness.

### 4. Source Code

Read hook scripts, prompt templates, and search implementation in the
`autodev-memory` repo when needed to understand current behavior.

## Analysis Process

### Phase 0: Establish Baseline

Before collecting evidence, determine the **last deployed commit to autodev-memory**.
Only analyze sessions and operation logs **after** that commit timestamp. Issues that
predate the latest code are likely already fixed — flagging them wastes everyone's time.

**IMPORTANT:** Use `origin/main` — not the local `main` branch pointer, which may be
stale if the workspace is on a feature branch. The autodev-memory workspace is often
on a feature branch ahead of main, so `main` can point to an old commit while
`origin/main` reflects what's actually deployed.

```bash
# Get the latest DEPLOYED autodev-memory commit timestamp
# CRITICAL: Always use origin/main, never bare main
cd ~/conductor/workspaces/autodev-memory/west-monroe && \
  git fetch origin --quiet && \
  git log -1 --format="%ai %H %s" origin/main

# Or if the repo isn't checked out locally:
cd ~/dev/autodev-memory && \
  git fetch origin --quiet && \
  git log -1 --format="%ai %H %s" origin/main
```

Use this timestamp as the **evidence cutoff**. When collecting session logs and
operation logs in Phase 1, filter to sessions that started AFTER this timestamp.
In the audit report, state the baseline commit explicitly:

```
**Baseline commit:** <hash> (<date>) — <message>
**Evidence window:** <baseline date> → now
```

If a finding's evidence is entirely from before the baseline, skip it — the fix
may already be deployed. If evidence spans both sides, note it but check whether
the post-baseline sessions still show the issue.

### Phase 1: Collect Evidence

Run these in parallel where possible:

1. **Session index** — Read `~/.claude/history.jsonl`, filter for project (after baseline)
2. **Recent sessions** — Parse 3-5 most recent session JSONLs for the project
3. **Subagent logs** — Parse subagent logs from those sessions
4. **Operation logs** — `debug_logs(project="<project>", operation="mcp_search", hours=48)`
5. **Entry index** — `list_entries(project="<project>")` for current KB state
6. **Hook logs** — `tail -100 ~/.config/autodev-memory/hooks.log`

### Phase 2: Verify Memory Surfacing

For each session analyzed, answer these questions:

#### A. Were relevant memories surfaced?

For each user message, determine what knowledge SHOULD have been relevant, then
check whether:
1. The session-start hook injected starred memories (check for `session-start` hook result)
2. Hook results appeared before Claude's response on topic-relevant messages
3. If the user asked about a topic with a known entry, did it appear in any hook injection?

**Red flags:**
- User asks about "alembic migration" but no migration memories appeared
- User works on auth scraper but DataDome gotchas weren't injected
- Subagent spawned for investigation but received no memory context
- Session has zero hook injections (hooks may be broken)

#### B. Did Claude use the surfaced memories?

Even when memories ARE injected, Claude sometimes ignores them. Check:
1. Was a memory injected in a `<system-reminder>`?
2. Did Claude's subsequent response reference or apply that knowledge?
3. Did the user have to correct Claude on something the memory already covered?

**Red flags:**
- Memory says "never suppress flow failures" but Claude recommended suppressing
- Memory says "use `logger.exception()`" but Claude used `logger.error()`
- User correction matches an existing memory entry exactly

#### C. Were MCP tools called when appropriate?

Check if Claude proactively searched the knowledge base when:
1. Starting a complex task (should search for related patterns/gotchas)
2. Encountering an error (should search for known solutions)
3. The CLAUDE.md says to search the Knowledge Menu on every message

**Red flags:**
- Zero `mcp__autodev-memory__search` calls in a long session
- Claude relied solely on hook-injected context without ever searching manually
- `/save` or `/compound` never called after user corrections

### Phase 3: Detect Bloat

#### D. Entry utilization

Cross-reference the entry list against operation logs:
1. Which entries are NEVER returned in search results over 7+ days? (Dead entries)
2. Which entries duplicate content already in CLAUDE.md? (Redundant)
3. Which entries overlap significantly with each other? (Merge candidates)
4. Are there entries about code patterns that have since changed? (Stale)

```
# Get all entries
list_entries(project="<project>")

# Check search logs for which entries get returned
debug_logs(project="<project>", operation="mcp_search", hours=168, limit=200)
```

#### E. Injection size

Check if injected context is too large:
1. Starred memories token count (target: <2000 tokens)
2. Typical pre-agent injection size (target: <1000 tokens)
3. Knowledge Menu line count (target: <200 lines)

### Phase 4: Additional Dimensions

#### F. Query Generation Quality
- Are generated queries capturing user intent?
- Do queries include exact identifiers (function names, error codes)?
- Are queries too generic (irrelevant results) or too specific (missing)?

#### G. Search Effectiveness
- Right entries ranking highest? Check similarity/RRF scores.
- Searches returning 0 results that should have found something?
- Cross-project (global) results found when they should be?

#### H. Hook Orchestration
- Latency issues? (Search adds ~1-3s per message)
- Pre-agent hook firing for the right agent types?
- Error patterns in hook execution?

#### I. Feedback Loop Completeness
- Corrections flowing through the pipeline?
- Zero-result searches signaling entry gaps?
- Knowledge types with no capture pathway?

## Output Format

```markdown
# Autodev Audit Report

**Date:** YYYY-MM-DD
**Project:** <project-name>
**Focus:** <specific focus or "full audit">
**Sessions analyzed:** <count and date range>
**Baseline commit:** <hash> (<date>) — <message>
**Evidence window:** <baseline date> → now

## Executive Summary

<2-3 sentences on the most impactful findings>

## Memory Surfacing Verification

### Sessions Analyzed
| Session | Date | Workspace | Messages | MCP Calls | Hook Events |
|---|---|---|---|---|---|

### Surfacing Hits (memories correctly delivered)
- <specific examples with session + message context>

### Surfacing Misses (memories should have appeared but didn't)
- <user message, relevant memory entry, why it wasn't found>

### Ignored Memories (surfaced but not used by Claude)
- <memory injected, Claude didn't apply it, user had to correct>

## MCP Tool Call Verification

### Tool Call Frequency
| Tool | Total Calls | Sessions With 0 Calls |
|---|---|---|

### Missed Opportunities
- <cases where Claude should have searched but didn't>

## Bloat Analysis

### Dead Entries (never retrieved)
| Entry | Type | Last Retrieved |
|---|---|---|

### Redundant (duplicates CLAUDE.md or overlaps)
- <specific entries>

### Stale (outdated content)
- <entries no longer matching reality>

## Additional Findings

### [PRIORITY] Finding Title
**Dimension:** <A-I>
**Evidence:** <specific data>
**Proposed change:** <actionable recommendation>
**Files to modify:** <exact paths>

## Metrics to Track
<suggested ongoing metrics>
```

### Priority Levels

| Priority | Meaning |
|---|---|
| P0 | Knowledge actively misleading or system broken |
| P1 | Significant missed surfacing — user had to repeat known knowledge |
| P2 | Quality improvement, better precision/recall |
| P3 | Nice-to-have, minor optimization |

## Usage

**Audit mode** (broad analysis):
- `/autodev-improve ts` — full audit of the `ts` project
- `/autodev-improve ts surfacing` — focus on memory surfacing only
- `/autodev-improve ts bloat` — focus on bloat detection only
- `/autodev-improve` — audit the current repo's project

**Design mode** (specific question):
- `/autodev-improve should we switch to text-embedding-3-small?`
- `/autodev-improve what if we added repo-level filtering to search?`

Valid focus areas: `surfacing`, `mcp-calls`, `bloat`, `query-generation`, `search`,
`hooks`, `schema`, `latency`, `feedback-loop`

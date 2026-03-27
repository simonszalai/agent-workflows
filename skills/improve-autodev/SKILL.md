---
name: improve-autodev
description: >-
  General-purpose improvement skill for the autodev-memory system. Diagnoses
  problems, evaluates design changes, explores new capabilities, and audits
  system health. Covers query generation, search, correction detection, chunking,
  schema, hooks, embeddings, and architecture. Propose-only, never auto-implements.
user_invocable: true
argument-hint: "[project] [focus-area]"
---

# Improve Autodev

General-purpose improvement methodology for the entire autodev-memory system. Use
this for any kind of autodev improvement:

- **Diagnosing problems** — search returning wrong results, corrections not captured,
  latency too high, entries poorly organized
- **Evaluating design changes** — switching embedding models, adding new entry types,
  changing the chunking strategy, restructuring the schema
- **Exploring new capabilities** — repo-level search filtering, zero-result gap
  detection, new hook trigger points, new MCP tools, new prompt strategies
- **Auditing system health** — full audit of search quality, entry coverage, and
  pipeline effectiveness across recent sessions

When invoked with a specific question or idea, skip the full audit and focus the
analysis on that topic. When invoked without context, run a broad audit.

**Rule: Propose only. Never auto-implement changes.**

## Scope

Everything that affects whether the right knowledge reaches the right agent at the
right time:

| Layer                | Files / Components                                 |
| -------------------- | -------------------------------------------------- |
| Query generation     | `hooks/prompts/query-generation.md`                |
| Hook orchestration   | `hooks/autodev-memory-prompt-submit.sh`            |
|                      | `hooks/autodev-memory-pre-agent.sh`                |
|                      | `hooks/autodev-memory-session-start.sh`            |
|                      | `hooks/mem-env.sh`                                 |
| Hook logging         | `hooks/mem-log.sh`                                 |
|                      | `~/.config/autodev-memory/hooks.log`               |
| Correction detection | `hooks/autodev-memory-correction-detect.sh`        |
|                      | `hooks/prompts/classify-and-extract.md`            |
|                      | `hooks/prompts/match-entry.md`                     |
|                      | `hooks/prompts/decide-action.md`                   |
| Search engine        | `src/search.py` (hybrid search, RRF merge)         |
| Chunking             | `src/chunking.py` (split, embed, index)            |
| Schema / models      | `src/models.py` (Entry, Chunk, OperationLog)       |
| MCP tools            | `src/mcp_tools.py`                                 |
| REST endpoints       | `src/endpoints.py`                                 |
| Embeddings           | `src/embeddings.py`                                |
| Result formatting    | Hook scripts (jq formatting in prompt-submit/pre-agent) |

## Data Sources

### 0. Hook Log File (Quick Debug)

All hooks write structured logs to `~/.config/autodev-memory/hooks.log`. This is the
fastest way to see what hooks are doing — no API calls needed.

```bash
# Live tail during a session
tail -f ~/.config/autodev-memory/hooks.log

# Recent activity
tail -50 ~/.config/autodev-memory/hooks.log

# Errors only
grep ERROR ~/.config/autodev-memory/hooks.log

# What happened on a specific hook
grep prompt-submit ~/.config/autodev-memory/hooks.log | tail -20

# See the full additionalContext output (what Claude received)
grep "output ->" ~/.config/autodev-memory/hooks.log | tail -5
```

Log format: `YYYY-MM-DD HH:MM:SS [hook-name     ] LEVEL message`

Key events logged per hook:
- **session-start**: config, glossary fetch count, final output
- **prompt-submit**: prompt (truncated), triggers (???/!!!/>>>), search decision + reason,
  query count + display, result count, status line, full additionalContext output
- **pre-agent**: agent type/desc, query count + body, result count, full output
- **correction-detect**: each pipeline step (classify, index, candidates, decide, store)
- **glossary-extract**: term extraction, store result
- **mem-err-trap**: all error exits with stderr capture

The log auto-rotates at ~1MB. Use this FIRST when diagnosing "Claude didn't show the
hook result" — check `grep "output ->" hooks.log` to see exactly what was returned.

### 1. Operation Logs (Primary)

Query via autodev-memory MCP `debug_logs` tool:

```
debug_logs(project="<project>", operation="search", hours=48, limit=100)
```

Key fields to analyze:
- `request.queries` — what was searched for
- `response.results` — what came back (titles, types, similarity scores, chunks)
- `response.search_time_ms` — latency
- `result_count` — how many results returned
- `hook_source` — which hook triggered it (`user_prompt`, `pre_tool_use`, `mcp`,
  `correction_detect`)
- `error` — any failures
- `caller_context` — structured context from LLM callers

Also query correction operations:

```
debug_logs(project="<project>", operation="store", hours=48, limit=50)
```

Key fields: `action` (new/append/supersede/rebalance/deprecate/skip), `entry_id`

### 2. Claude Session Logs (Secondary)

JSONL files in `~/.claude/projects/<path-encoded-cwd>/`.

**Finding the current session:**
```bash
ls -t ~/.claude/projects/-<path-encoded>/*.jsonl | head -1
```

Path encoding: replace `/` with `-`, prefix with `-`.
Example: `/Users/simon/dev/ts-api` -> `-Users-simon-dev-ts-api`

**What to look for in session logs:**
- `type: "user"` entries — what the user asked about
- `type: "assistant"` entries with `tool_use` — what tools were invoked
- `type: "progress"` with `hookEvent` — hook execution traces
- Patterns of repeated questions (knowledge not surfacing)
- Corrections that weren't captured
- Search results returned but not used by the agent

**Prioritize the invoking session** but also scan recent sessions for patterns.

### 3. Knowledge Base Content

Query via MCP `list_entries` and `get_entry` tools to audit:
- Entry quality (well-written, proper size, correct type)
- Duplicate or overlapping entries
- Gaps (topics discussed but no entries exist)
- Stale entries (outdated content)

### 4. Source Code

Read the hook scripts, prompt templates, and search implementation directly to
understand current behavior before proposing changes.

## Analysis Process

### Phase 1: Collect Evidence

Run these in parallel where possible:

1. **Recent searches** — `debug_logs(operation="search", hours=48, limit=100)`
2. **Recent stores** — `debug_logs(operation="store", hours=48, limit=50)`
3. **Recent errors** — `debug_logs(hours=48, limit=50)` filtered for non-null errors
4. **Entry index** — `list_entries(project="<project>")` for KB state
5. **Current session log** — Read the JSONL for the invoking session
6. **Recent session logs** — Scan 2-3 most recent sessions for patterns
7. **Source code** — Read current versions of hook scripts and prompt templates

### Phase 2: Analyze

Evaluate each dimension below. For each, note specific evidence from Phase 1.

#### A. Query Generation Quality

- Are generated queries capturing user intent?
- Do queries include exact identifiers (function names, error codes, config keys)?
- Are queries too generic (returning irrelevant results) or too specific (missing)?
- Is the Haiku prompt template giving good guidance?
- Is enough conversation context being passed? (Currently last 3 messages, truncated
  to 500 chars each for user, 200 chars for assistant)
- Are there query patterns that consistently return empty results?

#### B. Search Effectiveness

- Are the right entries ranking highest? Check similarity/RRF scores.
- Is the vector-vs-BM25 balance appropriate? (RRF k=60)
- Are there searches returning 0 results that should have found something?
- Is the result limit (default 5) appropriate?
- Is the top-20 per-retriever limit sufficient?
- Are cross-project (global DB) results being found when they should be?

#### C. Correction Detection

- Is the regex gate catching real corrections? (`CORRECTION_REGEX` in prompt-submit)
- Are corrections being missed by the regex? (Check session logs for uncaptured
  corrections)
- Is the classify-and-extract prompt correctly distinguishing corrections vs noise?
- Are the match-entry and decide-action prompts making good decisions?
- Is the 4-step pipeline too slow or too aggressive?
- Are `skip` actions justified? (Check operation logs for store with action=skip)

#### D. Entry Quality & Coverage

- Are entries well-sized? (Target: 200-800 tokens, max ~1500 tokens)
- Are summaries search-friendly? (Use vocabulary people naturally use)
- Are canonical keys consistent and useful?
- Are entry types accurate?
- Are there topic gaps? (Things discussed in sessions but no KB entry exists)
- Are there duplicate/overlapping entries that should be merged?
- Are entries being superseded properly or accumulating stale versions?

#### E. Chunking & Embedding

- Are chunks the right size? (~500 tokens / ~2000 chars target)
- Are code blocks being preserved as atomic units?
- Are headings being merged with their content?
- Is the sentence-level splitting working well for oversized paragraphs?
- Is `text-embedding-3-large` (3072 dims) the right choice? Dimension reduction
  opportunity?

#### F. Result Formatting & Delivery

- Is the markdown formatting in hook output clear and useful?
- Is too much or too little content being returned? (1500-token threshold for full
  entry vs chunk-only)
- Are canonical keys and entry types adding value in the formatted output?
- Is the `additionalContext` format being consumed well by Claude?
- Could results be ranked/filtered differently before injection?

#### G. Hook Orchestration

- Are there latency issues? (Search typically adds ~1-3s to each message)
- Is the recursion guard (`_MEM_HOOK_ACTIVE`) working correctly?
- Is the pre-agent hook firing too often or not enough?
- Is the minimum prompt length filter (20 chars for user, 30 chars for agent)
  appropriate?
- Are there error patterns in hook execution?
- Is the topology fetch at session start stale by end of long sessions?

#### H. Schema & Architecture

- Are there missing fields that would improve search or curation?
- Are indexes optimal for the query patterns?
- Is the multi-database architecture (global + per-project) working well?
- Are there opportunities for new entry types, metadata, or relationships?
- Would additional tsvector configurations (language, weights) improve BM25?
- Is the HNSW index configuration (m=16, ef_construction=64) appropriate for
  the current data size?
- Would tags, categories, or cross-entry links improve navigation?

#### I. Latency & Performance

- End-to-end hook latency (embedding call ~200ms per query, search, formatting)
- Number of queries per message (each adds ~200ms for embedding)
- Database query times (from `duration_ms` in operation logs)
- Are there unnecessary sequential operations that could be parallelized?
- Could query count be reduced without hurting recall?

#### J. Feedback Loop Completeness

- Are corrections flowing through the pipeline end-to-end?
- Is the regex gate → classify → match → decide → store chain losing signal?
- Are there types of knowledge that should be captured but have no pathway?
  (e.g., architectural decisions, debugging patterns, workflow preferences)
- Is the system learning from its own failures? (Searches that return nothing
  could signal missing entries)
- Could zero-result searches trigger automatic gap detection?

## Output Format

Present findings as a structured improvement proposal:

```markdown
# Autodev Improvement Proposal

**Date:** YYYY-MM-DD
**Project:** <project-name>
**Focus:** <specific focus or "full audit">
**Evidence period:** <date range of analyzed data>

## Executive Summary

<2-3 sentences on the most impactful findings>

## Findings

### [PRIORITY] Finding Title

**Dimension:** <A-J from analysis dimensions>
**Evidence:**
- <specific data points from operation logs, session logs, or source code>

**Current behavior:** <what happens now>
**Problem:** <why this is suboptimal>
**Proposed change:** <specific, actionable recommendation>
**Files to modify:** <exact file paths>
**Impact:** <expected improvement>

---

<repeat for each finding>

## Structural Recommendations

<cross-cutting or architectural recommendations>

## Metrics to Track

<suggested metrics to measure whether improvements are working>
```

### Priority Levels

| Priority | Meaning                                          |
| -------- | ------------------------------------------------ |
| P0       | Knowledge actively misleading or system broken   |
| P1       | Significant missed surfacing or false negatives  |
| P2       | Quality improvement, better precision/recall     |
| P3       | Nice-to-have, minor optimization                 |

## Usage

**Audit mode** (no specific question — runs broad analysis):
- `/improve-autodev ts` — full audit of the `ts` project
- `/improve-autodev ts query-generation` — focus on query generation only
- `/improve-autodev` — audit the current repo's project (from CLAUDE.md mem stub)

**Design mode** (specific question or idea — focused analysis):
- `/improve-autodev should we switch to text-embedding-3-small?`
- `/improve-autodev what if we added repo-level filtering to search?`
- `/improve-autodev the correction regex is missing "actually" at mid-sentence`

In design mode, skip the full audit. Collect only the evidence relevant to the
question, analyze trade-offs, and propose a concrete change with rationale.

Valid focus areas: `query-generation`, `search`, `correction-detection`, `entries`,
`chunking`, `formatting`, `hooks`, `schema`, `latency`, `feedback-loop`

The skill reads operation logs, session logs, KB content, and source code — it may
take several minutes in audit mode. All proposals are returned as text. Findings
should be specific enough to implement without further investigation (include exact
file paths and before/after examples where possible).

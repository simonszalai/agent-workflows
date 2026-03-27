---
name: autodev-debug
description: >-
  Debug and observe the autodev-memory system. System architecture overview, hook
  pipeline tracing, log file analysis, and diagnostic commands. Use when hooks
  return results that Claude ignores, searches return wrong results, or the system
  behaves unexpectedly.
user_invocable: true
argument-hint: "[symptom or area to debug]"
---

# Autodev Debug — Memory System Observability

Hands-on debugging skill for the autodev-memory system. Use this when:

- Hooks return results but Claude doesn't show them
- Searches return wrong or no results
- Correction detection isn't capturing what it should
- You want to understand what the hooks are doing on each message
- Something is silently failing

**Scope:** Observing and diagnosing. For broad system audits and design proposals, use
`improve-autodev`. For single-failure pipeline traces triggered by `???`, use `autodev-wtf`.

## System Architecture Overview

### How It Works

The autodev-memory system is a knowledge base that automatically injects relevant context
into Claude Code sessions. It runs as three Claude Code hooks that fire on specific events:

```
User types message
       |
       v
[UserPromptSubmit hook]
  1. Check for triggers (??? / !!! / >>>)
  2. Ask Haiku: "should we search the KB?"
  3. If yes: generate queries, search, format results
  4. Return additionalContext JSON -> Claude sees it
       |
       v
Claude generates response
       |
       v
Claude spawns subagent
       |
       v
[PreToolUse[Agent] hook]
  1. Extract subagent prompt/type
  2. Ask Haiku to generate search queries
  3. Search KB, format results
  4. Return additionalContext JSON -> subagent sees it
```

### Components

| Component              | Location                                         | Purpose                       |
| ---------------------- | ------------------------------------------------ | ----------------------------- |
| Hook config            | `~/.claude/settings.json` (hooks section)        | Which hooks fire when         |
| Session start hook     | `hooks/autodev-memory-session-start.sh`          | Load glossary on session init |
| Prompt submit hook     | `hooks/autodev-memory-prompt-submit.sh`          | Search KB on user messages    |
| Pre-agent hook         | `hooks/autodev-memory-pre-agent.sh`              | Search KB for subagent tasks  |
| Correction detect      | `hooks/autodev-memory-correction-detect.sh`      | 4-step correction pipeline    |
| Glossary extract       | `hooks/autodev-memory-glossary-extract.sh`       | Define terms via >>>          |
| Env/config             | `hooks/mem-env.sh`                               | Parse CLAUDE.md mem stub      |
| Error trap             | `hooks/mem-err-trap.sh`                          | Catch errors, return JSON     |
| Logging                | `hooks/mem-log.sh`                               | Persistent log file           |
| Search decision prompt | `hooks/prompts/search-decision.md`               | Haiku decides if search needed|
| Query generation prompt| `hooks/prompts/query-generation.md`              | Haiku generates search queries|
| Classify prompt        | `hooks/prompts/classify-and-extract.md`          | Sonnet classifies corrections |
| Match prompt           | `hooks/prompts/match-entry.md`                   | Sonnet picks candidate entries|
| Decide prompt          | `hooks/prompts/decide-action.md`                 | Sonnet decides store action   |
| Memory API             | `$AUTODEV_MEMORY_API_URL` (default localhost:8475)| REST + MCP search/store API  |
| Env config file        | `~/.config/autodev-memory/.env`                  | API token and URL             |
| **Log file**           | **`~/.config/autodev-memory/hooks.log`**         | **All hook activity**         |

### Hook Data Flow

Each hook returns JSON to Claude Code:

```json
{"additionalContext": "<autodev-memory-hook-result source=\"...\">...</autodev-memory-hook-result>"}
```

Claude Code injects this into the conversation as a `<system-reminder>`. The hook output
includes instructions like "MANDATORY: Start your reply with this status line" but Claude
frequently ignores these. The log file captures the full output regardless.

### Project Configuration

Each project's `CLAUDE.md` contains a mem stub that identifies it:

```html
<!-- mem:project=ts repo=ts-prefect -->
```

The hooks parse this to know which project/repo to search. Without it, hooks skip silently.

## Primary Debug Tool: Hook Log File

All hooks write structured logs to `~/.config/autodev-memory/hooks.log`.

### Log Format

```
YYYY-MM-DD HH:MM:SS [hook-name     ] LEVEL message
```

Example:

```
2026-03-26 14:23:01 [prompt-submit ] INFO  start prompt=how do I configure the scraper f
2026-03-26 14:23:02 [prompt-submit ] INFO  search decision: should_search=true reason=user asking about scraper config
2026-03-26 14:23:02 [prompt-submit ] INFO  queries: count=2 display=scraper, config: scraper configuration setup
2026-03-26 14:23:03 [prompt-submit ] INFO  search results: count=3
2026-03-26 14:23:03 [prompt-submit ] INFO  done status_line=Memory: searched — 3 results added to context
2026-03-26 14:23:03 [prompt-submit ] DEBUG output -> <autodev-memory-hook-result source="prompt-submit">...
```

### Essential Commands

```bash
# Live tail during a session — the single most useful debug command
tail -f ~/.config/autodev-memory/hooks.log

# Recent activity (last 50 lines)
tail -50 ~/.config/autodev-memory/hooks.log

# Errors only
grep ERROR ~/.config/autodev-memory/hooks.log

# What a specific hook did recently
grep session-start ~/.config/autodev-memory/hooks.log | tail -10
grep prompt-submit ~/.config/autodev-memory/hooks.log | tail -20
grep pre-agent ~/.config/autodev-memory/hooks.log | tail -20
grep correction-detect ~/.config/autodev-memory/hooks.log | tail -10
grep glossary-extract ~/.config/autodev-memory/hooks.log | tail -5

# See the full additionalContext output (exactly what Claude received)
grep "output ->" ~/.config/autodev-memory/hooks.log | tail -5

# Search decisions (did Haiku say yes/no to searching?)
grep "search decision" ~/.config/autodev-memory/hooks.log | tail -20

# What queries were generated
grep "queries:" ~/.config/autodev-memory/hooks.log | tail -10

# Skipped hooks (config missing, prompt too short, etc.)
grep "skip" ~/.config/autodev-memory/hooks.log | tail -20

# Clear the log (start fresh for a debug session)
> ~/.config/autodev-memory/hooks.log
```

### What Each Hook Logs

| Hook               | Key Events                                                    |
| ------------------- | ------------------------------------------------------------- |
| session-start       | config skip/start, glossary term count, final output          |
| prompt-submit       | prompt (truncated 120 chars), trigger type, search decision   |
|                     | + reason, query count + display, result count, status line,   |
|                     | full additionalContext output                                 |
| pre-agent           | skip reason OR agent type/desc, query count + body, result    |
|                     | count, full output                                            |
| correction-detect   | each pipeline step: classify type, index count, candidate     |
|                     | IDs, decide action, store result                              |
| glossary-extract    | prompt, extracted term, store result                          |
| mem-err-trap        | all error exits with stderr capture and exit code             |

## Secondary Debug Tools

### API Operation Logs

The memory API logs every search and store operation. Query via MCP:

```
debug_logs(project="<project>", operation="search", hours=2, limit=20)
debug_logs(project="<project>", operation="store", hours=2, limit=10)
```

Key fields:
- `request.queries` — what was searched for (keywords + text)
- `response.results` — what came back (titles, scores, types)
- `response.search_time_ms` — API-side latency
- `hook_source` — which hook triggered it (`user_prompt`, `pre_tool_use`, `correction_detect`)
- `error` — any API-side failures

### Claude Session Logs

JSONL files in `~/.claude/projects/<path-encoded-cwd>/`. Path encoding: replace `/` with
`-`, prefix with `-`. Example: `/Users/simon/dev/ts-api` -> `-Users-simon-dev-ts-api`.

```bash
# Find current session log
ls -t ~/.claude/projects/-Users-simon-dev-ts-api/*.jsonl | head -1

# Look for hook results in the session
grep -l "autodev-memory-hook-result" ~/.claude/projects/-Users-simon-*/*.jsonl | head -5
```

### Direct API Health Check

```bash
# Check API is reachable
curl -s -H "Authorization: Bearer $AUTODEV_MEMORY_API_TOKEN" \
  "${AUTODEV_MEMORY_API_URL:-http://localhost:8475}/health"

# Check project topology
curl -s -H "Authorization: Bearer $AUTODEV_MEMORY_API_TOKEN" \
  "${AUTODEV_MEMORY_API_URL:-http://localhost:8475}/topology?project=ts"

# List entries in KB
curl -s -H "Authorization: Bearer $AUTODEV_MEMORY_API_TOKEN" \
  "${AUTODEV_MEMORY_API_URL:-http://localhost:8475}/entries/index?project=ts" | jq '.entries | length'

# Manual search
curl -s -X POST -H "Authorization: Bearer $AUTODEV_MEMORY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"searches":[{"keywords":["scraper","config"],"text":"scraper configuration"}],"project":"ts","limit":5}' \
  "${AUTODEV_MEMORY_API_URL:-http://localhost:8475}/search" | jq '.results[] | {title, type, score}'
```

## Common Debug Scenarios

### "Claude didn't show the hook result"

This is the most common issue. The hook returned `additionalContext` but Claude ignored the
"MANDATORY: show this status line" instruction.

**Diagnosis:**
```bash
# See what was actually returned
grep "output ->" ~/.config/autodev-memory/hooks.log | tail -3
```

If the output contains results, the hook worked — Claude just didn't surface it. This is a
Claude compliance issue, not a hook issue. The log file is your ground truth.

### "Search returned wrong results"

**Diagnosis:**
```bash
# What queries were generated?
grep "queries:" ~/.config/autodev-memory/hooks.log | tail -5

# What results came back?
grep "search results:" ~/.config/autodev-memory/hooks.log | tail -5

# Check the full output to see result titles
grep "output ->" ~/.config/autodev-memory/hooks.log | tail -1
```

Then compare with a manual search to see if the issue is query generation or search ranking:
```bash
# Test with your own query
curl -s -X POST -H "Authorization: Bearer $AUTODEV_MEMORY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"searches":[{"keywords":["your","terms"],"text":"what you expected to find"}],"project":"ts","limit":5}' \
  "${AUTODEV_MEMORY_API_URL:-http://localhost:8475}/search" | jq '.results[] | {title, score}'
```

### "Correction wasn't captured"

**Diagnosis:**
```bash
# Was correction-detect triggered?
grep correction-detect ~/.config/autodev-memory/hooks.log | tail -10

# What did classify say?
grep "step1 classify" ~/.config/autodev-memory/hooks.log | tail -5

# What action was decided?
grep "step3c decide" ~/.config/autodev-memory/hooks.log | tail -5
```

Common causes:
- `type=not_correction` — Sonnet didn't classify it as a correction (use `!!!` to force)
- `action=skip` — decided existing KB already covers it
- No log lines at all — hook didn't fire (check for trigger characters `!!!` or `???`)

### "Hook is erroring"

**Diagnosis:**
```bash
grep ERROR ~/.config/autodev-memory/hooks.log | tail -10
```

Common errors:
- `AUTODEV_MEMORY_API_TOKEN not set` — check `~/.config/autodev-memory/.env`
- `memory API unreachable` — API server is down or URL is wrong
- `Haiku CLI error` / `claude -p returned nothing` — Claude CLI issue or rate limit
- `exit_code=1 stderr=...` — error trap caught something, check stderr content

### "Hooks aren't firing at all"

**Diagnosis:**
```bash
# Is there ANY recent log activity?
tail -5 ~/.config/autodev-memory/hooks.log

# Does the project have a mem stub?
grep 'mem:project=' CLAUDE.md

# Is the settings.json hook config correct?
cat ~/.claude/settings.json | jq '.hooks'

# Is the env file present?
cat ~/.config/autodev-memory/.env
```

### "Pre-agent hook fires too much / not enough"

**Diagnosis:**
```bash
# See what's being skipped vs searched
grep pre-agent ~/.config/autodev-memory/hooks.log | tail -20
```

The pre-agent hook skips when:
- Subagent prompt is < 30 chars
- No mem config in CLAUDE.md
- Recursion guard is active (nested claude -p call)

## Log File Management

The log auto-rotates at ~1MB (keeps last ~500KB). To manage manually:

```bash
# Check log size
ls -lh ~/.config/autodev-memory/hooks.log

# Clear for a fresh debug session
> ~/.config/autodev-memory/hooks.log

# Archive before clearing
cp ~/.config/autodev-memory/hooks.log ~/.config/autodev-memory/hooks.$(date +%Y%m%d).log
```

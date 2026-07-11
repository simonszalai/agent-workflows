# Evidence Scouts — Briefs & Parsing Recipes

Phase 1 fans out five scout agents. Scouts read large, noisy data (session logs, tickets, the
whole memory store) and return **compact, locator-bound findings**. They run on cheap models —
`sonnet` for the judgment-bearing scouts, `haiku` for mechanical extraction. Scouts **never
mutate anything**; they only read and summarize.

Spawn all five in one message (parallel `Agent` blocks). Give each the orchestrator's resolved
**project / repo / evidence-window-start** and its brief below. Every finding a scout returns
**must** carry a concrete locator (`session:line`, ticket id, entry id, `file:line`, grep hit).

The common return envelope each scout uses:

```
## <scout> findings  (window: <start> → now)
- [<locator>] <one-line finding> | signal: <correction|rehit|ignored|fail-loop|missed-search|
  recurring-root-cause|stale-entry|dup|leak|broken-ref|gap> | confidence: high|med|low
...
## Counts: <what was scanned>  | ## Notable nothing-to-report: <areas that were clean>
```

---

## Scout 1 — claude-logs  (model: sonnet)

**Goal:** From recent Claude sessions, surface *what went wrong* and *what the memory/workflow
system failed to prevent* — the raw material for K (skill) and G (knowledge gap) candidates, and
for spotting stale/missing memory.

**Locations**
- Session index: `~/.claude/history.jsonl` — one line per session:
  `{"display": "<prompt>", "project": "<cwd>", "sessionId": "<uuid>", "timestamp": <epoch_ms>}`.
- Project sessions: `~/.claude/projects/<path-encoded-cwd>/<session-id>.jsonl`.
  Path encoding: replace `/` with `-`, prefix with `-`.
- Subagents: `~/.claude/projects/<.../><session-id>/subagents/agent-<id>.jsonl` (same format —
  scan these too; subagents do much of the work).

**Find sessions in window**
```bash
find ~/.claude/projects -path "*<repo>*" -name "*.jsonl" -not -path "*/subagents/*" \
  -newermt "<window-start>" -exec ls -lt {} + | head -40
```

**Per-session timeline**
```bash
SESSION="<path>.jsonl"
PARSER="$HOME/.agents/skills/deep-dream/scripts/parse_session_log.py"
[ -f "$PARSER" ] || PARSER="$HOME/.claude/skills/deep-dream/scripts/parse_session_log.py"
python3 "$PARSER" "$SESSION" --provider claude --include-locators
```

The parser emits compact event metadata without tool or message bodies. Paths/repository locators
are omitted by default; `--include-locators` is an explicit local-audit opt-in. Claude's
`Agent` attempts include a privacy-safe `delegated_prompt_hash`; match it to the child log's first
`human_message.message_hash` to correlate direct and nested children without copying prompts.
Claude's
SessionStart hook explicitly does **not** persist its additional context into the transcript, so
`summary.memory_context_observed=false` is not evidence that no memory was delivered. Join hook
logs/backend `session_init` by native session id when making delivery claims. A transcript marker
can prove observed context; absence cannot disprove delivery.

**Signals to extract**
- **correction** — user reverses Claude's approach (explicit "no/that's wrong/actually", or
  implicit: redoes it differently, contradicts an assumption). Capture wrong-vs-right.
- **rehit** — the session rediscovered the hard way something an existing memory entry already
  covers (cross-check against the memory-inventory scout's list if available).
- **ignored** — delivery is confirmed by an explicit transcript marker or hook/backend event,
  yet Claude acted against that exact rule. Never infer this from transcript absence.
- **missed-search** — long/complex task with zero `mcp__autodev-memory__search` calls.
- **fail-loop** — repeated failing tool calls / retries on the same thing before it worked.
Aggregate across sessions: a signal appearing in **≥2 sessions** is a pattern — say so and list
all locators.

**Return:** the common envelope. Locator form: `claude:<short-session-id>:<line>`.

---

## Scout 2 — codex-logs  (model: sonnet)

**Goal:** Identical signal set to Scout 1, on the **Codex** side. Codex logs are large (1–7 MB
per session) — never read them whole; stream-parse with the recipe below.

**Locations**
- Rollups: `~/.codex/sessions/YYYY/MM/DD/rollout-<ISO-ts>-<uuid>.jsonl`. Filename encodes start
  time + session UUID.
- Title index: `~/.codex/session_index.jsonl` — `{"id","thread_name","updated_at"}` (no cwd).
- Typed-input history: `~/.codex/history.jsonl` — `{"session_id","ts","text"}` (interactive
  user input only).

**Find sessions in window & map to project**
```bash
find ~/.codex/sessions -name "rollout-*.jsonl" -newermt "<window-start>" -exec ls -lt {} + | head -40
```
Each rollout's **first line** is `type:"session_meta"` carrying the project:
`payload.cwd`, `payload.git.branch`, `payload.git.repository_url`. Keep only rollouts whose
`cwd`/repo matches the target.

**Line shape:** every line is `{"timestamp","type","payload"}`. Both generations below are
live and must be parsed:

| `type` | `payload.type` / role | Carries |
|---|---|---|
| `session_meta` | — | `cwd`, `git.branch`, `git.repository_url` (first line) |
| `event_msg` | `user_message` | `payload.message` = **real human turn** — skip if it starts with `<system_instruction>` / `<collaboration_mode>` / `<environment_context>` |
| `event_msg` | `agent_message` | assistant narrative (`payload.message`) |
| `response_item` | `message` role `assistant` | assistant text (`payload.content[].type=="output_text"`) |
| `response_item` | `function_call` | tool call: `payload.name`, `payload.arguments` (JSON string). MCP calls use the tool name directly (e.g. `get_ticket`). |
| `response_item` | `function_call_output` | shell/tool result. For `exec_command`, output contains `"Process exited with code N"`. |
| `response_item` | `custom_tool_call` | current Codex outer tool call. `name="exec"` carries JavaScript in `payload.input`; nested calls appear only as `tools.<name>(...)` source. |
| `response_item` | `custom_tool_call_output` | outer result. Current `exec` output is rendered text blocks; it does not identify which nested call produced each block. |
| `response_item` | `message`, role `developer` | current hook/developer context. Detect the memory marker, but never copy its body into a report. |
| `event_msg` | `patch_apply_end` | `payload.success` (bool), `payload.stderr` — **patch failures** |
| `event_msg` | `mcp_tool_call_end` | `payload.result` has `"Err"` vs `"Ok"` — **MCP errors** |
| `event_msg` | `task_complete` | `payload.last_agent_message` (final summary) |

**Timeline parser (fixtures cover both generations)**
```bash
PARSER="$HOME/.agents/skills/deep-dream/scripts/parse_session_log.py"
[ -f "$PARSER" ] || PARSER="$HOME/.claude/skills/deep-dream/scripts/parse_session_log.py"
python3 "$PARSER" "$SESSION" --provider codex
```

For current `custom_tool_call(name="exec")`, the parser reports nested `tools.*` names as
`nested_tool_attempts` and marks their results `not_individually_attributed`. The outer script's
`completed` status proves only that the JavaScript wrapper completed; it does **not** prove every
nested call succeeded. Confirm an inner MCP call with `mcp_tool_call_end`/operation logs, or an
inner shell call with structured executor telemetry. Do not turn JavaScript source matches into
success counts.

**"What went wrong" signals:** non-zero `exit` in `function_call_output`; `Traceback` /
`ImportError` / `Error:` in output text; `patch_apply_end.success == false`; `mcp_tool_call_end`
with `Err`; short real `user_message`s that read as corrections/retries ("no", "that's wrong",
"again", "stop"); a session with `task_started` but no `task_complete` (abandoned).

**Memory context:** current Codex sessions do receive the autodev memory hook in developer
context, and the marker is transcript-visible. Count delivery once per native session, not once
per repeated developer message. As with Claude, a confirmed marker shows delivery—not reading,
agreement, or application.

**Return:** the common envelope. Locator form: `codex:<short-session-id>:<HH:MM:SS>`.

---

## Scout 3 — tickets  (model: sonnet)

**Goal:** Find **recurring** failure root causes and review themes across tickets in the window
— the kind of thing that should become a skill checklist item, a starred rule, or a memory entry
so it stops recurring.

**Tools** (all `mcp__autodev-memory__*`, project + repo required):
- `list_tickets(project, repo, status=...)` — pull bugs (`B*`) and recently-completed tickets in
  window.
- `search_tickets(project, query)` — semantic+BM25 over ticket artifacts; probe recurring themes
  (e.g. "Atlas default removed", "DataDome block", "schema NOT NULL", "selector changed").
- `get_review_patterns(project, ...)` — review findings that recur across tickets (gold for K).
- `get_similar_tickets(...)` / `get_ticket(...)` — confirm clusters; read `investigation` and
  `retrospective` artifacts where the real root cause is written down.

**Signals to extract**
- **recurring-root-cause** — the same underlying cause behind ≥2 bug tickets (e.g. several B-items
  all tracing to raw-SQL inserts omitting a NOT-NULL column). Cite each ticket id.
- **repeated review finding** — `get_review_patterns` shows the same class of issue flagged again
  and again → candidate for a review-skill checklist line (K).
- **known-but-unwritten** — a root cause solved in a ticket retrospective that isn't in any memory
  entry or skill → G/P candidate.
- **already-fixed** — a cluster whose fix landed in a recent commit; the lesson is "capture why",
  not "re-flag".

**Return:** the common envelope. Locator form: `ticket:<REPO>/<ID>`. Group by root-cause cluster.

---

## Scout 4 — memory-inventory  (model: haiku)

**Goal:** Produce the per-entry audit table the memory channel needs (this is `dream` Steps 1–3,
delegated to a cheap model because it's heavy mechanical reading).

**Steps**
1. `list_entries(project="global")` and `list_entries(project=<project>)`; also
   `include_superseded: true` for both (to spot orphaned chains).
2. `get_entry` for every active entry (batch ~5 in parallel). Also
   `get_all_tags(project=...)` for both scopes (tag-vocabulary audit).
3. For each entry record: `id` (short), `title`, `entry_type`, `summary`, `tags`, `repos`,
   `scope`, `created_at`, `updated_at`, `token_estimate`.

`updated_at` is not content freshness: retrieval counters currently trigger it. Record it for
diagnostics only; verify staleness against source provenance, current code/config, and newer
superseding guidance.

**Flag (per the dimensions in `dream/references/audit-checklist.md`)** — but do **not** decide;
just flag with evidence for the orchestrator to turn into M candidates:
- stale (references symbols/files/APIs — give the grep the orchestrator should run to confirm),
- duplicate / overlapping pairs, merge clusters, split candidates,
- mis-scoped (project entry that's actually general, or vice-versa),
- contradictions, tag synonyms/casing issues, mistyped entries,
- **low-utility review** (accurate but with no identified audience after a counterfactual test;
  never infer this from zero returns or search-hit counters alone),
- **reusable-methodology** entries that read like a portable HOW (flag as P-migration candidates
  for the orchestrator).

**Return:** the audit table + a flagged-issues list, each with the entry id and the confirming
check still to run. Locator form: `entry:<short-id>`.

---

## Scout 5 — skill-inventory  (model: sonnet)

**Goal:** Map the skills in play (project-relevant + shared workflow skills) for both
**structure** (heal-workflows) and **content quality** (the substantive part heal-workflows
doesn't do).

**Read**
```bash
find ~/dev/agent-workflows/skills -name SKILL.md
find . -path "*/.agents/skills/*" -name SKILL.md   # project-level skills, if any
find . -path "*/.claude/skills/*" -name SKILL.md
```

**Structural checks (W candidates)**
- valid frontmatter (`name`, `description`); referenced `references/*.md` / `templates/*.md` exist;
- cross-references to other skills resolve; no orphaned skills; consistent naming.

**Content checks (K / P candidates)** — the valuable part:
- **project leakage** — a *shared* skill containing project-specific detail (table names, service
  ids, routes, repo paths). Per `agent-workflows/CLAUDE.md` shared skills must be project-agnostic
  → P-migration down to memory/CLAUDE.md.
- **stale steps** — a step referencing a tool/path/flag that no longer exists (cite `file:line`).
- **overlap / contradiction between skills** — two skills giving different guidance on the same
  thing, or near-duplicate coverage that should be cross-referenced or merged.
- **missing coverage** — a failure class the evidence scouts keep hitting that no skill checklist
  catches (the orchestrator pairs this with the log/ticket evidence to form a K candidate).

**Return:** the common envelope, split into `## structural` and `## content`. Locator form:
`skills/<name>/SKILL.md:<line>`.

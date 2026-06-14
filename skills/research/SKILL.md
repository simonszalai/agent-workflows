---
name: research
description: Research how something is implemented across the entire codebase. Finds patterns and inconsistencies.
---

# Research

Research a codebase question using either a single researcher agent (light path) or a
multi-modal sweep with loop-until-dry completeness checking (heavy path), then store the
findings as a ticket artifact.

## Usage

```
/research F0014 "how is historical pricing calculated"   # Add research to existing ticket
/research B0009 "where do timeout errors originate"      # Add research to bug ticket
/research "how is error handling done"                   # Creates new research ticket
/research F0014 "..." --deep                             # Force heavyweight workflow path
/research F0014 "..." --light                            # Force single-agent path
/research F0014 "..." --solo                             # Skip external Codex searcher (Claude only)
```

## When to Use

| Situation                            | Use `/research`? | Instead Use    |
| ------------------------------------ | ---------------- | -------------- |
| Understanding current implementation | Yes              | -              |
| Finding patterns across codebase     | Yes              | -              |
| Finding inconsistencies              | Yes              | -              |
| Research to inform a feature/bug     | Yes              | -              |
| Bug/incident investigation           | **No**           | `/investigate` |
| Planning a new feature               | **No**           | `/plan`        |
| Checking specific file/function      | **No**           | Read directly  |

## Context Resolution

```
# Project: from <!-- mem:project=X --> in CLAUDE.md
# Repo: from git remote — basename -s .git $(git config --get remote.origin.url)
# Repo root: git rev-parse --show-toplevel
```

## Ticket Setup

**If ticket ID given** (e.g., `/research F0014 "question"`):

```
ticket = mcp__autodev-memory__get_ticket(project=PROJECT, ticket_id=ID, repo=REPO)
```
- If not found: error - "Ticket {ID} not found"
- Read source artifact for context

**If only a question given** (e.g., `/research "how does X work"`):

```
ticket = mcp__autodev-memory__create_ticket(
  project=PROJECT, repo=REPO,
  title="Research: <slug from question>",
  type="refactor",
  description="Research question: <user's question>",
  status="in_progress",
  command="/research"
)
```

## Process

1. **Parse the research question.** Identify subject (concept being researched) and scope
   (entire codebase vs specific layer).

2. **Decide the execution path — complexity gate:**

   Heavy path runs a multi-modal sweep, loop-until-dry completeness check, and opus-driven
   synthesis. It pays off when the question is broad enough that one researcher would miss
   things. Light path uses a single researcher agent — cheaper, faster, fine for narrow
   questions.

   Use this gate (top-to-bottom, first match wins):

   | Condition                                                              | Path  |
   | ---------------------------------------------------------------------- | ----- |
   | User passed `--deep`                                                   | Heavy |
   | User passed `--light`                                                  | Light |
   | Question contains "across", "all", "every", "entire", "everywhere"     | Heavy |
   | Question names a specific file or symbol (e.g. "X in path/to/Y.ts")    | Light |
   | Question word count ≥ 12                                               | Heavy |
   | Otherwise                                                              | Light |

   Announce the chosen path before fanning out:

   ```
   Question: how is authentication implemented
   Path: heavy (broad-scope keyword "implemented" + word count) — research-fanout workflow
   ```

3. **Discover zones (heavy path only — optional):**

   Check the project's `CLAUDE.md` or `AGENTS.md` for zone definitions. If present, pass
   them as `args.zones`. If absent, the workflow falls back to modality-only search.
   A zone is `{ key, description, paths: [glob patterns] }`.

3b. **Gather prior knowledge (heavy path only):**

   The heavy-path workflow spawns generic subagents — they receive NO knowledge-menu
   injection and do NOT load the `autodev-search` skill, so they are blind to the memory
   system unless you feed it to them. Before invoking the workflow, search autodev for
   memories and past work related to the question:

   ```
   # Related memories (gotchas, patterns, architecture)
   memories = mcp__autodev-memory__search(
     project=PROJECT,
     queries=[{ "keywords": [<2-4 terms from the question>],
                "text": "<the research question>" }],
     limit=8
   )

   # Related past work — by similarity to this ticket and by keyword
   similar = mcp__autodev-memory__get_similar_tickets(
     project=PROJECT, ticket_id=ID, repo=REPO, status="completed"
   )
   ticket_hits = mcp__autodev-memory__search_tickets(
     project=PROJECT, query="<keywords from the question>"
   )
   ```

   Render the hits into a compact markdown blob (omit a section if it is empty):

   ```markdown
   ## Related memories
   - [<title>] (<type>): <one-line takeaway>

   ## Related past work
   - <TICKET_ID> "<title>" (<status>): <approach / key learning>
   ```

   This blob becomes `args.priorKnowledge` in step 4a, where it is injected into the
   completeness-critic and synthesis prompts. If nothing relevant turns up, pass `null` —
   do not fabricate entries. (The light path skips this step: its single `researcher` agent
   loads `autodev-search` and searches the memory system itself.)

4. **Fan out — light path (inline):**

   When the gate selects "Light", spawn ONE researcher agent:

   ```
   Agent(
     subagent_type="researcher",
     prompt="
       Research question: {question}
       Repository root: {REPO_ROOT}

       Search the codebase to answer this question. Focus on:
       - Finding ALL relevant implementations
       - Identifying architectural patterns
       - Noting inconsistencies between implementations
       - Reading context, not just grep
       - Each occurrence: file, line, snippet (1-5 lines), pattern_variant

       Return per the searcher output schema (see workflows/research-fanout.js).
     "
   )
   ```

   After the agent returns, validate the occurrence shape (drop entries missing
   `file`/`line`/`snippet`/`pattern_variant`; count drops into `invalid_occurrences`).
   No critic, no gap-fill loop, no separate synthesis — the researcher does its own
   pattern/inconsistency call. Assemble the same return shape as the heavy path
   (zero-fill the loop-related stats fields).

   Skip steps 4a-4b below — those are for the heavy path only.

4a. **Fan out — heavy path (workflow):**

   When the gate selects "Heavy", invoke the workflow by name. The runtime resolves
   `name:` against `~/.claude/workflows/`, where agent-workflows is symlinked in every
   environment:

   ```
   result = Workflow({
     name: "research-fanout",
     args: {
       question: "<original research question>",
       priorKnowledge: "<rendered blob from step 3b, or null>",
       zones: [
         { key: "routes", description: "...", paths: ["app/api/**", ...] },
         // optional; omit to use modality-only search
       ],
       modalities: [
         // optional; defaults to by-grep, by-symbol, by-tests, by-config
       ],
       repoRoot: "<absolute path>",
       mode: "interactive" | "headless",
       loopCap: 2,    // optional; max gap-fill rounds (default 2)
     }
   })
   ```

4b. **Result shape (both paths produce this object):**

   ```
   {
     question: "...",
     summary: "narrative answer to the question",
     patterns: [
       {
         name: "...",
         description: "...",
         canonical_example: { file: "...", line: N },
         usage_example: "code snippet"
       }
     ],
     inconsistencies: [
       {
         description: "...",
         locations: [{file, line}, ...],
         impact: "...",
         severity: "high" | "medium" | "low",
         recommendation: "..."
       }
     ],
     occurrences: [
       { file, line, snippet, pattern_variant, notes, sources: ["zone-or-modality-key"] }
     ],
     zones_searched: ["zone-key", ...],
     modalities_searched: ["modality-key", ...],
     searcher_summaries: [
       { key, files_searched, occurrences_found, summary }
     ],
     loop_iterations: N,   // heavy path; light always 0
     residual_gaps: ["unanswered question 1", ...],
     stats: {
       searchers, searcher_errors, invalid_occurrences,
       unique_occurrences, multi_source_occurrences,
       gap_iterations, gaps_identified, gaps_filled
     }
   }
   ```

   The light path must zero-fill the loop-related stats (`gap_iterations: 0`,
   `gaps_identified: 0`, `gaps_filled: 0`) and report `loop_iterations: 0`. Downstream
   step 5 must not branch on path.

4c. **Cross-provider searchers (on by default — both paths):**

   After the chosen path produces its occurrences, add external Codex and Grok searchers that
   answer the same question over the same repo **unless** the user passed `--solo`. Both run
   read-only with real repo access (Codex via its sandbox, Grok via a read/search-only tool
   allowlist), so they grep and read files independently — an occurrence multiple searchers
   find is the dominant pattern; one only an external provider finds is a coverage gap Claude's
   sweep missed. This is a required step, not optional: you MUST run the commands below and
   read the files they write. Do NOT simulate their output.

   External providers are not Claude subagents (Claude stays in-process on the subscription —
   never shell out to `claude -p`). They run through the `external-agent` adapter
   (`bin/external-agent` in agent-workflows, symlinked onto `PATH`) and each returns a searcher
   envelope `{key, files_searched, occurrences, summary, questions_for_synthesis}` whose
   occurrence items match `occurrenceSchema` in `workflows/research-fanout.js` — the same shape
   your searchers produce, so they merge with no special-casing.

   ```bash
   mkdir -p .context/research
   # Write the question to a file so it survives shell quoting.
   Q="$(cat .context/research/question.txt)"
   external-agent --task research --provider codex --question "$Q" \
     --out .context/research/codex.json 2>.context/research/codex.log &
   external-agent --task research --provider grok  --question "$Q" \
     --out .context/research/grok.json 2>.context/research/grok.log &
   wait
   ```

   Then fold both envelopes into the occurrence set:

   1. Read `.context/research/codex.json` and `.context/research/grok.json`. A failed run still
      returns a valid envelope with empty `occurrences` and a note — surface the note, do not block.
   2. Merge external occurrences into `result.occurrences`, deduping by `(file, line,
      pattern_variant)`. For each occurrence, append the provider key to its `sources`; an
      occurrence found by both a Claude searcher and an external provider is multi-source (the
      strongest signal).
   3. Add `codex`/`grok` to `result.modalities_searched` and fold `files_searched` /
      `questions_for_synthesis` into the coverage stats and `residual_gaps` as appropriate.

   `.context/research/*.json` are ephemeral inter-agent scratch consumed immediately by
   synthesis — correct use of `.context/` per the File Storage Rules.

5. **Render and store the artifact:**

   Format `result` into the Research Output Template below (replace the markdown placeholders
   with values from `result`). Store via MCP:

   ```
   mcp__autodev-memory__create_artifact(
     project=PROJECT, ticket_id=ID, repo=REPO,
     artifact_type="investigation",
     content="<rendered markdown>",
     title="Research: <question>",
     command="/research"
   )
   ```

## Research Output Template (MANDATORY)

```markdown
# Research Findings

**Question:** [result.question]
**Path:** [light | heavy] — searchers: [count], occurrences: [N], loop iterations: [N]

## Summary

[result.summary]

## Key Architectural Patterns

### [pattern.name]

**What:** [pattern.description]
**Where:** `[pattern.canonical_example.file]:[pattern.canonical_example.line]` - canonical example
**Usage:**
```
[pattern.usage_example]
```

## Findings (Occurrences)

| File | Line | Pattern Variant | Sources |
|------|------|----------------|---------|
| `[occurrence.file]` | [line] | [pattern_variant] | [sources joined] |

## Inconsistencies

### [inconsistency.description]

**Severity:** [severity]
**Locations:**
- `[location.file]:[line]`

**Impact:** [impact]
**Recommendation:** [recommendation]

## Coverage

- Searchers run: [searcher_summaries[].key joined]
- Total occurrences: [stats.unique_occurrences]
- Multi-source occurrences (found by ≥2 searchers): [stats.multi_source_occurrences]
- Gap-fill iterations: [stats.gap_iterations] / cap
- Invalid occurrences dropped: [stats.invalid_occurrences]
- Searcher errors: [stats.searcher_errors]

## Residual Gaps

- [residual_gap entry]

---

**Formatting:** Limit lines to 100 chars (tables exempt).
```

## Quality Standards

- **No sampling** — every relevant file must be checked by some searcher
- **Code evidence** — every pattern's canonical_example must point to a real occurrence
- **Exact locations** — file paths and line numbers throughout
- **Quantified results** — counts of patterns, files, variations come from `stats`
- **Honest gaps** — `residual_gaps` should be non-empty whenever coverage is partial;
  do not over-claim completeness

## What the Heavy Path Adds Over the Light Path

- Structured occurrence output enforced at the tool layer (schema retry on mismatch)
- Multi-modal sweep: parallel searchers using different search angles (by-grep, by-symbol,
  by-tests, by-config) catch what a single zone-by-zone walk misses
- Loop-until-dry: completeness critic identifies gaps, gap-fillers run, repeat (up to
  `loopCap` rounds) — fixes the "we found 3, assumed that's all, missed 7 more" failure
- Cross-searcher confirmation: `sources` on each occurrence shows which searchers found it;
  multi-source occurrences are typically the dominant pattern
- Diagnostic stats so the skill can report how much coverage was actually achieved

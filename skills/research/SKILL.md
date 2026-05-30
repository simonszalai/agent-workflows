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
  status="active",
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

   When the gate selects "Heavy", invoke the workflow via `scriptPath`. Resolve `$HOME`
   at invocation time so the path works in every environment (local, NanoClaw, cloud):

   ```
   import os
   workflow_path = f"{os.environ['HOME']}/.claude/workflows/research-fanout.js"

   result = Workflow({
     scriptPath: workflow_path,
     args: {
       question: "<original research question>",
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

---
name: autodev-save
description: Save knowledge to the memory system. Fetches all entries, determines scope via project topology, decides whether to create, append, supersede, or skip.
user_invocable: false
---

# Autodev Save

Save a piece of knowledge to the memory system. This skill replaces the old `!!!` hook trigger
with a proper in-process flow that has full access to MCP tools and conversation context.

## When to Load

Loaded by the `/save` command when the user wants to persist knowledge. Also available to other
skills that need to store memories (compound, extract, ingest).

## Procedure

### Step 1: Understand What to Save

Extract the knowledge from the user's message and recent conversation context. Determine:

| Field | How to Determine |
|---|---|
| `title` | Descriptive title — use vocabulary people naturally use when this topic comes up |
| `content` | Full knowledge content, self-contained, actionable, includes WHY. Target 200-800 tokens |
| `entry_type` | gotcha, pattern, preference, correction, solution, reference, architecture |
| `summary` | 1-sentence search-friendly summary |
| `tags` | Use the autodev-tags skill procedure to determine tags |

If the user's message is a correction ("don't do X, do Y"), extract what was wrong and what the
correct approach is. If it's a learning ("I discovered that..."), extract the discovery. If it's
a preference ("always use X"), extract the preference.

### Step 2: Determine Scope (Global vs Project vs Repo)

Fetch the project topology to understand what projects and repos exist. The SessionStart hook
already fetches topology and exports it — if you have the sibling repo list from session
context, you can skip re-fetching and use it directly. Otherwise:

```
mcp__autodev-memory__list_projects()
```

Then for the current project (from `<!-- mem:project=X -->` in CLAUDE.md):

```
mcp__autodev-memory__list_repos(project_name: <project>)
```

Use this decision matrix:

| Knowledge Type | Scope | Why |
|---|---|---|
| Framework/library behavior (React Router, Prisma, SQLAlchemy, Mantine, etc.) | **global** | Any project might use it |
| Language patterns (Python, TypeScript, SQL) | **global** | Universal |
| CLI tools, dev environment, editor config | **global** | Cross-project |
| Agent workflow conventions | **global** | Shared infrastructure |
| CI/CD patterns, deployment patterns | **global** (unless truly unique) | Usually transferable |
| Testing patterns and gotchas | **global** (unless project-specific test infra) | Usually transferable |
| Business logic, domain rules | **project-scoped** | Specific to one product |
| Project architecture decisions | **project-scoped** | Specific to one codebase |
| Service configuration, infra specifics | **project-scoped**, optionally repo-tagged | Deployment-specific |
| Single-repo implementation details | **project-scoped** + `repos: ["repo-name"]` | Narrow scope |

**Bias toward global.** The downside of storing globally when it should be project-scoped is
minimal (slightly noisier search results). The downside of storing project-scoped when it should
be global is significant (future projects won't find it, knowledge gets duplicated). New projects
and repos will come in over time — global entries are immediately available to them.

**When in doubt, go global.** If you're even 30% unsure whether something is project-specific,
make it global. It's easy to scope down later but hard to discover scattered project-level entries
that should have been shared.

### Step 3: Fetch All Existing Entries

Get the complete entry index for the target scope. This is critical — we need to see everything
to make a good dedup decision.

For global knowledge:

```
mcp__autodev-memory__list_entries(project: "global")
```

For project-scoped knowledge:

```
mcp__autodev-memory__list_entries(project: <project>)
```

Also fetch global entries if storing project-scoped (to check if a global entry already covers it):

```
mcp__autodev-memory__list_entries(project: "global")
```

### Step 4: Match Against Existing Entries

Review the entry list from Step 3. Look at titles, summaries, and tags. Identify entries that
may cover the same topic or closely related ground.

**Be liberal with matching.** False positives are cheap (just an extra fetch), false negatives are
expensive (duplicate or conflicting entries).

For each candidate match (up to 3), fetch the full content:

```
mcp__autodev-memory__get_entry(entry_id: <id>, project: <project>)
```

Read the full content and compare with the new knowledge.

### Step 5: Decide Action

| Situation | Action |
|---|---|
| No matches, or all matches are about different topics | **new** — create fresh entry |
| Strong match covers same topic but new adds information | **append** — merge into existing |
| Strong match exists but new is better/more complete/corrects old | **supersede** — replace with improved version |
| Entry exists but merging would exceed ~1,500 tokens | **rebalance** — split and reorganize |
| Existing entry already fully covers this knowledge | **skip** — already captured |
| Existing entry is wrong and there's no replacement | **deprecate** — mark as outdated |

Use judgment, not just titles. Two entries can have similar titles but cover different aspects
(both should exist). Or dissimilar titles but one clearly supersedes the other.

### Step 6: Execute

**New — create fresh entry:**

```
mcp__autodev-memory__add_entry(
  title: <title>,
  content: <content>,
  entry_type: <type>,
  project: <project>,           # "global" or project name
  summary: <summary>,
  tags: <tags>,
  repos: <repos>,               # null for global/project-wide, ["repo"] for repo-specific
  source: "captured",
  source_metadata: {
    "created_via": "save_skill",
    "trigger": "user_invocation"
  },
  caller_context: {
    "skill": "save",
    "reason": "<why this knowledge is worth persisting>",
    "action_rationale": "No existing entry covers this topic"
  }
)
```

**Append — merge into existing entry:**

Write a coherent combined version that integrates both pieces of knowledge. Don't just
concatenate — restructure if needed so the entry reads naturally. The merged content must stay
under ~1,500 tokens (~6,000 chars).

```
mcp__autodev-memory__update_entry(
  entry_id: <existing_entry_id>,
  project: <project>,
  content: "<merged content combining existing + new information>",
  summary: "<updated summary reflecting combined knowledge>",
  caller_context: {
    "skill": "save",
    "reason": "<why this knowledge is worth persisting>",
    "action_rationale": "Appending to existing entry — new info: <what's new>"
  }
)
```

**Supersede — replace with better version:**

```
mcp__autodev-memory__supersede_entry(
  old_entry_id: <old_entry_id>,
  title: <title>,
  content: "<improved content that supersedes the old entry>",
  entry_type: <type>,
  project: <project>,
  summary: <summary>,
  tags: <tags>,
  repos: <repos>,
  source: "captured",
  source_metadata: {
    "created_via": "save_skill",
    "trigger": "user_invocation"
  },
  caller_context: {
    "skill": "save",
    "reason": "<why this knowledge is worth persisting>",
    "action_rationale": "Superseding entry <old_id> — <why old is outdated>"
  }
)
```

**Skip — already covered:**

No MCP calls. Tell the user which existing entry already covers this knowledge and why no
change is needed.

**Deprecate — mark entry as wrong:**

```
mcp__autodev-memory__update_entry(
  entry_id: <entry_id>,
  project: <project>,
  content: "DEPRECATED: <reason>",
  summary: "DEPRECATED — <brief reason>",
  caller_context: {
    "skill": "save",
    "action_rationale": "Deprecating — <why it's wrong>"
  }
)
```

### Step 7: Report

Tell the user exactly what happened:

```
Saved: <action> — "<title>"
Scope: <global | project/repo>
Reason: <brief explanation of why this action was chosen>
Entry ID: <id>
```

If skipped, explain which existing entry already covers it.

---
description: Add knowledge docs (solutions, gotchas, references) with YAML frontmatter.
---

# Compound Command

Capture learnings as knowledge documents with user approval.

## 2-Tier Knowledge System

Knowledge is stored in two tiers based on how often it needs to be applied:

| Tier       | Location             | Purpose                                       | Always in Context? |
| ---------- | -------------------- | --------------------------------------------- | ------------------ |
| **Tier 1** | `AGENTS.md`          | Critical rules that agents keep getting wrong | Yes                |
| **Tier 2** | `.claude/knowledge/` | Detailed references, gotchas, solutions       | No (searched)      |

### Tier 1: AGENTS.md Rules

Add to AGENTS.md when:

- User says "you keep getting this wrong" or "you made this mistake again"
- User says "always remember" or "critical rule" or "never forget"
- A gotcha has been violated multiple times
- The rule is simple and can be stated in 1-2 sentences

**Format for AGENTS.md rules:**

```markdown
## [Section Name]

- **[Rule name]**: [One-sentence explanation]
```

### Tier 2: .claude/knowledge/ Docs

Add to `.claude/knowledge/` when:

- The knowledge needs detailed explanation with code examples
- It's a solution to a specific problem (searchable for future reference)
- It's a reference document for deeper research
- It's a gotcha that needs full context to understand

## Usage

```
/compound                    # Interactive: analyzes recent context
/compound solution           # Propose solution doc
/compound gotcha             # Propose gotcha doc
/compound reference          # Propose reference doc
/compound rule               # Propose AGENTS.md rule addition
/compound "topic or context" # Propose docs related to topic
```

## Document Types

| Type      | Purpose                                   | Location                        |
| --------- | ----------------------------------------- | ------------------------------- |
| rule      | Critical rules agents keep violating      | `AGENTS.md`                     |
| solution  | Problem resolution, debugging steps       | `.claude/knowledge/solutions/`  |
| gotcha    | Common pitfalls and their solutions       | `.claude/knowledge/gotchas/`    |
| reference | Architecture, patterns, deployment guides | `.claude/knowledge/references/` |

## Tier Detection Signals

**Promote to Tier 1 (AGENTS.md) when user says:**

- "you keep getting this wrong"
- "you made this mistake again"
- "always remember this"
- "critical rule"
- "never forget"
- "add this to your rules"
- "you keep forgetting"
- Any indication of repeated violations

**Keep in Tier 2 (.claude/knowledge/) when:**

- First occurrence of a gotcha/solution
- Needs detailed code examples
- Reference documentation
- Complex explanation required

## Process

### Step 1: Research and Propose

1. **Gather context:**
   - Review recent conversation for learnings
   - Check existing knowledge docs to avoid duplicates
   - **Detect tier signals** in user's language
   - Identify what's worth documenting

2. **Present proposals** with clear numbering:

   ```
   ## Proposed Knowledge Additions

   ### 1. [Type] Title
   **Location:** [AGENTS.md | .claude/knowledge/[type]/filename.md]
   **Tier:** [1 - Always in context | 2 - Searchable reference]
   **Summary:** Brief description of what will be documented
   **Tags:** tag1, tag2

   ### 2. [Type] Title
   **Location:** .claude/knowledge/[type]/filename.md
   **Tier:** 2 - Searchable reference
   **Summary:** Brief description of what will be documented
   **Tags:** tag1, tag2
   ```

3. **Wait for approval:**
   - User responds with numbers (e.g., "1, 3" or "all" or "none")

### Step 2: Write Approved Docs

1. **Create only approved documents:**

   **For Tier 1 (AGENTS.md):** Append rule to appropriate section:

   ```markdown
   ## [Existing Section]

   - **[New rule]**: [One-sentence explanation]
   ```

   **For Tier 2 (.claude/knowledge/):** Create file with YAML frontmatter:

   ```markdown
   ---
   title: [Descriptive title]
   created: YYYY-MM-DD
   tags: [tag1, tag2]
   ---

   # [Title]

   [Content following template for type]
   ```

2. **Report what was written:**
   ```
   Created:
   - AGENTS.md: Added rule "[rule name]" to [section]
   - .claude/knowledge/solutions/example-solution.md
   - .claude/knowledge/references/example-reference.md
   ```

## Templates by Type

### Solution

```markdown
---
title: [Problem] Resolution
created: YYYY-MM-DD
tags: [area, technology]
---

# [Problem] Resolution

## Problem

[What went wrong]

## Root Cause

[Why it happened]

## Solution

[How it was fixed]

## Prevention

[How to avoid in future]
```

### Gotcha

```markdown
---
title: [Pitfall Title]
created: YYYY-MM-DD
tags: [area, technology]
---

# [Pitfall Title]

## The Gotcha

[What catches people off guard]

## Why It Happens

[Underlying cause]

## The Fix

[How to handle it correctly]
```

### Reference

```markdown
---
title: [Topic] Guide
created: YYYY-MM-DD
tags: [area, technology]
---

# [Topic] Guide

## Overview

[What this covers]

## [Section]

[Content]

## Examples

[Practical examples]
```

## Output

- Numbered proposals for user approval
- Tier 1 rules added to `AGENTS.md`
- Tier 2 documents written to `.claude/knowledge/`

# Research Requirements

**This is the core of build planning.** Before writing any build todo, you MUST thoroughly
research each of these areas:

## 1. Curated Memory Context (REQUIRED)

Read the context-curator packet supplied by the orchestrator. It is the single retrieval owner's
filtered result from every current ticket artifact, consolidated memory queries, expanded applicable
entries, and similar completed/failed tickets. Do not repeat broad MCP searches in build planning.

**Document in each build todo:**

- Which gotchas apply to this step
- Which standards must be followed
- Which past solutions inform this step

## 2. Codebase Pattern Research (REQUIRED)

Find existing implementations to follow:

```bash
# Find similar code patterns
grep -r "pattern" src/

# Find how similar features were implemented
git log --all --oneline --grep="similar-feature"

# Find error handling patterns in affected area
grep -r "try:" src/path/to/affected/

# Find test patterns for this type of code
grep -r "def test_\|describe(" tests/
```

**Document in each build todo:**

- Patterns that MUST be followed (with file:line references)
- Conventions specific to the affected area
- Test patterns to match

## 3. Git History Research (REQUIRED)

Understand why code exists as it does:

```bash
# File evolution
git log --follow --oneline -20 <file>

# Code origin
git blame -w -C -C -C <file>

# Related changes
git log -S"keyword" --oneline

# Past issues in this area
git log --grep="fix" -- <path>
```

**Document in each build todo:**

- Why affected code was written this way
- Past issues that inform this implementation
- Recent changes that might conflict

## 4. CLAUDE.md Compliance (REQUIRED)

Check project rules:

- Read CLAUDE.md for any rules that apply
- Document which rules affect this step
- Note specific requirements (e.g., "no Any types", "use TEXT not VARCHAR")

## 5. Patch & Solution Selection (REQUIRED)

For each build step, select the applicable patches, fixes, past solutions, and review lessons from
the curator packet. The curator expanded the selected memory bodies, so titles alone were not used
to decide applicability. If the packet lacks one exact fact newly exposed by code research, return a
targeted context-refresh request instead of running a second broad search.

**Document in each build todo:**

- Relevant memories found (auto-injected or explicitly searched)
- Known patches and solutions that apply to this step
- Past ticket review findings that flagged issues in this area
- User preferences that apply to this step
- Past debug learnings for this area

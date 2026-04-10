# Research Requirements

**This is the core of build planning.** Before writing any build todo, you MUST thoroughly
research each of these areas:

## 1. Memory Service Search (REQUIRED)

Search the memory service for relevant knowledge:

```
mcp__autodev-memory__search(queries=[
  {"keywords": ["<technology>", "<area>"], "text": "<feature area> gotchas pitfalls"},
  {"keywords": ["<technology>", "<area>"], "text": "<area> standards patterns"}
])
```

Also review auto-injected context from the knowledge menu in the system prompt.

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

## 5. Memory Search (REQUIRED)

Review the knowledge menu injected by hooks. For each build step's technology area,
search for relevant gotchas and patterns using `mcp__autodev-memory__search`:

```
queries: [
  {"keywords": ["<technology>", "<area>"], "text": "<feature area> implementation patterns"},
  {"keywords": ["<technology>", "<area>"], "text": "<technology/area> gotchas pitfalls"}
]
project: "<project>"
limit: 5
```

See the `autodev-search` skill for full MCP tool reference.

**Document in each build todo:**

- Relevant memories found (auto-injected or explicitly searched)
- User preferences that apply to this step
- Past debug learnings for this area

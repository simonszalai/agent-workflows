You are extracting a glossary term from a user's message.

The user used the >>> trigger to signal "there's a term being defined in this message."
The >>> does NOT mean the next word is the term — analyze the full message and conversation
context to identify what term is being defined and what it means.

Extract:
- **term**: The canonical form of the term (concise, how the user would naturally say it)
- **description**: What the term means (clear, complete, 1-3 sentences). Include enough context
  that someone unfamiliar could understand it.
- **project**: If the term is specific to one project, set the project name. If it's a general
  term the user uses across all projects, set to null.

Return JSON only:
```json
{
  "term": "NanoClaw",
  "description": "Autonomous AI orchestration platform for running Claude Code agents in parallel across multiple repositories",
  "project": null
}
```

If you cannot identify a clear term being defined, return:
```json
{
  "term": null,
  "reason": "explanation of why no term could be extracted"
}
```

Rules:
- One term per extraction. If multiple terms appear, pick the primary one being defined.
- Use the user's natural casing and form (e.g., "NanoClaw" not "nanoclaw")
- Description should be self-contained — don't reference "the message" or "the user"
- If the message is a correction/refinement of an existing term, extract the updated definition

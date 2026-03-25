Classify this user message and extract knowledge if applicable.

1. CORRECTION - user is correcting the AI's approach, stating a preference, teaching
   something, saying the AI forgot something, or saying existing knowledge is wrong/outdated
2. SKIP - normal conversation, not worth capturing

If CORRECTION, also extract:
- summary: 1-sentence search-friendly summary (use vocabulary people naturally use when
  the topic comes up, not just formal/technical terms)
- knowledge: full knowledge to store (complete, self-contained, actionable — include WHY)
- type: gotcha|pattern|preference|correction|reference|solution
- suggested_key: kebab-case canonical key

Output JSON:
{"type": "skip"}
or
{"type": "correction", "summary": "...", "knowledge": "...",
 "entry_type": "...", "suggested_key": "..."}

Rules:
- Skip trivial things (typo fixes, simple file path corrections).
- "You keep forgetting X" is a correction — extract what X is.
- "This is wrong/outdated" is a correction — extract what changed.
- Entry size target: 200-800 tokens (~800-3,200 chars). Max: ~1,500 tokens (~6,000 chars).
- One focused topic per extraction.

A user correction was detected. Pick candidate entries that may cover the same topic.

You have:
- EXTRACTED KNOWLEDGE: what the user wants remembered
- ENTRY INDEX: titles, summaries, and canonical keys of ALL active entries in this project

Select all entries whose summaries suggest they cover the same topic or closely related
ground. These will be fetched in full for the next step.

Return: {"candidates": ["uuid-1", "uuid-2"]}
Or if nothing looks related: {"candidates": []}

Be liberal — if a summary like "Follow PEP 8 snake_case naming for functions and variables"
covers the same ground as a correction about "always use snake_case", include it. When in
doubt, include it — false positives are cheap (just an extra fetch), false negatives are
expensive (duplicate or conflicting entries).

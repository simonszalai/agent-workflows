---
description: Get debug info for the current Conductor conversation (conversation ID, workspace).
model: sonnet
---

Run this exact bash command and display the output to the user:

```bash
ws_path="$CONDUCTOR_WORKSPACE_PATH" && ws_name="$CONDUCTOR_WORKSPACE_NAME" && projects_dir="$HOME/.claude/projects/-$(echo "$ws_path" | sed 's|^/||; s|/|-|g')" && jsonl=$(ls -t "$projects_dir"/*.jsonl 2>/dev/null | head -1) && conv_id=$(basename "$jsonl" .jsonl 2>/dev/null) && echo "$jsonl" | pbcopy && echo "Conversation ID: $conv_id" && echo "JSONL log path:  $jsonl" && echo "Workspace name:  $ws_name" && echo "Workspace path:  $ws_path" && echo "" && echo "(JSONL path copied to clipboard)"
```

Do not add any commentary. Just run the command and show the output.
